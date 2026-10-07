# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for ProRadCS ProcessorWorker daemon.

Produces standalone executable: proradcs-worker.exe
Entry point: backend/workers/service.py
"""

from pathlib import Path
import sys

block_cipher = None

# Workspace root
project_root = Path.cwd().resolve()
entry_script = project_root / "backend" / "workers" / "service.py"

a = Analysis(
    [str(entry_script)],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "openjpeg",
        "pylibjpeg",
        "pylibjpeg.openjpeg",
        "pylibjpeg_openjpeg",
        "pydicom",
        "pydicom.pixel_data_handlers",
        "pydicom.encoders",
        "pydicom.uid",
        "pydicom.datadict",
        "pydicom.values",
        "numpy",
        "httpx",
        "httpcore",
        "sqlite3",
        "hashlib",
        "psutil",
        "concurrent.futures",
        "backend.core",
        "backend.core.config",
        "backend.core.database",
        "backend.core.audit",
        "backend.core.telemetry",
        "backend.workers",
        "backend.workers.anonymizer",
        "backend.workers.transcoder",
        "backend.workers.uploader",
        "backend.workers.service",
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
    name="proradcs-worker",
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
