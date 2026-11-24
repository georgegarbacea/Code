"""Art-Net 4 output (ArtDmx / ArtSync) and node discovery (ArtPoll / ArtPollReply).

Designed for the BanlanX SP801E (WiFi) but works with any Art-Net node:
* unicast to the configured controller IP (recommended over WiFi), broadcast fallback
* ArtPoll discovery; ArtPollReply port-addresses can be applied to the port mapping
* automatic reconnection after network errors (WiFi drop, adapter change)
* controlled stop: blackout frames are sent before the transmission ends
* adaptive frame rate: backs off on socket congestion, recovers slowly
"""
from __future__ import annotations

import ipaddress
import socket
import struct
import threading
import time
from dataclasses import dataclass, field

ARTNET_PORT = 6454
ARTNET_ID = b"Art-Net\x00"
OP_POLL = 0x2000
OP_POLL_REPLY = 0x2100
OP_DMX = 0x5000
OP_SYNC = 0x5200
PROT_VER = 14


# ----------------------------------------------------------------------------- packets
def build_artdmx(port_address: int, data: bytes, sequence: int = 0, physical: int = 0) -> bytes:
    """ArtDmx packet. ``port_address`` is the 15-bit Port-Address (Net:SubNet:Universe)."""
    n = len(data)
    if n % 2:
        data = data + b"\x00"
        n += 1
    n = max(2, min(512, n))
    data = data[:n].ljust(n, b"\x00")
    return (
        ARTNET_ID
        + struct.pack("<H", OP_DMX)
        + struct.pack(">H", PROT_VER)
        + bytes((sequence & 0xFF, physical & 0xFF, port_address & 0xFF, (port_address >> 8) & 0x7F))
        + struct.pack(">H", n)
        + data
    )


def build_artpoll(flags: int = 0x00) -> bytes:
    return ARTNET_ID + struct.pack("<H", OP_POLL) + struct.pack(">H", PROT_VER) + bytes((flags, 0x10))


def build_artsync() -> bytes:
    return ARTNET_ID + struct.pack("<H", OP_SYNC) + struct.pack(">H", PROT_VER) + b"\x00\x00"


def parse_opcode(pkt: bytes) -> int | None:
    if len(pkt) < 10 or pkt[:8] != ARTNET_ID:
        return None
    return struct.unpack("<H", pkt[8:10])[0]


@dataclass
class NodeInfo:
    ip: str
    short_name: str = ""
    long_name: str = ""
    node_report: str = ""
    mac: str = ""
    firmware: str = ""
    oem: int = 0
    esta: int = 0
    num_ports: int = 0
    port_types: list[int] = field(default_factory=list)
    sw_out: list[int] = field(default_factory=list)      # full 15-bit port-addresses of outputs
    sw_in: list[int] = field(default_factory=list)
    good_output: list[int] = field(default_factory=list)
    bind_index: int = 0
    style: int = 0
    status1: int = 0
    status2: int = 0
    last_seen: float = 0.0

    @property
    def key(self) -> str:
        return f"{self.ip}#{self.bind_index}"

    @property
    def looks_like_sp801e(self) -> bool:
        txt = f"{self.short_name} {self.long_name}".upper()
        return any(k in txt for k in ("SP801", "SP80", "BANLANX", "SP8"))

    def describe(self) -> str:
        ports = ", ".join(str(p) for p in self.sw_out) or "-"
        return (
            f"{self.short_name or '?'} ({self.long_name or 'fără nume'}) @ {self.ip}  MAC {self.mac or '?'}  "
            f"firmware {self.firmware or '?'}  porturi: {self.num_ports}  universuri ieșire: {ports}"
        )


def parse_artpollreply(pkt: bytes, src_ip: str) -> NodeInfo | None:
    if parse_opcode(pkt) != OP_POLL_REPLY or len(pkt) < 197:
        return None

    def cstr(b: bytes) -> str:
        return b.split(b"\x00", 1)[0].decode("latin-1", "replace").strip()

    ip = ".".join(str(x) for x in pkt[10:14])
    if ip == "0.0.0.0":
        ip = src_ip
    net = pkt[18] & 0x7F
    sub = pkt[19] & 0x0F
    num_ports = min(4, pkt[173])
    sw_out = [(net << 8) | (sub << 4) | (pkt[190 + i] & 0x0F) for i in range(max(num_ports, 0))]
    sw_in = [(net << 8) | (sub << 4) | (pkt[186 + i] & 0x0F) for i in range(max(num_ports, 0))]
    mac = ""
    if len(pkt) >= 207:
        mac = ":".join(f"{x:02X}" for x in pkt[201:207])
    return NodeInfo(
        ip=ip,
        short_name=cstr(pkt[26:44]),
        long_name=cstr(pkt[44:108]),
        node_report=cstr(pkt[108:172]),
        mac=mac,
        firmware=f"{pkt[16]}.{pkt[17]}",
        oem=(pkt[20] << 8) | pkt[21],
        esta=pkt[24] | (pkt[25] << 8),
        num_ports=num_ports,
        port_types=list(pkt[174:178]),
        sw_out=sw_out,
        sw_in=sw_in,
        good_output=list(pkt[182:186]),
        bind_index=pkt[211] if len(pkt) > 211 else 0,
        style=pkt[200] if len(pkt) > 200 else 0,
        status1=pkt[23],
        status2=pkt[212] if len(pkt) > 212 else 0,
        last_seen=time.time(),
    )


# ------------------------------------------------------------------------- utilities
def local_ipv4_addresses() -> list[str]:
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    for probe in ("192.168.1.1", "10.0.0.1", "8.8.8.8"):
        ip = route_ip_for(probe)
        if ip:
            ips.add(ip)
    return sorted(i for i in ips if not i.startswith("127."))


def route_ip_for(target: str) -> str:
    """Local IP the OS would use to reach ``target`` (no packet is sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((target, ARTNET_PORT))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return ""


def broadcast_for(ip: str) -> str:
    try:
        return str(ipaddress.ip_network(f"{ip}/24", strict=False).broadcast_address)
    except ValueError:
        return "255.255.255.255"


def valid_ipv4(ip: str) -> bool:
    try:
        ipaddress.IPv4Address(ip)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------- output
class ArtNetOutput:
    """Thread-safe Art-Net sender with a background receive/reconnect thread."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sock: socket.socket | None = None
        self._bound_port = 0
        self._thread: threading.Thread | None = None
        self._running = False
        self.enabled = False
        self.controller_ip = ""
        self.interface_ip = ""
        self.art_sync = False
        self.use_sequence = True
        self.poll_interval = 6.0
        self.nodes: dict[str, NodeInfo] = {}
        self.status = "disabled"
        self.last_error = ""
        self.packets_sent = 0
        self.frames_sent = 0
        self.errors = 0
        self.fps_actual = 0.0
        self.bytes_per_s = 0.0
        self.fps_scale = 1.0       # adaptive back-off factor (0.3..1)
        self._seq: dict[int, int] = {}
        self._next_retry = 0.0
        self._last_poll = 0.0
        self._fps_t0 = time.monotonic()
        self._fps_frames = 0
        self._fps_bytes = 0
        self._last_reply = 0.0
        self._congestion_t = 0.0

    # -------------------------------------------------------------- lifecycle
    def configure(self, enabled: bool, controller_ip: str, interface_ip: str = "", art_sync: bool = False,
                  poll_interval: float = 6.0, use_sequence: bool = True) -> None:
        with self._lock:
            rebind = interface_ip != self.interface_ip
            self.controller_ip = controller_ip.strip()
            self.interface_ip = interface_ip.strip()
            self.art_sync = art_sync
            self.poll_interval = max(0.0, poll_interval)
            self.use_sequence = use_sequence
            if rebind:
                self._close()
            if enabled and not self.enabled:
                self.enabled = True
                self.status = "connecting"
            elif not enabled and self.enabled:
                self.stop_transmission()
        self.start()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="artnet-rx", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self.stop_transmission()
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.5)
        with self._lock:
            self._close()

    def stop_transmission(self, blackout: dict[int, bytes] | None = None) -> None:
        """Controlled stop: send a few blackout frames, then stop sending."""
        with self._lock:
            if self.enabled and blackout:
                for _ in range(3):
                    self._send_universes(blackout, count_frame=False)
                    time.sleep(0.03)
            self.enabled = False
            self.status = "disabled"

    # ------------------------------------------------------------------ socket
    def _open(self) -> bool:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 20)
            except OSError:
                pass
            host = self.interface_ip or ""
            try:
                s.bind((host, ARTNET_PORT))
            except OSError:
                # port 6454 busy (another Art-Net app) -> send from an ephemeral port
                s.bind((host, 0))
                self.last_error = "Portul UDP 6454 este ocupat de altă aplicație; descoperirea poate fi limitată."
            if hasattr(socket, "SIO_UDP_CONNRESET"):
                # Windows: an ICMP "port unreachable" would otherwise make recvfrom() fail repeatedly
                try:
                    s.ioctl(socket.SIO_UDP_CONNRESET, False)
                except (OSError, ValueError):
                    pass
            s.settimeout(0.25)
            self._sock = s
            self._bound_port = s.getsockname()[1]
            return True
        except OSError as e:
            self.last_error = f"Nu pot deschide socketul UDP: {e}"
            self.status = "error"
            self._sock = None
            return False

    def _close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None

    def _target(self) -> str:
        if self.controller_ip and valid_ipv4(self.controller_ip):
            return self.controller_ip
        local = self.interface_ip or route_ip_for("192.168.1.1")
        return broadcast_for(local) if local else "255.255.255.255"

    # ------------------------------------------------------------------ sending
    def send_frame(self, universes: dict[int, bytes]) -> bool:
        with self._lock:
            if not self.enabled:
                return False
            return self._send_universes(universes, count_frame=True)

    def _send_universes(self, universes: dict[int, bytes], count_frame: bool) -> bool:
        if self._sock is None:
            if time.monotonic() < self._next_retry or not self._open():
                self._next_retry = time.monotonic() + 2.0
                return False
        target = (self._target(), ARTNET_PORT)
        sent_bytes = 0
        try:
            for uni in sorted(universes):
                seq = 0
                if self.use_sequence:
                    seq = self._seq.get(uni, 0) % 255 + 1
                    self._seq[uni] = seq
                pkt = build_artdmx(uni, universes[uni], seq)
                self._sock.sendto(pkt, target)
                sent_bytes += len(pkt)
                self.packets_sent += 1
            if self.art_sync:
                pkt = build_artsync()
                self._sock.sendto(pkt, target)
                sent_bytes += len(pkt)
        except OSError as e:
            self.errors += 1
            win = getattr(e, "winerror", None)
            if win in (10035, 10055) or getattr(e, "errno", None) in (11, 55, 105):
                # buffer full / would block: congestion -> back off the frame rate
                self.fps_scale = max(0.3, self.fps_scale * 0.85)
                self._congestion_t = time.monotonic()
                self.last_error = "Congestie rețea: rata de cadre a fost redusă automat."
                return False
            self.last_error = f"Eroare rețea: {e}. Reconectare automată..."
            self.status = "error"
            self._close()
            self._next_retry = time.monotonic() + 2.0
            return False
        if count_frame:
            self.frames_sent += 1
            self._fps_frames += 1
            self._fps_bytes += sent_bytes
            now = time.monotonic()
            if now - self._fps_t0 >= 1.0:
                self.fps_actual = self._fps_frames / (now - self._fps_t0)
                self.bytes_per_s = self._fps_bytes / (now - self._fps_t0)
                self._fps_t0, self._fps_frames, self._fps_bytes = now, 0, 0
            if now - self._congestion_t > 5.0 and self.fps_scale < 1.0:
                self.fps_scale = min(1.0, self.fps_scale + 0.01)
            self._update_status()
        return True

    def _update_status(self) -> None:
        if not self.enabled:
            self.status = "disabled"
            return
        age = time.time() - self._last_reply
        if self._last_reply and age < 3 * max(2.0, self.poll_interval) + 2:
            self.status = "online"
        elif self._last_reply:
            self.status = "lost"
        else:
            self.status = "sending"

    # ---------------------------------------------------------------- discovery
    def poll(self) -> None:
        """Broadcast an ArtPoll (and unicast it to the configured controller)."""
        with self._lock:
            if self._sock is None and not self._open():
                return
            pkt = build_artpoll()
            targets = {"255.255.255.255"}
            local = self.interface_ip or route_ip_for(self.controller_ip or "192.168.1.1")
            if local:
                targets.add(broadcast_for(local))
            if self.controller_ip and valid_ipv4(self.controller_ip):
                targets.add(self.controller_ip)
            for t in targets:
                try:
                    self._sock.sendto(pkt, (t, ARTNET_PORT))
                except OSError:
                    pass
            self._last_poll = time.monotonic()

    def discover(self, wait: float = 2.0) -> list[NodeInfo]:
        """Blocking discovery used by the UI 'Scan' button."""
        self.start()
        t0 = time.time()
        self.poll()
        time.sleep(wait / 2)
        self.poll()
        time.sleep(wait / 2)
        return [n for n in self.nodes.values() if n.last_seen >= t0 - 0.1]

    def _run(self) -> None:
        while self._running:
            sock = self._sock
            if sock is None:
                with self._lock:
                    if self.enabled and time.monotonic() >= self._next_retry:
                        if not self._open():
                            self._next_retry = time.monotonic() + 2.0
                time.sleep(0.2)
                continue
            if self.enabled and self.poll_interval > 0 and time.monotonic() - self._last_poll > self.poll_interval:
                self.poll()
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                if self.enabled:
                    self._update_status()
                continue
            except OSError:
                time.sleep(0.2)
                continue
            op = parse_opcode(data)
            if op == OP_POLL_REPLY:
                node = parse_artpollreply(data, addr[0])
                if node:
                    self.nodes[node.key] = node
                    if not self.controller_ip or node.ip == self.controller_ip:
                        self._last_reply = time.time()

    # ------------------------------------------------------------------ helpers
    def controller_node(self) -> NodeInfo | None:
        for n in self.nodes.values():
            if n.ip == self.controller_ip:
                return n
        return None

    def stats(self) -> dict:
        return {
            "status": self.status,
            "fps": round(self.fps_actual, 1),
            "kbps": round(self.bytes_per_s * 8 / 1000, 1),
            "packets": self.packets_sent,
            "errors": self.errors,
            "last_error": self.last_error,
            "target": self._target() if self.enabled else "",
            "port": self._bound_port,
            "fps_scale": round(self.fps_scale, 2),
        }
