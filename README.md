# DiskVision — source tree

Single-file application: `DiskVision.py` (all engines + GUI + team module map in header comments).

## Layout

| Path | Purpose |
|------|---------|
| `DiskVision.py` | Main app |
| `assets/` | `logo.png`, `logo.ico` (generated) |
| `tools/make_icons.py` | Creates logos (needs Pillow) |
| `DiskVision.spec` | PyInstaller definition |
| `build_release.bat` | `pip install` → icons → PyInstaller → copy EXE to `../DiskVision_Release/` |
| `tests/` | Smoke tests |
| `requirements.txt` | Runtime |
| `requirements-dev.txt` | Build + Pillow |

## Run from source

```bat
python -m pip install -r requirements.txt
python DiskVision.py
```

## Build Windows EXE

```bat
build_release.bat
```

Requires running from inside `DiskVision_Source\` (or pass the full path to `DiskVision.spec`).  
PyInstaller 6 may set `SPECPATH` to the **folder** containing the spec; `DiskVision.spec` handles both layouts.

Output: `..\DiskVision_Release\DiskVision.exe`

## Team reference modules

Original per-member drafts live in `../team_modules/` (not imported at runtime).
