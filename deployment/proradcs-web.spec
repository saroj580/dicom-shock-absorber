# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for ProRadCS WebDashboardService daemon.

Produces standalone executable: proradcs-web.exe
Entry point: backend/api/service.py
Bundles compiled React SPA production assets into the distribution.
"""

from pathlib import Path
import sys

block_cipher = None

# Workspace root
project_root = Path.cwd().resolve()
entry_script = project_root / "backend" / "api" / "service.py"
frontend_dist = project_root / "frontend" / "dist"

# Add frontend dist if available
datas = []
if frontend_dist.exists():
    datas.append((str(frontend_dist), "frontend/dist"))

a = Analysis(
    [str(entry_script)],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "fastapi",
        "fastapi.staticfiles",
        "starlette",
        "starlette.staticfiles",
        "starlette.responses",
        "starlette.routing",
        "starlette.middleware",
        "starlette.middleware.cors",
        "sqlite3",
        "psutil",
        "backend.core",
        "backend.core.config",
        "backend.core.database",
        "backend.core.audit",
        "backend.core.telemetry",
        "backend.api",
        "backend.api.models",
        "backend.api.routes",
        "backend.api.service",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "scipy",
        "IPython",
        "PIL",
        "notebook",
        "pytest",
        "unittest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="proradcs-web",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
