# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ai-token-usage tray executable (onedir, no console)."""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent

datas = [
    (str(ROOT / "frontend" / "dist"), "frontend/dist"),
    (str(ROOT / "config" / "model_pricing.yaml"), "config"),
    (str(ROOT / "config" / "quota_providers.example.yaml"), "config"),
]
# Optional icon assets for tray fallback
for extra in ("assets/tray-32.png", "assets/icon-previews/variant-a.png", "assets/app.ico"):
    src = ROOT / extra
    if src.is_file():
        datas.append((str(src), "assets"))

hiddenimports = [
    "aiosqlite",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "anyio._backends._asyncio",
    "sniffio",
    "idna",
    "pydantic.deprecated.decorator",
    "backend.main",
    "backend.tray_app",
    "pystray",
    "pystray._win32",
    "PIL.Image",
    "yaml",
]

a = Analysis(
    [str(ROOT / "backend" / "tray_app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib.tests"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ai-token-usage",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "app.ico") if (ROOT / "assets" / "app.ico").is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ai-token-usage",
)
