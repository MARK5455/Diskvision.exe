"""Smoke test — exercise public APIs (run from DiskVision_Source: python tests/_test_funcs.py)."""
import os
import sys
import tempfile
import threading
import time
import traceback
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
import DiskVision as dv  # noqa: E402

WINHELP = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Help")


def run(name, fn):
    try:
        out = fn()
        print(f"[PASS] {name:38s} -> {out}")
        return True
    except Exception as e:
        print(f"[FAIL] {name:38s} -> {type(e).__name__}: {e}")
        return False


R = []

R.append(run("list_drives", lambda: f"{len(dv.list_drives())} drives"))
R.append(run("get_drives", lambda: f"{dv.get_drives()}"))
R.append(run("fmt_size", lambda: f"{dv.fmt_size(1024**3)}"))


def t1():
    sc = dv.DiskScanner(threading.Event())
    return f"{len(sc.top_folders(WINHELP, limit=10))} folders"


R.append(run("DiskScanner.top_folders", t1))


def t2():
    df = dv.DuplicateFinder()
    stop = threading.Event()
    groups = df.scan(WINHELP, progress_cb=None, stop=stop)
    return f"{len(groups)} dup groups"


R.append(run("DuplicateFinder.scan", t2))


def t3():
    items = dv.TempScanner.scan(
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp")
    )
    return f"{len(items)} entries in user temp"


R.append(run("TempScanner.scan", t3))


def t4():
    eng = dv.FileIndexEngine.instance()
    eng.start_build([Path("C:/Users/Public")])
    time.sleep(2)
    return f"building={eng.is_building} ready={eng.ready}"


R.append(run("FileIndexEngine.start_build", t4))

R.append(run("get_startup", lambda: f"{len(dv.get_startup())} entries"))


def t5():
    data = dv.build_treemap(Path(WINHELP), depth=2, cancel=threading.Event())
    return (
        f"size={dv.fmt_size(data.get('size', 0))}, "
        f"kids={len(data.get('children', []))}"
    )


R.append(run("build_treemap", t5))

R.append(run("system_stats", lambda: f"keys={list(dv.system_stats().keys())}"))
R.append(run("top_processes", lambda: f"{len(dv.top_processes(5))} procs"))
R.append(run("ollama_check", lambda: "{0}: {1}".format(*dv.ollama_check())))
R.append(run("test_llm", lambda: "{0}: {1}".format(*dv.test_llm())))


def t6():
    src = Path(tempfile.gettempdir()) / "_dvtest.txt"
    enc = src.with_suffix(".enc")
    dec = src.with_suffix(".dec")
    src.write_bytes(b"DiskVision crypto test " * 50)
    ok1, m1 = dv.encrypt_file(src, enc, "secret")
    if not ok1:
        raise RuntimeError(f"encrypt: {m1}")
    ok2, m2 = dv.decrypt_file(enc, dec, "secret")
    if not ok2:
        raise RuntimeError(f"decrypt: {m2}")
    data = dec.read_bytes()
    for p in (src, enc, dec):
        try:
            p.unlink()
        except OSError:
            pass
    assert data.startswith(b"DiskVision crypto test")
    return "round-trip OK"


R.append(run("encrypt_file/decrypt_file", t6))


def t7():
    src = Path(tempfile.gettempdir()) / "_dvtest.txt"
    out = Path(tempfile.gettempdir()) / "_dvtest.zip"
    src.write_bytes(b"hello" * 1000)
    cnt, orig, sz = dv.compress_files([src], out)
    is_zip = zipfile.is_zipfile(out)
    for p in (src, out):
        try:
            p.unlink()
        except OSError:
            pass
    return f"zip OK ({cnt} files, {orig}->{sz} bytes, valid={is_zip})"


R.append(run("compress_files", t7))

print()
print(f"=== {sum(R)}/{len(R)} passed ===")
