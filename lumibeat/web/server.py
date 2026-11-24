"""Local web remote for phones (FastAPI + uvicorn, runs in a background thread).

Security model
* PIN login -> HMAC-signed session cookie (HttpOnly, SameSite=Strict)
* only clients from private / link-local / loopback addresses are accepted
  (the server is meant for the home WiFi, never for the internet)
* login attempts are rate limited per client address
* no UPnP / port forwarding is ever performed
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import threading
import time
from pathlib import Path

import numpy as np

log = logging.getLogger("lumibeat.web")

try:
    from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
    from fastapi.responses import FileResponse, JSONResponse, Response
    from fastapi.staticfiles import StaticFiles
    import uvicorn
    HAVE_WEB = True
except Exception:  # pragma: no cover
    HAVE_WEB = False

STATIC = Path(__file__).resolve().parent / "static"
COOKIE = "lb_session"


def is_private(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_loopback or ip.is_link_local


def lan_urls(port: int) -> list[str]:
    from ..core.artnet import local_ipv4_addresses
    ips = [ip for ip in local_ipv4_addresses() if is_private(ip)]
    return [f"http://{ip}:{port}" for ip in ips] or [f"http://{socket.gethostname()}:{port}"]


class Auth:
    def __init__(self, secret: str, pin: str):
        self.key = hashlib.sha256((secret + "|" + pin).encode()).digest()
        self.pin = pin
        self.attempts: dict[str, list[float]] = {}

    def make_token(self) -> str:
        nonce = secrets.token_urlsafe(16)
        sig = hmac.new(self.key, nonce.encode(), hashlib.sha256).digest()
        return nonce + "." + base64.urlsafe_b64encode(sig).decode().rstrip("=")

    def check(self, token: str | None) -> bool:
        if not token or "." not in token:
            return False
        nonce, sig = token.split(".", 1)
        good = base64.urlsafe_b64encode(hmac.new(self.key, nonce.encode(), hashlib.sha256).digest()).decode().rstrip("=")
        return hmac.compare_digest(sig, good)

    def allow_attempt(self, client: str) -> bool:
        now = time.time()
        lst = [t for t in self.attempts.get(client, []) if now - t < 60]
        self.attempts[client] = lst
        return len(lst) < 6

    def login(self, client: str, pin: str) -> str | None:
        self.attempts.setdefault(client, []).append(time.time())
        if hmac.compare_digest(str(pin).strip(), self.pin):
            self.attempts[client] = []
            return self.make_token()
        return None


def downsample_preview(prev: np.ndarray, max_rows: int = 72) -> tuple[int, int, bytes]:
    cols, rows, _ = prev.shape
    if rows > max_rows:
        idx = np.linspace(0, rows - 1, max_rows).astype(int)
        prev = prev[:, idx]
        rows = max_rows
    data = (np.clip(prev, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)
    return cols, rows, data.tobytes()


def build_app(ctrl) -> "FastAPI":
    cfg = ctrl.cfg
    auth = Auth(cfg.web.secret, cfg.web.pin)
    app = FastAPI(title="LumiBeat Remote", docs_url=None, redoc_url=None, openapi_url=None)
    allow_public = cfg.web.allow_public_clients

    @app.middleware("http")
    async def lan_only(request: Request, call_next):
        host = request.client.host if request.client else ""
        if not allow_public and not is_private(host):
            return JSONResponse({"error": "Acces permis doar din rețeaua locală."}, status_code=403)
        resp = await call_next(request)
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def authed(request: Request) -> bool:
        return auth.check(request.cookies.get(COOKIE))

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html", media_type="text/html")

    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    @app.post("/api/login")
    async def login(request: Request):
        host = request.client.host if request.client else "?"
        if not auth.allow_attempt(host):
            return JSONResponse({"ok": False, "error": "Prea multe încercări. Așteaptă un minut."}, status_code=429)
        try:
            body = await request.json()
        except Exception:
            body = {}
        token = auth.login(host, str(body.get("pin", "")))
        if not token:
            return JSONResponse({"ok": False, "error": "PIN greșit."}, status_code=401)
        resp = JSONResponse({"ok": True})
        resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=60 * 60 * 24 * 180)
        return resp

    @app.post("/api/logout")
    async def logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE)
        return resp

    @app.get("/api/session")
    async def session(request: Request):
        return {"ok": authed(request)}

    @app.get("/api/catalog")
    async def catalog(request: Request):
        if not authed(request):
            return JSONResponse({"error": "auth"}, status_code=401)
        return ctrl.catalog()

    @app.get("/api/state")
    async def state(request: Request):
        if not authed(request):
            return JSONResponse({"error": "auth"}, status_code=401)
        return {"state": public_state(ctrl), "status": ctrl.status()}

    @app.post("/api/cmd")
    async def cmd(request: Request):
        if not authed(request):
            return JSONResponse({"error": "auth"}, status_code=401)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "json"}, status_code=400)
        ok, msg = run_command(ctrl, body)
        return {"ok": ok, "message": msg, "state": public_state(ctrl)}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        host = websocket.client.host if websocket.client else ""
        if (not allow_public and not is_private(host)) or not auth.check(websocket.cookies.get(COOKIE)):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        last_ver = -1
        last_status = 0.0
        try:
            while True:
                now = time.time()
                if ctrl.store.version != last_ver:
                    last_ver = ctrl.store.version
                    await websocket.send_text(json.dumps({"type": "state", "state": public_state(ctrl)}))
                if now - last_status > 0.5:
                    last_status = now
                    await websocket.send_text(json.dumps({"type": "status", "status": ctrl.status()}))
                cols, rows, data = downsample_preview(ctrl.engine.latest.preview)
                await websocket.send_bytes(bytes((cols, rows)) + data)
                try:
                    msg = await asyncio.wait_for(websocket.receive_text(), timeout=0.066)
                    try:
                        run_command(ctrl, json.loads(msg))
                    except Exception:
                        pass
                except asyncio.TimeoutError:
                    pass
        except (WebSocketDisconnect, RuntimeError):
            return

    @app.get("/health")
    async def health():
        return Response("ok", media_type="text/plain")

    return app


def public_state(ctrl) -> dict:
    s = ctrl.state().to_dict()
    s.pop("studio_spec", None)
    s.pop("effect_params", None)
    return s


def run_command(ctrl, body: dict) -> tuple[bool, str]:
    action = str(body.get("action", ""))
    v = body.get("value")
    if action == "led":
        ctrl.toggle_led(None if v is None else bool(v))
    elif action == "mode":
        ctrl.set_state(mode=str(v))
    elif action == "effect":
        ctrl.set_state(music_effect=str(v), mode="music")
    elif action == "ambient":
        ctrl.set_state(ambient_scene=str(v), mode="ambient")
    elif action == "party_preset":
        ctrl.set_state(party_preset=str(v), mode="party")
    elif action == "auto_dj":
        ctrl.set_state(party_preset="auto_dj", mode="party")
    elif action == "palette":
        ctrl.set_state(palette=str(v))
    elif action == "color":
        st = ctrl.state()
        upd = {"color": str(v)}
        if st.mode == "ambient":
            upd["ambient_scene"] = "solid_color"
        else:
            upd["palette"] = "color"
        ctrl.set_state(**upd)
    elif action in ("brightness", "intensity", "speed", "sensitivity", "ambient_temp", "ambient_intensity",
                    "duration"):
        ctrl.set_state(**{action: v})
    elif action == "strobe":
        # the phone UI shows the photosensitivity warning before sending this
        ctrl.set_strobe(bool(v))
    elif action == "preset":
        return ctrl.apply_preset(str(v)), ""
    else:
        return False, "Comandă necunoscută"
    return True, ""


class WebRemote:
    def __init__(self, ctrl):
        self.ctrl = ctrl
        self.port = ctrl.cfg.web.port
        self.server = None
        self.thread: threading.Thread | None = None
        self.error = ""

    @property
    def urls(self) -> list[str]:
        return lan_urls(self.port)

    def start(self) -> None:
        if not HAVE_WEB:
            self.error = "FastAPI/uvicorn indisponibil"
            return
        app = build_app(self.ctrl)
        config = uvicorn.Config(app, host="0.0.0.0", port=self.port, log_level="warning", log_config=None,
                                loop="asyncio", http="h11", ws="websockets", lifespan="off", access_log=False)
        self.server = uvicorn.Server(config)

        def run():
            try:
                self.server.run()
            except SystemExit:
                self.error = f"Portul {self.port} este ocupat."
            except Exception as e:  # pragma: no cover
                self.error = str(e)

        self.thread = threading.Thread(target=run, name="web-remote", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=3)
        self.server = None
        self.thread = None

    @property
    def running(self) -> bool:
        return bool(self.server and getattr(self.server, "started", False))
