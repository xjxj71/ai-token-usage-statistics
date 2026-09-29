#!/usr/bin/env python3
"""One-shot Windows build: frontend -> icons -> PyInstaller -> Inno Setup."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
DIST = ROOT / "dist" / "ai-token-usage"
OUTPUT = BUILD / "output"


def read_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else "0.0.0"


def run(cmd: list[str], **kw) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT, **kw)


def main() -> int:
    version = read_version()
    print(f"building AI Token Usage Statistics v{version}")

    # 1) Frontend
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        print("error: npm not found", file=sys.stderr)
        return 1
    run([npm, "run", "build"], cwd=ROOT / "frontend")
    index = ROOT / "frontend" / "dist" / "index.html"
    if not index.is_file():
        print("error: frontend/dist/index.html missing after build", file=sys.stderr)
        return 1

    # 2) Icons (variant A -> app.ico + tray png)
    py = sys.executable
    run([py, str(ROOT / "assets" / "generate_icon.py"), "--export-build-assets"])

    # 3) PyInstaller (workpath under build/work, which is gitignored)
    run([
        py, "-m", "PyInstaller", "--noconfirm",
        "--workpath", str(BUILD / "work"),
        str(BUILD / "tray_app.spec"),
    ])
    if not (DIST / "ai-token-usage.exe").is_file():
        print("error: onedir output missing ai-token-usage.exe", file=sys.stderr)
        return 1

    # 4) Inno Setup
    iscc = shutil.which("iscc") or shutil.which("ISCC")
    if not iscc:
        print("warning: iscc not found — skipping installer; onedir is at", DIST)
        return 0
    OUTPUT.mkdir(parents=True, exist_ok=True)
    run([iscc, f"/DAppVersion={version}", str(BUILD / "installer.iss")])
    setup = OUTPUT / f"AI-Token-Usage-Setup-{version}.exe"
    print("installer:", setup if setup.is_file() else OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
