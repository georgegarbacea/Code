"""SP801E / Art-Net compatibility check (run from the Network page before going live)."""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field

from .artnet import ArtNetOutput, NodeInfo, local_ipv4_addresses, route_ip_for, valid_ipv4
from .config import Config
from .mapping import OutputMapper

# Published limits for the BanlanX SP801E (vendor listings / FCC filing):
SP801E_PORTS = 4
SP801E_MAX_PIXELS_PER_PORT = 1024
SP801E_MAX_PIXELS = 4096
# Practical Art-Net-over-WiFi budget (2.4 GHz, unicast). Conservative estimate.
WIFI_SAFE_PACKETS_PER_S = 900


@dataclass
class Check:
    level: str        # ok | warn | error | info
    title: str
    detail: str = ""


@dataclass
class CompatReport:
    checks: list[Check] = field(default_factory=list)
    node: NodeInfo | None = None
    recommended_fps: int = 30

    @property
    def ok(self) -> bool:
        return not any(c.level == "error" for c in self.checks)

    def add(self, level, title, detail=""):
        self.checks.append(Check(level, title, detail))


def run_check(cfg: Config, artnet: ArtNetOutput, nodes: list[NodeInfo] | None = None) -> CompatReport:
    rep = CompatReport()
    ip = cfg.network.controller_ip.strip()
    mapper = OutputMapper(cfg)
    mr = mapper.report()

    # 1. IP / subnet
    if not ip:
        rep.add("warn", "IP controler nesetat",
                "Fără IP, cadrele se trimit prin broadcast – pe WiFi broadcastul e lent și nesigur. "
                "Folosește «Caută controlere» sau introdu IP-ul din aplicația BanlanX / router.")
    elif not valid_ipv4(ip):
        rep.add("error", "IP invalid", f"«{ip}» nu este o adresă IPv4 validă.")
    else:
        local = route_ip_for(ip)
        same = False
        if local:
            try:
                same = ipaddress.ip_address(ip) in ipaddress.ip_network(f"{local}/24", strict=False)
            except ValueError:
                same = False
        if same:
            rep.add("ok", "Rețea", f"PC-ul ({local}) și controlerul ({ip}) sunt în aceeași subrețea.")
        else:
            rep.add("warn", "Subrețea diferită",
                    f"Interfața locală folosită ar fi {local or 'necunoscută'}. Verifică faptul că PC-ul și SP801E "
                    "sunt în aceeași rețea WiFi (mod STA) sau conectează PC-ul la hotspotul controlerului (mod AP).")
    rep.add("info", "Interfețe locale", ", ".join(local_ipv4_addresses()) or "niciuna")

    # 2. Discovery
    nodes = nodes if nodes is not None else artnet.discover(2.0)
    if ip:
        mine = [n for n in nodes if n.ip == ip]
    elif nodes:
        first_ip = nodes[0].ip
        mine = [n for n in nodes if n.ip == first_ip]
    else:
        mine = []
    mine.sort(key=lambda n: n.bind_index)
    node = mine[0] if mine else None
    rep.node = node
    if node:
        reported = sorted({u for n in mine for u in n.sw_out})
        name_ok = node.looks_like_sp801e
        rep.add("ok" if name_ok else "warn", "Răspuns ArtPoll", node.describe().split("  universuri")[0] +
                f"  universuri raportate: {', '.join(map(str, reported)) or '-'}" +
                (f" ({len(mine)} răspunsuri grupate)" if len(mine) > 1 else "") +
                ("" if name_ok else "  – numele nu indică un SP801E; verifică modelul."))
        used = sorted({u for us in mapper.port_universes for u in us})
        if reported:
            missing = [u for u in used if u not in reported]
            if missing:
                rep.add("warn", "Universuri pe care controlerul nu le raportează",
                        f"Aplicația trimite pe {', '.join(map(str, missing))}, controlerul raportează "
                        f"{', '.join(map(str, reported))}. Verifică universurile din BanlanX sau folosește "
                        "«Scanare universuri» din pagina Rețea.")
            else:
                rep.add("ok", "Mapare universuri", "Toate universurile trimise sunt raportate de controler.")
    else:
        rep.add("warn", "Fără răspuns ArtPoll",
                "Controlerul nu a răspuns la descoperire. Unele firmware-uri SP801E nu răspund la ArtPoll; "
                "transmisia unicast către IP funcționează oricum. Verifică: modul Art-Net activ în aplicația BanlanX, "
                "aceeași rețea, Windows Firewall (permite LumiBeat Studio pe rețele private).")
    if artnet._bound_port and artnet._bound_port != 6454:
        rep.add("warn", "Port UDP 6454 ocupat", "Altă aplicație Art-Net folosește portul; răspunsurile ArtPoll nu vor ajunge.")

    # 3. Capacity
    for i, n in enumerate(mapper.port_len):
        if n > SP801E_MAX_PIXELS_PER_PORT:
            rep.add("error", f"Portul {i + 1} depășește capacitatea",
                    f"{n} pixeli > {SP801E_MAX_PIXELS_PER_PORT} declarați pentru SP801E.")
    if mapper.total > SP801E_MAX_PIXELS:
        rep.add("error", "Capacitate totală depășită", f"{mapper.total} > {SP801E_MAX_PIXELS} pixeli.")
    if not any(c.title.startswith("Portul") and c.level == "error" for c in rep.checks):
        rep.add("ok", "Capacitate porturi", "Pixeli per port: " + ", ".join(
            f"P{i + 1}={n}" for i, n in enumerate(mapper.port_len)) + f" (max. {SP801E_MAX_PIXELS_PER_PORT}).")
    for e in mr.errors:
        rep.add("error", "Mapare", e)
    for w in mr.warnings:
        rep.add("warn", "Mapare", w)
    rep.add("info", "Universuri", "; ".join(
        f"P{i + 1}: {', '.join(map(str, u)) or '-'}" for i, u in enumerate(mapper.port_universes)))

    # 4. Frame rate budget
    n_uni = len(mapper.universe_len)
    hw = mapper.hardware_fps_cap()
    wifi_fps = WIFI_SAFE_PACKETS_PER_S / max(1, n_uni)
    rec = int(max(10, min(60, hw * 0.9, wifi_fps)))
    rep.recommended_fps = rec
    rep.add("info", "Rată de cadre",
            f"WS2811: max ≈ {hw:.0f} FPS pentru cel mai lung lanț; WiFi: {n_uni} universuri/cadru → "
            f"≈ {wifi_fps:.0f} FPS sigur. Recomandat: {rec} FPS (setat acum: {cfg.network.target_fps}).")
    if cfg.network.target_fps > rec:
        rep.add("warn", "FPS prea mare", f"Coboară ținta la {rec} FPS sau lasă «Rată adaptivă» activă.")
    rep.add("info", "Pixeli reali",
            "720 LED/m pe COB WS2811 nu înseamnă 720 pixeli/m: un IC WS2811 controlează un segment. "
            "Determină numărul real cu testul «Numărare pixeli» din pagina Instalație.")
    return rep
