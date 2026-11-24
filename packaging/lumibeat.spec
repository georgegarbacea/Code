# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for LumiBeat Studio.
#   pyinstaller --noconfirm --clean packaging/lumibeat.spec              -> dist/LumiBeat Studio/ (folder, for the installer)
#   set LUMIBEAT_ONEFILE=1 && pyinstaller --noconfirm packaging/lumibeat.spec  -> dist/LumiBeat Studio.exe (portable)
import os
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
ONEFILE = os.environ.get("LUMIBEAT_ONEFILE") == "1"

hidden = [
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.asyncio", "uvicorn.protocols",
    "uvicorn.protocols.http", "uvicorn.protocols.http.h11_impl", "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.websockets_impl", "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan", "uvicorn.lifespan.off", "uvicorn.lifespan.on",
    "websockets", "websockets.legacy", "websockets.legacy.server", "websockets.asyncio.server",
    "OpenGL.platform.win32", "OpenGL.arrays.numpymodule", "OpenGL.arrays.ctypesarrays",
    "OpenGL.arrays.numbers", "OpenGL.arrays.strings", "OpenGL.arrays.lists",
    "pyaudiowpatch", "qrcode", "qrcode.main",
    "scipy.ndimage", "scipy.signal", "scipy.fft",
    "PySide6.QtOpenGLWidgets", "PySide6.QtOpenGL", "PySide6.QtNetwork",
]
excludes = [
    "tkinter", "matplotlib", "IPython", "pytest", "PIL.ImageQt",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuick3D",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtMultimedia", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "assets"), "assets"),
        (str(ROOT / "lumibeat" / "web" / "static"), "lumibeat/web/static"),
    ],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

common = dict(
    name="LumiBeat Studio",
    icon=str(ROOT / "assets" / "icon.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
    console=False,
    debug=False,
    strip=False,
    upx=False,
)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], runtime_tmpdir=None, **common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="LumiBeat Studio")
