"""AL\CE — network_probe: Async network prober.

Provides low-level async operations: ICMP ping, TCP port scan,
service banner checks, ARP device discovery, and local network
interface enumeration.  All public methods are coroutines.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import subprocess
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from backend.core.config import NetworkProbeConfig

# -- Lazy psutil import ----------------------------------------------------

try:
    import psutil

    _PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None  # type: ignore[assignment]
    _PSUTIL_AVAILABLE = False

# -- Data classes ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PingResult:
    """Result of an ICMP ping operation."""

    host: str
    reachable: bool
    sent: int
    received: int
    loss_pct: float
    avg_ms: float | None = None
    min_ms: float | None = None
    max_ms: float | None = None


@dataclass(frozen=True, slots=True)
class PortResult:
    """Result of a single TCP port probe."""

    port: int
    open: bool
    service_hint: str | None = None


@dataclass(frozen=True, slots=True)
class ServiceResult:
    """Result of a service-level check (HTTP, SSH, FTP …)."""

    host: str
    port: int
    protocol: str
    reachable: bool
    response_ms: float | None = None
    detail: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class InterfaceInfo:
    """Network interface descriptor."""

    name: str
    ip: str
    netmask: str
    mac: str
    is_up: bool
    speed_mbps: int


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """A device discovered on the local network."""

    ip: str
    mac: str | None = None
    hostname: str | None = None


@dataclass(frozen=True, slots=True)
class NetworkInfo:
    """Aggregated local network information."""

    hostname: str
    interfaces: list[InterfaceInfo]
    gateway: str | None = None
    dns_servers: list[str] = field(default_factory=list)


# -- Service hints ---------------------------------------------------------

_SERVICE_HINTS: dict[int, str] = {
    20: "ftp-data", 21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp",
    53: "dns", 80: "http", 110: "pop3", 143: "imap", 443: "https",
    445: "smb", 993: "imaps", 995: "pop3s", 3306: "mysql",
    3389: "rdp", 5000: "upnp", 5001: "synology-dsm", 5432: "postgresql",
    5900: "vnc", 8000: "http-alt", 8080: "http-proxy", 8443: "https-alt",
    8888: "http-alt", 9090: "prometheus", 32400: "plex",
}

# -- Regex patterns (Windows ping output) ---------------------------------

_RE_PING_STATS_EN = re.compile(
    r"Sent\s*=\s*(\d+).*Received\s*=\s*(\d+).*Lost\s*=\s*(\d+)",
    re.DOTALL,
)
_RE_PING_STATS_IT = re.compile(
    r"Inviati\s*=\s*(\d+).*Ricevuti\s*=\s*(\d+).*Persi\s*=\s*(\d+)",
    re.DOTALL,
)
_RE_PING_RTT_EN = re.compile(
    r"Minimum\s*=\s*(\d+)ms.*Maximum\s*=\s*(\d+)ms.*Average\s*=\s*(\d+)ms",
    re.DOTALL,
)
_RE_PING_RTT_IT = re.compile(
    r"Minimo\s*=\s*(\d+)ms.*Massimo\s*=\s*(\d+)ms.*Media\s*=\s*(\d+)ms",
    re.DOTALL,
)

# -- ARP table regex -------------------------------------------------------

_RE_ARP_ENTRY = re.compile(
    r"(\d+\.\d+\.\d+\.\d+)\s+"
    r"([\da-fA-F]{2}[:-][\da-fA-F]{2}[:-][\da-fA-F]{2}"
    r"[:-][\da-fA-F]{2}[:-][\da-fA-F]{2}[:-][\da-fA-F]{2})\s+"
    r"(\w+)"
)


# -- Helper functions ------------------------------------------------------


def _parse_windows_ping(output: str, host: str, count: int) -> PingResult:
    """Parse Windows ``ping`` command output into a :class:`PingResult`.

    Supports both English and Italian locale output.

    Args:
        output: Raw stdout from the ping subprocess.
        host: Target host that was pinged.
        count: Number of pings that were requested.

    Returns:
        Parsed :class:`PingResult`.
    """
    # Try English first, then Italian
    stats_match = _RE_PING_STATS_EN.search(output) or _RE_PING_STATS_IT.search(output)
    rtt_match = _RE_PING_RTT_EN.search(output) or _RE_PING_RTT_IT.search(output)

    if stats_match:
        sent = int(stats_match.group(1))
        received = int(stats_match.group(2))
        lost = int(stats_match.group(3))
        loss_pct = (lost / sent * 100.0) if sent > 0 else 100.0
    else:
        # Fallback: if we can't parse, assume total loss
        sent = count
        received = 0
        loss_pct = 100.0

    avg_ms: float | None = None
    min_ms: float | None = None
    max_ms: float | None = None

    if rtt_match:
        min_ms = float(rtt_match.group(1))
        max_ms = float(rtt_match.group(2))
        avg_ms = float(rtt_match.group(3))

    return PingResult(
        host=host,
        reachable=received > 0,
        sent=sent,
        received=received,
        loss_pct=round(loss_pct, 1),
        avg_ms=avg_ms,
        min_ms=min_ms,
        max_ms=max_ms,
    )


def _get_local_subnets() -> list[tuple[str, int]]:
    """Return ``(network_addr, prefix_len)`` for each RFC‑1918 interface.

    Uses *psutil* to enumerate network interfaces and filters to
    only RFC-1918 private addresses (10.x, 172.16-31.x, 192.168.x).

    Returns:
        List of ``(network_address, prefix_length)`` tuples.

    Raises:
        RuntimeError: If psutil is not installed.
    """
    if not _PSUTIL_AVAILABLE:
        raise RuntimeError("psutil is required for subnet discovery")

    rfc1918 = (
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
    )

    subnets: list[tuple[str, int]] = []
    for _iface_name, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family != socket.AF_INET or not addr.netmask:
                continue
            try:
                iface_ip = ipaddress.ip_address(addr.address)
            except ValueError:
                continue
            if not any(iface_ip in net for net in rfc1918):
                continue
            # Build the network from address + netmask
            try:
                network = ipaddress.ip_network(
                    f"{addr.address}/{addr.netmask}", strict=False
                )
                subnets.append((str(network.network_address), network.prefixlen))
            except ValueError:
                continue
    return subnets


async def _resolve_hostname(ip: str, timeout_s: float = 1.0) -> str | None:
    """Attempt reverse DNS lookup for *ip* with a timeout.

    Args:
        ip: IP address to resolve.
        timeout_s: Maximum seconds to wait for the lookup.

    Returns:
        Resolved hostname or ``None`` if lookup fails or times out.
    """
    try:
        hostname, _, _ = await asyncio.wait_for(
            asyncio.to_thread(socket.gethostbyaddr, ip),
            timeout=timeout_s,
        )
        return hostname
    except (socket.herror, socket.gaierror, asyncio.TimeoutError, OSError):
        return None


# -- Main prober class -----------------------------------------------------


def _run_cmd(
    *args: str, timeout: float | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Execute a command synchronously and return the result.

    Designed to be called via ``asyncio.to_thread`` so it works on
    any event loop (including ``SelectorEventLoop`` on Windows,
    which does not support ``asyncio.create_subprocess_exec``).

    Args:
        *args: Command and arguments (no shell).
        timeout: Max seconds to wait; ``None`` = unlimited.

    Returns:
        :class:`subprocess.CompletedProcess` with captured stdout/stderr.
    """
    return subprocess.run(
        args,
        capture_output=True,
        timeout=timeout,
    )


class NetworkProber:
    """Async network prober for LAN discovery and diagnostics.

    All public methods are coroutines.  Subprocess calls use
    ``asyncio.to_thread(subprocess.run, …)`` so they work on any
    event loop, including ``SelectorEventLoop`` on Windows.

    Args:
        cfg: Plugin configuration with timeouts and limits.
    """

    def __init__(self, cfg: NetworkProbeConfig) -> None:
        self._cfg = cfg

    # -- Ping --------------------------------------------------------------

    async def ping_host(self, host: str, count: int) -> PingResult:
        """Send ICMP echo requests to *host* via the system ``ping`` command.

        Args:
            host: Target IP or hostname (must be pre-validated as local).
            count: Number of pings to send (clamped to config limits).

        Returns:
            Parsed :class:`PingResult` with latency statistics.
        """
        count = max(1, min(count, self._cfg.max_ping_count))
        timeout_ms = str(int(self._cfg.ping_timeout_s * 1000))
        total_timeout = self._cfg.ping_timeout_s * (count + 2)

        try:
            result = await asyncio.to_thread(
                _run_cmd,
                "ping", "-n", str(count), "-w", timeout_ms, host,
                timeout=total_timeout,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Ping to {} timed out after {}s", host, total_timeout)
            return PingResult(
                host=host, reachable=False, sent=count,
                received=0, loss_pct=100.0,
            )
        except OSError as exc:
            logger.error("Failed to execute ping for {}: {}", host, exc)
            return PingResult(
                host=host, reachable=False, sent=count,
                received=0, loss_pct=100.0,
            )

        output = result.stdout.decode("oem", errors="replace")
        return _parse_windows_ping(output, host, count)

    # -- Port scan ---------------------------------------------------------

    async def scan_ports(
        self,
        host: str,
        ports: list[int],
        timeout_s: float,
    ) -> list[PortResult]:
        """Probe a list of TCP ports on *host*.

        Args:
            host: Target IP or hostname (must be pre-validated as local).
            ports: List of TCP port numbers to check.
            timeout_s: Connection timeout per port in seconds.

        Returns:
            List of :class:`PortResult`, one per requested port.
        """
        ports = ports[: self._cfg.max_ports_per_scan]
        semaphore = asyncio.Semaphore(self._cfg.max_concurrent_scans)

        async def _probe(port: int) -> PortResult:
            async with semaphore:
                try:
                    _, writer = await asyncio.wait_for(
                        asyncio.open_connection(host, port),
                        timeout=timeout_s,
                    )
                    writer.close()
                    await writer.wait_closed()
                    return PortResult(
                        port=port, open=True,
                        service_hint=_SERVICE_HINTS.get(port),
                    )
                except (asyncio.TimeoutError, OSError):
                    return PortResult(
                        port=port, open=False,
                        service_hint=_SERVICE_HINTS.get(port),
                    )

        results = await asyncio.gather(*[_probe(p) for p in ports])
        return list(results)

    # -- Service check -----------------------------------------------------

    async def check_service(
        self,
        host: str,
        port: int,
        protocol: str,
    ) -> ServiceResult:
        """Check if a specific service is running on *host*:*port*.

        Supported protocols: ``http``, ``https``, ``ssh``, ``ftp``.

        Args:
            host: Target IP or hostname (must be pre-validated as local).
            port: TCP port of the service.
            protocol: Service protocol to check.

        Returns:
            :class:`ServiceResult` with reachability and details.
        """
        protocol = protocol.lower().strip()
        timeout_s = self._cfg.service_check_timeout_s
        t0 = time.perf_counter()

        match protocol:
            case "http" | "https":
                return await self._check_http(host, port, protocol, timeout_s, t0)
            case "ssh":
                return await self._check_ssh(host, port, timeout_s, t0)
            case "ftp":
                return await self._check_ftp(host, port, timeout_s, t0)
            case _:
                return ServiceResult(
                    host=host, port=port, protocol=protocol,
                    reachable=False,
                    error=f"Unsupported protocol: {protocol}",
                )

    async def _check_http(
        self,
        host: str,
        port: int,
        protocol: str,
        timeout_s: float,
        t0: float,
    ) -> ServiceResult:
        """Probe an HTTP/HTTPS service."""
        import httpx  # noqa: local import — avoid hard dependency

        scheme = protocol
        url = f"{scheme}://{host}:{port}/"

        try:
            # No SSRF hooks — this is explicitly for local service probing
            async with httpx.AsyncClient(
                verify=False,
                timeout=timeout_s,
            ) as client:
                resp = await client.get(url)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            server_header = resp.headers.get("server", "")
            return ServiceResult(
                host=host, port=port, protocol=protocol,
                reachable=True,
                response_ms=round(elapsed_ms, 2),
                detail=f"HTTP {resp.status_code}"
                       + (f" — Server: {server_header}" if server_header else ""),
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            return ServiceResult(
                host=host, port=port, protocol=protocol,
                reachable=False,
                response_ms=round(elapsed_ms, 2),
                error=str(exc)[:200],
            )

    async def _check_ssh(
        self,
        host: str,
        port: int,
        timeout_s: float,
        t0: float,
    ) -> ServiceResult:
        """Probe an SSH service by reading its banner."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout_s,
            )
            data = await asyncio.wait_for(reader.read(256), timeout=timeout_s)
            writer.close()
            await writer.wait_closed()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            is_ssh = b"SSH-" in data
            banner = repr(data[:128])[2:-1]  # Strip b'...' wrapper
            return ServiceResult(
                host=host, port=port, protocol="ssh",
                reachable=is_ssh,
                response_ms=round(elapsed_ms, 2),
                detail=f"Banner: {banner}" if is_ssh else None,
                error=None if is_ssh else "No SSH banner detected",
            )
        except (asyncio.TimeoutError, OSError) as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            return ServiceResult(
                host=host, port=port, protocol="ssh",
                reachable=False,
                response_ms=round(elapsed_ms, 2),
                error=str(exc)[:200],
            )

    async def _check_ftp(
        self,
        host: str,
        port: int,
        timeout_s: float,
        t0: float,
    ) -> ServiceResult:
        """Probe an FTP service by reading its greeting."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout_s,
            )
            line = await asyncio.wait_for(reader.readline(), timeout=timeout_s)
            writer.close()
            await writer.wait_closed()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            is_ftp = line.startswith(b"220")
            banner = repr(line[:128])[2:-1]
            return ServiceResult(
                host=host, port=port, protocol="ftp",
                reachable=is_ftp,
                response_ms=round(elapsed_ms, 2),
                detail=f"Banner: {banner}" if is_ftp else None,
                error=None if is_ftp else "No FTP 220 greeting",
            )
        except (asyncio.TimeoutError, OSError) as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            return ServiceResult(
                host=host, port=port, protocol="ftp",
                reachable=False,
                response_ms=round(elapsed_ms, 2),
                error=str(exc)[:200],
            )

    # -- Device discovery --------------------------------------------------

    async def discover_local_devices(self) -> list[DeviceInfo]:
        """Discover devices on the local network via ARP scan.

        Steps:

        1. Enumerate local RFC-1918 subnets via psutil.
        2. Parallel ping sweep to populate the ARP table.
        3. Read the ARP cache (``arp -a``) and parse entries.
        4. Optional reverse DNS for each discovered device.

        Returns:
            List of :class:`DeviceInfo` for each discovered device.
        """
        # Step 1: get local subnets
        try:
            subnets = await asyncio.to_thread(_get_local_subnets)
        except RuntimeError:
            logger.warning("psutil not available for subnet discovery")
            return []

        if not subnets:
            logger.info("No RFC-1918 subnets found on this host")
            return []

        # Step 2: ping sweep to populate ARP table
        semaphore = asyncio.Semaphore(self._cfg.max_concurrent_pings)

        async def _ping_one(ip_str: str) -> None:
            async with semaphore:
                try:
                    await asyncio.to_thread(
                        _run_cmd,
                        "ping", "-n", "1", "-w", "200", ip_str,
                        timeout=3.0,
                    )
                except (subprocess.TimeoutExpired, OSError):
                    pass

        ping_tasks: list[asyncio.Task[None]] = []
        for net_addr, prefix in subnets:
            network = ipaddress.ip_network(f"{net_addr}/{prefix}", strict=False)
            for ip in network.hosts():
                ping_tasks.append(asyncio.create_task(_ping_one(str(ip))))

        if ping_tasks:
            logger.debug("Ping sweep: {} addresses across {} subnets",
                         len(ping_tasks), len(subnets))
            await asyncio.gather(*ping_tasks)

        # Step 3: read ARP table
        try:
            result = await asyncio.to_thread(
                _run_cmd, "arp", "-a", timeout=10.0,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.error("Failed to read ARP table: {}", exc)
            return []

        arp_output = result.stdout.decode("oem", errors="replace")
        devices: dict[str, DeviceInfo] = {}

        for match in _RE_ARP_ENTRY.finditer(arp_output):
            ip_str = match.group(1)
            mac = match.group(2)
            entry_type = match.group(3).lower()

            # Filter: only dynamic entries
            if entry_type not in ("dynamic", "dinamico"):
                continue

            # Skip broadcast (.255) and multicast (224-239.x.x.x)
            if ip_str.endswith(".255"):
                continue
            try:
                first_octet = int(ip_str.split(".")[0])
            except (ValueError, IndexError):
                continue
            if 224 <= first_octet <= 239:
                continue

            devices[ip_str] = DeviceInfo(ip=ip_str, mac=mac)

        # Step 4: optional reverse DNS
        if devices:
            dns_tasks = {
                ip: asyncio.create_task(_resolve_hostname(ip, timeout_s=1.0))
                for ip in devices
            }
            await asyncio.gather(*dns_tasks.values(), return_exceptions=True)

            result: list[DeviceInfo] = []
            for ip, info in devices.items():
                hostname = dns_tasks[ip].result() if not dns_tasks[ip].cancelled() else None
                if isinstance(hostname, BaseException):
                    hostname = None
                result.append(DeviceInfo(ip=ip, mac=info.mac, hostname=hostname))
            return result

        return list(devices.values())

    # -- Network info ------------------------------------------------------

    async def get_local_network_info(self) -> NetworkInfo:
        """Collect local network interface information.

        Uses psutil for interface enumeration, ``route print`` for the
        default gateway, and ``ipconfig /all`` for DNS servers.

        Returns:
            :class:`NetworkInfo` with interfaces, gateway, and DNS servers.

        Raises:
            RuntimeError: If psutil is not installed.
        """
        if not _PSUTIL_AVAILABLE:
            raise RuntimeError("psutil is required for network info")

        # Interfaces (via psutil in executor)
        addrs, stats = await asyncio.gather(
            asyncio.to_thread(psutil.net_if_addrs),
            asyncio.to_thread(psutil.net_if_stats),
        )

        interfaces: list[InterfaceInfo] = []
        for iface_name, iface_addrs in addrs.items():
            ipv4_addr = ""
            netmask = ""
            mac = ""
            for a in iface_addrs:
                if a.family == socket.AF_INET:
                    ipv4_addr = a.address
                    netmask = a.netmask or ""
                elif a.family == psutil.AF_LINK:
                    mac = a.address

            if not ipv4_addr:
                continue

            iface_stat = stats.get(iface_name)
            interfaces.append(InterfaceInfo(
                name=iface_name,
                ip=ipv4_addr,
                netmask=netmask,
                mac=mac,
                is_up=iface_stat.isup if iface_stat else False,
                speed_mbps=iface_stat.speed if iface_stat else 0,
            ))

        # Gateway via 'route print 0.0.0.0'
        gateway = await self._get_default_gateway()

        # DNS servers via 'ipconfig /all'
        dns_servers = await self._get_dns_servers()

        return NetworkInfo(
            hostname=socket.gethostname(),
            interfaces=interfaces,
            gateway=gateway,
            dns_servers=dns_servers,
        )

    async def _get_default_gateway(self) -> str | None:
        """Parse the default gateway from ``route print 0.0.0.0``."""
        try:
            result = await asyncio.to_thread(
                _run_cmd, "route", "print", "0.0.0.0", timeout=5.0,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None

        output = result.stdout.decode("oem", errors="replace")
        # Match the default route line: 0.0.0.0  0.0.0.0  <gateway>
        gw_match = re.search(
            r"0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)", output
        )
        return gw_match.group(1) if gw_match else None

    async def _get_dns_servers(self) -> list[str]:
        """Parse DNS server addresses from ``ipconfig /all``."""
        try:
            result = await asyncio.to_thread(
                _run_cmd, "ipconfig", "/all", timeout=5.0,
            )
        except (subprocess.TimeoutExpired, OSError):
            return []

        output = result.stdout.decode("oem", errors="replace")
        dns_list: list[str] = []
        # Match lines like "DNS Servers . . . : 192.168.1.1"
        for match in re.finditer(r"DNS.*?:\s*(\d+\.\d+\.\d+\.\d+)", output):
            ip = match.group(1)
            if ip not in dns_list:
                dns_list.append(ip)
        return dns_list
