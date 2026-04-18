<script setup lang="ts">
import { ref, computed } from 'vue'
import { api } from '../../services/api'

/* ── Type definitions ───────────────────────────────────────────────── */

interface PingResult {
    host: string
    reachable: boolean
    sent: number
    received: number
    loss_pct: number
    avg_ms: number | null
    min_ms: number | null
    max_ms: number | null
}

interface PortResultData {
    port: number
    open: boolean
    service_hint: string | null
}

interface ScanResult {
    host: string
    total_scanned: number
    open: PortResultData[]
    closed: PortResultData[]
}

interface DeviceResult {
    count: number
    devices: { ip: string; mac: string | null; hostname: string | null }[]
}

interface ServiceResultData {
    host: string
    port: number
    protocol: string
    reachable: boolean
    response_ms: number | null
    detail: string | null
    error: string | null
}

interface NetworkInfoResult {
    hostname: string
    gateway: string | null
    dns_servers: string[]
    interfaces: {
        name: string
        ip: string
        netmask: string
        mac: string
        is_up: boolean
        speed_mbps: number
    }[]
}

interface TracerouteHop {
    hop: number
    ip: string | null
    hostname: string | null
    rtt_ms: number | null
    timed_out: boolean
}

interface TracerouteResult {
    host: string
    hops: TracerouteHop[]
    reached: boolean
}

interface DnsResult {
    query: string
    query_type: string
    addresses: string[]
    hostname: string | null
    aliases: string[]
    error: string | null
}

interface ConnectionEntry {
    protocol: string
    local_ip: string
    local_port: number
    remote_ip: string
    remote_port: number
    status: string
    pid: number | null
    process_name: string | null
}

interface ConnectionsResult {
    count: number
    connections: ConnectionEntry[]
}

type TabKey = 'ping' | 'ports' | 'devices' | 'info' | 'traceroute' | 'dns' | 'connections'

/* ── Props / Emits ──────────────────────────────────────────────────── */

defineProps<{ visible: boolean }>()
const emit = defineEmits<{ close: [] }>()

/* ── Tab state ──────────────────────────────────────────────────────── */

const activeTab = ref<TabKey>('ping')
const tabs: { key: TabKey; icon: string; label: string }[] = [
    { key: 'ping', icon: '🏓', label: 'Ping' },
    { key: 'ports', icon: '🔌', label: 'Ports' },
    { key: 'traceroute', icon: '🔀', label: 'Route' },
    { key: 'dns', icon: '🔍', label: 'DNS' },
    { key: 'connections', icon: '🔗', label: 'Conns' },
    { key: 'devices', icon: '📡', label: 'Devices' },
    { key: 'info', icon: 'ℹ️', label: 'Info' }
]

/* ── Ping ───────────────────────────────────────────────────────────── */

const pingHost = ref('192.168.1.1')
const pingCount = ref(4)
const pingResult = ref<PingResult | null>(null)
const pingLoading = ref(false)
const pingError = ref('')

async function doPing(): Promise<void> {
    const host = pingHost.value.trim()
    if (!host) return
    pingLoading.value = true
    pingError.value = ''
    pingResult.value = null
    try {
        const res = await api.executePluginTool<PingResult>(
            'network_probe', 'ping_host', { host, count: pingCount.value }
        )
        if (res.success) pingResult.value = res.content
        else pingError.value = res.error_message ?? 'Ping failed'
    } catch {
        pingError.value = 'Cannot reach the server'
    } finally {
        pingLoading.value = false
    }
}

/* ── Port scan ──────────────────────────────────────────────────────── */

const scanHost = ref('192.168.1.1')
const scanPortsInput = ref('80, 443, 22, 8080')
const scanResult = ref<ScanResult | null>(null)
const scanLoading = ref(false)
const scanError = ref('')
const showClosedPorts = ref(false)

/* Service check (quick-check section) */
const svcHost = ref('')
const svcPort = ref(80)
const svcProtocol = ref<'tcp' | 'udp'>('tcp')
const svcResult = ref<ServiceResultData | null>(null)
const svcLoading = ref(false)
const svcError = ref('')

function parsePorts(input: string): number[] {
    return input
        .split(',')
        .map((s) => parseInt(s.trim(), 10))
        .filter((n) => !isNaN(n) && n > 0 && n <= 65535)
}

async function doScan(): Promise<void> {
    const host = scanHost.value.trim()
    const ports = parsePorts(scanPortsInput.value)
    if (!host || !ports.length) return
    scanLoading.value = true
    scanError.value = ''
    scanResult.value = null
    showClosedPorts.value = false
    try {
        const res = await api.executePluginTool<ScanResult>(
            'network_probe', 'scan_ports', { host, ports }
        )
        if (res.success) scanResult.value = res.content
        else scanError.value = res.error_message ?? 'Scan failed'
    } catch {
        scanError.value = 'Cannot reach the server'
    } finally {
        scanLoading.value = false
    }
}

async function checkService(): Promise<void> {
    const host = svcHost.value.trim()
    if (!host) return
    svcLoading.value = true
    svcError.value = ''
    svcResult.value = null
    try {
        const res = await api.executePluginTool<ServiceResultData>(
            'network_probe', 'check_service',
            { host, port: svcPort.value, protocol: svcProtocol.value }
        )
        if (res.success) svcResult.value = res.content
        else svcError.value = res.error_message ?? 'Check failed'
    } catch {
        svcError.value = 'Cannot reach the server'
    } finally {
        svcLoading.value = false
    }
}

/* ── Devices ────────────────────────────────────────────────────────── */

const deviceResult = ref<DeviceResult | null>(null)
const deviceLoading = ref(false)
const deviceError = ref('')

const deviceCount = computed(() => deviceResult.value?.count ?? 0)

async function discoverDevices(): Promise<void> {
    deviceLoading.value = true
    deviceError.value = ''
    deviceResult.value = null
    try {
        const res = await api.executePluginTool<DeviceResult>(
            'network_probe', 'discover_local_devices', {}
        )
        if (res.success) deviceResult.value = res.content
        else deviceError.value = res.error_message ?? 'Discovery failed'
    } catch {
        deviceError.value = 'Cannot reach the server'
    } finally {
        deviceLoading.value = false
    }
}

/* ── Network Info ───────────────────────────────────────────────────── */

const infoResult = ref<NetworkInfoResult | null>(null)
const infoLoading = ref(false)
const infoError = ref('')

async function getNetworkInfo(): Promise<void> {
    infoLoading.value = true
    infoError.value = ''
    infoResult.value = null
    try {
        const res = await api.executePluginTool<NetworkInfoResult>(
            'network_probe', 'get_local_network_info', {}
        )
        if (res.success) infoResult.value = res.content
        else infoError.value = res.error_message ?? 'Failed to get info'
    } catch {
        infoError.value = 'Cannot reach the server'
    } finally {
        infoLoading.value = false
    }
}

/* ── Traceroute ─────────────────────────────────────────────────────── */

const traceHost = ref('192.168.1.1')
const traceMaxHops = ref(15)
const traceResult = ref<TracerouteResult | null>(null)
const traceLoading = ref(false)
const traceError = ref('')

async function doTraceroute(): Promise<void> {
    const host = traceHost.value.trim()
    if (!host) return
    traceLoading.value = true
    traceError.value = ''
    traceResult.value = null
    try {
        const res = await api.executePluginTool<TracerouteResult>(
            'network_probe', 'traceroute_host',
            { host, max_hops: traceMaxHops.value }
        )
        if (res.success) traceResult.value = res.content
        else traceError.value = res.error_message ?? 'Traceroute failed'
    } catch {
        traceError.value = 'Cannot reach the server'
    } finally {
        traceLoading.value = false
    }
}

/* ── DNS Resolve ────────────────────────────────────────────────────── */

const dnsQuery = ref('')
const dnsResult = ref<DnsResult | null>(null)
const dnsLoading = ref(false)
const dnsError = ref('')

async function doResolve(): Promise<void> {
    const query = dnsQuery.value.trim()
    if (!query) return
    dnsLoading.value = true
    dnsError.value = ''
    dnsResult.value = null
    try {
        const res = await api.executePluginTool<DnsResult>(
            'network_probe', 'resolve_hostname', { query }
        )
        if (res.success) dnsResult.value = res.content
        else dnsError.value = res.error_message ?? 'DNS lookup failed'
    } catch {
        dnsError.value = 'Cannot reach the server'
    } finally {
        dnsLoading.value = false
    }
}

/* ── Open Connections ───────────────────────────────────────────────── */

const connProtocol = ref<'tcp' | 'udp' | 'all'>('tcp')
const connResult = ref<ConnectionsResult | null>(null)
const connLoading = ref(false)
const connError = ref('')

async function getConnections(): Promise<void> {
    connLoading.value = true
    connError.value = ''
    connResult.value = null
    try {
        const res = await api.executePluginTool<ConnectionsResult>(
            'network_probe', 'get_open_connections',
            { protocol: connProtocol.value }
        )
        if (res.success) connResult.value = res.content
        else connError.value = res.error_message ?? 'Failed to list connections'
    } catch {
        connError.value = 'Cannot reach the server'
    } finally {
        connLoading.value = false
    }
}

/* ── Helpers ────────────────────────────────────────────────────────── */

function fmtMs(v: number | null): string {
    return v != null ? `${v.toFixed(1)} ms` : '—'
}
</script>

<template>
    <Transition name="panel-slide">
        <aside v-if="visible" class="net-probe">
            <!-- Header -->
            <header class="net-probe__header">
                <span class="net-probe__title">
                    🔬 Network Probe
                    <span v-if="deviceCount" class="net-probe__badge">{{ deviceCount }}</span>
                </span>
                <button class="net-probe__close" aria-label="Close panel" @click="emit('close')">✕</button>
            </header>

            <!-- Tabs -->
            <nav class="net-probe__tabs" role="tablist" aria-label="Network probe tabs">
                <button v-for="t in tabs" :key="t.key" role="tab" :aria-selected="activeTab === t.key"
                    class="net-probe__tab" :class="{ 'net-probe__tab--active': activeTab === t.key }"
                    @click="activeTab = t.key">
                    {{ t.icon }} {{ t.label }}
                </button>
            </nav>

            <!-- Tab content -->
            <div class="net-probe__body">
                <!-- ─── Ping ─────────────────────────────────────────── -->
                <div v-if="activeTab === 'ping'" class="net-probe__section">
                    <div class="net-probe__field">
                        <label class="net-probe__label">Host</label>
                        <input v-model="pingHost" class="net-probe__input" type="text" placeholder="192.168.1.1"
                            @keydown.enter="doPing" />
                    </div>
                    <div class="net-probe__field">
                        <label class="net-probe__label">Count</label>
                        <input v-model.number="pingCount" class="net-probe__input net-probe__input--sm" type="number"
                            min="1" max="10" />
                    </div>
                    <button class="net-probe__btn" :disabled="pingLoading" @click="doPing">
                        <span v-if="pingLoading" class="net-probe__spinner" />
                        {{ pingLoading ? 'Pinging…' : '🏓 Ping' }}
                    </button>

                    <div v-if="pingError" class="net-probe__error">⚠️ {{ pingError }}</div>

                    <div v-if="pingResult" class="net-probe__card">
                        <div class="net-probe__row">
                            <span class="net-probe__label-sm">Status</span>
                            <span class="net-probe__dot"
                                :class="pingResult.reachable ? 'net-probe__dot--ok' : 'net-probe__dot--fail'" />
                            <span :class="pingResult.reachable ? 'net-probe__text--ok' : 'net-probe__text--fail'">
                                {{ pingResult.reachable ? 'Reachable' : 'Unreachable' }}
                            </span>
                        </div>
                        <div class="net-probe__row">
                            <span class="net-probe__label-sm">Packets</span>
                            <span>{{ pingResult.sent }} sent · {{ pingResult.received }} received</span>
                        </div>
                        <div class="net-probe__row">
                            <span class="net-probe__label-sm">Loss</span>
                            <span>{{ pingResult.loss_pct.toFixed(1) }}%</span>
                        </div>
                        <div v-if="pingResult.reachable" class="net-probe__row">
                            <span class="net-probe__label-sm">Latency</span>
                            <span>avg {{ fmtMs(pingResult.avg_ms) }} · min {{ fmtMs(pingResult.min_ms) }} · max {{
                                fmtMs(pingResult.max_ms) }}</span>
                        </div>
                    </div>
                </div>

                <!-- ─── Ports ────────────────────────────────────────── -->
                <div v-if="activeTab === 'ports'" class="net-probe__section">
                    <div class="net-probe__field">
                        <label class="net-probe__label">Host</label>
                        <input v-model="scanHost" class="net-probe__input" type="text" placeholder="192.168.1.1"
                            @keydown.enter="doScan" />
                    </div>
                    <div class="net-probe__field">
                        <label class="net-probe__label">Ports (comma-separated)</label>
                        <input v-model="scanPortsInput" class="net-probe__input" type="text"
                            placeholder="80, 443, 22, 8080" @keydown.enter="doScan" />
                    </div>
                    <button class="net-probe__btn" :disabled="scanLoading" @click="doScan">
                        <span v-if="scanLoading" class="net-probe__spinner" />
                        {{ scanLoading ? 'Scanning…' : '🔌 Scan' }}
                    </button>

                    <div v-if="scanError" class="net-probe__error">⚠️ {{ scanError }}</div>

                    <div v-if="scanResult" class="net-probe__card">
                        <div class="net-probe__row">
                            <span class="net-probe__label-sm">Host</span>
                            <span>{{ scanResult.host }}</span>
                        </div>
                        <div class="net-probe__row">
                            <span class="net-probe__label-sm">Scanned</span>
                            <span>{{ scanResult.total_scanned }} ports</span>
                        </div>

                        <!-- Open ports -->
                        <div v-if="scanResult.open.length" class="net-probe__subcard">
                            <div class="net-probe__subcard-title net-probe__text--ok">
                                Open ({{ scanResult.open.length }})
                            </div>
                            <div v-for="p in scanResult.open" :key="p.port" class="net-probe__port-row">
                                <span class="net-probe__dot net-probe__dot--ok" />
                                <span class="net-probe__port-num">{{ p.port }}</span>
                                <span v-if="p.service_hint" class="net-probe__port-svc">{{ p.service_hint }}</span>
                            </div>
                        </div>

                        <!-- Closed ports (collapsed) -->
                        <div v-if="scanResult.closed.length">
                            <button class="net-probe__btn-link" @click="showClosedPorts = !showClosedPorts">
                                {{ showClosedPorts ? '▼' : '▶' }} Closed ({{ scanResult.closed.length }})
                            </button>
                            <div v-if="showClosedPorts" class="net-probe__closed-list">
                                <span v-for="cp in scanResult.closed" :key="cp.port" class="net-probe__closed-port">
                                    {{ cp.port }}
                                </span>
                            </div>
                        </div>
                    </div>

                    <!-- Service quick-check -->
                    <div class="net-probe__divider" />
                    <div class="net-probe__sub-title">Quick Service Check</div>
                    <div class="net-probe__field-row">
                        <input v-model="svcHost" class="net-probe__input" type="text" placeholder="Host"
                            @keydown.enter="checkService" />
                        <input v-model.number="svcPort" class="net-probe__input net-probe__input--sm" type="number"
                            min="1" max="65535" placeholder="Port" />
                        <select v-model="svcProtocol" class="net-probe__select">
                            <option value="tcp">TCP</option>
                            <option value="udp">UDP</option>
                        </select>
                    </div>
                    <button class="net-probe__btn net-probe__btn--sm" :disabled="svcLoading" @click="checkService">
                        <span v-if="svcLoading" class="net-probe__spinner" />
                        {{ svcLoading ? 'Checking…' : '⚡ Check' }}
                    </button>
                    <div v-if="svcError" class="net-probe__error">⚠️ {{ svcError }}</div>
                    <div v-if="svcResult" class="net-probe__card">
                        <div class="net-probe__row">
                            <span class="net-probe__label-sm">Status</span>
                            <span class="net-probe__dot"
                                :class="svcResult.reachable ? 'net-probe__dot--ok' : 'net-probe__dot--fail'" />
                            <span :class="svcResult.reachable ? 'net-probe__text--ok' : 'net-probe__text--fail'">
                                {{ svcResult.reachable ? 'Reachable' : 'Unreachable' }}
                            </span>
                        </div>
                        <div class="net-probe__row">
                            <span class="net-probe__label-sm">Protocol</span>
                            <span>{{ svcResult.protocol }}</span>
                        </div>
                        <div v-if="svcResult.response_ms != null" class="net-probe__row">
                            <span class="net-probe__label-sm">Latency</span>
                            <span>{{ svcResult.response_ms.toFixed(1) }} ms</span>
                        </div>
                        <div v-if="svcResult.detail" class="net-probe__row">
                            <span class="net-probe__label-sm">Detail</span>
                            <span class="net-probe__mono">{{ svcResult.detail }}</span>
                        </div>
                        <div v-if="svcResult.error" class="net-probe__row">
                            <span class="net-probe__label-sm">Error</span>
                            <span class="net-probe__text--fail">{{ svcResult.error }}</span>
                        </div>
                    </div>
                </div>

                <!-- ─── Devices ──────────────────────────────────────── -->
                <div v-if="activeTab === 'devices'" class="net-probe__section">
                    <button class="net-probe__btn" :disabled="deviceLoading" @click="discoverDevices">
                        <span v-if="deviceLoading" class="net-probe__spinner" />
                        {{ deviceLoading ? 'Discovering…' : '📡 Discover Devices' }}
                    </button>

                    <div v-if="deviceError" class="net-probe__error">⚠️ {{ deviceError }}</div>

                    <template v-if="deviceResult">
                        <div class="net-probe__count">{{ deviceResult.count }} device(s) found</div>
                        <div v-for="(d, i) in deviceResult.devices" :key="i" class="net-probe__card">
                            <div class="net-probe__row">
                                <span class="net-probe__label-sm">IP</span>
                                <span class="net-probe__mono">{{ d.ip }}</span>
                            </div>
                            <div class="net-probe__row">
                                <span class="net-probe__label-sm">MAC</span>
                                <span class="net-probe__mono">{{ d.mac ?? '—' }}</span>
                            </div>
                            <div class="net-probe__row">
                                <span class="net-probe__label-sm">Hostname</span>
                                <span>{{ d.hostname ?? 'unknown' }}</span>
                            </div>
                        </div>
                    </template>
                </div>

                <!-- ─── Info ─────────────────────────────────────────── -->
                <div v-if="activeTab === 'info'" class="net-probe__section">
                    <button class="net-probe__btn" :disabled="infoLoading" @click="getNetworkInfo">
                        <span v-if="infoLoading" class="net-probe__spinner" />
                        {{ infoLoading ? 'Loading…' : '🔄 Refresh' }}
                    </button>

                    <div v-if="infoError" class="net-probe__error">⚠️ {{ infoError }}</div>

                    <template v-if="infoResult">
                        <div class="net-probe__card">
                            <div class="net-probe__row">
                                <span class="net-probe__label-sm">Hostname</span>
                                <span class="net-probe__mono">{{ infoResult.hostname }}</span>
                            </div>
                            <div class="net-probe__row">
                                <span class="net-probe__label-sm">Gateway</span>
                                <span class="net-probe__mono">{{ infoResult.gateway ?? '—' }}</span>
                            </div>
                            <div class="net-probe__row">
                                <span class="net-probe__label-sm">DNS</span>
                                <span class="net-probe__mono">{{ infoResult.dns_servers.join(', ') || '—' }}</span>
                            </div>
                        </div>

                        <div class="net-probe__sub-title">Interfaces</div>
                        <div v-for="(iface, idx) in infoResult.interfaces" :key="idx" class="net-probe__card">
                            <div class="net-probe__row">
                                <span class="net-probe__label-sm">Name</span>
                                <span class="net-probe__mono">{{ iface.name }}</span>
                            </div>
                            <div class="net-probe__row">
                                <span class="net-probe__label-sm">IP</span>
                                <span class="net-probe__mono">{{ iface.ip }}</span>
                            </div>
                            <div class="net-probe__row">
                                <span class="net-probe__label-sm">Netmask</span>
                                <span class="net-probe__mono">{{ iface.netmask }}</span>
                            </div>
                            <div class="net-probe__row">
                                <span class="net-probe__label-sm">MAC</span>
                                <span class="net-probe__mono">{{ iface.mac }}</span>
                            </div>
                            <div class="net-probe__row">
                                <span class="net-probe__label-sm">Status</span>
                                <span class="net-probe__dot"
                                    :class="iface.is_up ? 'net-probe__dot--ok' : 'net-probe__dot--fail'" />
                                <span :class="iface.is_up ? 'net-probe__text--ok' : 'net-probe__text--fail'">
                                    {{ iface.is_up ? 'Up' : 'Down' }}
                                </span>
                            </div>
                            <div class="net-probe__row">
                                <span class="net-probe__label-sm">Speed</span>
                                <span>{{ iface.speed_mbps > 0 ? `${iface.speed_mbps} Mbps` : '—' }}</span>
                            </div>
                        </div>
                    </template>
                </div>

                <!-- ─── Traceroute ───────────────────────────────────── -->
                <div v-if="activeTab === 'traceroute'" class="net-probe__section">
                    <div class="net-probe__field">
                        <label class="net-probe__label">Host</label>
                        <input v-model="traceHost" class="net-probe__input" type="text" placeholder="192.168.1.1"
                            @keydown.enter="doTraceroute" />
                    </div>
                    <div class="net-probe__field">
                        <label class="net-probe__label">Max Hops</label>
                        <input v-model.number="traceMaxHops" class="net-probe__input net-probe__input--sm" type="number"
                            min="1" max="30" />
                    </div>
                    <button class="net-probe__btn" :disabled="traceLoading" @click="doTraceroute">
                        <span v-if="traceLoading" class="net-probe__spinner" />
                        {{ traceLoading ? 'Tracing…' : '🔀 Traceroute' }}
                    </button>

                    <div v-if="traceError" class="net-probe__error">⚠️ {{ traceError }}</div>

                    <template v-if="traceResult">
                        <div class="net-probe__card">
                            <div class="net-probe__row">
                                <span class="net-probe__label-sm">Target</span>
                                <span class="net-probe__mono">{{ traceResult.host }}</span>
                            </div>
                            <div class="net-probe__row">
                                <span class="net-probe__label-sm">Status</span>
                                <span class="net-probe__dot"
                                    :class="traceResult.reached ? 'net-probe__dot--ok' : 'net-probe__dot--fail'" />
                                <span :class="traceResult.reached ? 'net-probe__text--ok' : 'net-probe__text--fail'">
                                    {{ traceResult.reached ? 'Reached' : 'Not reached' }}
                                </span>
                            </div>
                        </div>

                        <div v-if="traceResult.hops.length" class="net-probe__sub-title">
                            Hops ({{ traceResult.hops.length }})
                        </div>
                        <div v-for="h in traceResult.hops" :key="h.hop" class="net-probe__card">
                            <div class="net-probe__row">
                                <span class="net-probe__label-sm">Hop {{ h.hop }}</span>
                                <span v-if="h.timed_out" class="net-probe__text--fail">* * *</span>
                                <template v-else>
                                    <span class="net-probe__mono">{{ h.ip ?? '—' }}</span>
                                    <span v-if="h.hostname" class="net-probe__port-svc">({{ h.hostname }})</span>
                                </template>
                            </div>
                            <div v-if="!h.timed_out && h.rtt_ms != null" class="net-probe__row">
                                <span class="net-probe__label-sm">RTT</span>
                                <span>{{ fmtMs(h.rtt_ms) }}</span>
                            </div>
                        </div>
                    </template>
                </div>

                <!-- ─── DNS ──────────────────────────────────────────── -->
                <div v-if="activeTab === 'dns'" class="net-probe__section">
                    <div class="net-probe__field">
                        <label class="net-probe__label">Hostname or IP</label>
                        <input v-model="dnsQuery" class="net-probe__input" type="text"
                            placeholder="my-nas.local or 192.168.1.1" @keydown.enter="doResolve" />
                    </div>
                    <button class="net-probe__btn" :disabled="dnsLoading" @click="doResolve">
                        <span v-if="dnsLoading" class="net-probe__spinner" />
                        {{ dnsLoading ? 'Resolving…' : '🔍 Resolve' }}
                    </button>

                    <div v-if="dnsError" class="net-probe__error">⚠️ {{ dnsError }}</div>

                    <div v-if="dnsResult" class="net-probe__card">
                        <div class="net-probe__row">
                            <span class="net-probe__label-sm">Query</span>
                            <span class="net-probe__mono">{{ dnsResult.query }}</span>
                        </div>
                        <div class="net-probe__row">
                            <span class="net-probe__label-sm">Type</span>
                            <span>{{ dnsResult.query_type === 'forward' ? 'Forward (A)' : 'Reverse (PTR)' }}</span>
                        </div>
                        <div v-if="dnsResult.hostname" class="net-probe__row">
                            <span class="net-probe__label-sm">Hostname</span>
                            <span class="net-probe__mono">{{ dnsResult.hostname }}</span>
                        </div>
                        <div v-if="dnsResult.addresses.length" class="net-probe__row">
                            <span class="net-probe__label-sm">Addresses</span>
                            <span class="net-probe__mono">{{ dnsResult.addresses.join(', ') }}</span>
                        </div>
                        <div v-if="dnsResult.aliases.length" class="net-probe__row">
                            <span class="net-probe__label-sm">Aliases</span>
                            <span class="net-probe__mono">{{ dnsResult.aliases.join(', ') }}</span>
                        </div>
                        <div v-if="dnsResult.error" class="net-probe__row">
                            <span class="net-probe__label-sm">Error</span>
                            <span class="net-probe__text--fail">{{ dnsResult.error }}</span>
                        </div>
                    </div>
                </div>

                <!-- ─── Connections ──────────────────────────────────── -->
                <div v-if="activeTab === 'connections'" class="net-probe__section">
                    <div class="net-probe__field-row">
                        <select v-model="connProtocol" class="net-probe__select">
                            <option value="tcp">TCP</option>
                            <option value="udp">UDP</option>
                            <option value="all">All</option>
                        </select>
                        <button class="net-probe__btn" :disabled="connLoading" @click="getConnections">
                            <span v-if="connLoading" class="net-probe__spinner" />
                            {{ connLoading ? 'Loading…' : '🔗 List Connections' }}
                        </button>
                    </div>

                    <div v-if="connError" class="net-probe__error">⚠️ {{ connError }}</div>

                    <template v-if="connResult">
                        <div class="net-probe__count">{{ connResult.count }} active connection(s)</div>
                        <div v-for="(c, i) in connResult.connections" :key="i" class="net-probe__card">
                            <div class="net-probe__row">
                                <span class="net-probe__label-sm">Proto</span>
                                <span class="net-probe__conn-proto">{{ c.protocol.toUpperCase() }}</span>
                                <span class="net-probe__conn-status">{{ c.status }}</span>
                            </div>
                            <div class="net-probe__row">
                                <span class="net-probe__label-sm">Local</span>
                                <span class="net-probe__mono">{{ c.local_ip }}:{{ c.local_port }}</span>
                            </div>
                            <div class="net-probe__row">
                                <span class="net-probe__label-sm">Remote</span>
                                <span class="net-probe__mono">{{ c.remote_ip }}:{{ c.remote_port }}</span>
                            </div>
                            <div v-if="c.process_name" class="net-probe__row">
                                <span class="net-probe__label-sm">Process</span>
                                <span>{{ c.process_name }}<span v-if="c.pid" class="net-probe__port-svc"> (PID {{ c.pid
                                        }})</span></span>
                            </div>
                        </div>
                    </template>
                </div>
            </div>
        </aside>
    </Transition>
</template>

<style scoped>
/* ── Panel container ────────────────────────────────────────────────── */

.net-probe {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    width: 400px;
    display: flex;
    flex-direction: column;
    background: var(--bg-primary);
    border-left: 1px solid var(--border);
    z-index: var(--z-dropdown);
    color: var(--text-primary);
    font-size: 13px;
}

/* ── Header ─────────────────────────────────────────────────────────── */

.net-probe__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 14px;
    border-bottom: 1px solid var(--border);
}

.net-probe__title {
    font-weight: 600;
    font-size: 14px;
    display: flex;
    align-items: center;
    gap: 6px;
}

.net-probe__badge {
    padding: 1px 7px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 700;
    background: var(--accent);
    color: var(--bg-primary);
}

.net-probe__close {
    background: none;
    border: none;
    color: var(--text-secondary);
    font-size: 16px;
    cursor: pointer;
    padding: 2px 6px;
    border-radius: var(--radius-sm);
    transition: background var(--transition-fast);
}

.net-probe__close:hover {
    background: var(--white-medium);
}

/* ── Tabs ───────────────────────────────────────────────────────────── */

.net-probe__tabs {
    display: flex;
    gap: 0;
    padding: 0 14px;
    border-bottom: 1px solid var(--border);
}

.net-probe__tab {
    flex: 1;
    padding: 8px 4px 6px;
    border: none;
    background: none;
    color: var(--text-secondary);
    font-size: 12px;
    cursor: pointer;
    border-bottom: 2px solid transparent;
    transition: color var(--transition-fast),
        border-color var(--transition-fast);
    white-space: nowrap;
}

.net-probe__tab:hover {
    color: var(--text-primary);
}

.net-probe__tab--active {
    color: var(--accent);
    border-bottom-color: var(--accent);
}

/* ── Body ───────────────────────────────────────────────────────────── */

.net-probe__body {
    flex: 1;
    overflow-y: auto;
    padding: 10px 14px;
}

.net-probe__section {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

/* ── Form elements ──────────────────────────────────────────────────── */

.net-probe__field {
    display: flex;
    flex-direction: column;
    gap: 3px;
}

.net-probe__field-row {
    display: flex;
    gap: 6px;
}

.net-probe__label {
    font-size: 11px;
    color: var(--text-secondary);
    font-weight: 500;
}

.net-probe__input {
    width: 100%;
    box-sizing: border-box;
    padding: 7px 10px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    background: var(--surface-2);
    color: var(--text-primary);
    font-size: 13px;
    font-family: inherit;
    outline: none;
    transition: border-color var(--transition-fast);
}

.net-probe__input::placeholder {
    color: var(--text-muted);
}

.net-probe__input:focus {
    border-color: var(--accent);
}

.net-probe__input--sm {
    width: 80px;
    flex-shrink: 0;
}

.net-probe__select {
    padding: 7px 8px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    background: var(--surface-2);
    color: var(--text-primary);
    font-size: 12px;
    font-family: inherit;
    outline: none;
    cursor: pointer;
    flex-shrink: 0;
}

.net-probe__select:focus {
    border-color: var(--accent);
}

/* ── Buttons ────────────────────────────────────────────────────────── */

.net-probe__btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 7px 14px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    background: var(--surface-3);
    color: var(--text-primary);
    font-size: 12px;
    font-family: inherit;
    cursor: pointer;
    transition: background var(--transition-fast),
        border-color var(--transition-fast);
}

.net-probe__btn:hover:not(:disabled) {
    background: var(--accent-dim);
    border-color: var(--accent);
}

.net-probe__btn:disabled {
    opacity: 0.5;
    cursor: wait;
}

.net-probe__btn--sm {
    padding: 5px 10px;
    font-size: 11px;
}

.net-probe__btn-link {
    background: none;
    border: none;
    color: var(--text-secondary);
    font-size: 12px;
    cursor: pointer;
    padding: 4px 0;
    text-align: left;
    transition: color var(--transition-fast);
}

.net-probe__btn-link:hover {
    color: var(--text-primary);
}

/* ── Cards & rows ───────────────────────────────────────────────────── */

.net-probe__card {
    padding: 10px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    background: var(--surface-1);
    display: flex;
    flex-direction: column;
    gap: 5px;
}

.net-probe__subcard {
    margin-top: 4px;
    padding: 8px;
    border-radius: 4px;
    background: var(--surface-2);
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.net-probe__subcard-title {
    font-size: 11px;
    font-weight: 600;
    margin-bottom: 2px;
}

.net-probe__row {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    line-height: 1.4;
}

.net-probe__label-sm {
    font-size: 11px;
    color: var(--text-muted);
    min-width: 64px;
    flex-shrink: 0;
}

.net-probe__mono {
    font-family: 'Cascadia Code', 'Fira Code', monospace;
    font-size: 12px;
}

/* ── Status indicators ──────────────────────────────────────────────── */

.net-probe__dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}

.net-probe__dot--ok {
    background: var(--success);
    box-shadow: 0 0 4px var(--success);
}

.net-probe__dot--fail {
    background: var(--danger);
    box-shadow: 0 0 4px var(--danger);
}

.net-probe__text--ok {
    color: var(--success);
    font-weight: 500;
}

.net-probe__text--fail {
    color: var(--danger);
    font-weight: 500;
}

/* ── Port scan specifics ────────────────────────────────────────────── */

.net-probe__port-row {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
}

.net-probe__port-num {
    font-family: 'Cascadia Code', 'Fira Code', monospace;
    font-weight: 600;
    min-width: 44px;
}

.net-probe__port-svc {
    color: var(--text-secondary);
    font-size: 11px;
}

.net-probe__closed-list {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 4px;
}

.net-probe__closed-port {
    font-size: 11px;
    font-family: 'Cascadia Code', 'Fira Code', monospace;
    color: var(--text-muted);
    padding: 1px 5px;
    background: var(--surface-2);
    border-radius: 3px;
}

/* ── Connection specifics ───────────────────────────────────────────── */

.net-probe__conn-proto {
    font-size: 11px;
    font-weight: 600;
    font-family: 'Cascadia Code', 'Fira Code', monospace;
}

.net-probe__conn-status {
    font-size: 10px;
    color: var(--text-secondary);
    padding: 1px 6px;
    background: var(--surface-2);
    border-radius: 3px;
    margin-left: auto;
}

/* ── Misc ───────────────────────────────────────────────────────────── */

.net-probe__divider {
    height: 1px;
    background: var(--white-medium);
    margin: 6px 0;
}

.net-probe__sub-title {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-secondary);
    margin-top: 4px;
}

.net-probe__count {
    font-size: 12px;
    color: var(--text-secondary);
    font-weight: 500;
}

.net-probe__error {
    font-size: 12px;
    color: var(--danger);
}

/* ── Spinner ────────────────────────────────────────────────────────── */

.net-probe__spinner {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    border: 2px solid var(--text-secondary);
    border-top-color: transparent;
    animation: net-probe-spin 0.7s linear infinite;
}

@keyframes net-probe-spin {
    to {
        transform: rotate(360deg);
    }
}

/* ── Slide transition ───────────────────────────────────────────────── */

.panel-slide-enter-active,
.panel-slide-leave-active {
    transition: transform 0.2s ease;
}

.panel-slide-enter-from,
.panel-slide-leave-to {
    transform: translateX(100%);
}
</style>
