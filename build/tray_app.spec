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

# Conda's _ssl.pyd must load the matching OpenSSL DLLs from
# <conda>/Library/bin — PyInstaller may otherwise pick a mismatched pair
# (missing COMP_get_type at runtime). python.org interpreters bundle their
# own OpenSSL DLLs, so only pin them when a conda install is detected.
import os
import sys
from pathlib import Path as _P


def _conda_library_bin():
    """Library/bin of the conda install owning this interpreter, if any."""
    prefixes = []
    if os.environ.get("CONDA_PREFIX"):
        prefixes.append(_P(os.environ["CONDA_PREFIX"]))
    base = _P(sys.base_prefix)
    prefixes.extend([base, base.parent])
    for p in prefixes:
        for cand in (p, p.parent):
            bin_dir = cand / "Library" / "bin"
            if (bin_dir / "libssl-3-x64.dll").is_file():
                return bin_dir
    return None


_extra_binaries = []
if sys.platform == "win32":
    _conda_bin = _conda_library_bin()
    if _conda_bin is not None:
        for _name in ("libcrypto-3-x64.dll", "libssl-3-x64.dll"):
            _src = _conda_bin / _name
            if not _src.is_file():
                raise SystemExit(f"missing OpenSSL DLL for conda _ssl.pyd: {_src}")
            _extra_binaries.append((str(_src), "."))

a = Analysis(
    [str(ROOT / "backend" / "tray_app.py")],
    pathex=[str(ROOT)],
    binaries=_extra_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(_P(SPECPATH) / "pyi_rth_ssl_fix.py")],
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
