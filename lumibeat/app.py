"""LumiBeat Studio entry point."""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
from pathlib import Path

from .core.config import APP_NAME, APP_VERSION, app_data_dir


def resource_path(rel: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base / rel


def setup_logging() -> Path:
    log_path = app_data_dir() / "lumibeat.log"
    # windowed (no console) builds have no stdout/stderr
    if sys.stdout is None or sys.stderr is None:
        fh = open(app_data_dir() / "console.log", "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = fh
        if sys.stderr is None:
            sys.stderr = fh
    handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return log_path


def parse_args(argv):
    p = argparse.ArgumentParser(prog="LumiBeat Studio")
    p.add_argument("--minimized", action="store_true", help="start hidden in the tray (used by autostart)")
    p.add_argument("--selftest", action="store_true", help="run the built-in self test and exit")
    p.add_argument("--screenshot", metavar="PNG", help="render the UI, save a screenshot and exit")
    p.add_argument("--page", type=int, default=0, help="page index for --screenshot")
    p.add_argument("--demo", action="store_true", help="use the built-in demo track as audio source")
    p.add_argument("--software-gl", action="store_true", help="disable the OpenGL simulator")
    p.add_argument("--data", metavar="DIR", help="use another data directory")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.data:
        os.environ["LUMIBEAT_HOME"] = args.data
    setup_logging()
    log = logging.getLogger("lumibeat")
    log.info("%s %s starting", APP_NAME, APP_VERSION)

    if args.selftest:
        from .selftest import run
        return run(screenshot=args.screenshot)

    if sys.platform == "win32":
        try:  # own taskbar icon instead of python's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LumiBeat.Studio")
        except Exception:
            pass

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QIcon, QSurfaceFormat
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    fmt = QSurfaceFormat()
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("LumiBeat")
    app.setQuitOnLastWindowClosed(False)
    icon = QIcon(str(resource_path("assets/icon.ico" if sys.platform == "win32" else "assets/icon.png")))
    app.setWindowIcon(icon)

    # ---- single instance: a second launch just brings the first window forward
    key = "LumiBeatStudio-" + (os.environ.get("USERNAME") or os.environ.get("USER") or "user")
    sock = QLocalSocket()
    sock.connectToServer(key)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(key)
    server = QLocalServer()
    server.listen(key)

    from .ui import theme
    theme.apply(app)

    from .core.controller import Controller
    ctrl = Controller()
    if args.demo:
        ctrl.cfg.audio.source = "demo"
    ctrl.start()

    from .ui.main_window import MainWindow
    win = MainWindow(ctrl, icon, software_gl=args.software_gl)

    def on_new_conn():
        c = server.nextPendingConnection()
        if c:
            c.readyRead.connect(win.bring_to_front)
    server.newConnection.connect(on_new_conn)

    start_hidden = args.minimized or (ctrl.cfg.app.start_minimized and win.tray is not None)
    if not start_hidden:
        win.show()

    if args.screenshot:
        win.show_page(args.page)

        def shot():
            win.grab().save(args.screenshot)
            win.quit_app()
        QTimer.singleShot(3500, shot)

    def cleanup():
        log.info("shutting down")
        ctrl.shutdown()
    app.aboutToQuit.connect(cleanup)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
