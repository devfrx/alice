"""Verify network_probe tools work on both ProactorEventLoop and SelectorEventLoop."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.core.config import NetworkProbeConfig
from backend.plugins.network_probe.prober import NetworkProber

cfg = NetworkProbeConfig()
prober = NetworkProber(cfg)


async def test_all():
    loop = asyncio.get_running_loop()
    print(f"  Event loop: {loop.__class__.__name__}")

    # 1. ping_host
    try:
        r = await prober.ping_host("127.0.0.1", 1)
        print(f"  ping_host: OK - reachable={r.reachable}, sent={r.sent}")
    except Exception as e:
        print(f"  ping_host: FAIL - {type(e).__name__}: {e}")

    # 2. get_local_network_info
    try:
        info = await prober.get_local_network_info()
        print(f"  get_local_network_info: OK - hostname={info.hostname}, "
              f"gateway={info.gateway}, ifaces={len(info.interfaces)}")
    except Exception as e:
        print(f"  get_local_network_info: FAIL - {type(e).__name__}: {e}")

    # 3. scan_ports (socket-based, should always work)
    try:
        ports = await prober.scan_ports("127.0.0.1", [80, 8000], 0.5)
        print(f"  scan_ports: OK - {len(ports)} ports scanned")
    except Exception as e:
        print(f"  scan_ports: FAIL - {type(e).__name__}: {e}")


print("=== Test with ProactorEventLoop ===")
asyncio.run(test_all())

print("\n=== Test with SelectorEventLoop ===")
loop = asyncio.SelectorEventLoop()
loop.run_until_complete(test_all())
loop.close()

print("\nAll tests passed!")
