# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for DiskVision (run from DiskVision_Source/).

Bundles Tcl/Tk from the Python used to invoke PyInstaller so onefile EXE
finds init.tcl regardless of install path.
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

# PyInstaller 6 may set SPECPATH to this folder (not the .spec file path).
_sp = Path(SPECPATH).resolve()
spec_dir = _sp if _sp.is_dir() else _sp.parent

# Assets must exist (run tools/make_icons.py first).
_logo_png = spec_dir / "assets" / "logo.png"
_logo_ico = spec_dir / "assets" / "logo.ico"
if not _logo_png.is_file() or not _logo_ico.is_file():
    print(
        "ERROR: Missing logo assets. Run:  python tools/make_icons.py",
        file=sys.stderr,
    )
    sys.exit(1)


def _tcl_tk_datas():
    out = []
    try:
        import tkinter

        py_root = Path(tkinter.__file__).resolve().parent.parent.parent
        tcl86 = py_root / "tcl" / "tcl8.6"
        tk86 = py_root / "tcl" / "tk8.6"
        if (tcl86 / "init.tcl").is_file() and (tk86 / "tk.tcl").is_file():
            out.append((str(tcl86), "tcl/tcl8.6"))
            out.append((str(tk86), "tcl/tk8.6"))
        else:
            print("WARNING: Tcl/Tk folders not under", py_root, file=sys.stderr)
    except Exception as ex:
        print("WARNING: Tcl/Tk auto-locate failed:", ex, file=sys.stderr)
    return out


datas = [
    (str(_logo_png), "."),
    (str(_logo_ico), "."),
] + _tcl_tk_datas()

binaries = []
hiddenimports = [
    "psutil",
    "requests",
    "send2trash",
    "cryptography",
    "cryptography.hazmat.primitives.kdf.pbkdf2",
    "cryptography.hazmat.primitives.ciphers",
    "cryptography.hazmat.primitives.padding",
]
hiddenimports += collect_submodules("cryptography")
_tmp = collect_all("tkinter")
datas += _tmp[0]
binaries += _tmp[1]
hiddenimports += _tmp[2]

a = Analysis(
    [str(spec_dir / "DiskVision.py")],
    pathex=[str(spec_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    a.binaries,
    a.datas,
    [],
    name="DiskVision",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(_logo_ico)],
)
