"""GUI smoke test — run from DiskVision_Source: python tests/_test_gui.py"""
import os
import sys
import time
import traceback

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import tkinter as tk  # noqa: E402
import DiskVision as dv  # noqa: E402


def run(name, fn):
    try:
        out = fn()
        print(f"[OK]   {name:38s} -> {out}")
        return True
    except Exception as e:
        print(f"[FAIL] {name:38s} -> {type(e).__name__}: {e}")
        traceback.print_exc()
        return False


print("Creating DiskVisionApp...")
try:
    app = dv.DiskVisionApp()
    app.update()
    print("[OK] App created and updated")
except Exception as e:
    print(f"[FAIL] App creation: {type(e).__name__}: {e}")
    traceback.print_exc()
    sys.exit(1)

print()
print("=== Testing tab switches (sidebar nav) ===")
for tid, _, _label in dv.DiskVisionApp.NAV_ITEMS:
    run(
        f"_switch('{tid}')",
        lambda t=tid: (app._switch(t), app.update(), app._cur_tab),
    )
run("_switch('settings')", lambda: (app._switch("settings"), app.update(), app._cur_tab))

print()
print("=== Testing engine triggers ===")

run(
    "_disk_reload",
    lambda: (
        app._switch("disk"),
        app.update(),
        app._disk_reload(),
        app.update(),
        len(app._disk_drives),
    ),
)
run(
    "_temp_scan trigger",
    lambda: (
        app._switch("temp"),
        app.update(),
        app._temp_scan(),
        app.update(),
        "started",
    ),
)
run(
    "_refresh_home_stats",
    lambda: (
        app._switch("home"),
        app.update(),
        app._refresh_home_stats(),
        app.update(),
        "ok",
    ),
)

print()
print("=== Verify critical attributes ===")
checks = [
    "_disk_tree",
    "_disk_status",
    "_disk_drives",
    "_temp_tree",
    "_dup_tree",
    "_search_entry",
    "_search_var",
    "_ai_box",
    "_ai_input",
    "_crypto_log",
]
for attr in checks:
    has = hasattr(app, attr)
    print(f"  {attr:25s} -> {'OK' if has else 'MISSING'}")

print()
print("Closing in 1s...")
time.sleep(1)
app.destroy()
print("DONE.")
