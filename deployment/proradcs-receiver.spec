# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for ProRadCS DicomReceiverService daemon.

Produces standalone executable: proradcs-receiver.exe
Entry point: backend/dicom/service.py
"""

from pathlib import Path
import sys

block_cipher = None

# Workspace root
project_root = Path.cwd().resolve()
entry_script = project_root / "backend" / "dicom" / "service.py"

a = Analysis(
    [str(entry_script)],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "pynetdicom",
        "pynetdicom.apps",
        "pynetdicom.sop_class",
        "pynetdicom.status",
        "pydicom",
        "pydicom.encoders",
        "pydicom.uid",
        "pydicom.datadict",
        "pydicom.values",
        "sqlite3",
        "psutil",
        "backend.core",
        "backend.core.config",
        "backend.core.database",
        "backend.core.audit",
        "backend.core.telemetry",
        "backend.dicom",
        "backend.dicom.models",
        "backend.dicom.storage",
        "backend.dicom.scp",
        "backend.dicom.service",
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
    name="proradcs-receiver",
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
