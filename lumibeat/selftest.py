"""Built-in self test: ``LumiBeat Studio.exe --selftest``.

Exercises the real code paths without hardware: audio analysis on the demo track,
every effect, the Party director, Art-Net packets, the output mapping (serpentine
wiring, universes), the phone web server (login + commands) and, optionally, the GUI.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import time
import traceback

import numpy as np


_LOG = None


def _print(msg: str) -> None:
    """Print to the console (if any) and to selftest.log (windowed builds have no console)."""
    try:
        if sys.stdout is not None:
            print(msg, flush=True)
    except Exception:
        pass
    if _LOG is not None:
        _LOG.write(msg + "\n")
        _LOG.flush()


def _ok(name, cond, detail=""):
    _print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" – {detail}" if detail else ""))
    return bool(cond)


def run(screenshot: str | None = None, log_path: str = "selftest.log") -> int:
    global _LOG
    try:
        _LOG = open(log_path, "w", encoding="utf-8")
    except OSError:
        _LOG = None
    tmp = tempfile.mkdtemp(prefix="lumibeat-selftest-")
    os.environ["LUMIBEAT_HOME"] = tmp
    from .core.config import APP_VERSION, Config
    _print(f"LumiBeat Studio {APP_VERSION} self test (data: {tmp})")
    results = []
    try:
        results += test_mapping()
        results += test_audio()
        results += test_effects()
        results += test_party()
        results += test_artnet()
        results += test_web()
        test_devices()
        if screenshot:
            results += test_gui(screenshot)
    except Exception:
        _print(traceback.format_exc())
        results.append(False)
    ok = all(results)
    _print(f"\n{'PASSED' if ok else 'FAILED'}: {sum(results)}/{len(results)} checks")
    if _LOG:
        _LOG.close()
    return 0 if ok else 1


def test_mapping():
    from .core.config import Config
    from .core.mapping import OutputMapper
    cfg = Config.default()
    m = OutputMapper(cfg)
    r = []
    r.append(_ok("4 porturi × 3 profile × 84 px", m.port_len == [252] * 4, str(m.port_len)))
    r.append(_ok("universuri contigue (2/port)", m.port_universes == [[0, 1], [2, 3], [4, 5], [6, 7]], str(m.port_universes)))
    # serpentine: profile 2 (index 1) is wired top->bottom: its first data pixel is at the top
    frame = np.zeros((12, cfg.wall.matrix_rows, 3), np.float32)
    frame[1, -1] = (1, 0, 0)  # top pixel of profile 2 red
    unis = m.map(frame, 1.0)
    port1 = unis[0] + unis[1]
    first_px_of_p2 = 84 * 3
    r.append(_ok("compensare DATA ↓ (profil 2: primul pixel = sus)", port1[first_px_of_p2] > 0,
                 f"R={port1[first_px_of_p2]}"))
    frame[:] = 0
    frame[0, 0] = (0, 1, 0)   # bottom of profile 1 (data up) green
    unis = m.map(frame, 1.0)
    r.append(_ok("profil 1 DATA ↑ (primul pixel = jos)", unis[0][1] > 0))
    cfg.ports[0].color_order = "GRB"
    m = OutputMapper(cfg)
    unis = m.map(frame, 1.0)
    r.append(_ok("ordine culori GRB", unis[0][0] > 0 and unis[0][1] == 0))
    full = np.ones((12, cfg.wall.matrix_rows, 3), np.float32)
    cfg.output.power_limit_w = 100
    m = OutputMapper(cfg)
    m.map(full, 1.0)
    r.append(_ok("limitare putere", m.last_power_w <= 100.5 and m.last_scale < 1, f"{m.last_power_w:.1f} W"))
    return r


def _demo_features(seconds: float, start: float = 0.0):
    from .audio.analysis import AudioAnalyzer
    from .audio.demo import DemoSynth
    an = AudioAnalyzer(48000, 512)
    syn = DemoSynth(48000)
    if start:
        syn.n = int(start * 48000)
    for _ in range(int(seconds * 48000 / 512)):
        an.process(syn.render(512))
    return an


def test_audio():
    t0 = time.perf_counter()
    an = _demo_features(60)
    f = an.features
    dt = time.perf_counter() - t0
    r = [_ok("BPM detectat pe piesa demo (124)", abs(f.bpm - 124) < 2.5, f"{f.bpm:.1f} BPM, conf {f.bpm_confidence:.2f}"),
         _ok("bătăi urmărite", f.beat_count > 90, str(f.beat_count)),
         _ok("bass drop detectat", f.drop_count >= 1, str(f.drop_count)),
         _ok("analiză mai rapidă decât timpul real", dt < 30, f"60 s audio în {dt:.1f} s")]
    return r


def test_effects():
    from .core.config import Config
    from .core.geometry import build_geometry
    from .effects import REGISTRY, Ctx, LayeredEffect, Palette, default_spec
    from .audio.analysis import AudioFeatures
    g = build_geometry(Config.default())
    bad = []
    t0 = time.perf_counter()
    for k, cls in REGISTRY.items():
        try:
            e = cls(g)
            for i in range(30):
                f = AudioFeatures(level=0.6, bass=0.7, mid=0.5, high=0.4, bpm=124, beat_phase=(i % 15) / 15,
                                  bands=np.full(32, 0.5, np.float32), energy=0.6, energy_long=0.5)
                out = e.frame(Ctx(g=g, dt=1 / 60, audio=f, palette=Palette.named(cls.palette), beat=i % 15 == 0,
                                  kick=i % 15 == 0, drop=i == 10, strobe_ok=True))
                if out.shape != g.shape or not np.isfinite(out).all():
                    raise ValueError("bad output")
        except Exception as ex:
            bad.append(f"{k}: {ex}")
    ms = (time.perf_counter() - t0) / max(1, len(REGISTRY) * 30) * 1000
    music = sum(1 for c in REGISTRY.values() if c.category in ("music", "special"))
    amb = sum(1 for c in REGISTRY.values() if c.category == "ambient")
    le = LayeredEffect(g, default_spec())
    out = le.frame(Ctx(g=g, dt=1 / 60, audio=AudioFeatures(), palette=Palette.named("neon")))
    return [_ok(f"{len(REGISTRY)} efecte randate ({music} muzicale/speciale, {amb} ambient)", not bad and music >= 30,
                "; ".join(bad) or f"{ms:.2f} ms/cadru"),
            _ok("efect Studio pe straturi", out.shape == g.shape)]


def test_party():
    from .core.artnet import ArtNetOutput
    from .core.config import Config
    from .core.engine import Engine
    from .core.state import ShowState, StateStore
    from .audio.analysis import AudioAnalyzer
    from .audio.demo import DemoSynth
    cfg = Config.default()
    st = StateStore(ShowState(mode="party", party_preset="auto_dj"))
    an = AudioAnalyzer(48000, 512)
    syn = DemoSynth()
    eng = Engine(cfg, st, an, ArtNetOutput())
    effects, standby, sections = set(), False, set()
    t0 = time.perf_counter()
    for _ in range(60 * 146):
        an.process(syn.render(800))
        fo = eng.step(1 / 60)
        effects.add(fo.effect)
        sections.add(fo.section)
        standby |= fo.standby
    ms = (time.perf_counter() - t0) / (60 * 146) * 1000
    return [_ok("Party/Auto DJ schimbă efectele", len(effects) >= 6, f"{len(effects)} efecte, {ms:.2f} ms/cadru"),
            _ok("secțiuni detectate (drop, build-up…)", "DROP" in sections, ", ".join(sorted(s for s in sections if s))),
            _ok("standby ambiental la liniște", standby)]


def test_artnet():
    from .core.artnet import (ArtNetOutput, build_artdmx, build_artpoll, parse_artpollreply, parse_opcode)
    pkt = build_artdmx(0x0102, bytes(range(10)), 7)
    r = [_ok("pachet ArtDmx", pkt[:8] == b"Art-Net\x00" and pkt[8:10] == b"\x00\x50" and pkt[12] == 7
             and pkt[14] == 0x02 and pkt[15] == 0x01 and pkt[16:18] == b"\x00\x0a", pkt[:18].hex())]
    r.append(_ok("pachet ArtPoll", parse_opcode(build_artpoll()) == 0x2000))
    reply = bytearray(239)
    reply[:8] = b"Art-Net\x00"
    reply[8:10] = b"\x00\x21"
    reply[10:14] = bytes([192, 168, 1, 50])
    reply[18], reply[19] = 0, 1
    reply[26:26 + 6] = b"SP801E"
    reply[173] = 4
    reply[190:194] = bytes([0, 2, 4, 6])
    n = parse_artpollreply(bytes(reply), "192.168.1.50")
    r.append(_ok("parsare ArtPollReply", n and n.looks_like_sp801e and n.sw_out == [16, 18, 20, 22], str(n.sw_out if n else None)))
    out = ArtNetOutput()
    out.configure(True, "127.0.0.1", poll_interval=0)
    ok = out.send_frame({0: bytes(510), 1: bytes(246)})
    out.shutdown()
    r.append(_ok("trimitere UDP Art-Net (loopback)", ok, out.last_error))
    return r


def test_web():
    from .core.config import Config
    from .core.controller import Controller
    try:
        import httpx
    except Exception:
        _print("  [SKIP] httpx lipsește – testul web folosește urllib")
        return test_web_urllib()
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    cfg = Config.default()
    cfg.audio.source = "demo"
    cfg.web.port = port
    cfg.web.pin = "123456"
    ctrl = Controller(cfg)
    ctrl.start()
    r = []
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                httpx.get(base + "/health", timeout=0.5)
                break
            except Exception:
                time.sleep(0.1)
        with httpx.Client(base_url=base, timeout=3) as c:
            r.append(_ok("server web: refuz fără autentificare", c.get("/api/state").status_code == 401))
            r.append(_ok("server web: PIN greșit respins", c.post("/api/login", json={"pin": "000000"}).status_code == 401))
            r.append(_ok("server web: login PIN", c.post("/api/login", json={"pin": "123456"}).json().get("ok")))
            j = c.post("/api/cmd", json={"action": "auto_dj"}).json()
            r.append(_ok("server web: comandă Auto DJ", j["state"]["mode"] == "party"))
            j = c.post("/api/cmd", json={"action": "brightness", "value": 0.5}).json()
            r.append(_ok("server web: luminozitate", abs(j["state"]["brightness"] - 0.5) < 1e-6))
            cat = c.get("/api/catalog").json()
            r.append(_ok("server web: catalog efecte", len(cat["music"]) >= 30 and len(cat["ambient"]) >= 10))
            r.append(_ok("server web: pagina mobilă", "LumiBeat" in c.get("/").text))
    finally:
        ctrl.shutdown()
    return r


def test_web_urllib():
    import http.cookiejar
    import urllib.error
    import urllib.request
    from .core.config import Config
    from .core.controller import Controller
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    cfg = Config.default()
    cfg.audio.source = "demo"
    cfg.web.port = port
    cfg.web.pin = "123456"
    ctrl = Controller(cfg)
    ctrl.start()
    base = f"http://127.0.0.1:{port}"
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def req(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        rq = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with op.open(rq, timeout=3) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, ""
    r = []
    try:
        for _ in range(50):
            try:
                if req("/health")[0] == 200:
                    break
            except Exception:
                time.sleep(0.1)
        r.append(_ok("server web: refuz fără autentificare", req("/api/state")[0] == 401))
        r.append(_ok("server web: login PIN", req("/api/login", {"pin": "123456"})[0] == 200))
        code, txt = req("/api/cmd", {"action": "auto_dj"})
        r.append(_ok("server web: comandă Auto DJ", code == 200 and json.loads(txt)["state"]["mode"] == "party"))
        r.append(_ok("server web: pagina mobilă", "LumiBeat" in req("/")[1]))
    finally:
        ctrl.shutdown()
    return r


def test_devices():
    try:
        from .audio.capture import HAVE_PAW, list_devices
        d = list_devices()
        _print(f"  [INFO] WASAPI loopback disponibil: {HAVE_PAW}; dispozitive loopback: {len(d['loopback'])}, "
               f"intrări: {len(d['mic'])}")
        for n in d["loopback"][:6]:
            _print(f"         loopback: {n}")
    except Exception as e:
        _print(f"  [INFO] enumerare dispozitive audio: {e}")


def test_gui(path: str):
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from .app import resource_path
    from .core.controller import Controller
    from .ui import theme
    from .ui.main_window import MainWindow
    app = QApplication.instance() or QApplication(sys.argv[:1])
    theme.apply(app)
    ctrl = Controller(start_web=False)
    ctrl.cfg.audio.source = "demo"
    ctrl.start()
    win = MainWindow(ctrl, QIcon(str(resource_path("assets/icon.png"))))
    win.show()
    out = {}

    def shot():
        out["ok"] = win.grab().save(path)
        win.quit_app()
    QTimer.singleShot(3000, shot)
    app.exec()
    ctrl.shutdown()
    return [_ok("interfață grafică + captură ecran", out.get("ok"), path)]
