# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys


root = Path(SPECPATH)

project_tshark = root / "tshark"
installed_tshark_dirs = (
    Path(r"C:\Program Files\Wireshark"),
    Path(r"C:\Program Files (x86)\Wireshark"),
)
tshark_dir = project_tshark if project_tshark.is_dir() else next(
    (path for path in installed_tshark_dirs if (path / "tshark.exe").is_file()),
    None,
)
if tshark_dir is None:
    raise FileNotFoundError(
        "TShark not found. Put Wireshark in project/tshark or install Wireshark."
    )

ffi_dll = Path(sys.prefix) / "Library" / "bin" / "ffi.dll"
openssl_dlls = [
    Path(sys.prefix) / "Library" / "bin" / "libcrypto-3-x64.dll",
    Path(sys.prefix) / "Library" / "bin" / "libssl-3-x64.dll",
    Path(sys.prefix) / "Library" / "bin" / "sqlite3.dll",
]
required_dlls = [ffi_dll, *openssl_dlls]
missing_dlls = [str(path) for path in required_dlls if not path.is_file()]
if missing_dlls:
    raise FileNotFoundError(
        "Required Conda runtime DLLs not found: " + ", ".join(missing_dlls)
    )

a = Analysis(
    [str(root / "desktop.py")],
    pathex=[str(root)],
    binaries=[(str(path), ".") for path in required_dlls],
    datas=[
        (str(root / "frontend"), "frontend"),
        (str(root / "data"), "data"),
        (str(tshark_dir), "tshark"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NightfallGachaAnalyzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(root / "frontend" / "assets" / "nightfall.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="NightfallGachaAnalyzer",
)
