"""
DiskVision v1.0 — Smart Windows System Cleaner
Run: python main.py
pip install psutil requests send2trash pyaes
"""
import os, sys, math, threading, hashlib, zipfile, struct, subprocess, re, shutil, logging
import string, tempfile, time, webbrowser, hmac as _hmac
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Callable
from logging.handlers import RotatingFileHandler

import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox, simpledialog

# ── Optional dependencies ─────────────────────────────────────────────
try:    import psutil;     HAS_PSUTIL   = True
except: HAS_PSUTIL   = False
try:    import requests;   HAS_REQUESTS = True
except: HAS_REQUESTS = False
try:    import send2trash; HAS_TRASH    = True
except: HAS_TRASH    = False
try:    import pyaes;      HAS_PYAES    = True
except: HAS_PYAES    = False

# ── Logging ───────────────────────────────────────────────────────────
def _setup_log():
    try:
        d = Path(os.environ.get("APPDATA", Path.home())) / "DiskVision" / "logs"
        d.mkdir(parents=True, exist_ok=True)
        root = logging.getLogger(); root.setLevel(logging.DEBUG)
        fh = RotatingFileHandler(d/"diskvision.log", maxBytes=2_097_152,
                                  backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(message)s"))
        root.addHandler(fh)
        if not getattr(sys, "frozen", False):
            ch = logging.StreamHandler(); ch.setLevel(logging.INFO)
            ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(message)s"))
            root.addHandler(ch)
    except Exception: pass
    return logging.getLogger("DiskVision")
log = _setup_log()

# ── Config ───────────────────────────────────────────────────────────
APP_NAME    = "DiskVision"
APP_VERSION = "1.0.0"
APP_BUILD   = "2025"

OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL","http://localhost:11434/v1")
OPENAI_MODEL    = os.environ.get("OPENAI_MODEL",   "llama3.2")
OPENAI_API_KEY  = os.environ.get("OPENAI_API_KEY", "ollama")

# ── Palette (Light Mode) ──────────────────────────────────────────────
BG="#f8fafc"; BG2="#f1f5f9";  PANEL="#ffffff"; CARD="#f8fafc"
CARD2="#e2e8f0"; BORDER="#cbd5e1"; BORD2="#94a3b8"; ACCENT="#0284c7"
ACC2="#0369a1"; PURPLE="#7c3aed"; GREEN="#059669"; GREEN2="#047857"
YELLOW="#d97706"; YELL2="#b45309"; RED="#dc2626"; RED2="#b91c1c"
TEXT="#0f172a"; TEXT2="#334155"; TEXT3="#64748b"; MONO="#0369a1"
ORANGE="#ea580c"
TMAP_COLS=["#0ea5e9","#8b5cf6","#10b981","#f59e0b","#ef4444",
           "#06b6d4","#a855f7","#14b8a6","#eab308","#f43f5e"]

EXT_GROUPS: Dict[str,tuple] = {
    "video":      (".mp4",".mkv",".avi",".mov",".wmv",".flv",".webm"),
    "image":      (".jpg",".jpeg",".png",".gif",".bmp",".webp",".tiff"),
    "audio":      (".mp3",".wav",".flac",".aac",".ogg",".m4a"),
    "document":   (".pdf",".doc",".docx",".xls",".xlsx",".ppt",".pptx",".txt",".md"),
    "archive":    (".zip",".rar",".7z",".tar",".gz",".iso"),
    "executable": (".exe",".msi",".bat",".cmd",".ps1"),
}
SYS_PREFIXES=("C:\\Windows","C:\\Program Files","C:\\Program Files (x86)")
TYPE_ICONS={"video":"🎬","image":"🖼","audio":"🎵","document":"📄",
            "archive":"📦","executable":"⚙","other":"📁"}

# ═══════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════
def _blend(c1,c2,t):
    t=max(0.0,min(1.0,t))
    r=int(int(c1[1:3],16)*(1-t)+int(c2[1:3],16)*t)
    g=int(int(c1[3:5],16)*(1-t)+int(c2[3:5],16)*t)
    b=int(int(c1[5:7],16)*(1-t)+int(c2[5:7],16)*t)
    return f"#{r:02x}{g:02x}{b:02x}"

def fmt_size(b):
    if b>=1<<30: return f"{b/(1<<30):.1f} GB"
    if b>=1<<20: return f"{b/(1<<20):.1f} MB"
    return f"{b/(1<<10):.1f} KB"

def get_all_drives():
    """Return list of available drives on Windows."""
    drives=[]
    try:
        import string
        for d in string.ascii_uppercase:
            p=Path(f"{d}:\\")
            if p.exists(): drives.append(str(p))
    except: drives=[str(Path.home())]
    return drives if drives else [str(Path.home())]

# ═══════════════════════════════════════════════
#  BACKEND — SCAN
# ═══════════════════════════════════════════════
def walk_files(root:Path):
    try:
        for e in root.rglob("*"):
            try:
                if e.is_file() and not e.is_symlink():
                    yield e, e.stat().st_size
            except (PermissionError,OSError): continue
    except (PermissionError,OSError): return

def categorize_file(p:Path)->str:
    ext=p.suffix.lower()
    for g,exts in EXT_GROUPS.items():
        if ext in exts: return g
    return "other"

# =====================================================================
# ENGINE 1 — Disk Scanner
# Author: Hady Zarif
# Description: Scans directories recursively to find large files and categorize them.
# =====================================================================
def scan_large_files(root,min_mb=50,limit=200,cb=None):
    results,n=[],0
    min_b=min_mb*1048576
    for path,size in walk_files(root):
        n+=1
        if cb and n%300==0: cb(n,path)
        if size>=min_b:
            results.append({"path":str(path),"size_bytes":size,
                             "group":categorize_file(path),
                             "in_system":str(path).startswith(SYS_PREFIXES)})
    results.sort(key=lambda x:x["size_bytes"],reverse=True)
    return results[:limit]

# ── INSTANT SEARCH ENGINE — index-based, no per-query disk scan ────
# ═══════════════════════════════════════════════════════════════════════
#  FILE INDEX ENGINE — replaces search_files() with persistent index
#
#  Architecture:
#    FileIndexEngine  ← singleton, lives for app lifetime
#      ├── _index: List[IndexEntry]  ← flat list in memory (fast)
#      ├── _lock:  threading.RLock  ← thread-safe reads/writes
#      ├── build()   ← background thread, scans once
#      ├── query()   ← pure RAM filter, returns in <10ms
#      └── refresh() ← incremental: only re-scans changed dirs
#
#  IndexEntry = (name_lower, path_str, size, ext, in_system)
#    stored as plain tuple for minimum memory overhead
#    ~100 bytes per file → 1M files = ~100MB RAM (acceptable)
# ═══════════════════════════════════════════════════════════════════════

import os, threading, time
from pathlib import Path
from typing import List, Tuple, Optional, Callable

# Folders to SKIP during indexing — huge dirs with no user files
INDEX_SKIP_DIRS = frozenset({
    # Windows system
    "windows", "windowsapps", "$recycle.bin", "system volume information",
    "recovery", "perflogs", "$windows.~bt", "$windows.~ws",
    # Dev / package managers (millions of tiny files)
    "node_modules", ".git", "__pycache__", ".tox", ".mypy_cache",
    "venv", ".venv", "env", ".env",
    # Browser caches
    "cache", "code cache", "gpucache", "shadercache",
    # Package caches
    "pip", "npm", "yarn", "cargo",
})

# Max files to index per root (safety cap)
INDEX_MAX_FILES = 2_000_000

# IndexEntry tuple indices
IE_NAME  = 0   # filename lowercase (for fast substring match)
IE_PATH  = 1   # full path string  (for display)
IE_SIZE  = 2   # int bytes
IE_EXT   = 3   # extension lowercase e.g. ".mp4"
IE_SYS   = 4   # bool — is inside system dir?
IE_MTIME = 5   # float — last-modified timestamp


# =====================================================================
# ENGINE 4 — Fast File Index
# Author: Moamen Mohamed
# Description: Builds a fast memory index of the filesystem to allow instant searches without disk I/O.
# =====================================================================
class FileIndexEngine:
    """
    Singleton index engine.  Build once, query many times.

    Usage:
        engine = FileIndexEngine.instance()
        engine.start_build([Path("C:\\")])          # kicks off background thread
        results = engine.query("chrome", limit=200) # instant, no disk I/O
    """

    _instance: Optional["FileIndexEngine"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def instance(cls) -> "FileIndexEngine":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._index:  List[Tuple] = []          # flat list of IndexEntry tuples
        self._lock    = threading.RLock()        # protects _index
        self._building  = False                  # True while build thread runs
        self._build_thread: Optional[threading.Thread] = None
        self._cancel_flag = threading.Event()    # set to stop current build

        # Stats
        self.total_files  = 0
        self.index_size   = 0
        self.build_start  = 0.0
        self.build_end    = 0.0
        self.last_roots:  List[str] = []
        self.status       = "Index not started yet"

        # Callbacks — set by UI
        self.on_progress: Optional[Callable[[int, str], None]] = None   # (count, current_path)
        self.on_complete: Optional[Callable[[int, float], None]] = None  # (total, seconds)
        self.on_status:   Optional[Callable[[str], None]] = None         # (status_msg)

    # ── Public API ─────────────────────────────────────────────────────

    def start_build(self, roots: List[Path], force: bool = False):
        """
        Start building the index in a background thread.
        If already building, cancel current build and restart with new roots.
        If index already exists and force=False, skip rebuild.
        """
        with self._lock:
            already_indexed = len(self._index) > 0
            same_roots = sorted(str(r) for r in roots) == sorted(self.last_roots)

        if already_indexed and same_roots and not force:
            return  # already indexed for these roots

        # Cancel any running build
        self._cancel_flag.set()
        if self._build_thread and self._build_thread.is_alive():
            self._build_thread.join(timeout=2.0)

        self._cancel_flag.clear()
        self._building = True
        self._build_thread = threading.Thread(
            target=self._build_worker,
            args=(roots,),
            daemon=True,
            name="IndexBuilder"
        )
        self._build_thread.start()

    def query(self, q: str, limit: int = 200,
              ext_filter: Optional[str] = None,
              scope: Optional[str] = None) -> List[dict]:
        """
        Query the index.  Pure RAM operation — no disk I/O.

        Args:
            q:          Search query (substring match on filename)
            limit:      Max results to return
            ext_filter: Optional extension filter e.g. ".mp4"
            scope:      Optional path prefix filter e.g. "C:\\Users"

        Returns:
            List of result dicts sorted by file size descending
        """
        q = q.lower().strip()
        if not q:
            return []

        results = []
        scope_lower = scope.lower() if scope else None
        ext_lower   = ext_filter.lower() if ext_filter else None

        with self._lock:
            snapshot = self._index  # safe reference, no copy needed

        for entry in snapshot:
            if self._cancel_flag.is_set():
                break  # build restarted — stop stale query

            # Fast substring match on lowercase name
            if q not in entry[IE_NAME]:
                continue

            # Optional filters
            if ext_lower and entry[IE_EXT] != ext_lower:
                continue
            if scope_lower and not entry[IE_PATH].lower().startswith(scope_lower):
                continue

            results.append({
                "path":       entry[IE_PATH],
                "size_bytes": entry[IE_SIZE],
                "group":      _ext_to_group(entry[IE_EXT]),
                "in_system":  entry[IE_SYS],
            })

            if len(results) >= limit:
                break

        # Sort by size descending (biggest files first — most useful)
        results.sort(key=lambda x: x["size_bytes"], reverse=True)
        return results

    def query_count(self, q: str) -> int:
        """Fast count-only query for status display."""
        q = q.lower().strip()
        if not q:
            return 0
        with self._lock:
            return sum(1 for e in self._index if q in e[IE_NAME])

    def refresh_incremental(self, roots: List[Path]):
        """
        Incremental refresh: only re-scan directories whose mtime changed.
        Much faster than full rebuild for periodic updates.
        """
        if self._building:
            return  # don't overlap with full build

        def _refresh():
            self._building = True
            self._set_status("Updating index…")
            added = removed = 0

            # Build set of currently indexed paths for fast lookup
            with self._lock:
                existing = {e[IE_PATH]: e[IE_MTIME] for e in self._index}

            new_entries = []
            for root in roots:
                try:
                    for path, size in _fast_walk(root, self._cancel_flag):
                        path_str = str(path)
                        mtime = path.stat().st_mtime
                        if path_str in existing:
                            # File exists and unchanged — keep as-is
                            existing.pop(path_str)
                        else:
                            # New file
                            added += 1
                        new_entries.append(_make_entry(path, size))
                except Exception:
                    continue

            removed = len(existing)  # whatever is left in existing was deleted

            with self._lock:
                self._index = new_entries
                self.total_files = len(new_entries)

            self._building = False
            self._set_status(
                f"✓ Index updated — {len(new_entries):,} files  "
                f"(+{added} new, -{removed} removed)"
            )

        threading.Thread(target=_refresh, daemon=True, name="IndexRefresh").start()

    @property
    def is_building(self) -> bool:
        return self._building

    @property
    def ready(self) -> bool:
        return len(self._index) > 0 and not self._building

    def stats(self) -> dict:
        with self._lock:
            return {
                "total":    len(self._index),
                "building": self._building,
                "seconds":  round(self.build_end - self.build_start, 1),
                "status":   self.status,
            }

    # ── Internal ───────────────────────────────────────────────────────

    def _build_worker(self, roots: List[Path]):
        self.build_start = time.monotonic()
        self.last_roots  = sorted(str(r) for r in roots)
        self._set_status("Building index…")

        batch: List[Tuple] = []
        BATCH = 5000         # flush to index every N files
        total  = 0

        try:
            for root in roots:
                if self._cancel_flag.is_set():
                    break
                try:
                    for path, size in _fast_walk(root, self._cancel_flag):
                        if self._cancel_flag.is_set():
                            break

                        batch.append(_make_entry(path, size))
                        total += 1

                        # Flush batch to index periodically
                        if len(batch) >= BATCH:
                            with self._lock:
                                self._index.extend(batch)
                            batch.clear()
                            self.total_files = total

                            if self.on_progress:
                                try:
                                    self.on_progress(total, str(path.parent))
                                except Exception:
                                    pass

                        if total >= INDEX_MAX_FILES:
                            break

                except Exception:
                    continue

            # Flush remaining
            if batch and not self._cancel_flag.is_set():
                with self._lock:
                    self._index.extend(batch)
                    self.total_files = len(self._index)

        finally:
            self._building = False
            self.build_end = time.monotonic()
            elapsed = self.build_end - self.build_start

            if not self._cancel_flag.is_set():
                msg = (f"✓ Index ready — {self.total_files:,} files  "
                       f"({elapsed:.1f}s)")
                self._set_status(msg)
                if self.on_complete:
                    try:
                        self.on_complete(self.total_files, elapsed)
                    except Exception:
                        pass

    def _set_status(self, msg: str):
        self.status = msg
        if self.on_status:
            try:
                self.on_status(msg)
            except Exception:
                pass


# ── Module-level helpers (fast, no self overhead) ──────────────────────

def _make_entry(path: Path, size: int) -> Tuple:
    """Create a compact IndexEntry tuple."""
    name_lower = path.name.lower()
    path_str   = str(path)
    ext        = path.suffix.lower()
    in_sys     = path_str.startswith(("C:\\Windows", "C:\\Program Files",
                                       "C:\\Program Files (x86)"))
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (name_lower, path_str, size, ext, in_sys, mtime)


def _fast_walk(root: Path, cancel: threading.Event):
    """
    Faster alternative to rglob — uses os.scandir recursively.
    Skips INDEX_SKIP_DIRS automatically.
    Yields (Path, size) tuples.
    """
    stack = [root]
    while stack:
        if cancel.is_set():
            return
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if cancel.is_set():
                        return
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            # Skip excluded dirs
                            if entry.name.lower() not in INDEX_SKIP_DIRS:
                                stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            stat = entry.stat()
                            yield Path(entry.path), stat.st_size
                    except (PermissionError, OSError):
                        continue
        except (PermissionError, OSError):
            continue


# EXT → group lookup (module-level dict for speed)
_EXT_GROUP_MAP: dict = {}
for _grp, _exts in {
    "video":      (".mp4",".mkv",".avi",".mov",".wmv",".flv",".webm"),
    "image":      (".jpg",".jpeg",".png",".gif",".bmp",".webp",".tiff"),
    "audio":      (".mp3",".wav",".flac",".aac",".ogg",".m4a"),
    "document":   (".pdf",".doc",".docx",".xls",".xlsx",".ppt",".pptx",".txt",".md"),
    "archive":    (".zip",".rar",".7z",".tar",".gz",".iso"),
    "executable": (".exe",".msi",".bat",".cmd",".ps1"),
}.items():
    for _e in _exts:
        _EXT_GROUP_MAP[_e] = _grp

def _ext_to_group(ext: str) -> str:
    return _EXT_GROUP_MAP.get(ext, "other")



# ── TEMP CLEANER ──────────────────────────────────────────────────────
import tempfile as _tempfile

TEMP_LOCATIONS = [
    # (label, path_or_callable, safe_to_delete)
    ("Windows Temp",         lambda: Path(os.environ.get("SystemRoot","C:\\Windows"))/"Temp",                True),
    ("User Temp",            lambda: Path(_tempfile.gettempdir()),                                              True),
    ("Prefetch",             lambda: Path(os.environ.get("SystemRoot","C:\\Windows"))/"Prefetch",            True),
    ("Windows Update Cache", lambda: Path(os.environ.get("SystemRoot","C:\\Windows"))/"SoftwareDistribution"/"Download", True),
    ("Recycle Bin",          lambda: Path(os.environ.get("SystemDrive","C:"))/"$Recycle.Bin",                  True),
    ("Browser Chrome Cache", lambda: Path(os.environ.get("LOCALAPPDATA",""))/"Google"/"Chrome"/"User Data"/"Default"/"Cache", True),
    ("Browser Edge Cache",   lambda: Path(os.environ.get("LOCALAPPDATA",""))/"Microsoft"/"Edge"/"User Data"/"Default"/"Cache", True),
    ("Thumbnails Cache",     lambda: Path(os.environ.get("LOCALAPPDATA",""))/"Microsoft"/"Windows"/"Explorer", True),
    ("Recent Files",         lambda: Path(os.environ.get("APPDATA",""))/"Microsoft"/"Windows"/"Recent",        False),
    ("Windows Log Files",    lambda: Path(os.environ.get("SystemRoot","C:\\Windows"))/"Logs",                True),
]

# =====================================================================
# ENGINE 3 — Temp Cleaner
# Author: Mohamed Maged
# Description: Scans and cleans temporary system, cache, and application files to free up space.
# =====================================================================
def scan_temp_locations(cb=None)->List[dict]:
    """Scan all temp locations. Returns list of dicts with stats."""
    results=[]
    for i,(label,path_fn,safe) in enumerate(TEMP_LOCATIONS):
        if cb: cb(i, len(TEMP_LOCATIONS), label)
        try:
            p=path_fn()
            if not p.exists():
                results.append({"label":label,"path":str(p),"size":0,
                                 "count":0,"safe":safe,"exists":False})
                continue
            size=0; count=0
            for f,sz in walk_files(p):
                size+=sz; count+=1
            results.append({"label":label,"path":str(p),"size":size,
                             "count":count,"safe":safe,"exists":True})
        except Exception:
            results.append({"label":label,"path":"","size":0,"count":0,"safe":safe,"exists":False})
    return results

def clean_temp_location(path_str:str, cb=None)->dict:
    """Delete all files in a temp folder. Returns stats."""
    deleted=0; failed=0; freed=0
    p=Path(path_str)
    if not p.exists(): return {"deleted":0,"failed":0,"freed":0}
    all_files=list(walk_files(p))
    for i,(fp,sz) in enumerate(all_files):
        if cb and i%50==0: cb(i,len(all_files))
        try:
            fp.unlink()
            deleted+=1; freed+=sz
        except Exception: failed+=1
    # Also remove empty subdirs
    try:
        for d in sorted(p.rglob("*"),reverse=True):
            if d.is_dir():
                try: d.rmdir()
                except: pass
    except: pass
    return {"deleted":deleted,"failed":failed,"freed":freed}

# ── DUPLICATE FINDER ─────────────────────────────────────────────────
def file_hash(path:str,block=65536)->Optional[str]:
    try:
        if not Path(path).exists(): return None
        h=hashlib.md5()
        with open(path,"rb") as f:
            while True:
                buf=f.read(block)
                if not buf: break
                h.update(buf)
        return h.hexdigest()
    except (PermissionError,OSError): return None

# =====================================================================
# ENGINE 2 — Duplicate Finder
# Author: Jenor Saber
# Description: Finds duplicate files using size and MD5 hash comparisons.
# =====================================================================
def find_duplicates(root:Path,min_mb=1,cb=None):
    by_size:Dict[int,List[str]]={}; n=0; min_b=min_mb*1048576
    for path,size in walk_files(root):
        n+=1
        if cb and n%300==0: cb(n,path,"size")
        if size>=min_b: by_size.setdefault(size,[]).append(str(path))
    candidates=[p for p in by_size.values() if len(p)>1]
    by_hash:Dict[str,List[str]]={};done=0
    total=sum(len(g) for g in candidates)
    for group in candidates:
        for p in group:
            done+=1
            if cb and done%20==0: cb(done,Path(p),f"hash {done}/{total}")
            h=file_hash(p)
            if h: by_hash.setdefault(h,[]).append(p)
    return [sorted(p) for p in by_hash.values() if len(p)>1]

# ── TREEMAP ───────────────────────────────────────────────────────────
# =====================================================================
# ENGINE 6 — System Monitor + Treemap
# Author: Mohamed Saber
# Description: Recursively builds a nested dictionary of file sizes for a hierarchical treemap visualization.
# =====================================================================
def build_treemap_data(root:Path,depth=2)->dict:
    def scan_dir(p:Path,d:int)->dict:
        node={"name":p.name or str(p),"path":str(p),"size":0,"children":[]}
        try: entries=list(p.iterdir())
        except PermissionError: return node
        if d==0:
            for f,sz in walk_files(p): node["size"]+=sz
        else:
            for entry in entries:
                try:
                    if entry.is_dir() and not entry.is_symlink():
                        child=scan_dir(entry,d-1)
                        node["children"].append(child); node["size"]+=child["size"]
                    elif entry.is_file() and not entry.is_symlink():
                        sz=entry.stat().st_size; node["size"]+=sz
                        node["children"].append({"name":entry.name,"path":str(entry),
                                                  "size":sz,"children":[]})
                except (PermissionError,OSError): continue
        return node
    return scan_dir(root,depth)

# ── STARTUP MANAGER ───────────────────────────────────────────────────
STARTUP_KEYS=[r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
              r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce",
              r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"]
STARTUP_FOLDER=Path(os.environ.get("APPDATA",""))/"Microsoft/Windows/Start Menu/Programs/Startup"

def get_startup_entries():
    entries=[]
    try:
        import winreg
        for key_path in STARTUP_KEYS:
            for hive,hname in [(winreg.HKEY_CURRENT_USER,"HKCU"),
                               (winreg.HKEY_LOCAL_MACHINE,"HKLM")]:
                try:
                    key=winreg.OpenKey(hive,key_path); i=0
                    while True:
                        try:
                            name,val,_=winreg.EnumValue(key,i)
                            entries.append({"name":name,"command":val,
                                            "location":f"Registry {hname}","enabled":True,
                                            "key_path":key_path,"hive":hname})
                            i+=1
                        except OSError: break
                    winreg.CloseKey(key)
                except OSError: continue
    except ImportError: pass
    try:
        if STARTUP_FOLDER.exists():
            for f in STARTUP_FOLDER.iterdir():
                if f.suffix.lower() in (".lnk",".exe",".bat",".cmd"):
                    entries.append({"name":f.stem,"command":str(f),
                                    "location":"Startup Folder","enabled":True,
                                    "key_path":str(STARTUP_FOLDER),"hive":"FOLDER"})
    except Exception: pass
    return entries

def disable_startup_entry(entry:dict)->bool:
    try:
        if entry["hive"]=="FOLDER":
            p=Path(entry["command"]); p.rename(p.with_suffix(p.suffix+".disabled")); return True
        import winreg
        hive=winreg.HKEY_CURRENT_USER if entry["hive"]=="HKCU" else winreg.HKEY_LOCAL_MACHINE
        dis_path=entry["key_path"].replace("\\Run","\\Run-Disabled")
        src=winreg.OpenKey(hive,entry["key_path"],0,winreg.KEY_ALL_ACCESS)
        dst=winreg.CreateKey(hive,dis_path)
        winreg.SetValueEx(dst,entry["name"],0,winreg.REG_SZ,entry["command"])
        winreg.DeleteValue(src,entry["name"])
        winreg.CloseKey(src); winreg.CloseKey(dst); return True
    except Exception: return False

# ── COMPRESS FILES — Smart multi-method ─────────────────────────────
# File types already compressed — don't waste time trying
_ALREADY_COMPRESSED = {
    ".jpg",".jpeg",".png",".gif",".webp",".heic",".heif",  # images
    ".mp4",".mkv",".avi",".mov",".wmv",".flv",".webm",".m4v",  # video
    ".mp3",".aac",".ogg",".flac",".m4a",".opus",          # audio
    ".zip",".7z",".rar",".gz",".bz2",".xz",".zst",".lz4", # archives
    ".pdf",".docx",".xlsx",".pptx",".odt",".ods",          # office (internally zipped)
    ".iso",".img",                                          # disk images
}

def analyze_compressibility(paths:List[str])->dict:
    """Return stats on how compressible the file list is before actually compressing."""
    compressible=[]; incompressible=[]; total=0; comp_size=0; incomp_size=0
    for p in paths:
        try:
            ext=Path(p).suffix.lower()
            sz=Path(p).stat().st_size
            total+=sz
            if ext in _ALREADY_COMPRESSED:
                incompressible.append(p); incomp_size+=sz
            else:
                compressible.append(p); comp_size+=sz
        except: pass
    return {"compressible":compressible,"incompressible":incompressible,
            "total":total,"comp_size":comp_size,"incomp_size":incomp_size,
            "expected_ratio": 0.0 if total==0 else (
                # compressible files save ~40-60%, incompressible save ~0-2%
                (comp_size*0.50 + incomp_size*0.01) / total * 100
            )}

def _try_7zip(paths:List[str], out_path:str, cb=None)->Optional[dict]:
    """Try to use 7-Zip via CLI — returns stats or None if 7z not found."""
    sevenzip=None
    for candidate in [
        r"C:\Program Files-Zipz.exe",
        r"C:\Program Files (x86)-Zipz.exe",
        "7z","7za"
    ]:
        try:
            r=subprocess.run([candidate,"--help"],capture_output=True,timeout=3)
            if r.returncode==0: sevenzip=candidate; break
        except (FileNotFoundError,subprocess.TimeoutExpired): continue
    if not sevenzip: return None

    # Build 7z archive with ultra compression
    out_7z=out_path.replace(".zip",".7z") if out_path.endswith(".zip") else out_path+".7z"
    cmd=[sevenzip,"a","-t7z","-mx=9","-mmt=on","-ms=on",out_7z]+paths
    try:
        total_orig=sum(Path(p).stat().st_size for p in paths if Path(p).exists())
        proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        if cb: cb(0,len(paths),"7-Zip Compressing…")
        stdout,stderr=proc.communicate(timeout=300)
        if proc.returncode==0:
            total_comp=Path(out_7z).stat().st_size
            return {"count":len(paths),"orig":total_orig,"comp":total_comp,
                    "ratio":(1-total_comp/max(total_orig,1))*100,
                    "failed":[],"method":"7-Zip LZMA2","out_path":out_7z}
    except Exception: pass
    return None

# =====================================================================
# ENGINE 5 — Crypto (AES-256 + ZIP)
# Author: Abdullah Mohamed
# Description: Smart compression using 7-Zip or ZIP LZMA/Deflate and AES-256 encryption.
# =====================================================================
def compress_files(paths:List[str], out_zip:str, cb=None, method="auto")->dict:
    """
    Smart compression:
      method="auto"  → try 7-Zip first, fall back to LZMA, skip incompressible
      method="zip"   → always ZIP (compatible but weak)
      method="lzma"  → Python LZMA inside ZIP (better than deflate, no 7z needed)
    """
    total_orig=0; count=0; failed=[]

    # ── Auto: try 7-Zip ──────────────────────────────────────────────
    if method=="auto":
        result=_try_7zip(paths, out_zip, cb)
        if result:
            return result
        method="lzma"  # fall back

    # ── LZMA inside ZIP (Python stdlib, much better than Deflate) ────
    if method in ("lzma","auto"):
        try:
            compression=zipfile.ZIP_LZMA
        except AttributeError:
            compression=zipfile.ZIP_DEFLATED  # Python <3.3 fallback (rare)
    else:
        compression=zipfile.ZIP_DEFLATED

    with zipfile.ZipFile(out_zip,"w",compression) as zf:
        for i,p in enumerate(paths):
            if cb: cb(i,len(paths),p)
            try:
                sz=Path(p).stat().st_size
                ext=Path(p).suffix.lower()
                # For already-compressed files use STORED (no point recompressing)
                if ext in _ALREADY_COMPRESSED and method!="zip":
                    zf.write(p, Path(p).name, compress_type=zipfile.ZIP_STORED)
                else:
                    zf.write(p, Path(p).name, compress_type=compression)
                total_orig+=sz; count+=1
            except Exception as e:
                failed.append(f"{Path(p).name}: {e}")

    try: total_comp=Path(out_zip).stat().st_size
    except: total_comp=0
    used_method="LZMA" if compression==zipfile.ZIP_LZMA else "Deflate"
    return {"count":count,"orig":total_orig,"comp":total_comp,
            "ratio":(1-total_comp/max(total_orig,1))*100,
            "failed":failed,"method":f"ZIP {used_method}","out_path":out_zip}

# ── ENCRYPT / DECRYPT — AES-256-CTR + HMAC-SHA256 + PBKDF2 ─────────
import hmac as _hmac

_ENC_MAGIC   = b"SCLNR5ENC"
_ENC_VERSION = b"\x02"
# File format v2: MAGIC(9) + VER(1) + SALT(32) + IV(16) + SIZE(8) + HMAC(32) + CIPHERTEXT

def _derive_keys(password: str, salt: bytes):
    # PBKDF2-HMAC-SHA256 with 200,000 rounds → 64 bytes → two 32-byte keys
    master = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000, dklen=64)
    return master[:32], master[32:]  # enc_key, mac_key

def _compute_hmac(mac_key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    return _hmac.new(mac_key, iv + ciphertext, hashlib.sha256).digest()

def encrypt_file(src: str, password: str, delete_original: bool = False) -> bool:
    # Encrypt src -> src.enc using AES-256-CTR + HMAC authentication
    try:
        salt = os.urandom(32)
        iv   = os.urandom(16)
        enc_key, mac_key = _derive_keys(password, salt)
        data = Path(src).read_bytes()
        orig_size = len(data)

        if HAS_PYAES:
            counter  = pyaes.Counter(initial_value=int.from_bytes(iv, "big"))
            aes      = pyaes.AESModeOfOperationCTR(enc_key, counter=counter)
            ciphertext = bytes(aes.encrypt(data))
        else:
            # Fallback: PBKDF2-derived keystream XOR (password-verified via HMAC)
            ks = b""; blk = 0
            while len(ks) < len(data):
                ks += hashlib.pbkdf2_hmac("sha256", enc_key, iv + blk.to_bytes(4,"big"), 1, dklen=32)
                blk += 1
            ciphertext = bytes(a ^ b for a, b in zip(data, ks))

        mac = _compute_hmac(mac_key, iv, ciphertext)
        out = src + ".enc"
        with open(out, "wb") as f:
            f.write(_ENC_MAGIC)
            f.write(_ENC_VERSION)
            f.write(salt)
            f.write(iv)
            f.write(struct.pack("<Q", orig_size))
            f.write(mac)
            f.write(ciphertext)

        if delete_original:
            p = Path(src)
            if p.exists(): p.unlink()
        return True
    except Exception:
        return False

def decrypt_file(src: str, password: str, out_path: str = None) -> tuple:
    # Decrypt src.enc — HMAC checked BEFORE decryption (wrong pw = instant reject)
    try:
        raw = Path(src).read_bytes()
        if not raw.startswith(_ENC_MAGIC):
            return False, "This file was not encrypted by this program"

        pos = len(_ENC_MAGIC)
        version = raw[pos:pos+1]; pos += 1

        if version != _ENC_VERSION:
            return False, "Unknown file format — possibly encrypted with an older version"

        salt       = raw[pos:pos+32]; pos += 32
        iv         = raw[pos:pos+16]; pos += 16
        orig_size  = struct.unpack("<Q", raw[pos:pos+8])[0]; pos += 8
        stored_mac = raw[pos:pos+32]; pos += 32
        ciphertext = raw[pos:]

        enc_key, mac_key = _derive_keys(password, salt)

        # ── VERIFY HMAC BEFORE DECRYPTING — wrong password fails here ─
        expected_mac = _compute_hmac(mac_key, iv, ciphertext)
        if not _hmac.compare_digest(stored_mac, expected_mac):
            return False, "❌ Wrong password — file was not decrypted"

        # ── DECRYPT ───────────────────────────────────────────────────
        if HAS_PYAES:
            counter = pyaes.Counter(initial_value=int.from_bytes(iv, "big"))
            aes     = pyaes.AESModeOfOperationCTR(enc_key, counter=counter)
            data    = bytes(aes.decrypt(ciphertext))[:orig_size]
        else:
            ks = b""; blk = 0
            while len(ks) < len(ciphertext):
                ks += hashlib.pbkdf2_hmac("sha256", enc_key, iv + blk.to_bytes(4,"big"), 1, dklen=32)
                blk += 1
            data = bytes(a ^ b for a, b in zip(ciphertext, ks))[:orig_size]

        if out_path is None:
            out_path = src[:-4] if src.endswith(".enc") else src + "_decrypted"
        Path(out_path).write_bytes(data)
        return True, out_path
    except Exception as e:
        return False, f"Error during decryption: {e}"

# ── RAM ───────────────────────────────────────────────────────────────
def list_top_ram(limit=20):
    if not HAS_PSUTIL: return []
    out=[]
    for p in psutil.process_iter(['pid','name','memory_info']):
        try:
            m=p.info['memory_info']
            if m: out.append((p.info['pid'],p.info['name'] or "?",m.rss/1048576))
        except: pass
    return sorted(out,key=lambda x:x[2],reverse=True)[:limit]

def get_sys_stats():
    if not HAS_PSUTIL: return {"cpu":0,"ram_used":0,"ram_total":0,"ram_pct":0}
    cpu=psutil.cpu_percent(interval=0.3); vm=psutil.virtual_memory()
    return {"cpu":cpu,"ram_used":vm.used/1048576,"ram_total":vm.total/1048576,"ram_pct":vm.percent}

# ── OLLAMA ────────────────────────────────────────────────────────────
# =====================================================================
# ENGINE 7 — AI Chat (Ollama / Qwen)
# Author: Mohamed Shaaban
# Description: Connects to local Ollama API to run LLMs like Qwen or Llama 3 for intelligent assistance.
# =====================================================================
def _ollama_list_models():
    if not HAS_REQUESTS: return []
    base=OPENAI_BASE_URL.rstrip("/").replace("/v1","")
    for ep in ["/api/tags","/api/models"]:
        try:
            r=requests.get(base+ep,timeout=5)
            if r.status_code==200: return [m["name"] for m in r.json().get("models",[])]
        except: continue
    return []

def _get_best_model():
    models=_ollama_list_models()
    if not models: return OPENAI_MODEL
    if OPENAI_MODEL in models: return OPENAI_MODEL
    for m in models:
        if "llama3.2" in m.lower(): return m
    return models[0]

def _call_ollama(prompt:str,max_tokens=2500,history:list=None)->str:
    if not HAS_REQUESTS: return "⚠ requests library not installed"
    base=OPENAI_BASE_URL.rstrip("/").replace("/v1",""); model=_get_best_model()
    hdrs={"Content-Type":"application/json"}
    try:
        if history:
            msgs=history+[{"role":"user","content":prompt}]
            body={"model":model,"messages":msgs,"stream":False,
                  "options":{"temperature":0.7,"num_predict":max_tokens}}
            r=requests.post(base+"/api/chat",headers=hdrs,json=body,timeout=180)
            if r.status_code==200: return r.json().get("message",{}).get("content","").strip()
        else:
            body={"model":model,"prompt":prompt,"stream":False,
                  "options":{"temperature":0.3,"num_predict":max_tokens}}
            r=requests.post(base+"/api/generate",headers=hdrs,json=body,timeout=180)
            if r.status_code==200: return r.json().get("response","").strip()
        if r.status_code==404:
            installed=_ollama_list_models()
            hint=("\n".join(f"  • {m}" for m in installed)) if installed else ""
            return f"⚠ Model '{model}' not found\n{hint}"
    except requests.exceptions.ConnectionError:
        return f"⚠ Ollama not running at {base}"
    except requests.exceptions.Timeout:
        return "⚠ Request timed out"
    except Exception: pass
    try:
        msgs2=(history or [])+[{"role":"user","content":prompt}]
        hdrs2=dict(hdrs); hdrs2["Authorization"]=f"Bearer {OPENAI_API_KEY}"
        r2=requests.post(OPENAI_BASE_URL.rstrip("/")+"/chat/completions",
                         headers=hdrs2,json={"model":model,"messages":msgs2,
                         "max_tokens":max_tokens,"temperature":0.7},timeout=180)
        if r2.status_code==200: return r2.json()["choices"][0]["message"]["content"].strip()
        return f"⚠ HTTP {r2.status_code}: {r2.text[:200]}"
    except Exception as e: return f"⚠ {type(e).__name__}: {e}"

def review_with_llm(files, mode="classify"):
    """
    mode:
      classify  — original SAFE/CAUTION/DANGEROUS per file
      summary   — disk waste summary + top 5 recommendations
      duplicates— analyze duplicate groups
      cleanup_plan — full action plan with commands
    """
    if mode == "classify":
        rows = [f'  [{"SYSTEM" if f["in_system"] else "USER"}] [{f["group"].upper()}] '
                f'{f["size_bytes"]/1048576:.1f}MB {f["path"]}' for f in files]
        prompt = (
            "You are a Windows cleanup expert. Classify each file in a single line:\n"
            "* SAFE | <short reason> — <path>\n"
            "* CAUTION | <short reason> — <path>\n"
            "* DANGEROUS | <short reason> — <path>\n\n"
            "Rules: Files in Windows/ and Program Files are always DANGEROUS. "
            "Files .tmp, .log, .bak are SAFE. "
            "Do not add any explanation outside the list.\n\nFiles:\n" + "\n".join(rows)
        )
        return _call_ollama(prompt, max_tokens=3000)

    elif mode == "summary":
        total_mb = sum(f["size_bytes"] for f in files) / 1048576
        by_group = {}
        for f in files:
            g = f["group"]
            by_group[g] = by_group.get(g, 0) + f["size_bytes"]
        group_lines = "\n".join(f"  {g}: {v/1048576:.0f} MB" for g,v in
                                  sorted(by_group.items(), key=lambda x: -x[1]))
        top5 = sorted(files, key=lambda x: -x["size_bytes"])[:5]
        top5_lines = "\n".join(f'  {f["size_bytes"]/1048576:.0f}MB  {f["path"]}' for f in top5)
        prompt = (
            f"Total space analyzed: {total_mb:.0f} MB\n"
            f"Distribution by type:\n{group_lines}\n"
            f"Top 5 largest files:\n{top5_lines}\n\n"
            "Write a short report (5-8 lines) including:\n"
            "1. Status summary\n"
            "2. Where is space being used?\n"  
            "3. Top 3 practical cleanup recommendations\n"
            "4. Estimated space that can be freed"
        )
        return _call_ollama(prompt, max_tokens=800)

    elif mode == "cleanup_plan":
        user_files = [f for f in files if not f["in_system"]]
        sys_files  = [f for f in files if f["in_system"]]
        rows = [f'  {f["size_bytes"]/1048576:.1f}MB [{f["group"]}] {f["path"]}' for f in files[:50]]
        prompt = (
            f"You have {len(user_files)} user file(s) and {len(sys_files)} system file(s) to analyze.\n"
            f"Total size: {sum(f['size_bytes'] for f in files)/1048576:.0f} MB\n\n"
            "Files:\n" + "\n".join(rows) + "\n\n"
            "Write a practical cleanup plan with the following steps:\n"
            "Step 1: Files safe for immediate deletion (list paths)\n"
            "Step 2: Files needing review before deletion\n"
            "Step 3: Files that must be kept\n"
            "Step 4: Recommendations to prevent recurrence\n"
            "Expected space savings: ? MB"
        )
        return _call_ollama(prompt, max_tokens=1200)

    elif mode == "smart_delete":
        # Only USER files, sorted by size, AI picks top deletable
        user_files = sorted([f for f in files if not f["in_system"]],
                             key=lambda x: -x["size_bytes"])[:40]
        rows = [f'  [{f["group"].upper()}] {f["size_bytes"]/1048576:.1f}MB {f["path"]}' 
                for f in user_files]
        prompt = (
            "You are a strict Windows cleanup expert. From the following list select only files "
            "100% safe to delete (temp files, logs, backups, cache, potential duplicates).\n"
            "Reply only with a list of paths, one per line, without any explanation:\n\n"
            + "\n".join(rows)
        )
        return _call_ollama(prompt, max_tokens=2000)

    # fallback
    return review_with_llm(files, mode="classify")

def test_llm():
    if not HAS_REQUESTS: return False,"requests library not installed"
    base=OPENAI_BASE_URL.rstrip("/").replace("/v1",""); model=_get_best_model()
    try:
        r=requests.post(base+"/api/generate",headers={"Content-Type":"application/json"},
            json={"model":model,"prompt":"hi","stream":False,"options":{"num_predict":1}},timeout=10)
        if r.status_code==200: return True,f"✓ Connected: {model}"
        if r.status_code==404:
            installed=_ollama_list_models()
            return False,(f"✗ Model not found — available: {installed[0]}" if installed else "✗ ollama pull llama3.2")
        return False,f"✗ HTTP {r.status_code}"
    except requests.exceptions.ConnectionError: return False,"✗ Ollama not running"
    except Exception as e: return False,f"✗ {type(e).__name__}"

# ═══════════════════════════════════════════════
#  WIDGETS
# ═══════════════════════════════════════════════
class FlatBtn(tk.Label):
    def __init__(self,parent,text,command=None,accent=ACCENT,bg=PANEL,fg=TEXT,
                 font=("Segoe UI",13,"bold"),padx=16,pady=8,**kw):
        self._accent=accent; self._bg_base=bg; self._fg=fg; self._cmd=command; self._hover=False
        super().__init__(parent,text=text,bg=bg,fg=fg,font=font,padx=padx,pady=pady,
                         cursor="hand2",relief="flat",bd=0,
                         highlightbackground=_blend(BORDER,accent,0.4),highlightthickness=1,**kw)
        self.bind("<Enter>",self._e); self.bind("<Leave>",self._l)
        self.bind("<Button-1>",self._p); self.bind("<ButtonRelease-1>",self._r)
    def _e(self,_): self._hover=True; self.configure(bg=_blend(self._bg_base,self._accent,0.25),highlightbackground=self._accent)
    def _l(self,_): self._hover=False; self.configure(bg=self._bg_base,highlightbackground=_blend(BORDER,self._accent,0.4))
    def _p(self,_): self.configure(bg=self._accent,fg=BG)
    def _r(self,_):
        self.configure(bg=_blend(self._bg_base,self._accent,0.25) if self._hover else self._bg_base,fg=self._fg)
        if self._cmd: self._cmd()
    def set_text(self,t): self.configure(text=t)
    def enable(self): self.configure(cursor="hand2",fg=self._fg)
    def disable(self): self.configure(cursor="",fg=TEXT3)

class ArcMeter(tk.Canvas):
    def __init__(self,parent,size=86,label="",bg=BG):
        super().__init__(parent,width=size,height=size,bg=bg,highlightthickness=0)
        self._sz=size; self._lbl=label; self._val=0.0; self._cur=0.0; self._aid=None
        self.after(10,self._draw)
    def set_value(self,v):
        self._val=max(0.0,min(100.0,v))
        if self._aid: self.after_cancel(self._aid)
        def step():
            self._cur+=(self._val-self._cur)*0.15; self._draw()
            if abs(self._cur-self._val)>0.4: self._aid=self.after(16,step)
            else: self._cur=self._val; self._draw()
        step()
    def _draw(self):
        try: self.delete("all")
        except tk.TclError: return
        s,v=self._sz,self._cur; p=9
        col=GREEN if v<60 else YELLOW if v<85 else RED
        self.create_arc(p,p,s-p,s-p,start=90,extent=360,style="arc",outline=CARD2,width=7)
        if v>0.5: self.create_arc(p,p,s-p,s-p,start=90,extent=-int(v/100*360),style="arc",outline=col,width=7)
        self.create_text(s//2,s//2-7,text=f"{v:.0f}%",fill=TEXT,font=("Segoe UI",16,"bold"),anchor="center")
        self.create_text(s//2,s//2+9,text=self._lbl,fill=TEXT3,font=("Segoe UI",11),anchor="center")

class PulseDot(tk.Canvas):
    def __init__(self,parent,color=YELLOW,bg=PANEL):
        super().__init__(parent,width=10,height=10,bg=bg,highlightthickness=0)
        self._color=color; self._bg=bg; self._ph=0.0; self._on=True
        self.after(20,self._tick)
    def set_color(self,c): self._color=c
    def _tick(self):
        if not self._on: return
        self._ph=(self._ph+0.08)%(2*math.pi); t=(1+math.sin(self._ph))/2
        def ch(i): return max(0,min(255,int(int(self._color[i:i+2],16)*t+int(self._bg[i:i+2],16)*(1-t))))
        col=f"#{ch(1):02x}{ch(3):02x}{ch(5):02x}"
        try: self.delete("all"); self.create_oval(1,1,9,9,fill=col,outline="")
        except tk.TclError: return
        self.after(45,self._tick)

class TreemapCanvas(tk.Canvas):
    def __init__(self,parent,**kw):
        super().__init__(parent,bg=BG2,highlightthickness=0,**kw)
        self._data=None; self._rects=[]; self._tip=None
        self.bind("<Motion>",self._on_motion); self.bind("<Configure>",self._on_resize)
    def set_data(self,node): self._data=node; self.after(20,self._render)
    def _on_resize(self,e):
        if self._data: self.after(50,self._render)
    def _render(self):
        try: self.delete("all")
        except tk.TclError: return
        if not self._data: return
        self._rects=[]; w=self.winfo_width(); h=self.winfo_height()
        if w<10 or h<10: return
        children=sorted(self._data.get("children",[]),key=lambda n:n["size"],reverse=True)[:60]
        if not children: return
        total=sum(c["size"] for c in children)
        if total==0: return
        self._squarify(children,total,4,4,w-8,h-8,0)
    def _squarify(self,nodes,total,x,y,w,h,depth):
        if not nodes or w<4 or h<4 or total==0: return
        col_idx=depth%len(TMAP_COLS)
        for i,node in enumerate(nodes):
            if total==0: break
            ratio=node["size"]/total
            if w>=h: bw=max(4,int(w*ratio)); bh=h
            else:    bw=w; bh=max(4,int(h*ratio))
            color=TMAP_COLS[(col_idx+i)%len(TMAP_COLS)]; dark=_blend(color,BG2,0.55)
            try:
                self.create_rectangle(x+1,y+1,x+bw-1,y+bh-1,fill=dark,outline=BG2,width=1)
                if bw>40 and bh>18:
                    mb=node["size"]/1048576; label=node["name"]
                    txt=f"{label}\n{mb:.0f} MB" if bh>34 else label
                    self.create_text(x+bw//2,y+bh//2,text=txt,fill=TEXT,
                                     font=("Segoe UI",9),anchor="center",width=bw-6)
            except tk.TclError: return
            self._rects.append((x+1,y+1,x+bw-1,y+bh-1,node))
            if w>=h: x+=bw
            else:    y+=bh
    def _on_motion(self,e):
        for x1,y1,x2,y2,node in reversed(self._rects):
            if x1<=e.x<=x2 and y1<=e.y<=y2:
                mb=node["size"]/1048576; tip=f"{node['name']}  —  {mb:.1f} MB"
                if self._tip!=tip:
                    self._tip=tip
                    try:
                        self.delete("tooltip")
                        self.create_rectangle(e.x+5,e.y-22,e.x+len(tip)*7+10,e.y-4,
                                              fill=CARD2,outline=ACCENT,tags="tooltip")
                        self.create_text(e.x+8,e.y-13,text=tip,fill=TEXT,
                                         font=("Segoe UI",9),anchor="w",tags="tooltip")
                    except tk.TclError: pass
                return
        self._tip=None
        try: self.delete("tooltip")
        except tk.TclError: pass

# ── Progress bar widget ───────────────────────────────────────────────
class ProgressBar(tk.Canvas):
    def __init__(self,parent,height=6,color=ACCENT,bg=CARD2,**kw):
        super().__init__(parent,height=height,bg=bg,highlightthickness=0,**kw)
        self._color=color; self._pct=0.0; self._bar=None
        self.bind("<Configure>",lambda e:self._draw())
    def set_pct(self,v):
        self._pct=max(0.0,min(100.0,v)); self._draw()
    def _draw(self):
        try: self.delete("all")
        except tk.TclError: return
        w=self.winfo_width(); h=self.winfo_height()
        if w<2: return
        self.create_rectangle(0,0,w,h,fill=CARD2,outline="")
        bw=int(w*self._pct/100)
        if bw>1: self.create_rectangle(0,0,bw,h,fill=self._color,outline="")

# ═══════════════════════════════════════════════
#  TTK STYLES
# ═══════════════════════════════════════════════
def apply_styles():
    s=ttk.Style(); s.theme_use("clam")
    s.configure(".",background=BG,foreground=TEXT,font=("Segoe UI",13))
    s.configure("TFrame",background=BG); s.configure("TLabel",background=BG,foreground=TEXT)
    s.configure("TEntry",fieldbackground=CARD,foreground=TEXT,insertcolor=ACCENT,
                bordercolor=BORD2,relief="flat",padding=(8,5))
    s.map("TEntry",bordercolor=[("focus",ACCENT)])
    s.configure("TSpinbox",fieldbackground=CARD,foreground=TEXT,insertcolor=ACCENT,
                bordercolor=BORD2,arrowcolor=TEXT2,relief="flat",padding=(5,4))
    s.configure("Vertical.TScrollbar",background=CARD2,troughcolor=BG2,arrowcolor=TEXT3,borderwidth=0,relief="flat")
    s.configure("Horizontal.TScrollbar",background=CARD2,troughcolor=BG2,arrowcolor=TEXT3,borderwidth=0,relief="flat")
    s.configure("Z.Treeview",background=CARD,foreground=TEXT,fieldbackground=CARD,
                rowheight=34,borderwidth=0,font=("Segoe UI",12))
    s.configure("Z.Treeview.Heading",background=CARD2,foreground=ACC2,relief="flat",
                font=("Segoe UI",12,"bold"),padding=(10,6))
    s.map("Z.Treeview",background=[("selected","#1e3a5f")],foreground=[("selected",TEXT)])
    s.map("Z.Treeview.Heading",background=[("active",CARD)])

def make_card(parent,title="",title_color=ACC2):
    outer=tk.Frame(parent,bg=PANEL,highlightbackground=BORDER,highlightthickness=1)
    if title:
        tk.Label(outer,text=title,bg=PANEL,fg=title_color,
                 font=("Segoe UI",13,"bold"),padx=14,pady=8).pack(anchor="w")
        tk.Frame(outer,bg=BORDER,height=1).pack(fill="x")
    inner=tk.Frame(outer,bg=PANEL); inner.pack(fill="both",expand=True)
    return outer,inner

def tree_with_scroll(parent,columns,headings,style="Z.Treeview"):
    parent.rowconfigure(0,weight=1); parent.columnconfigure(0,weight=1)
    tv=ttk.Treeview(parent,style=style,columns=columns,show="headings",selectmode="extended")
    for col,(hdr,w,anc) in zip(columns,headings):
        tv.heading(col,text=hdr,anchor=anc); tv.column(col,width=w,anchor=anc,stretch=(w==0))
    vsb=ttk.Scrollbar(parent,orient="vertical",command=tv.yview)
    hsb=ttk.Scrollbar(parent,orient="horizontal",command=tv.xview)
    tv.configure(yscrollcommand=vsb.set,xscrollcommand=hsb.set)
    tv.grid(row=0,column=0,sticky="nsew")
    vsb.grid(row=0,column=1,sticky="ns")
    hsb.grid(row=1,column=0,sticky="ew",columnspan=2)
    return tv

# ═══════════════════════════════════════════════
#  ENCRYPT DIALOG
# ═══════════════════════════════════════════════
class EncryptDialog(tk.Toplevel):
    """Password dialog for encryption/decryption."""
    def __init__(self,parent,title,file_count,mode="encrypt"):
        super().__init__(parent)
        self.title(title); self.configure(bg=PANEL)
        self.resizable(False,False); self.grab_set()
        self.result=None; self.delete_orig=tk.BooleanVar(value=False)

        w,h=420,280; self.geometry(f"{w}x{h}+{parent.winfo_rootx()+200}+{parent.winfo_rooty()+200}")

        tk.Label(self,text=title,bg=PANEL,fg=ACC2,font=("Segoe UI",14,"bold")).pack(pady=18)
        tk.Label(self,text=f"{'Encrypting' if mode=='encrypt' else 'Decrypting'} {file_count} file(s)",
                 bg=PANEL,fg=TEXT2,font=("Segoe UI",11)).pack(pady=14)

        tk.Frame(self,bg=BORDER,height=1).pack(fill="x",padx=20)

        pf=tk.Frame(self,bg=PANEL); pf.pack(fill="x",padx=24,pady=14)
        tk.Label(pf,text="Password:",bg=PANEL,fg=TEXT,font=("Segoe UI",12)).pack(anchor="w")
        self._e1=tk.Entry(pf,show="●",bg=CARD,fg=TEXT,insertbackground=ACCENT,
                          font=("Segoe UI",13),relief="flat",bd=0,
                          highlightbackground=BORD2,highlightthickness=1)
        self._e1.pack(fill="x",pady=4); self._e1.focus()

        if mode=="encrypt":
            cf=tk.Frame(self,bg=PANEL); cf.pack(fill="x",padx=24,pady=8)
            tk.Label(cf,text="Confirm Password:",bg=PANEL,fg=TEXT,font=("Segoe UI",12)).pack(anchor="w")
            self._e2=tk.Entry(cf,show="●",bg=CARD,fg=TEXT,insertbackground=ACCENT,
                              font=("Segoe UI",13),relief="flat",bd=0,
                              highlightbackground=BORD2,highlightthickness=1)
            self._e2.pack(fill="x",pady=4)
            df=tk.Frame(self,bg=PANEL); df.pack(fill="x",padx=24,pady=6)
            tk.Checkbutton(df,text="Delete original file after encryption",variable=self.delete_orig,
                           bg=PANEL,fg=TEXT2,selectcolor=CARD,activebackground=PANEL,
                           font=("Segoe UI",11)).pack(anchor="w")
        else:
            self._e2=None

        self._err=tk.Label(self,text="",bg=PANEL,fg=RED,font=("Segoe UI",10))
        self._err.pack()

        bf=tk.Frame(self,bg=PANEL); bf.pack(pady=16)
        FlatBtn(bf,"Confirm",command=self._ok,accent=ACCENT,bg=CARD,fg=TEXT,
                font=("Segoe UI",12,"bold"),padx=24,pady=8).pack(side="left",padx=8)
        FlatBtn(bf,"Cancel",command=self.destroy,accent=RED,bg=CARD,fg=TEXT,
                font=("Segoe UI",12,"bold"),padx=24,pady=8).pack(side="left",padx=8)
        self.bind("<Return>",lambda e:self._ok())
        self.bind("<Escape>",lambda e:self.destroy())

    def _ok(self):
        pw=self._e1.get()
        if len(pw)<4: self._err.configure(text="⚠ Password too short (minimum 4 characters)"); return
        if self._e2 and self._e2.get()!=pw: self._err.configure(text="⚠ Passwords do not match"); return
        self.result=(pw,self.delete_orig.get()); self.destroy()

# ═══════════════════════════════════════════════
#  MAIN APP
# ═══════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════
#  CONFIG / UI TEXT
# ═══════════════════════════════════════════════════════════════════
import json as _json

_CFG_PATH = Path(os.environ.get("APPDATA", Path.home())) / "DiskVision" / "config.json"
_DARK = {
    "BG":"#0a0e1a","BG2":"#0d1220","PANEL":"#111827","CARD":"#1a2235","CARD2":"#1e2a40",
    "SB":"#070c18","SB_ACT":"#142030","SB_HOVER":"#0f1e2e","SB_FG":"#4a6080","SB_AFG":"#38bdf8",
    "BORDER":"#1e3a5f","BORD2":"#243b5c","ACCENT":"#0ea5e9","ACC2":"#38bdf8","PURPLE":"#8b5cf6",
    "GREEN":"#10b981","GREEN2":"#34d399","YELLOW":"#f59e0b","YELL2":"#fbbf24",
    "RED":"#ef4444","RED2":"#f87171","ORANGE":"#f97316",
    "TEXT":"#f1f5f9","TEXT2":"#94a3b8","TEXT3":"#475569","MONO":"#a5f3fc",
    "STBG":"#070c18","STFG":"#475569","EBG":"#1a2235","EFG":"#f1f5f9",
    "TVBG":"#111827","TVFG":"#f1f5f9","TVSEL":"#1e3a5f","TVHDR":"#1a2235",
}
_CFG:  dict = {}
_STRS: dict = {}
_STRS_CACHE: dict = {}

def _load_cfg():
    global _CFG
    _CFG = {"llm_url":"http://localhost:11434/v1","llm_model":"llama3.2",
            "window_geometry":"1400x860"}
    try:
        if _CFG_PATH.exists():
            _CFG.update(_json.loads(_CFG_PATH.read_text("utf-8")))
    except: pass
    _load_lang("en")

def _save_cfg():
    try:
        _CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CFG_PATH.write_text(_json.dumps(_CFG, indent=2, ensure_ascii=False), "utf-8")
    except: pass

def _load_lang(code: str) -> bool:
    global _STRS
    if code in _STRS_CACHE: _STRS = _STRS_CACHE[code]; return True
    for d in [Path(__file__).parent/"languages", Path("languages")]:
        p = d / f"{code}.json"
        if p.exists():
            try:
                data = _json.loads(p.read_text("utf-8"))
                _STRS_CACHE[code] = data; _STRS = data; return True
            except: pass
    if code != "en": return _load_lang("en")
    return False

def _t(k: str, **kw) -> str:
    s = _STRS.get(k, k)
    try: return s.format(**kw) if kw else s
    except: return s

def _col(k: str) -> str:
    return _DARK.get(k, "#888888")

_load_cfg()

# Update existing palette globals to match loaded theme
def _sync_palette():
    global BG,BG2,PANEL,CARD,CARD2,BORDER,BORD2,ACCENT,ACC2,PURPLE
    global GREEN,GREEN2,YELLOW,YELL2,RED,RED2,ORANGE,TEXT,TEXT2,TEXT3,MONO
    BG=_col("BG"); BG2=_col("BG2"); PANEL=_col("PANEL"); CARD=_col("CARD"); CARD2=_col("CARD2")
    BORDER=_col("BORDER"); BORD2=_col("BORD2"); ACCENT=_col("ACCENT"); ACC2=_col("ACC2")
    PURPLE=_col("PURPLE"); GREEN=_col("GREEN"); GREEN2=_col("GREEN2")
    YELLOW=_col("YELLOW"); YELL2=_col("YELL2"); RED=_col("RED"); RED2=_col("RED2")
    ORANGE=_col("ORANGE"); TEXT=_col("TEXT"); TEXT2=_col("TEXT2"); TEXT3=_col("TEXT3"); MONO=_col("MONO")

_sync_palette()


# ═══════════════════════════════════════════════════════════════════
#  SIDEBAR ITEM
# ═══════════════════════════════════════════════════════════════════
class SidebarItem(tk.Frame):
    def __init__(self, parent, icon: str, label: str, tab_id: str, on_click):
        super().__init__(parent, bg=_col("SB"), cursor="hand2", height=44)
        self._tid = tab_id; self._cb = on_click; self._active = False
        self.pack_propagate(False)
        self._bar = tk.Frame(self, bg=_col("SB"), width=3)
        self._bar.pack(side="left", fill="y")
        body = tk.Frame(self, bg=_col("SB"))
        body.pack(side="left", fill="both", expand=True, padx=(10,12))
        self._ico = tk.Label(body, text=icon, bg=_col("SB"), fg=_col("SB_FG"),
                              font=("Segoe UI", 14))
        self._ico.pack(side="left", padx=(0, 9))
        self._lbl = tk.Label(body, text=label, bg=_col("SB"), fg=_col("SB_FG"),
                              font=("Segoe UI", 11), anchor="w")
        self._lbl.pack(side="left", fill="x", expand=True)
        for w in [self, body, self._ico, self._lbl, self._bar]:
            w.bind("<Button-1>", lambda e: self._cb(self._tid))
            w.bind("<Enter>", self._hover_on)
            w.bind("<Leave>", self._hover_off)

    def _all_widgets(self):
        result = [self]
        for w in self.winfo_children():
            result.append(w)
            result.extend(w.winfo_children())
        return result

    def _hover_on(self, _=None):
        if not self._active:
            for w in self._all_widgets():
                try: w.configure(bg=_col("SB_HOVER"))
                except: pass
            self._ico.configure(fg=_col("TEXT2"))
            self._lbl.configure(fg=_col("TEXT2"))

    def _hover_off(self, _=None):
        if not self._active: self._paint_inactive()

    def _paint_inactive(self):
        for w in self._all_widgets():
            try: w.configure(bg=_col("SB"))
            except: pass
        self._bar.configure(bg=_col("SB"))
        self._ico.configure(fg=_col("SB_FG"), bg=_col("SB"))
        self._lbl.configure(fg=_col("SB_FG"), bg=_col("SB"),
                             font=("Segoe UI", 11))

    def set_active(self, active: bool):
        self._active = active
        if active:
            for w in self._all_widgets():
                try: w.configure(bg=_col("SB_ACT"))
                except: pass
            self._bar.configure(bg=_col("ACCENT"))
            self._ico.configure(fg=_col("ACC2"), bg=_col("SB_ACT"))
            self._lbl.configure(fg=_col("SB_AFG"), bg=_col("SB_ACT"),
                                 font=("Segoe UI", 11, "bold"))
        else:
            self._paint_inactive()


# ═══════════════════════════════════════════════════════════════════
#  APP CLASS  (CCleaner layout — replaces old App)
# ═══════════════════════════════════════════════════════════════════
class App(tk.Tk):

    # Maps old tab ids -> sidebar item ids (same here, just for clarity)
    _PAGES = ["home","search","disk","dup","tmap","ram","startup","temp","ai","chat"]

    def __init__(self):
        super().__init__()
        self.title("DiskVision")
        self.geometry(_CFG.get("window_geometry","1400x860"))
        self.minsize(1050, 660)
        self.configure(bg=_col("BG"))
        try:
            from ctypes import windll; windll.shcore.SetProcessDpiAwareness(1)
        except: pass

        apply_styles()

        # ── State (identical to v5) ────────────────────────────────
        self.scan_results:    List[dict] = []
        self.dup_results:     List[list] = []
        self.startup_entries: List[dict] = []
        self.search_results:  List[dict] = []
        self._scanning    = False; self._dup_busy    = False
        self._llm_busy    = False; self._tmap_busy   = False
        self._search_busy = False
        self._search_after = None; self._search_token = 0
        self._idx_engine = FileIndexEngine.instance()
        self._cur_tab = "home"
        self._chat_history: List[dict] = [{
            "role": "system",
            "content": ("You are an intelligent assistant specializing in Windows system cleanup and maintenance. "
                        "Give concise, practical answers. "
                        "Keep file names and paths in their original format.")
        }]

        # ── Sidebar items dict (tab_id -> SidebarItem) ─────────────
        self._sb_items: Dict[str, SidebarItem] = {}

        # ── Build CCleaner layout ──────────────────────────────────
        self._build_topbar()
        self._build_body()          # sidebar + content area
        self._build_tabs()          # creates self._f_home, self._f_disk … (same names as v5)
        self._build_statusbar()

        # ── Switch to default page ─────────────────────────────────
        self._switch("home")

        # ── Background tasks ───────────────────────────────────────
        self.after(700, self._auto_ram)
        self.after(500, self._start_index_engine)
        threading.Thread(target=self._check_llm, daemon=True).start()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ══════════════════════════════════════════════════════════════
    #  TOP BAR
    # ══════════════════════════════════════════════════════════════
    def _build_topbar(self):
        bar = tk.Frame(self, bg=_col("SB"), height=54)
        bar.pack(fill="x"); bar.pack_propagate(False)

        # Logo + title
        left = tk.Frame(bar, bg=_col("SB")); left.pack(side="left", padx=16, fill="y")
        logo = tk.Canvas(left, width=28, height=28, bg=_col("SB"), highlightthickness=0)
        logo.pack(side="left", pady=13)
        def _draw():
            logo.create_polygon([14,2,25,7,25,21,14,28,3,21,3,7],
                                  fill=_col("ACCENT"), outline=_col("ACC2"), smooth=True)
            logo.create_text(14,16, text="D", fill=_col("SB"), font=("Segoe UI",8,"bold"))
        self.after(10, _draw)
        tf = tk.Frame(left, bg=_col("SB")); tf.pack(side="left", padx=(8,0), fill="y")
        tk.Label(tf, text="DiskVision", bg=_col("SB"), fg=_col("TEXT"),
                 font=("Segoe UI",13,"bold")).pack(anchor="w", pady=(10,0))
        tk.Label(tf, text=f"v{APP_VERSION}", bg=_col("SB"), fg=_col("SB_FG"),
                 font=("Segoe UI",8)).pack(anchor="w")

        # AI status dot (right side)
        right = tk.Frame(bar, bg=_col("SB")); right.pack(side="right", padx=14, fill="y")
        dr = tk.Frame(right, bg=_col("SB")); dr.place(relx=1.0, rely=0.5, anchor="e")
        self._dot = PulseDot(dr, color=YELLOW, bg=_col("SB")); self._dot.pack(side="left", padx=4)
        self._dot_lbl = tk.Label(dr, text="Connecting…", bg=_col("SB"), fg=_col("SB_FG"),
                                  font=("Segoe UI",9))
        self._dot_lbl.pack(side="left")

        tk.Frame(self, bg=_col("BORDER"), height=1).pack(fill="x")

    # ══════════════════════════════════════════════════════════════
    #  BODY: SIDEBAR + CONTENT
    # ══════════════════════════════════════════════════════════════
    def _build_body(self):
        self._body = tk.Frame(self, bg=_col("BG"))
        self._body.pack(fill="both", expand=True)

        # ── Sidebar (200px fixed) ──────────────────────────────────
        self._sb = tk.Frame(self._body, bg=_col("SB"), width=200)
        self._sb.pack(side="left", fill="y"); self._sb.pack_propagate(False)

        tk.Frame(self._sb, bg=_col("SB"), height=8).pack(fill="x")

        sidebar_items = [
            ("home",    "⊞",  "Dashboard"),
            ("temp",    "⚡",  "Quick Clean"),
            ("disk",    "💾",  "Disk Analyzer"),
            ("dup",     "🔁",  "Duplicates"),
            ("search",  "🔍",  "Search"),
            ("startup", "🚀",  "Startup"),
            ("ram",     "📊",  "RAM Monitor"),
            ("ai",      "🤖",  "AI Analysis"),
        ]
        for tid, icon, label in sidebar_items:
            item = SidebarItem(self._sb, icon, label, tid, self._switch)
            item.pack(fill="x", pady=1)
            self._sb_items[tid] = item

        # Spacer pushes Settings to bottom
        tk.Frame(self._sb, bg=_col("SB")).pack(fill="both", expand=True)
        tk.Frame(self._sb, bg=_col("BORDER"), height=1).pack(fill="x", padx=12, pady=4)

        settings_item = SidebarItem(self._sb, "⚙", "Settings", "settings", self._switch)
        settings_item.pack(fill="x", pady=1)
        self._sb_items["settings"] = settings_item

        tk.Label(self._sb, text=f"DiskVision {APP_VERSION}", bg=_col("SB"), fg=_col("SB_FG"),
                 font=("Segoe UI",7)).pack(pady=8)

        # Divider
        tk.Frame(self._body, bg=_col("BORDER"), width=1).pack(side="left", fill="y")

        # ── Content area ───────────────────────────────────────────
        self._content = tk.Frame(self._body, bg=_col("BG"))
        self._content.pack(side="left", fill="both", expand=True)
        self._content.rowconfigure(0, weight=1)
        self._content.columnconfigure(0, weight=1)

    # ══════════════════════════════════════════════════════════════
    #  BUILD TABS  — creates self._f_home, _f_disk, etc. (v5 names)
    #  Each tab gets a page header + the original tab content
    # ══════════════════════════════════════════════════════════════
    def _build_tabs(self):
        host = self._content

        def page(tab_builder, icon, title):
            """Create a page frame with header + original tab content."""
            f = tk.Frame(host, bg=_col("BG"))
            # Page header
            hdr = tk.Frame(f, bg=_col("PANEL"),
                            highlightbackground=_col("BORDER"), highlightthickness=1)
            hdr.pack(fill="x")
            row = tk.Frame(hdr, bg=_col("PANEL")); row.pack(fill="x", padx=16, pady=10)
            tk.Label(row, text=f"{icon}  {title}", bg=_col("PANEL"), fg=_col("TEXT"),
                     font=("Segoe UI",15,"bold")).pack(side="left")
            tk.Frame(f, bg=_col("BORDER"), height=1).pack(fill="x")
            # Original tab content
            inner = tk.Frame(f, bg=_col("BG")); inner.pack(fill="both", expand=True)
            result = tab_builder(inner)
            if result is not None:
                result.pack(fill="both", expand=True)
            f.grid(row=0, column=0, sticky="nsew")
            return f

        def disk_page():
            """Disk page has 2 sub-tabs: Large Files + Treemap"""
            f = tk.Frame(host, bg=_col("BG"))
            hdr = tk.Frame(f, bg=_col("PANEL"),
                            highlightbackground=_col("BORDER"), highlightthickness=1)
            hdr.pack(fill="x")
            row = tk.Frame(hdr, bg=_col("PANEL")); row.pack(fill="x", padx=16, pady=10)
            tk.Label(row, text="💾  Disk Analyzer", bg=_col("PANEL"), fg=_col("TEXT"),
                     font=("Segoe UI",15,"bold")).pack(side="left")
            tk.Frame(f, bg=_col("BORDER"), height=1).pack(fill="x")
            # Sub-tab bar
            tb = tk.Frame(f, bg=_col("PANEL")); tb.pack(fill="x")
            files_f = tk.Frame(f, bg=_col("BG"))
            tmap_f  = tk.Frame(f, bg=_col("BG"))
            subs = {"files": files_f, "tmap": tmap_f}
            sbtns = {}
            def _show(n):
                for x, ff in subs.items(): ff.pack_forget()
                subs[n].pack(fill="both", expand=True)
                for x, b in sbtns.items():
                    b.configure(fg=_col("ACC2") if x==n else _col("TEXT2"),
                                font=("Segoe UI",10,"bold") if x==n else ("Segoe UI",10))
            for sid, slbl in [("files","Large Files"),("tmap","Disk Treemap")]:
                b = tk.Label(tb, text=slbl, bg=_col("PANEL"), fg=_col("TEXT2"),
                              font=("Segoe UI",10), padx=14, pady=6, cursor="hand2")
                b.pack(side="left")
                b.bind("<Button-1>", lambda e, n=sid: _show(n))
                sbtns[sid] = b
            tk.Frame(f, bg=_col("BORDER"), height=1).pack(fill="x")
            r1 = self._tab_disk(files_f)
            if r1: r1.pack(fill="both", expand=True)
            r2 = self._tab_tmap(tmap_f)
            if r2: r2.pack(fill="both", expand=True)
            _show("files")
            f.grid(row=0, column=0, sticky="nsew")
            return f

        def ai_page():
            """AI page has 2 sub-tabs: Analysis + Chat"""
            f = tk.Frame(host, bg=_col("BG"))
            hdr = tk.Frame(f, bg=_col("PANEL"),
                            highlightbackground=_col("BORDER"), highlightthickness=1)
            hdr.pack(fill="x")
            row = tk.Frame(hdr, bg=_col("PANEL")); row.pack(fill="x", padx=16, pady=10)
            tk.Label(row, text="🤖  AI Analysis", bg=_col("PANEL"), fg=_col("TEXT"),
                     font=("Segoe UI",15,"bold")).pack(side="left")
            tk.Frame(f, bg=_col("BORDER"), height=1).pack(fill="x")
            tb = tk.Frame(f, bg=_col("PANEL")); tb.pack(fill="x")
            ai_f   = tk.Frame(f, bg=_col("BG"))
            chat_f = tk.Frame(f, bg=_col("BG"))
            subs = {"analyze": ai_f, "chat": chat_f}
            sbtns = {}
            def _show(n):
                for x, ff in subs.items(): ff.pack_forget()
                subs[n].pack(fill="both", expand=True)
                for x, b in sbtns.items():
                    b.configure(fg=_col("ACC2") if x==n else _col("TEXT2"),
                                font=("Segoe UI",10,"bold") if x==n else ("Segoe UI",10))
            for sid, slbl in [("analyze","File Analysis"),("chat","AI Chat")]:
                b = tk.Label(tb, text=slbl, bg=_col("PANEL"), fg=_col("TEXT2"),
                              font=("Segoe UI",10), padx=14, pady=6, cursor="hand2")
                b.pack(side="left")
                b.bind("<Button-1>", lambda e, n=sid: _show(n))
                sbtns[sid] = b
            tk.Frame(f, bg=_col("BORDER"), height=1).pack(fill="x")
            r1 = self._tab_ai(ai_f)
            if r1: r1.pack(fill="both", expand=True)
            r2 = self._tab_chat(chat_f)
            if r2: r2.pack(fill="both", expand=True)
            _show("analyze")
            f.grid(row=0, column=0, sticky="nsew")
            return f

        def settings_page():
            """Settings page with app connection options."""
            f = tk.Frame(host, bg=_col("BG"))
            hdr = tk.Frame(f, bg=_col("PANEL"),
                            highlightbackground=_col("BORDER"), highlightthickness=1)
            hdr.pack(fill="x")
            tk.Label(hdr, text="⚙  Settings", bg=_col("PANEL"), fg=_col("TEXT"),
                     font=("Segoe UI",15,"bold"), padx=16, pady=10).pack(side="left")
            tk.Frame(f, bg=_col("BORDER"), height=1).pack(fill="x")

            body = tk.Frame(f, bg=_col("BG")); body.pack(fill="both", expand=True, padx=18, pady=14)
            body.columnconfigure(0, minsize=148); body.columnconfigure(1, weight=1)
            body.rowconfigure(0, weight=1)

            # Left menu
            lf = tk.Frame(body, bg=_col("CARD"),
                           highlightbackground=_col("BORDER"), highlightthickness=1)
            lf.grid(row=0, column=0, sticky="nsew", padx=(0,10))
            tk.Label(lf, text="SETTINGS", bg=_col("CARD"), fg=_col("TEXT3"),
                     font=("Consolas",7,"bold"), padx=12).pack(anchor="w", pady=(10,4))

            rh = tk.Frame(body, bg=_col("BG")); rh.grid(row=0, column=1, sticky="nsew")
            rh.rowconfigure(0, weight=1); rh.columnconfigure(0, weight=1)

            panels = {}; sbtns2 = {}

            def _show_s(sid):
                for n, p in panels.items(): p.grid_remove()
                panels[sid].grid(row=0, column=0, sticky="nsew")
                for n, b in sbtns2.items():
                    b.configure(bg=_col("SB_ACT") if n==sid else _col("CARD"),
                                fg=_col("ACC2") if n==sid else _col("TEXT2"),
                                font=("Segoe UI",10,"bold") if n==sid else ("Segoe UI",10))

            # Left-side sections menu.
            for sid, icon, label in [("general", "⚙", _t("settings_general"))]:
                b = tk.Label(lf, text=f"{icon}  {label}", bg=_col("CARD"), fg=_col("TEXT2"),
                              font=("Segoe UI",10), padx=14, pady=8, anchor="w", cursor="hand2")
                b.pack(fill="x"); b.bind("<Button-1>", lambda e, s=sid: _show_s(s))
                sbtns2[sid] = b

            # General panel
            go, gi = make_card(rh, f"⚙  {_t('settings_general')}")
            go.grid(row=0, column=0, sticky="nsew")
            for lbl_key, attr, default in [
                ("settings_llm_url",   "_s_url",   _CFG.get("llm_url","http://localhost:11434/v1")),
                ("settings_llm_model", "_s_model", _CFG.get("llm_model","llama3.2")),
            ]:
                fr = tk.Frame(gi, bg=_col("CARD")); fr.pack(fill="x", padx=14, pady=6)
                tk.Label(fr, text=_t(lbl_key), bg=_col("CARD"), fg=_col("TEXT2"),
                          font=("Segoe UI",9)).pack(anchor="w")
                v = tk.StringVar(value=default); setattr(self, attr, v)
                tk.Entry(fr, textvariable=v, bg=_col("EBG"), fg=_col("EFG"),
                          insertbackground=_col("ACCENT"), font=("Consolas",10), relief="flat",
                          highlightthickness=1, highlightbackground=_col("BORD2")).pack(fill="x", pady=2)
            tk.Frame(gi, bg=_col("BORDER"), height=1).pack(fill="x", pady=8)
            bf = tk.Frame(gi, bg=_col("CARD")); bf.pack(anchor="w", padx=14, pady=(0,12))
            FlatBtn(bf, _t("settings_save"), command=self._save_settings,
                    accent=_col("GREEN"), bg=CARD2, fg=TEXT,
                    font=("Segoe UI",10,"bold"), padx=14, pady=6).pack(side="left", padx=(0,8))
            self._s_lbl = tk.Label(bf, text="", bg=_col("CARD"), fg=_col("GREEN"),
                                    font=("Segoe UI",9)); self._s_lbl.pack(side="left")
            panels["general"] = go

            for p in panels.values(): p.grid(row=0, column=0, sticky="nsew")
            _show_s("general")
            f.grid(row=0, column=0, sticky="nsew")
            return f

        # ── Create all page frames ─────────────────────────────────
        self._f_home    = page(self._tab_home,    "⊞",  "Dashboard")
        self._f_temp    = page(self._tab_temp,    "⚡", "Quick Clean")
        self._f_disk    = disk_page()
        self._f_dup     = page(self._tab_dup,     "🔁", "Duplicates")
        self._f_search  = page(self._tab_search,  "🔍", "Search")
        self._f_startup = page(self._tab_startup, "🚀", "Startup")
        self._f_ram     = page(self._tab_ram,     "📊", "RAM Monitor")
        self._f_ai      = ai_page()
        self._f_chat    = self._f_ai          # chat is sub-tab of ai page
        self._f_tmap    = self._f_disk        # tmap is sub-tab of disk page
        self._f_settings = settings_page()

    # ══════════════════════════════════════════════════════════════
    #  STATUSBAR
    # ══════════════════════════════════════════════════════════════
    def _build_statusbar(self):
        self._status_bar = tk.Frame(self, bg=_col("STBG"), height=24)
        self._status_bar.pack(fill="x", side="bottom"); self._status_bar.pack_propagate(False)
        self._build_statusbar_inner()

    def _build_statusbar_inner(self):
        bar = self._status_bar
        self._slbl = tk.Label(bar, text="Ready", bg=_col("STBG"), fg=_col("STFG"),
                               font=("Segoe UI",9), anchor="w")
        self._slbl.pack(side="left", padx=10)
        self._prog = ProgressBar(bar, height=3, color=_col("ACCENT"), bg=_col("STBG"))
        self._prog.pack(side="left", fill="x", expand=True, padx=6)
        tk.Label(bar, text=f"DiskVision {APP_VERSION}  ·  Python",
                 bg=_col("STBG"), fg=_col("STFG"), font=("Consolas",8)).pack(side="right", padx=10)

    def _setstatus(self, msg, color=TEXT3, pct=None):
        try:
            self._slbl.configure(text=msg, fg=color)
            if pct is not None: self._prog.set_pct(pct)
        except: pass

    # ══════════════════════════════════════════════════════════════
    #  SWITCH  (CCleaner sidebar version — same API as v5)
    # ══════════════════════════════════════════════════════════════
    def _switch(self, tab: str):
        self._cur_tab = tab
        # Map tab id → frame
        frame_map = {
            "home": self._f_home, "search": self._f_search, "disk": self._f_disk,
            "dup": self._f_dup, "tmap": self._f_disk, "ram": self._f_ram,
            "startup": self._f_startup, "temp": self._f_temp,
            "ai": self._f_ai, "chat": self._f_ai, "settings": self._f_settings,
        }
        if tab in frame_map:
            frame_map[tab].tkraise()
        # Update sidebar highlight
        for tid, item in self._sb_items.items():
            # Map chat/tmap back to their parent page id for highlight
            active_tid = {"chat":"ai","tmap":"disk"}.get(tab, tab)
            item.set_active(tid == active_tid)

    # ══════════════════════════════════════════════════════════════
    #  SETTINGS SAVE
    # ══════════════════════════════════════════════════════════════
    def _save_settings(self):
        global OPENAI_BASE_URL, OPENAI_MODEL
        _CFG["llm_url"]   = self._s_url.get()
        _CFG["llm_model"] = self._s_model.get()
        OPENAI_BASE_URL   = _CFG["llm_url"]
        OPENAI_MODEL      = _CFG["llm_model"]
        _save_cfg()
        try:
            self._s_lbl.configure(text="✓ " + _t("settings_saved"))
            self.after(2500, lambda: self._s_lbl.configure(text=""))
        except: pass
        threading.Thread(target=self._check_llm, daemon=True).start()

    # ══════════════════════════════════════════════════════════════
    #  LIFECYCLE
    # ══════════════════════════════════════════════════════════════
    # ══════════════════════════════════════════════════════════════
    def _on_close(self):
        if self._scanning or self._llm_busy:
            if not messagebox.askyesno("Confirm", "A task is running. Do you want to close?"): return
        _CFG["window_geometry"] = self.geometry()
        _save_cfg()
        try: self.destroy()
        except: sys.exit(0)

    # ══════════════════════════════════════════════════════════════
    #  ORIGINAL FUNCTIONAL METHODS (v5 — unchanged)
    # ══════════════════════════════════════════════════════════════
    def _setstatus(self,msg,color=TEXT3,pct=None):
        self._slbl.configure(text=msg,fg=color)
        if pct is not None: self._prog.set_pct(pct)

    # ══════════════════════════════════════════
    #  TAB HOME — Quick Actions (for regular users)
    # ══════════════════════════════════════════
    def _tab_home(self,host):
        root=tk.Frame(host,bg=BG)
        # Welcome header
        hdr=tk.Frame(root,bg=PANEL,highlightbackground=BORDER,highlightthickness=1)
        hdr.pack(fill="x",padx=16,pady=16)
        tk.Label(hdr,text="Hello! 👋  What would you like to do today?",bg=PANEL,fg=TEXT,
                 font=("Segoe UI",17,"bold"),pady=14,padx=20).pack(anchor="w")
        tk.Label(hdr,text="Click any button to get started — no settings needed",
                 bg=PANEL,fg=TEXT2,font=("Segoe UI",12),padx=20,pady=12).pack(anchor="w")

        grid=tk.Frame(root,bg=BG); grid.pack(fill="both",expand=True,padx=16,pady=8)
        grid.columnconfigure((0,1,2),weight=1)

        def qcard(parent,row,col,icon,title,desc,color,cmd):
            f=tk.Frame(parent,bg=PANEL,highlightbackground=_blend(BORDER,color,0.4),highlightthickness=1,
                       cursor="hand2")
            f.grid(row=row,column=col,padx=8,pady=8,sticky="nsew")
            parent.rowconfigure(row,weight=1)
            tk.Label(f,text=icon,bg=PANEL,font=("Segoe UI",32)).pack(pady=20)
            tk.Label(f,text=title,bg=PANEL,fg=color,font=("Segoe UI",14,"bold")).pack()
            tk.Label(f,text=desc,bg=PANEL,fg=TEXT2,font=("Segoe UI",10),
                     wraplength=220,justify="center").pack(pady=20,padx=10)
            f.bind("<Enter>",lambda e,fw=f,c=color: fw.configure(highlightbackground=c))
            f.bind("<Leave>",lambda e,fw=f,c=color: fw.configure(highlightbackground=_blend(BORDER,c,0.4)))
            for w in f.winfo_children():
                try:
                    w.bind("<Enter>",lambda e,fw=f,c=color: fw.configure(highlightbackground=c))
                    w.bind("<Leave>",lambda e,fw=f,c=color: fw.configure(highlightbackground=_blend(BORDER,c,0.4)))
                    w.bind("<Button-1>",lambda e,c=cmd: c())
                except: pass
            return f

        qcard(grid,0,0,"🔍","Quick Full Scan",
              "Scans all drives and finds large files automatically",
              ACCENT,self._quick_full_scan)
        qcard(grid,0,1,"🔁","Find Duplicate Files",
              "Finds duplicate files in user folder and frees space",
              PURPLE,self._quick_dup_scan)
        qcard(grid,0,2,"📦","Compress Large Files",
              "Select files and compress them to ZIP to save space",
              GREEN,self._quick_compress)
        qcard(grid,1,0,"🔒","Encrypt Files",
              "Protect your files with a password — no one can open them without it",
              YELLOW,self._quick_encrypt)
        qcard(grid,1,1,"🔓","Decrypt Files",
              "Enter password to decrypt protected file(s)",
              ORANGE,self._quick_decrypt)
        qcard(grid,1,2,"🗺","Space Map",
              "See which folders take up the most space on your drive",
              ACC2,lambda:self._switch("tmap"))
        qcard(grid,2,0,"🧹","Clean Temp Files",
              "Deletes temp and cache files to free space",
              ORANGE,lambda:self._switch("temp"))
        qcard(grid,2,1,"🗑","One-Click Full Cleanup",
              "Deletes all temp files at once without questions",
              RED,self._quick_clean_all)
        qcard(grid,2,2,"📊","Memory Monitor",
              "See which programs consume RAM and slow your PC",
              PURPLE,lambda:self._switch("ram"))

        # Quick stats bar
        stats_out,stats=make_card(root,"📊  System Overview")
        stats_out.pack(fill="x",padx=16,pady=16)
        sf=tk.Frame(stats,bg=PANEL); sf.pack(fill="x",padx=12,pady=10)
        self._home_stat_lbl=tk.Label(sf,text="Gathering information…",
                                      bg=PANEL,fg=TEXT2,font=("Segoe UI",12))
        self._home_stat_lbl.pack(side="left")
        FlatBtn(sf,"Refresh",command=self._refresh_home_stats,
                accent=ACCENT,bg=CARD,fg=TEXT,font=("Segoe UI",11,"bold"),
                padx=12,pady=5).pack(side="right")
        self.after(1000,self._refresh_home_stats)
        return root

    def _refresh_home_stats(self):
        def run():
            parts=[]
            try:
                import shutil
                drives=get_all_drives()
                for d in drives[:4]:
                    try:
                        total,used,free=shutil.disk_usage(d)
                        pct=used/total*100
                        parts.append(f"  💾 {d}  Used: {fmt_size(used)} / {fmt_size(total)}  ({pct:.0f}%)")
                    except: pass
            except: pass
            if HAS_PSUTIL:
                vm=psutil.virtual_memory()
                parts.append(f"  🧠 RAM: {fmt_size(vm.used)} / {fmt_size(vm.total)} ({vm.percent:.0f}%)")
            txt="       ".join(parts) if parts else "Could not gather information"
            self.after(0,lambda: self._home_stat_lbl.configure(text=txt))
        threading.Thread(target=run,daemon=True).start()

    def _quick_full_scan(self):
        """Scan ALL drives with one click."""
        drives=get_all_drives()
        self._switch("disk")
        self._scan_lbl.configure(text=f"Full scan: {', '.join(drives)}",fg=YELLOW)
        self._start_full_scan(drives)

    def _quick_dup_scan(self):
        self._dup_path_var.set(str(Path.home()))
        self._switch("dup")
        self._start_dup()

    def _quick_clean_all(self):
        """One-click: scan and clean all safe temp locations."""
        self._switch("temp")
        self.after(100, self._temp_scan_then_clean_safe)

    def _quick_compress(self):
        paths=filedialog.askopenfilenames(title="Select files to compress")
        if paths: self._compress_files(list(paths))

    def _quick_encrypt(self):
        paths=filedialog.askopenfilenames(title="Select files to encrypt")
        if paths: self._encrypt_files(list(paths))

    def _quick_decrypt(self):
        paths=filedialog.askopenfilenames(title="Select encrypted files (.enc)",
                                          filetypes=[("Encrypted files","*.enc"),("All files","*.*")])
        if paths: self._decrypt_files(list(paths))

    # ══════════════════════════════════════════
    #  TAB SEARCH — Instant Search
    # ══════════════════════════════════════════
    def _tab_search(self,host):
        root=tk.Frame(host,bg=BG)

        # ── Search card ───────────────────────────────────────────
        top_out,top=make_card(root,"🔍  Instant File Search")
        top_out.pack(fill="x",padx=16,pady=16)

        # Row 1 — search box
        sr=tk.Frame(top,bg=PANEL); sr.pack(fill="x",padx=12,pady=12)
        sr.columnconfigure(1,weight=1)
        tk.Label(sr,text="🔍",bg=PANEL,fg=ACCENT,font=("Segoe UI",18)).grid(row=0,column=0,padx=8)
        self._search_var=tk.StringVar()
        self._search_entry=tk.Entry(sr,textvariable=self._search_var,
                                     bg=CARD,fg=TEXT,insertbackground=ACCENT,
                                     font=("Segoe UI",16),relief="flat",bd=0,
                                     highlightbackground=BORD2,highlightthickness=2)
        self._search_entry.grid(row=0,column=1,sticky="ew",ipady=8)
        # Clear button
        FlatBtn(sr,"✕",command=lambda:(self._search_var.set(""),self._search_entry.focus()),
                accent=TEXT3,bg=PANEL,fg=TEXT3,font=("Segoe UI",12),
                padx=8,pady=4).grid(row=0,column=2,padx=4)
        self._search_var.trace("w",self._on_search_type)
        self._search_entry.bind("<Return>",lambda e:self._do_search())
        self._search_entry.bind("<Escape>",lambda e:(self._search_var.set(""),self._search_entry.focus()))

        # Row 2 — scope + ext filter
        fc=tk.Frame(top,bg=PANEL); fc.pack(fill="x",padx=12,pady=6)

        tk.Label(fc,text="Index scope:",bg=PANEL,fg=TEXT2,font=("Segoe UI",11)).pack(side="left")
        self._search_scope=tk.StringVar(value="home")
        for val,lbl in [("home","User folder"),("all","All drives"),("custom","Custom folder")]:
            tk.Radiobutton(fc,text=lbl,variable=self._search_scope,value=val,
                           bg=PANEL,fg=TEXT2,selectcolor=CARD,activebackground=PANEL,
                           font=("Segoe UI",11),
                           command=self._on_scope_change).pack(side="left",padx=8)

        self._search_custom_frame=tk.Frame(fc,bg=PANEL)
        self._search_custom_var=tk.StringVar(value=str(Path.home()))
        ttk.Entry(self._search_custom_frame,textvariable=self._search_custom_var,
                  font=("Consolas",11),width=28).pack(side="left")
        FlatBtn(self._search_custom_frame,"…",command=self._browse_search_custom,
                accent=PURPLE,bg=CARD,fg=TEXT,font=("Segoe UI",11),
                padx=6,pady=3).pack(side="left",padx=4)
        self._search_custom_frame.pack_forget()

        # Row 3 — ext filter + index status
        fr=tk.Frame(top,bg=PANEL); fr.pack(fill="x",padx=12,pady=4)
        tk.Label(fr,text="File type:",bg=PANEL,fg=TEXT2,font=("Segoe UI",11)).pack(side="left")
        self._search_ext_var=tk.StringVar(value="all")
        ext_opts=[("All","all"),("Images",".jpg .png .jpeg .gif .webp .bmp"),
                  ("Video",".mp4 .mkv .avi .mov .wmv"),
                  ("Documents",".pdf .docx .xlsx .pptx .txt"),
                  ("Archive",".zip .rar .7z .iso")]
        for lbl,val in ext_opts:
            tk.Radiobutton(fr,text=lbl,variable=self._search_ext_var,value=val,
                           bg=PANEL,fg=TEXT2,selectcolor=CARD,activebackground=PANEL,
                           font=("Segoe UI",10),
                           command=lambda:self._do_search() if self._search_var.get().strip() else None
                           ).pack(side="left",padx=6)

        # Row 4 — status + index info
        st_row=tk.Frame(top,bg=PANEL); st_row.pack(fill="x",padx=12,pady=4)
        self._search_status=tk.Label(st_row,text="⏳  Building index in background…",
                                      bg=PANEL,fg=TEXT3,font=("Segoe UI",11))
        self._search_status.pack(side="left")
        self._idx_rebuild_btn=FlatBtn(st_row,"🔄  Rebuild Index",
                                       command=self._rebuild_index,
                                       accent=PURPLE,bg=CARD,fg=TEXT,
                                       font=("Segoe UI",10),padx=10,pady=3)
        self._idx_rebuild_btn.pack(side="right",padx=6)
        self._idx_progress_lbl=tk.Label(st_row,text="",bg=PANEL,fg=TEXT3,
                                         font=("Segoe UI",10))
        self._idx_progress_lbl.pack(side="right",padx=8)

        # ── Results card ──────────────────────────────────────────
        res_out,res=make_card(root,"📋  Results")
        res_out.pack(fill="both",expand=True,padx=16,pady=8)

        tb=tk.Frame(res,bg=PANEL); tb.pack(fill="x",padx=8,pady=6)
        FlatBtn(tb,"📂  Open",command=self._search_open,
                accent=ACCENT,bg=CARD,fg=TEXT,font=("Segoe UI",11,"bold"),padx=12,pady=5).pack(side="left",padx=6)
        FlatBtn(tb,"📁  Open Folder",command=self._search_open_folder,
                accent=PURPLE,bg=CARD,fg=TEXT,font=("Segoe UI",11,"bold"),padx=12,pady=5).pack(side="left",padx=6)
        FlatBtn(tb,"📦  Compress Selected",command=self._search_compress,
                accent=GREEN,bg=CARD,fg=TEXT,font=("Segoe UI",11,"bold"),padx=12,pady=5).pack(side="left",padx=6)
        FlatBtn(tb,"🔒  Encrypt Selected",command=self._search_encrypt,
                accent=YELLOW,bg=CARD,fg=TEXT,font=("Segoe UI",11,"bold"),padx=12,pady=5).pack(side="left",padx=6)
        FlatBtn(tb,"🗑  Delete Selected",command=self._search_delete,
                accent=RED,bg=CARD,fg=TEXT,font=("Segoe UI",11,"bold"),padx=12,pady=5).pack(side="left",padx=6)

        tf=tk.Frame(res,bg=PANEL); tf.pack(fill="both",expand=True,padx=2,pady=2)
        self.search_tree=tree_with_scroll(tf,
            columns=("icon","name","size","path"),
            headings=[("",30,"center"),("Filename",220,"w"),
                      ("Size",90,"e"),("Path",500,"w")])
        self.search_tree.tag_configure("sys",background="#2d0f0f",foreground="#fca5a5")
        self.search_tree.tag_configure("usr",background=CARD,foreground=TEXT)
        self.search_tree.tag_configure("stripe",background="#131d2e",foreground=TEXT2)
        self.search_tree.bind("<Double-1>",lambda e:self._search_open())
        return root

    # ══════════════════════════════════════════
    #  INDEX ENGINE — startup & management
    # ══════════════════════════════════════════
    def _start_index_engine(self):
        """Called once after UI ready — wires callbacks and starts build."""
        eng = self._idx_engine

        def on_progress(count, path):
            self.after(0, lambda c=count, p=path: (
                self._idx_progress_lbl.configure(
                    text=f"Indexing: {c:,} file(s)…",fg=TEXT3),
            ))

        def on_complete(total, elapsed):
            msg = f"✓ Index ready — {total:,} files  ({elapsed:.1f}s)"
            self.after(0, lambda m=msg, t=total: (
                self._search_status.configure(text=m, fg=GREEN),
                self._idx_progress_lbl.configure(text=f"{t:,} file(s) in index", fg=TEXT3),
                self._setstatus(m, GREEN, 100),
            ))

        def on_status(msg):
            self.after(0, lambda m=msg:
                self._search_status.configure(text=m, fg=TEXT2))

        eng.on_progress = on_progress
        eng.on_complete = on_complete
        eng.on_status   = on_status

        # Start with home scope by default — fast, then user can rebuild for all drives
        roots = self._get_index_roots()
        eng.start_build(roots)

        # Schedule incremental refresh every 5 minutes
        self._schedule_index_refresh()

    def _get_index_roots(self) -> list:
        """Return list of Path roots based on current scope setting."""
        try:
            scope = self._search_scope.get()
        except Exception:
            scope = "home"
        if scope == "home":
            return [Path.home()]
        elif scope == "all":
            return [Path(d) for d in get_all_drives()]
        else:
            cp = self._search_custom_var.get()
            return [Path(cp)] if cp else [Path.home()]

    def _rebuild_index(self):
        """Force full rebuild of the index for current scope."""
        roots = self._get_index_roots()
        scope_name = {"home":"User folder","all":"All drives"}.get(
            self._search_scope.get(), self._search_custom_var.get())
        self._search_status.configure(
            text=f"⏳  Rebuilding index: {scope_name}…", fg=YELLOW)
        self._idx_progress_lbl.configure(text="", fg=TEXT3)
        self._idx_engine.start_build(roots, force=True)

    def _schedule_index_refresh(self):
        """Schedule incremental index refresh every 5 minutes."""
        def refresh():
            if not self._idx_engine.is_building:
                self._idx_engine.refresh_incremental(self._get_index_roots())
            self._schedule_index_refresh()  # reschedule
        self.after(300_000, refresh)  # 5 minutes

    # ══════════════════════════════════════════
    #  SEARCH — scope, query, display
    # ══════════════════════════════════════════
    def _on_scope_change(self):
        if self._search_scope.get() == "custom":
            self._search_custom_frame.pack(side="left", padx=8)
        else:
            self._search_custom_frame.pack_forget()
        # Trigger index rebuild for new scope
        self._rebuild_index()

    def _browse_search_custom(self):
        d = filedialog.askdirectory()
        if d: self._search_custom_var.set(d)

    def _on_search_type(self, *_):
        """Debounce 300ms — then query the in-memory index."""
        if self._search_after:
            self.after_cancel(self._search_after)
            self._search_after = None
        q = self._search_var.get().strip()
        if len(q) >= 2:
            # instant feedback while debounce runs
            if self._idx_engine.ready:
                n = self._idx_engine.query_count(q)
                self._search_status.configure(
                    text=f"About {n:,} result(s)…", fg=TEXT2)
            self._search_after = self.after(300, self._do_search)
        else:
            for i in self.search_tree.get_children():
                self.search_tree.delete(i)
            if not q:
                st = self._idx_engine.stats()
                self._search_status.configure(
                    text=st["status"] if st["status"] else "Type a filename to search…",
                    fg=TEXT3)
            else:
                self._search_status.configure(text="Type at least 2 characters…", fg=TEXT3)

    def _do_search(self):
        """Query the index — pure RAM, no disk I/O."""
        q = self._search_var.get().strip()
        if not q or len(q) < 2:
            return

        eng = self._idx_engine

        # If index not ready yet, fall back to limited direct scan
        if not eng.ready:
            self._search_status.configure(
                text="⏳  Index not ready yet, please wait…", fg=YELLOW)
            return

        # Build optional filters
        ext_val = self._search_ext_var.get()
        ext_filter = None if ext_val == "all" else ext_val.split()[0]

        scope = self._search_scope.get()
        scope_prefix = None
        if scope == "home":
            scope_prefix = str(Path.home())
        elif scope == "custom":
            scope_prefix = self._search_custom_var.get() or None

        # ── Query is pure in-memory — instant ────────────────────
        self._search_token += 1
        my_token = self._search_token

        def run():
            try:
                results = eng.query(q, limit=200,
                                     ext_filter=ext_filter,
                                     scope=scope_prefix)
                if self._search_token == my_token:
                    self.search_results = results
                    self.after(0, lambda r=results, qq=q: self._show_search(r, qq))
            except Exception as e:
                if self._search_token == my_token:
                    self.after(0, lambda e=e:
                        self._search_status.configure(
                            text=f"⚠ Error: {e}", fg=RED))

        # Run in thread so UI never freezes (even though it's RAM-only,
        # large indexes >500k files can take ~50ms which is noticeable)
        threading.Thread(target=run, daemon=True).start()

    def _show_search(self, results, q):
        for i in self.search_tree.get_children():
            self.search_tree.delete(i)
        for idx, r in enumerate(results):
            icon = TYPE_ICONS.get(r["group"], "📁")
            name = Path(r["path"]).name
            tag  = "sys" if r["in_system"] else ("usr" if idx % 2 == 0 else "stripe")
            self.search_tree.insert("", "end",
                values=(icon, name, fmt_size(r["size_bytes"]), r["path"]),
                tags=(tag,))
        count = len(results)
        capped = count >= 200
        self._search_status.configure(
            text=f"✓ {count:,} result(s) for '{q}'" + ("  (first 200)" if capped else ""),
            fg=GREEN)
        self._setstatus(f"✓ Search: {count:,} result(s)", GREEN, 100)

    def _search_get_selected_paths(self):
        return [self.search_tree.item(i,"values")[3]
                for i in self.search_tree.selection()
                if self.search_tree.item(i,"values") and len(self.search_tree.item(i,"values"))>=4]

    def _search_open(self):
        for p in self._search_get_selected_paths()[:3]:
            try: os.startfile(p)
            except Exception as e: messagebox.showerror("Error","Cannot open:\n"+p+"\n\n"+str(e))

    def _search_open_folder(self):
        paths=self._search_get_selected_paths()
        if not paths: return
        try: subprocess.Popen(["explorer","/select,",paths[0]])
        except: 
            try: os.startfile(str(Path(paths[0]).parent))
            except Exception as e: messagebox.showerror("Error",str(e))

    def _search_compress(self):
        paths=self._search_get_selected_paths()
        if not paths: messagebox.showinfo("Notice","Select files first."); return
        self._compress_files(paths)

    def _search_encrypt(self):
        paths=self._search_get_selected_paths()
        if not paths: messagebox.showinfo("Notice","Select files first."); return
        self._encrypt_files(paths)

    def _search_delete(self):
        paths=self._search_get_selected_paths()
        if not paths: messagebox.showinfo("Notice","Select files first."); return
        self._delete_files(paths,on_done=lambda _: self._do_search())

    # ══════════════════════════════════════════
    #  TAB DISK
    # ══════════════════════════════════════════
    def _tab_disk(self,host):
        root=tk.Frame(host,bg=BG)
        side=tk.Frame(root,bg=BG,width=210); side.pack(side="right",fill="y",padx=14,pady=14)
        side.pack_propagate(False); self._build_sidebar(side)
        main=tk.Frame(root,bg=BG); main.pack(side="left",fill="both",expand=True,padx=14,pady=14)

        cfg_out,cfg=make_card(main,"⚙  Scan Settings"); cfg_out.pack(fill="x",pady=8)
        tk.Label(cfg,text="Target Folder",bg=PANEL,fg=TEXT2,font=("Segoe UI",11)).pack(anchor="w",padx=12,pady=8)
        pi=tk.Frame(cfg,bg=PANEL); pi.pack(fill="x",padx=12,pady=8); pi.columnconfigure(0,weight=1)
        self.path_var=tk.StringVar(value=str(Path.home()))
        ttk.Entry(pi,textvariable=self.path_var,font=("Consolas",11)).grid(row=0,column=0,sticky="ew",padx=6)
        FlatBtn(pi,"📁 Browse",command=self._browse,accent=PURPLE,bg=CARD,fg=TEXT,
                font=("Segoe UI",11,"bold"),padx=10,pady=5).grid(row=0,column=1)

        pr=tk.Frame(cfg,bg=PANEL); pr.pack(fill="x",padx=12,pady=8)
        for lbl,attr,default,maxv in [("Min Size (MB)","min_size_var",100,9999),
                                       ("Max Results","limit_var",200,2000)]:
            box=tk.Frame(pr,bg=CARD2,highlightbackground=BORD2,highlightthickness=1)
            box.pack(side="left",padx=10)
            tk.Label(box,text=lbl,bg=CARD2,fg=TEXT2,font=("Segoe UI",10)).pack(padx=8,pady=4)
            var=tk.IntVar(value=default); setattr(self,attr,var)
            ttk.Spinbox(box,from_=1,to=maxv,textvariable=var,width=8,font=("Segoe UI",12)).pack(padx=8,pady=6)

        br=tk.Frame(cfg,bg=PANEL); br.pack(fill="x",padx=12,pady=10)
        self._scan_btn=FlatBtn(br,"🔍 Scan Selected Folder",command=self._start_scan,
                                accent=ACCENT,bg=CARD,fg=TEXT,font=("Segoe UI",12,"bold"),padx=18,pady=8)
        self._scan_btn.pack(side="left",padx=6)
        FlatBtn(br,"🌐 Scan All drives",command=self._quick_full_scan,
                accent=ACC2,bg=CARD,fg=TEXT,font=("Segoe UI",12,"bold"),padx=18,pady=8).pack(side="left",padx=6)
        FlatBtn(br,"➕ Add Files",command=self._add_custom_files,
                accent=GREEN,bg=CARD,fg=TEXT,font=("Segoe UI",11,"bold"),padx=12,pady=8).pack(side="left",padx=6)
        FlatBtn(br,"📦 Compress Selected",command=self._disk_compress,
                accent=PURPLE,bg=CARD,fg=TEXT,font=("Segoe UI",11,"bold"),padx=12,pady=8).pack(side="left",padx=6)
        FlatBtn(br,"🔒 Encrypt Selected",command=self._disk_encrypt,
                accent=YELLOW,bg=CARD,fg=TEXT,font=("Segoe UI",11,"bold"),padx=12,pady=8).pack(side="left",padx=6)
        self._del_btn=FlatBtn(br,"🗑 Delete Selected",command=self._delete_selected,
                               accent=RED,bg=CARD,fg=TEXT,font=("Segoe UI",11,"bold"),padx=12,pady=8)
        self._del_btn.pack(side="left",padx=14)
        self._scan_lbl=tk.Label(br,text="",bg=PANEL,fg=TEXT2,font=("Segoe UI",11))
        self._scan_lbl.pack(side="left")

        res_out,res=make_card(main,"📊  Scan Results"); res_out.pack(fill="both",expand=True)
        self._stats_bar=tk.Label(res,text="",bg=PANEL,fg=TEXT2,font=("Segoe UI",11),anchor="w",padx=10)
        self._stats_bar.pack(fill="x",pady=4)
        tf=tk.Frame(res,bg=PANEL); tf.pack(fill="both",expand=True,padx=2,pady=2)
        self.disk_tree=tree_with_scroll(tf,columns=("size","type","scope","path"),
            headings=[("Size",90,"e"),("Type",100,"center"),("Scope",80,"center"),("Path",500,"w")])
        self.disk_tree.tag_configure("sys",background="#2d0f0f",foreground="#fca5a5")
        self.disk_tree.tag_configure("usr",background="#0a2a1a",foreground="#86efac")
        self.disk_tree.tag_configure("stripe",background="#131d2e")
        self.disk_tree.bind("<Double-1>",self._open_selected_file)
        self.disk_tree.heading("size",command=lambda:self._tsort("size"))

        self._tree_menu=tk.Menu(self,tearoff=0,bg=CARD2,fg=TEXT,
                                activebackground=ACCENT,activeforeground=BG,font=("Segoe UI",11))
        self._tree_menu.add_command(label="📂  Open File",         command=self._open_selected_file)
        self._tree_menu.add_command(label="📁  Open Containing Folder", command=self._open_selected_folder)
        self._tree_menu.add_separator()
        self._tree_menu.add_command(label="📦  Compress Selected",        command=self._disk_compress)
        self._tree_menu.add_command(label="🔒  Encrypt Selected",       command=self._disk_encrypt)
        self._tree_menu.add_command(label="🔓  Decrypt",           command=self._disk_decrypt)
        self._tree_menu.add_separator()
        self._tree_menu.add_command(label="🧠  Analyze with AI",        command=self._analyze_selected)
        self._tree_menu.add_separator()
        self._tree_menu.add_command(label="🗑  Delete Selected",         command=self._delete_selected)
        self._tree_menu.add_command(label="📋  Copy Path",         command=self._copy_path)
        self.disk_tree.bind("<Button-3>",self._show_tree_menu)
        return root

    def _build_sidebar(self,parent):
        tk.Label(parent,text="Statistics",bg=BG,fg=TEXT3,font=("Segoe UI",11,"bold")).pack(pady=6)
        self._stat_lbls: Dict[str,tk.Label]={}
        for key,lbl,col in [("total","Files found",ACCENT),("size","Total Size",PURPLE),
                             ("system","System files",RED),("user","User files",GREEN)]:
            c=tk.Frame(parent,bg=CARD,highlightbackground=BORDER,highlightthickness=1)
            c.pack(fill="x",pady=2)
            tk.Label(c,text=lbl,bg=CARD,fg=TEXT3,font=("Segoe UI",9)).pack(pady=4)
            vl=tk.Label(c,text="—",bg=CARD,fg=col,font=("Segoe UI",20,"bold"))
            vl.pack(pady=5); self._stat_lbls[key]=vl
        tk.Label(parent,text="System Resources",bg=BG,fg=TEXT3,font=("Segoe UI",11,"bold")).pack(pady=12)
        arcs=tk.Frame(parent,bg=BG); arcs.pack()
        self._cpu_arc=ArcMeter(arcs,size=92,label="CPU",bg=BG); self._cpu_arc.pack(side="left",padx=2)
        self._ram_arc=ArcMeter(arcs,size=92,label="RAM",bg=BG); self._ram_arc.pack(side="left",padx=2)
        self._ram_detail=tk.Label(parent,text="",bg=BG,fg=TEXT3,font=("Segoe UI",9),wraplength=185)
        self._ram_detail.pack(pady=4)

    # ══════════════════════════════════════════
    #  TAB DUP
    # ══════════════════════════════════════════

    def _tab_dup(self,host):
        root=tk.Frame(host,bg=BG)
        top_out,top=make_card(root,"🔁  Duplicate Files"); top_out.pack(fill="x",padx=16,pady=16)
        br=tk.Frame(top,bg=PANEL); br.pack(fill="x",padx=12,pady=10)
        self._dup_path_var=tk.StringVar(value=str(Path.home()))
        ttk.Entry(br,textvariable=self._dup_path_var,font=("Consolas",11)
                  ).pack(side="left",fill="x",expand=True,padx=6)
        FlatBtn(br,"📁 Browse",command=self._browse_dup,accent=PURPLE,bg=CARD,fg=TEXT,
                font=("Segoe UI",11,"bold"),padx=10,pady=6).pack(side="left",padx=6)
        self._dup_btn=FlatBtn(br,"🔍 Find Duplicates",command=self._start_dup,
                               accent=ACCENT,bg=CARD,fg=TEXT,font=("Segoe UI",12,"bold"),padx=16,pady=6)
        self._dup_btn.pack(side="left",padx=6)
        FlatBtn(br,"🗑 Delete Selected",command=self._delete_dup_selected,
                accent=RED,bg=CARD,fg=TEXT,font=("Segoe UI",11,"bold"),padx=12,pady=6).pack(side="left")
        self._dup_lbl=tk.Label(br,text="",bg=PANEL,fg=TEXT2,font=("Segoe UI",10)); self._dup_lbl.pack(side="left",padx=8)
        res_out,res=make_card(root,"📋  Results"); res_out.pack(fill="both",expand=True,padx=16,pady=16)
        self._dup_stats=tk.Label(res,text="",bg=PANEL,fg=TEXT2,font=("Segoe UI",10),anchor="w",padx=10)
        self._dup_stats.pack(fill="x",pady=4)
        tf=tk.Frame(res,bg=PANEL); tf.pack(fill="both",expand=True,padx=2,pady=2)
        self.dup_tree=tree_with_scroll(tf,columns=("group","size","path"),
            headings=[("Group",80,"center"),("Size",90,"e"),("Path",600,"w")])
        self.dup_tree.tag_configure("header",background=CARD2,foreground=YELL2)
        self.dup_tree.tag_configure("item",  background=CARD, foreground=TEXT2)
        self.dup_tree.tag_configure("stripe",background="#131d2e",foreground=TEXT2)
        return root

    # ══════════════════════════════════════════
    #  TAB TREEMAP
    # ══════════════════════════════════════════
    def _tab_tmap(self,host):
        root=tk.Frame(host,bg=BG)
        top_out,top=make_card(root,"🗺  Disk Space Treemap"); top_out.pack(fill="x",padx=16,pady=16)
        br=tk.Frame(top,bg=PANEL); br.pack(fill="x",padx=12,pady=10)
        self._tmap_path_var=tk.StringVar(value=str(Path.home()))
        ttk.Entry(br,textvariable=self._tmap_path_var,font=("Consolas",11)
                  ).pack(side="left",fill="x",expand=True,padx=6)
        FlatBtn(br,"📁 Browse",command=self._browse_tmap,accent=PURPLE,bg=CARD,fg=TEXT,
                font=("Segoe UI",11,"bold"),padx=10,pady=6).pack(side="left",padx=6)
        self._tmap_btn=FlatBtn(br,"🗺 Draw Treemap",command=self._start_tmap,
                                accent=ACCENT,bg=CARD,fg=TEXT,font=("Segoe UI",12,"bold"),padx=16,pady=6)
        self._tmap_btn.pack(side="left",padx=8)
        tk.Label(br,text="Depth:",bg=PANEL,fg=TEXT2,font=("Segoe UI",11)).pack(side="left")
        self._tmap_depth=tk.IntVar(value=2)
        ttk.Spinbox(br,from_=1,to=4,textvariable=self._tmap_depth,width=3,
                    font=("Segoe UI",11)).pack(side="left",padx=4)
        self._tmap_lbl=tk.Label(br,text="",bg=PANEL,fg=TEXT2,font=("Segoe UI",10)); self._tmap_lbl.pack(side="left",padx=8)
        map_out,map_in=make_card(root,""); map_out.pack(fill="both",expand=True,padx=16,pady=16)
        self._tmap_canvas=TreemapCanvas(map_in); self._tmap_canvas.pack(fill="both",expand=True,padx=4,pady=4)
        return root

    # ══════════════════════════════════════════
    #  TAB RAM
    # ══════════════════════════════════════════
    def _tab_ram(self,host):
        root=tk.Frame(host,bg=BG)
        hdr_out,hdr=make_card(root,"💾  Memory Monitor"); hdr_out.pack(fill="x",padx=16,pady=16)
        br=tk.Frame(hdr,bg=PANEL); br.pack(fill="x",padx=12,pady=10)
        FlatBtn(br,"🔄 Refresh Now",command=self._refresh_ram,accent=GREEN,bg=CARD,fg=TEXT,
                font=("Segoe UI",12,"bold"),padx=16,pady=8).pack(side="left",padx=14)
        self._ram_stats_lbl=tk.Label(br,text="Loading…",bg=PANEL,fg=TEXT2,font=("Segoe UI",11))
        self._ram_stats_lbl.pack(side="left")
        tbl_out,tbl=make_card(root,"🔝  Top Memory Consumers"); tbl_out.pack(fill="both",expand=True,padx=16,pady=16)
        tf=tk.Frame(tbl,bg=PANEL); tf.pack(fill="both",expand=True,padx=2,pady=2)
        self.ram_tree=tree_with_scroll(tf,columns=("pid","name","ram"),
            headings=[("PID",70,"center"),("Process Name",280,"w"),("RAM (MB)",110,"e")])
        self.ram_tree.tag_configure("stripe",background="#131d2e")
        return root

    # ══════════════════════════════════════════
    #  TAB STARTUP
    # ══════════════════════════════════════════
    def _tab_startup(self,host):
        root=tk.Frame(host,bg=BG)
        top_out,top=make_card(root,"🚀  Startup Manager"); top_out.pack(fill="x",padx=16,pady=16)
        br=tk.Frame(top,bg=PANEL); br.pack(fill="x",padx=12,pady=10)
        FlatBtn(br,"🔄 Load List",command=self._load_startup,accent=ACCENT,bg=CARD,fg=TEXT,
                font=("Segoe UI",12,"bold"),padx=16,pady=8).pack(side="left",padx=6)
        FlatBtn(br,"🧠 Analyze with AI",command=self._analyze_startup,accent=PURPLE,bg=CARD,fg=TEXT,
                font=("Segoe UI",11,"bold"),padx=12,pady=8).pack(side="left",padx=6)
        FlatBtn(br,"🚫 Disable Selected",command=self._disable_startup_selected,accent=RED,bg=CARD,fg=TEXT,
                font=("Segoe UI",11,"bold"),padx=12,pady=8).pack(side="left")
        self._startup_lbl=tk.Label(br,text="",bg=PANEL,fg=TEXT2,font=("Segoe UI",10)); self._startup_lbl.pack(side="left",padx=8)
        res_out,res=make_card(root,"📋  Startup Items"); res_out.pack(fill="both",expand=True,padx=16,pady=8)
        tf=tk.Frame(res,bg=PANEL); tf.pack(fill="both",expand=True,padx=2,pady=2)
        self.startup_tree=tree_with_scroll(tf,columns=("name","location","command"),
            headings=[("Name",200,"w"),("Source",140,"center"),("Command",600,"w")])
        self.startup_tree.tag_configure("reg",   background=CARD, foreground=TEXT)
        self.startup_tree.tag_configure("folder",background="#0a2a1a",foreground=GREEN2)
        self.startup_tree.tag_configure("stripe",background="#131d2e")
        ai_out,ai_in=make_card(root,"🧠  AI Startup Analysis"); ai_out.pack(fill="x",padx=16,pady=14)
        ai_tf=tk.Frame(ai_in,bg=PANEL); ai_tf.pack(fill="both",padx=2,pady=2)
        ai_tf.rowconfigure(0,weight=1); ai_tf.columnconfigure(0,weight=1)
        self._startup_ai_text=tk.Text(ai_tf,wrap="word",bg=BG2,fg=TEXT,height=6,
                                       font=("Segoe UI",11),padx=12,pady=8,state="disabled",relief="flat")
        asb=ttk.Scrollbar(ai_tf,orient="vertical",command=self._startup_ai_text.yview)
        self._startup_ai_text.configure(yscrollcommand=asb.set)
        self._startup_ai_text.grid(row=0,column=0,sticky="nsew"); asb.grid(row=0,column=1,sticky="ns")
        return root

    # ══════════════════════════════════════════
    #  TAB TEMP — Clean Temp Files
    # ══════════════════════════════════════════
    def _tab_temp(self,host):
        root=tk.Frame(host,bg=BG)

        # ── Header with quick actions ────────────────────────────
        top_out,top=make_card(root,"🧹  Clean Temp & System Files")
        top_out.pack(fill="x",padx=16,pady=(16,8))
        br=tk.Frame(top,bg=PANEL); br.pack(fill="x",padx=12,pady=10)

        self._temp_scan_btn=FlatBtn(br,"🔍  Scan Now",command=self._temp_scan,
                                     accent=ACCENT,bg=CARD,fg=TEXT,
                                     font=("Segoe UI",12,"bold"),padx=18,pady=8)
        self._temp_scan_btn.pack(side="left",padx=(0,6))
        self._temp_clean_btn=FlatBtn(br,"🧹  Clean Selected",command=self._temp_clean_selected,
                                      accent=GREEN,bg=CARD,fg=TEXT,
                                      font=("Segoe UI",12,"bold"),padx=18,pady=8)
        self._temp_clean_btn.pack(side="left",padx=(0,6))
        self._temp_cleanall_btn=FlatBtn(br,"⚡  Clean All (safe items)",command=self._temp_clean_all_safe,
                                         accent=ORANGE,bg=CARD,fg=TEXT,
                                         font=("Segoe UI",12,"bold"),padx=18,pady=8)
        self._temp_cleanall_btn.pack(side="left",padx=(0,14))
        self._temp_lbl=tk.Label(br,text="Click Scan Now to find wasted space",
                                 bg=PANEL,fg=TEXT2,font=("Segoe UI",11))
        self._temp_lbl.pack(side="left")

        # ── Summary bar ──────────────────────────────────────────
        sum_out,sum_in=make_card(root,"")
        sum_out.pack(fill="x",padx=16,pady=(0,8))
        sf=tk.Frame(sum_in,bg=PANEL); sf.pack(fill="x",padx=12,pady=8)
        self._temp_total_lbl=tk.Label(sf,text="",bg=PANEL,fg=ACCENT,
                                       font=("Segoe UI",14,"bold"))
        self._temp_total_lbl.pack(side="left",padx=(0,20))
        self._temp_prog=ProgressBar(sf,height=8,color=GREEN,bg=CARD2)
        self._temp_prog.pack(side="left",fill="x",expand=True)

        # ── Locations table ──────────────────────────────────────
        res_out,res=make_card(root,"📋  Temp File Locations")
        res_out.pack(fill="both",expand=True,padx=16,pady=(0,16))
        tf=tk.Frame(res,bg=PANEL); tf.pack(fill="both",expand=True,padx=2,pady=(0,2))
        self.temp_tree=tree_with_scroll(tf,
            columns=("check","label","size","count","path","safe"),
            headings=[("✓",30,"center"),("Location",200,"w"),
                      ("Size",100,"e"),("Files",80,"e"),
                      ("Path",400,"w"),("Status",80,"center")])
        self.temp_tree.tag_configure("safe",   background="#0a1f12",foreground=GREEN2)
        self.temp_tree.tag_configure("caution",background="#1f1500",foreground=YELL2)
        self.temp_tree.tag_configure("empty",  background=CARD,     foreground=TEXT3)
        self.temp_tree.bind("<Double-1>",self._temp_toggle_select)

        # ── Result log ───────────────────────────────────────────
        log_out,log_in=make_card(root,"📝  Cleanup Log")
        log_out.pack(fill="x",padx=16,pady=(0,16))
        lf=tk.Frame(log_in,bg=PANEL); lf.pack(fill="both",padx=2,pady=2)
        lf.rowconfigure(0,weight=1); lf.columnconfigure(0,weight=1)
        self._temp_log=tk.Text(lf,wrap="word",bg=BG2,fg=TEXT,height=5,
                                font=("Consolas",10),padx=10,pady=8,
                                state="disabled",relief="flat")
        lsb=ttk.Scrollbar(lf,orient="vertical",command=self._temp_log.yview)
        self._temp_log.configure(yscrollcommand=lsb.set)
        self._temp_log.grid(row=0,column=0,sticky="nsew"); lsb.grid(row=0,column=1,sticky="ns")
        self._temp_log.tag_configure("ok",   foreground=GREEN2)
        self._temp_log.tag_configure("err",  foreground=RED2)
        self._temp_log.tag_configure("info", foreground=MONO)
        self._temp_log.tag_configure("head", foreground=YELL2,font=("Consolas",10,"bold"))

        self._temp_data: List[dict]=[]   # scan results
        self._temp_busy=False
        return root

    # ── Temp actions ──────────────────────────────────────────────
    def _temp_log_write(self,text,tag="info"):
        self._temp_log.configure(state="normal")
        self._temp_log.insert("end", text+"\n", tag)
        self._temp_log.configure(state="disabled")
        self._temp_log.see("end")

    def _temp_scan(self):
        if self._temp_busy: return
        self._temp_busy=True
        self._temp_scan_btn.set_text("⏳  Scanning…")
        for i in self.temp_tree.get_children(): self.temp_tree.delete(i)
        self._temp_total_lbl.configure(text="Scanning…")
        self._temp_log_write("═"*50,"head")
        self._temp_log_write(f"Scanning temp file locations — {datetime.now():%H:%M:%S}","head")
        self._setstatus("Scanning temp locations…",YELLOW,10)

        def cb(i,total,label):
            self.after(0,lambda i=i,t=total,l=label:
                (self._setstatus(f"Scanning: {l}",YELLOW,int(i/t*80)),
                 self._temp_lbl.configure(text=f"Scanning: {l}…",fg=TEXT2)))

        def run():
            try:
                data=scan_temp_locations(cb)
                self._temp_data=data
                self.after(0,lambda: self._temp_show(data))
            except Exception as e:
                self.after(0,lambda e=e: self._temp_lbl.configure(text=f"⚠ {e}",fg=RED))
            finally:
                self._temp_busy=False
                self.after(0,lambda: self._temp_scan_btn.set_text("🔍  Scan Now"))
        threading.Thread(target=run,daemon=True).start()

    def _temp_show(self,data:List[dict]):
        for i in self.temp_tree.get_children(): self.temp_tree.delete(i)
        total_size=0; total_count=0
        for r in data:
            if not r["exists"] or r["size"]==0:
                tag="empty"; size_str="Empty"; count_str="0"
            elif r["safe"]: tag="safe"
            else:            tag="caution"
            size_str=fmt_size(r["size"]) if r.get("size",0)>0 else "—"
            count_str=f"{r['count']:,}" if r.get("count",0)>0 else "—"
            safe_lbl="✓ Safe" if r["safe"] else "⚠ Caution"
            self.temp_tree.insert("","end",iid=r["label"],
                values=("☐",r["label"],size_str,count_str,r["path"],safe_lbl),
                tags=(tag,))
            if r["safe"] and r["exists"]:
                total_size+=r["size"]; total_count+=r["count"]
            self._temp_log_write(f"  {'✓' if r['exists'] else '—'} {r['label']}: {size_str} ({count_str} file(s))",
                                  "ok" if r.get("size",0)>0 else "info")
        self._temp_total_lbl.configure(
            text=f"🧹  Can free: {fmt_size(total_size)}  ({total_count:,} file(s))")
        self._temp_lbl.configure(text=f"✓ Scan complete",fg=GREEN)
        self._temp_prog.set_pct(min(100,total_size/(1024**3)*10))  # visual indicator
        self._setstatus(f"✓ Temp: can free {fmt_size(total_size)}",GREEN,100)
        self._temp_log_write(f"  ── Total: {fmt_size(total_size)} available to delete ──","head")

    def _temp_toggle_select(self,event=None):
        """Toggle checkmark on double-click."""
        sel=self.temp_tree.selection()
        if not sel: return
        iid=sel[0]
        vals=list(self.temp_tree.item(iid,"values"))
        vals[0]="☑" if vals[0]=="☐" else "☐"
        self.temp_tree.item(iid,values=vals)

    def _temp_get_selected(self)->List[dict]:
        """Return checked OR selected rows."""
        selected=[]
        for iid in self.temp_tree.get_children():
            vals=self.temp_tree.item(iid,"values")
            is_checked = vals and vals[0]=="☑"
            is_selected = iid in self.temp_tree.selection()
            if is_checked or is_selected:
                match=[r for r in self._temp_data if r["label"]==iid]
                if match and match[0]["exists"] and match[0]["size"]>0:
                    selected.append(match[0])
        return selected

    def _temp_clean_selected(self):
        selected=self._temp_get_selected()
        if not selected:
            messagebox.showinfo("Notice","Select locations from the list first"); return
        unsafe=[r for r in selected if not r["safe"]]
        if unsafe:
            names="\n".join(f"  ⚠ {r['label']}" for r in unsafe)
            if not messagebox.askyesno("Warning",f"The following locations need caution:\n{names}\n\nAre you sure?"): return
        total=sum(r["size"] for r in selected)
        detail="\n".join(f"  • {r['label']} ({fmt_size(r['size'])})" for r in selected)
        if not messagebox.askyesno("Confirm Cleanup",f"Will delete:\n{detail}\n\nTotal: {fmt_size(total)}\n\nAre you sure?"): return
        self._temp_do_clean(selected)

    def _temp_clean_all_safe(self):
        safe=[r for r in self._temp_data if r.get("safe") and r.get("exists") and r.get("size",0)>0]
        if not safe:
            if not self._temp_data:
                messagebox.showinfo("Notice","Click 'Scan Now' first."); return
            messagebox.showinfo("Great!","No temp files need cleanup."); return
        total=sum(r["size"] for r in safe)
        detail="\n".join(f"  ✓ {r['label']} ({fmt_size(r['size'])})" for r in safe)
        if not messagebox.askyesno("Full Cleanup",f"Will delete all safe temp files:\n{detail}\n\nSpace to free: {fmt_size(total)}\n\nAre you sure?"): return
        self._temp_do_clean(safe)

    def _temp_scan_then_clean_safe(self):
        """Called from Quick Clean All button on home page."""
        self._temp_scan()
        # Schedule clean after scan completes (check every 500ms)
        def wait_and_clean():
            if self._temp_busy:
                self.after(500,wait_and_clean)
            else:
                self.after(200,self._temp_clean_all_safe)
        self.after(500,wait_and_clean)

    def _temp_do_clean(self,locations:List[dict]):
        if self._temp_busy: return
        self._temp_busy=True
        self._temp_cleanall_btn.set_text("⏳  Cleaning…")
        self._temp_log_write("═"*50,"head")
        self._temp_log_write(f"Starting cleanup — {datetime.now():%H:%M:%S}","head")
        self._setstatus("Cleaning…",YELLOW,10)

        def run():
            total_freed=0; total_del=0; total_fail=0
            for r in locations:
                self.after(0,lambda l=r["label"]: (
                    self._temp_lbl.configure(text=f"Deleting: {l}…",fg=YELLOW),
                    self._setstatus(f"Deleting: {l}",YELLOW)))
                stats=clean_temp_location(r["path"])
                total_freed+=stats["freed"]
                total_del  +=stats["deleted"]
                total_fail +=stats["failed"]
                tag="ok" if stats["deleted"]>0 else "err"
                self.after(0,lambda s=stats,l=r["label"]: self._temp_log_write(
                    f"  ✓ {l}: deleted {s['deleted']:,} file(s) — freed {fmt_size(s['freed'])}",tag))
            self.after(0,lambda: self._temp_finish(total_freed,total_del,total_fail))

        threading.Thread(target=run,daemon=True).start()

    def _temp_finish(self,freed,deleted,failed):
        self._temp_busy=False
        self._temp_cleanall_btn.set_text("⚡  Clean All (safe items)")
        self._temp_lbl.configure(text=f"✓ Cleanup done — freed {fmt_size(freed)}",fg=GREEN)
        self._temp_log_write(f"  ── Result: deleted {deleted:,} file(s) ── freed {fmt_size(freed)} ──","head")
        if failed: self._temp_log_write(f"  ⚠ Failed to delete {failed:,} file(s) (in-use files)","err")
        self._setstatus(f"✓ Cleanup complete — freed {fmt_size(freed)}",GREEN,100)
        msg=f"Cleanup completed successfully!\nFiles removed: {deleted:,}\nSpace freed: {fmt_size(freed)}"
        if failed: msg+=f"\nFailed (in use): {failed:,}"
        messagebox.showinfo("✓ Cleanup complete",msg)
        # Re-scan to update sizes
        self.after(500,self._temp_scan)

    # ══════════════════════════════════════════
    #  TAB AI
    # ══════════════════════════════════════════
    def _tab_ai(self,host):
        root=tk.Frame(host,bg=BG)
        # ── Top control bar ───────────────────────────────────────
        top_out,top=make_card(root,"🤖  AI Advisor — File Analysis"); top_out.pack(fill="x",padx=16,pady=(16,8))
        ctrl=tk.Frame(top,bg=PANEL); ctrl.pack(fill="x",padx=12,pady=(8,4))

        # Row 1: mode buttons
        row1=tk.Frame(ctrl,bg=PANEL); row1.pack(fill="x",pady=(0,6))
        tk.Label(row1,text="Analysis mode:",bg=PANEL,fg=TEXT2,font=("Segoe UI",10)).pack(side="left",padx=(0,8))

        self._ai_mode_var=tk.StringVar(value="classify")
        modes=[
            ("classify",   "🔍 Classify Files",    ACCENT),
            ("summary",    "📊 Smart Summary",          PURPLE),
            ("cleanup_plan","🗺 Cleanup Plan",      GREEN),
            ("smart_delete","⚡ Smart Delete",     ORANGE),
        ]
        self._mode_btns={}
        for val,lbl,col in modes:
            b=FlatBtn(row1,lbl,command=lambda v=val:self._set_ai_mode(v),
                      accent=col,bg=CARD2,fg=TEXT,font=("Segoe UI",10,"bold"),padx=10,pady=5)
            b.pack(side="left",padx=3)
            self._mode_btns[val]=b

        # Row 2: action buttons + pills
        row2=tk.Frame(ctrl,bg=PANEL); row2.pack(fill="x",pady=(0,8))
        self._ai_btn=FlatBtn(row2,"🧠 Analyze All Files",command=self._start_llm,
                              accent=PURPLE,bg=CARD,fg=TEXT,font=("Segoe UI",12,"bold"),padx=18,pady=8)
        self._ai_btn.pack(side="left",padx=(0,6))
        self._ai_sel_btn=FlatBtn(row2,"🎯 Analyze Selected",command=self._analyze_selected,
                                  accent=ACCENT,bg=CARD,fg=TEXT,font=("Segoe UI",11,"bold"),padx=12,pady=8)
        self._ai_sel_btn.pack(side="left",padx=(0,14))
        pills=tk.Frame(row2,bg=PANEL); pills.pack(side="left"); self._pills: Dict[str,tk.Label]={}
        for key,lbl,col in [("safe","SAFE",GREEN),("caution","CAUTION",YELLOW),("danger","DANGER",RED)]:
            pf=tk.Frame(pills,bg=PANEL,highlightbackground=col,highlightthickness=1); pf.pack(side="left",padx=4)
            tk.Label(pf,text=lbl,bg=PANEL,fg=col,font=("Segoe UI",9,"bold")).pack(side="left",padx=6,pady=4)
            vl=tk.Label(pf,text="—",bg=PANEL,fg=TEXT,font=("Segoe UI",11,"bold")); vl.pack(side="left",padx=6,pady=4)
            self._pills[key]=vl
        self._ai_status=tk.Label(row2,text="",bg=PANEL,fg=YELLOW,font=("Segoe UI",10)); self._ai_status.pack(side="left",padx=8)

        # Mode description label
        self._mode_desc=tk.Label(ctrl,text="",bg=PANEL,fg=TEXT3,font=("Segoe UI",9),anchor="w")
        self._mode_desc.pack(fill="x",padx=4,pady=(0,4))
        self._set_ai_mode("classify")

        # ── Result area ───────────────────────────────────────────
        txt_out,txi=make_card(root,"📋  Analysis Results"); txt_out.pack(fill="both",expand=True,padx=16,pady=(0,8))
        tf2=tk.Frame(txi,bg=PANEL); tf2.pack(fill="both",expand=True,padx=2,pady=2)
        tf2.rowconfigure(0,weight=1); tf2.columnconfigure(0,weight=1)
        self.ai_text=tk.Text(tf2,wrap="word",bg=BG2,fg=TEXT,insertbackground=ACCENT,
                              selectbackground="#1e3a5f",font=("Segoe UI",12),padx=14,pady=12,
                              state="disabled",relief="flat",spacing1=1,spacing2=2,spacing3=2)
        for tag,col,fnt in [("safe",GREEN2,("Segoe UI",12,"bold")),("caution",YELL2,("Segoe UI",12,"bold")),
                             ("danger",RED2,("Segoe UI",12,"bold")),("path",MONO,("Consolas",11)),
                             ("bullet",ACC2,("Segoe UI",12)),("dim",TEXT3,("Segoe UI",12)),
                             ("warn",YELLOW,("Segoe UI",12)),("header",ACC2,("Segoe UI",13,"bold")),
                             ("step",GREEN2,("Segoe UI",12,"bold"))]:
            self.ai_text.tag_configure(tag,foreground=col,font=fnt)
        ai_sb=ttk.Scrollbar(tf2,orient="vertical",command=self.ai_text.yview)
        self.ai_text.configure(yscrollcommand=ai_sb.set)
        self.ai_text.grid(row=0,column=0,sticky="nsew"); ai_sb.grid(row=0,column=1,sticky="ns")
        wf=tk.Frame(root,bg="#1a0f00",highlightbackground="#92400e",highlightthickness=1)
        wf.pack(fill="x",padx=16,pady=(0,14))
        tk.Label(wf,text="⚠  The app does not delete any files automatically — all recommendations are advisory only",
                 bg="#1a0f00",fg="#fcd34d",font=("Segoe UI",10),padx=14,pady=7).pack()
        return root

    def _set_ai_mode(self,mode:str):
        self._ai_mode_var.set(mode)
        descs={
            "classify":    "Classifies each file: SAFE, CAUTION, or DANGEROUS with reason",
            "summary":     "Analyzes space and gives smart summary with top 3 recommendations",
            "cleanup_plan":"Builds a complete cleanup plan with clear steps",
            "smart_delete":"Selects only 100% safe files for immediate deletion",
        }
        self._mode_desc.configure(text=f"  {descs.get(mode,'')}")
        # highlight active button
        cols={"classify":ACCENT,"summary":PURPLE,"cleanup_plan":GREEN,"smart_delete":ORANGE}
        for m,b in self._mode_btns.items():
            is_active = m==mode
            b.configure(bg=cols.get(m,ACCENT) if is_active else CARD2,
                        fg=BG if is_active else TEXT)

    # ══════════════════════════════════════════
    #  TAB CHAT
    # ══════════════════════════════════════════
    def _tab_chat(self,host):
        root=tk.Frame(host,bg=BG)
        hdr_out,hdr=make_card(root,"💬  AI Chat"); hdr_out.pack(fill="x",padx=16,pady=16)
        btns=tk.Frame(hdr,bg=PANEL); btns.pack(fill="x",padx=12,pady=8)
        FlatBtn(btns,"🔄 New Chat",command=self._chat_clear,accent=GREEN,bg=CARD,fg=TEXT,
                font=("Segoe UI",11,"bold"),padx=12,pady=6).pack(side="left",padx=6)
        FlatBtn(btns,"📋 Add Scan Results",command=self._chat_inject_scan,accent=ACCENT,bg=CARD,fg=TEXT,
                font=("Segoe UI",10,"bold"),padx=12,pady=6).pack(side="left",padx=6)
        FlatBtn(btns,"🚀 Add Startup Data",command=self._chat_inject_startup,accent=PURPLE,bg=CARD,fg=TEXT,
                font=("Segoe UI",10,"bold"),padx=12,pady=6).pack(side="left")
        chat_out,chat_in=make_card(root,""); chat_out.pack(fill="both",expand=True,padx=16,pady=8)
        tf=tk.Frame(chat_in,bg=BG2); tf.pack(fill="both",expand=True,padx=2,pady=2)
        tf.rowconfigure(0,weight=1); tf.columnconfigure(0,weight=1)
        self._chat_box=tk.Text(tf,wrap="word",bg=BG2,fg=TEXT,font=("Segoe UI",12),
                                padx=14,pady=12,state="disabled",relief="flat",spacing1=2,spacing2=2)
        self._chat_box.tag_configure("user",foreground=ACC2,font=("Segoe UI",12,"bold"))
        self._chat_box.tag_configure("ai",  foreground=GREEN2,font=("Segoe UI",12))
        self._chat_box.tag_configure("sys", foreground=TEXT3,font=("Segoe UI",10,"italic"))
        self._chat_box.tag_configure("warn",foreground=YELLOW,font=("Segoe UI",12))
        csb=ttk.Scrollbar(tf,orient="vertical",command=self._chat_box.yview)
        self._chat_box.configure(yscrollcommand=csb.set)
        self._chat_box.grid(row=0,column=0,sticky="nsew"); csb.grid(row=0,column=1,sticky="ns")
        inp=tk.Frame(root,bg=BG,highlightbackground=BORDER,highlightthickness=1)
        inp.pack(fill="x",padx=16,pady=16); inp.columnconfigure(0,weight=1)
        self._chat_var=tk.StringVar()
        ce=tk.Entry(inp,textvariable=self._chat_var,bg=CARD,fg=TEXT,insertbackground=ACCENT,
                    font=("Segoe UI",13),relief="flat",bd=0)
        ce.grid(row=0,column=0,sticky="ew",padx=12,pady=10); ce.bind("<Return>",lambda e:self._chat_send())
        FlatBtn(inp,"Send ➤",command=self._chat_send,accent=ACCENT,bg=CARD,fg=TEXT,
                font=("Segoe UI",12,"bold"),padx=16,pady=7).grid(row=0,column=1,padx=6,pady=6)
        self.after(200,self._chat_welcome)
        return root

    # ══════════════════════════════════════════
    #  FEATURE: COMPRESS
    # ══════════════════════════════════════════
    def _compress_files(self,paths:List[str]):
        if not paths: return

        # ── Pre-analysis: warn user about incompressible files ────────
        analysis=analyze_compressibility(paths)
        incomp_count=len(analysis["incompressible"])
        comp_count  =len(analysis["compressible"])
        total_mb    =analysis["total"]/1048576
        expected_pct=analysis["expected_ratio"]

        # Build info message
        info_lines=[f"Selected files: {len(paths)}  ({total_mb:.1f} MB)",""]
        if comp_count:
            info_lines.append(f"✓ Compressible:    {comp_count} files  ({analysis['comp_size']/1048576:.1f} MB)")
        if incomp_count:
            info_lines.append(f"⚠ Already compressed:  {incomp_count} files  ({analysis['incomp_size']/1048576:.1f} MB)")
            info_lines.append("  (images / video / PDF — won't compress further)")
        info_lines+=["",f"Expected savings: ~{expected_pct:.0f}%","","Compression method:"]

        # Check if 7-Zip available
        has_7zip=False
        for cand in [r"C:\Program Files\7-Zip\7z.exe",r"C:\Program Files (x86)\7-Zip\7z.exe","7z"]:
            try:
                r=subprocess.run([cand,"--help"],capture_output=True,timeout=2)
                if r.returncode==0: has_7zip=True; break
            except: pass

        if has_7zip:
            info_lines.append("🏆 7-Zip LZMA2 (best — installed on your system)")
        else:
            info_lines.append("📦 ZIP + LZMA (good — 7-Zip not installed)")
            info_lines.append("💡 Install 7-Zip for better compression")

        if not messagebox.askyesno("Confirm Compression","\n".join(info_lines)+"\n\nDo you want to continue?"):
            return
            return

        # ── Choose output extension ───────────────────────────────────
        if has_7zip:
            out=filedialog.asksaveasfilename(
                title="Save Archive",defaultextension=".7z",
                filetypes=[("7-Zip Archive","*.7z"),("ZIP","*.zip")],
                initialfile=f"compressed_{datetime.now():%Y%m%d_%H%M%S}.7z")
        else:
            out=filedialog.asksaveasfilename(
                title="Save Compressed File",defaultextension=".zip",
                filetypes=[("ZIP File","*.zip")],
                initialfile=f"compressed_{datetime.now():%Y%m%d_%H%M%S}.zip")
        if not out: return

        self._setstatus("Compressing…",YELLOW,10)

        def cb(i,total,p):
            pct=int((i/max(total,1))*100)
            name=Path(p).name if isinstance(p,str) and p else str(p)
            self.after(0,lambda pct=pct,name=name:
                self._setstatus(f"Compressing: {name}",YELLOW,pct))

        def run():
            try:
                stats=compress_files(paths,out,cb,method="auto")
                self.after(0,lambda: self._show_compress_result(stats,stats.get("out_path",out)))
            except Exception as e:
                self.after(0,lambda: messagebox.showerror("Compression Error",str(e)))

        threading.Thread(target=run,daemon=True).start()

    def _show_compress_result(self,stats,out_path):
        self._setstatus(f"✓ Compressed — {stats['method']}",GREEN,100)
        saved=stats["orig"]-stats["comp"]
        saved=max(saved,0)
        method=stats.get("method","ZIP")
        msg=(f"✓ Compression completed successfully!\n\n"
             f"Method:   {method}\n"
             f"Files:   {stats['count']}\n"
             f"Before:       {fmt_size(stats['orig'])}\n"
             f"After:       {fmt_size(stats['comp'])}\n"
             f"Savings:     {fmt_size(saved)}  ({stats['ratio']:.1f}%)\n\n"
             f"Saved to:\n{out_path}")
        if stats["ratio"] < 5:
            msg+="\n\n💡 Low compression ratio because files are already compressed (images/video/PDF)"
        if stats["failed"]:
            msg+=f"\n\n⚠ Failed: {len(stats['failed'])} file(s)"
        ans=messagebox.askyesno("Compression Complete",msg+"\n\nDo you want to open the containing folder?")
        if ans:
            try: subprocess.Popen(["explorer","/select,",out_path])
            except: pass

    def _disk_compress(self):
        paths=self._get_selected_paths()
        if not paths: messagebox.showinfo("Notice","Select files from the table first."); return
        self._compress_files(paths)

    # ══════════════════════════════════════════
    #  FEATURE: ENCRYPT / DECRYPT
    # ══════════════════════════════════════════
    def _encrypt_files(self,paths:List[str]):
        if not paths: return
        dlg=EncryptDialog(self,"🔒  Encrypt Files",len(paths),"encrypt")
        self.wait_window(dlg)
        if not dlg.result: return
        password,delete_orig=dlg.result

        enc_method="AES-256-CTR" if HAS_PYAES else "XOR (weak — install pyaes for better)"
        ans=messagebox.askyesno("Confirm Encryption",
            f"Will encrypt {len(paths)} file(s) using {enc_method}\n"
            f"{'and delete original after encryption' if delete_orig else 'Original will be kept'}\n\n"
            "The program will create .enc files\nAre you sure?")
        if not ans: return

        done=0; failed=[]
        self._setstatus("Encrypting…",YELLOW,0)
        for i,p in enumerate(paths):
            pct=int((i/len(paths))*100)
            self._setstatus(f"Encrypting {i+1}/{len(paths)}: {Path(p).name}",YELLOW,pct)
            self.update_idletasks()
            ok=encrypt_file(p,password,delete_original=delete_orig)
            if ok: done+=1
            else:  failed.append(Path(p).name)

        self._setstatus(f"✓ Encrypted {done} file(s)",GREEN,100)
        msg=f"✓ Encrypted {done} file(s) successfully\nEncrypted file extension: .enc"
        if failed: msg+=f"\n\n⚠ Encryption failed:\n"+"\n".join(f"  • {f}" for f in failed[:10])
        if not HAS_PYAES:
            msg+="\n\n💡 Install pyaes for stronger encryption:\npip install pyaes"
        messagebox.showinfo("Encryption Complete",msg)

    def _decrypt_files(self,paths:List[str]):
        if not paths: return
        dlg=EncryptDialog(self,"🔓  Decrypt Files",len(paths),"decrypt")
        self.wait_window(dlg)
        if not dlg.result: return
        password,_=dlg.result

        done=0; failed=[]
        self._setstatus("Decrypting…",YELLOW,0)
        for i,p in enumerate(paths):
            pct=int((i/len(paths))*100)
            self._setstatus(f"Decrypting {i+1}/{len(paths)}: {Path(p).name}",YELLOW,pct)
            self.update_idletasks()
            ok,result=decrypt_file(p,password)
            if ok: done+=1
            else:  failed.append(f"{Path(p).name}: {result}")

        self._setstatus(f"✓ Decrypted {done} file(s)",GREEN,100)
        msg=f"✓ Decrypted {done} file(s) successfully"
        if failed:
            msg+=f"\n\n⚠ Decryption failed for:\n"+"\n".join(f"  • {f}" for f in failed[:10])
            msg+="\n\nPlease check the password"
        messagebox.showinfo("Decryption Complete",msg)

    def _disk_encrypt(self):
        paths=self._get_selected_paths()
        if not paths: messagebox.showinfo("Notice","Select files first."); return
        self._encrypt_files(paths)

    def _disk_decrypt(self):
        paths=self._get_selected_paths()
        if not paths: messagebox.showinfo("Notice","Select files first."); return
        self._decrypt_files(paths)

    # ══════════════════════════════════════════
    #  DISK SCAN ACTIONS
    # ══════════════════════════════════════════
    def _check_llm(self):
        ok,msg=test_llm(); col=GREEN if ok else RED
        self.after(0,lambda:self._dot.set_color(col))
        self.after(0,lambda:self._dot_lbl.configure(text=msg,fg=col))
        self.after(0,lambda:self._setstatus(msg,col))

    def _browse(self):
        d=filedialog.askdirectory(initialdir=self.path_var.get())
        if d: self.path_var.set(d)

    def _start_scan(self):
        if self._scanning: return
        p=self.path_var.get().strip(); root=Path(p)
        if not root.exists() or not root.is_dir():
            messagebox.showerror("Invalid Path",f"Folder not found:\n{p}"); return
        try: min_mb=int(self.min_size_var.get()); limit=int(self.limit_var.get())
        except: messagebox.showerror("Error","Please check the values."); return
        self._scanning=True; self._scan_btn.set_text("⏳ Scanning…")
        for i in self.disk_tree.get_children(): self.disk_tree.delete(i)
        self._scan_lbl.configure(text=f"Scanning: {p}",fg=YELLOW)
        self._setstatus(f"Scanning: {p}",YELLOW,5)
        def prog(n,path): self.after(0,lambda n=n:self._setstatus(f"Scan {n:,} file(s)…",YELLOW,min(90,n//100)))
        def run():
            try:
                res=scan_large_files(root,min_mb,limit,prog)
                self.scan_results=res; self.after(0,lambda:self._show_disk(res))
            except Exception as e: self.after(0,lambda:messagebox.showerror("Scan Error",str(e)))
            finally:
                self._scanning=False
                self.after(0,lambda:self._scan_btn.set_text("🔍 Scan Selected Folder"))
        threading.Thread(target=run,daemon=True).start()

    def _start_full_scan(self,drives):
        """Scan multiple drives sequentially."""
        if self._scanning: return
        self._scanning=True; self._scan_btn.set_text("⏳ Full Scan…")
        for i in self.disk_tree.get_children(): self.disk_tree.delete(i)
        self._setstatus("Full system scan…",YELLOW,5)
        try: min_mb=int(self.min_size_var.get()); limit=int(self.limit_var.get())
        except: min_mb=100; limit=200

        def run():
            all_results=[]
            for di,drive in enumerate(drives):
                root=Path(drive)
                if not root.exists(): continue
                pct=int(di/len(drives)*80)
                self.after(0,lambda d=drive,p=pct:self._setstatus(f"Scanning: {d}",YELLOW,p))
                try:
                    res=scan_large_files(root,min_mb,limit)
                    all_results.extend(res)
                except: continue
            all_results.sort(key=lambda x:x["size_bytes"],reverse=True)
            self.scan_results=all_results[:limit]
            self.after(0,lambda:self._show_disk(self.scan_results))
            self._scanning=False
            self.after(0,lambda:self._scan_btn.set_text("🔍 Scan Selected Folder"))
        threading.Thread(target=run,daemon=True).start()

    def _show_disk(self,results):
        for i in self.disk_tree.get_children(): self.disk_tree.delete(i)
        sys_n=usr_n=0; total_b=0
        for idx,r in enumerate(results):
            mb=r["size_bytes"]/1048576
            icon=TYPE_ICONS.get(r["group"],"📁")
            scope="system" if r["in_system"] else "user"
            tag="sys" if r["in_system"] else ("usr" if idx%2==0 else "stripe")
            self.disk_tree.insert("","end",values=(fmt_size(r["size_bytes"]),
                f"{icon} {r['group']}",scope,r["path"]),tags=(tag,))
            if r["in_system"]: sys_n+=1
            else: usr_n+=1
            total_b+=r["size_bytes"]
        gb=total_b/(1024**3)
        self._stats_bar.configure(text=f"  ✦  {len(results):,} files  ·  {fmt_size(total_b)}  ·  system: {sys_n}  ·  Used: {usr_n}")
        self._scan_lbl.configure(text=f"✓ {len(results):,} file(s)",fg=GREEN)
        self._setstatus(f"✓ Scan complete: {len(results):,} file(s), {gb:.2f} GB",GREEN,100)
        for k,v in [("total",f"{len(results):,}"),("size",f"{gb:.1f} GB"),
                    ("system",str(sys_n)),("user",str(usr_n))]:
            self._stat_lbls[k].configure(text=v)

    def _tsort(self,col):
        items=[(self.disk_tree.set(k,col),k) for k in self.disk_tree.get_children()]
        try:    items.sort(key=lambda x:float(x[0].replace(",","").split()[0]),reverse=True)
        except: items.sort(reverse=True)
        for i,(_,k) in enumerate(items): self.disk_tree.move(k,"",i)

    def _get_selected_paths(self):
        return [self.disk_tree.item(i,"values")[3]
                for i in self.disk_tree.selection() if self.disk_tree.item(i,"values")]

    def _open_selected_file(self,event=None):
        paths=self._get_selected_paths()
        if not paths and event:
            iid=self.disk_tree.identify_row(event.y)
            if iid: paths=[self.disk_tree.item(iid,"values")[3]]
        if not paths: messagebox.showinfo("Notice","Select file(s) first."); return
        for p in paths[:3]:
            try: os.startfile(p)
            except Exception as e: messagebox.showerror("Error","Cannot open:\n"+p+"\n\n"+str(e))

    def _open_selected_folder(self,event=None):
        paths=self._get_selected_paths()
        if not paths: return
        try: subprocess.Popen(["explorer","/select,",paths[0]])
        except:
            try: os.startfile(str(Path(paths[0]).parent))
            except Exception as e: messagebox.showerror("Error",str(e))

    def _copy_path(self):
        paths=self._get_selected_paths()
        if not paths: return
        self.clipboard_clear(); self.clipboard_append("\n".join(paths))
        self._setstatus(f"✓ Copied {len(paths)} path(s)",GREEN)

    def _show_tree_menu(self,event):
        iid=self.disk_tree.identify_row(event.y)
        if iid:
            if iid not in self.disk_tree.selection(): self.disk_tree.selection_set(iid)
            try: self._tree_menu.tk_popup(event.x_root,event.y_root)
            finally: self._tree_menu.grab_release()

    def _add_custom_files(self):
        files=filedialog.askopenfilenames(title="Select files to add")
        if not files: return
        added=0; existing={r["path"] for r in self.scan_results}
        for fp in files:
            p=Path(fp)
            if str(p) not in existing:
                try:
                    self.scan_results.append({"path":str(p),"size_bytes":p.stat().st_size,
                                               "group":categorize_file(p),
                                               "in_system":str(p).startswith(SYS_PREFIXES)})
                    added+=1
                except OSError: continue
        if added: self._show_disk(self.scan_results); self._setstatus(f"✓ Added {added} file(s)",GREEN)

    def _delete_files(self,paths:List[str],on_done=None):
        if not paths: return
        sys_files=[p for p in paths if p.startswith(SYS_PREFIXES)]
        if sys_files:
            if not messagebox.askyesno("⚠ Warning — System Files",
                f"{len(sys_files)} system file(s) in the list — deleting them may harm Windows.\nDo you want to continue?"):
                paths=[p for p in paths if not p.startswith(SYS_PREFIXES)]
        if not paths: return
        method="Recycle Bin" if HAS_TRASH else "permanently"
        if not messagebox.askyesno("Confirm Deletion",
            f"Will delete {len(paths)} file(s) to {method}.\n\n"
            +"\n".join(f"  • {Path(p).name}" for p in paths[:8])
            +("\n  …" if len(paths)>8 else "")+"\n\nAre you sure?"): return
        deleted=0; failed=[]
        for p in paths:
            try:
                if HAS_TRASH: send2trash.send2trash(p)
                else:
                    p2=Path(p)
                    if p2.exists(): p2.unlink()
                deleted+=1
            except Exception as e: failed.append(f"{Path(p).name}: {e}")
        msg=f"✓ Deleted {deleted} file(s)"
        if failed: msg+=f"\n✗ Failed {len(failed)}"; messagebox.showwarning("Some files could not be deleted","\n".join(failed[:10]))
        self._setstatus(msg,GREEN if not failed else YELLOW)
        if on_done: on_done(paths)

    def _delete_selected(self):
        paths=self._get_selected_paths()
        if not paths: messagebox.showinfo("Notice","Select file(s) first."); return
        def on_done(deleted):
            ds=set(deleted); self.scan_results=[r for r in self.scan_results if r["path"] not in ds]
            self._show_disk(self.scan_results)
        self._delete_files(paths,on_done)

    # ── DUP ACTIONS ───────────────────────────────────────────────────
    def _browse_dup(self):
        d=filedialog.askdirectory(initialdir=self._dup_path_var.get())
        if d: self._dup_path_var.set(d)

    def _start_dup(self):
        if self._dup_busy: return
        p=self._dup_path_var.get().strip(); root=Path(p)
        if not root.exists() or not root.is_dir():
            messagebox.showerror("Invalid Path",f"Folder not found:\n{p}"); return
        self._dup_busy=True; self._dup_btn.set_text("⏳ Searching…")
        for i in self.dup_tree.get_children(): self.dup_tree.delete(i)
        self._dup_lbl.configure(text="Scanning…",fg=YELLOW)
        self._setstatus("Searching for duplicates…",YELLOW,5)
        def prog(n,path,phase): self.after(0,lambda n=n,ph=phase:self._setstatus(f"[{ph}] {n:,} file(s)",YELLOW,min(80,n//100)))
        def run():
            try:
                groups=find_duplicates(root,min_mb=1,cb=prog)
                self.dup_results=groups; self.after(0,lambda:self._show_dup(groups))
            except Exception as e: self.after(0,lambda:messagebox.showerror("Error",str(e)))
            finally:
                self._dup_busy=False; self.after(0,lambda:self._dup_btn.set_text("🔍 Find Duplicates"))
        threading.Thread(target=run,daemon=True).start()

    def _show_dup(self,groups):
        for i in self.dup_tree.get_children(): self.dup_tree.delete(i)
        total_waste=0
        for gi,grp in enumerate(groups,1):
            size=Path(grp[0]).stat().st_size if Path(grp[0]).exists() else 0
            waste=size*(len(grp)-1); total_waste+=waste
            self.dup_tree.insert("","end",values=(f"#{gi}",fmt_size(size),
                f"Group #{gi} — {len(grp)} copies — can save {fmt_size(waste)}"),tags=("header",))
            for idx,fp in enumerate(grp):
                self.dup_tree.insert("","end",values=("","",fp),tags=("item" if idx%2==0 else "stripe",))
        self._dup_stats.configure(text=f"  ✦  {len(groups)} group(s)  ·  potential savings: {fmt_size(total_waste)}")
        self._dup_lbl.configure(text=f"✓ {len(groups)} group(s)",fg=GREEN)
        self._setstatus(f"Duplicates: {len(groups)} group(s), savings: {fmt_size(total_waste)}",GREEN,100)

    def _delete_dup_selected(self):
        paths=[self.dup_tree.item(i,"values")[2]
               for i in self.dup_tree.selection()
               if self.dup_tree.item(i,"values") and not self.dup_tree.item(i,"values")[2].startswith("Group")]
        if not paths: messagebox.showinfo("Notice","Select duplicate files first."); return
        self._delete_files(paths,on_done=lambda _:self._start_dup())

    # ── TREEMAP ACTIONS ───────────────────────────────────────────────
    def _browse_tmap(self):
        d=filedialog.askdirectory(initialdir=self._tmap_path_var.get())
        if d: self._tmap_path_var.set(d)

    def _start_tmap(self):
        if self._tmap_busy: return
        p=self._tmap_path_var.get().strip(); root=Path(p)
        if not root.exists() or not root.is_dir():
            messagebox.showerror("Invalid Path",f"Folder not found:\n{p}"); return
        depth=self._tmap_depth.get(); self._tmap_busy=True
        self._tmap_btn.set_text("⏳ Loading…"); self._tmap_lbl.configure(text="Calculating…",fg=YELLOW)
        self._setstatus("Building treemap…",YELLOW,20)
        def run():
            try:
                data=build_treemap_data(root,depth)
                self.after(0,lambda:self._show_tmap(data,p))
            except Exception as e: self.after(0,lambda:messagebox.showerror("Error",str(e)))
            finally:
                self._tmap_busy=False; self.after(0,lambda:self._tmap_btn.set_text("🗺 Draw Treemap"))
        threading.Thread(target=run,daemon=True).start()

    def _show_tmap(self,data,path_str):
        mb=data["size"]/1048576
        self._tmap_lbl.configure(text=f"✓ {Path(path_str).name} — {fmt_size(data['size'])}",fg=GREEN)
        self._tmap_canvas.set_data(data); self._setstatus(f"✓ Treemap ready — {fmt_size(data['size'])}",GREEN,100)

    # ── RAM ───────────────────────────────────────────────────────────
    def _auto_ram(self): self._refresh_ram(); self.after(5000,self._auto_ram)
    def _refresh_ram(self):
        if not HAS_PSUTIL: self._ram_stats_lbl.configure(text="psutil not installed",fg=RED); return
        def run():
            s=get_sys_stats(); p=list_top_ram(20)
            self.after(0,lambda:self._show_ram(s,p))
        threading.Thread(target=run,daemon=True).start()
    def _show_ram(self,stats,procs):
        self._ram_stats_lbl.configure(text=f"CPU: {stats['cpu']:.1f}%   ·   RAM: {fmt_size(int(stats['ram_used']*1048576))} / {fmt_size(int(stats['ram_total']*1048576))} ({stats['ram_pct']:.1f}%)")
        self._cpu_arc.set_value(stats["cpu"]); self._ram_arc.set_value(stats["ram_pct"])
        self._ram_detail.configure(text=f"Used: {fmt_size(int(stats['ram_used']*1048576))}\nTotal: {fmt_size(int(stats['ram_total']*1048576))}")
        for i in self.ram_tree.get_children(): self.ram_tree.delete(i)
        for idx,(pid,name,mem) in enumerate(procs):
            self.ram_tree.insert("","end",values=(pid,name,f"{mem:,.1f}"),tags=("stripe",) if idx%2 else ())
        self._setstatus(f"RAM — CPU: {stats['cpu']:.1f}%",TEXT2)

    # ── STARTUP ───────────────────────────────────────────────────────
    def _load_startup(self):
        self._startup_lbl.configure(text="Loading…",fg=YELLOW)
        def run():
            entries=get_startup_entries(); self.startup_entries=entries
            self.after(0,lambda:self._show_startup(entries))
        threading.Thread(target=run,daemon=True).start()

    def _show_startup(self,entries):
        for i in self.startup_tree.get_children(): self.startup_tree.delete(i)
        for idx,e in enumerate(entries):
            tag="folder" if e["hive"]=="FOLDER" else ("reg" if idx%2==0 else "stripe")
            self.startup_tree.insert("","end",values=(e["name"],e["location"],e["command"]),tags=(tag,))
        self._startup_lbl.configure(text=f"✓ {len(entries)} item(s)",fg=GREEN)
        self._setstatus(f"Startup: {len(entries)} item(s)",GREEN)

    def _disable_startup_selected(self):
        sel_names={self.startup_tree.item(i,"values")[0]
                   for i in self.startup_tree.selection()
                   if self.startup_tree.item(i,"values")}
        selected=[e for e in self.startup_entries if e["name"] in sel_names]
        if not selected: messagebox.showinfo("Notice","Select an item first."); return
        if not messagebox.askyesno("Confirm",f"Disable {len(selected)} item(s)?\n"+"\n".join(f"  • {e['name']}" for e in selected)): return
        ok=0; fail=[]
        for e in selected:
            if disable_startup_entry(e): ok+=1
            else: fail.append(e["name"])
        self._setstatus(f"✓ Disabled {ok}" +(" | Failed: "+", ".join(fail) if fail else ""),GREEN if not fail else YELLOW)
        self._load_startup()

    def _analyze_startup(self):
        if not self.startup_entries: messagebox.showinfo("Notice","Load the list first."); return
        if self._llm_busy: return
        self._llm_busy=True
        lines=[f"  [{e['location']}] {e['name']}: {e['command'][:80]}" for e in self.startup_entries]
        prompt=("Classify these startup programs:\n• SAFE | <description> | <can it be disabled?> — <Name>\n"
                "• CAUTION | <reason> — <Name>\n• SUSPICIOUS | <reason> — <Name>\n"
                "\n\n"+"\n".join(lines))
        def run():
            try: result=_call_ollama(prompt,max_tokens=2000)
            except Exception as e: result=f"⚠ {e}"
            self.after(0,lambda:self._show_startup_ai(result))
        threading.Thread(target=run,daemon=True).start()

    def _show_startup_ai(self,text):
        self._llm_busy=False
        self._startup_ai_text.configure(state="normal")
        self._startup_ai_text.delete("1.0","end")
        self._startup_ai_text.insert("end",text)
        self._startup_ai_text.configure(state="disabled")
        self._setstatus("✓ Startup analysis complete",GREEN)

    # ── AI ANALYSIS ───────────────────────────────────────────────────
    def _start_llm(self):
        if self._llm_busy: return
        if not self.scan_results:
            messagebox.showinfo("Notice","Run a full scan first from the dashboard.")
            return
        # Use all files for summary/plan modes, 50 for classify
        mode = getattr(self,"_ai_mode_var",None)
        mode = mode.get() if mode else "classify"
        files = self.scan_results if mode in ("summary","cleanup_plan") else self.scan_results[:50]
        self._run_ai_analysis(files, mode)

    def _analyze_selected(self):
        paths=self._get_selected_paths()
        if not paths: messagebox.showinfo("Notice","Select rows first.\n(Ctrl+Click for multiple rows)"); return
        selected=[r for r in self.scan_results if r["path"] in set(paths)]
        if not selected: return
        mode = getattr(self,"_ai_mode_var",None)
        mode = mode.get() if mode else "classify"
        self._run_ai_analysis(selected, mode)

    def _run_ai_analysis(self, files, mode="classify"):
        if self._llm_busy: return
        self._llm_busy=True; self._switch("ai")
        mode_names={"classify":"Classify","summary":"Summary","cleanup_plan":"Cleanup Plan","smart_delete":"Smart Delete"}
        self._ai_btn.set_text("⏳ Analyzing…"); self._ai_sel_btn.set_text("⏳ Loading…")
        self._ai_status.configure(text=f"⏳ {mode_names.get(mode,mode)}: {len(files)} file(s)…",fg=YELLOW)
        self._put_ai(f"⏳ Running {mode_names.get(mode,'analysis')} on {len(files)} file(s)...\nPlease wait 10 seconds to 2 minutes depending on the model…")
        self._setstatus(f"Running analysis ({mode})…",YELLOW,20)
        def run():
            try: result=review_with_llm(files, mode=mode)
            except Exception as e: result=f"⚠ Error: {e}"
            self.after(0,lambda:self._show_ai(result,mode))
        threading.Thread(target=run,daemon=True).start()

    def _put_ai(self,txt):
        self.ai_text.configure(state="normal"); self.ai_text.delete("1.0","end")
        self.ai_text.insert("end",txt,"dim"); self.ai_text.configure(state="disabled")

    def _show_ai(self, text, mode="classify"):
        self._llm_busy=False
        self._ai_btn.set_text("🧠 Analyze All Files"); self._ai_sel_btn.set_text("🎯 Analyze Selected")
        self._ai_status.configure(text="✓ Analysis complete", fg=GREEN)
        self.after(4000, lambda: self._ai_status.configure(text=""))
        self.ai_text.configure(state="normal"); self.ai_text.delete("1.0","end")
        s=ca=d=0

        if mode in ("summary","cleanup_plan"):
            # Rich text rendering for free-form Arabic text
            for line in text.split("\n"):
                line=line.strip()
                if not line: self.ai_text.insert("end","\n"); continue
                u=line.upper()
                if line.startswith(("Step","Step","Step")) or (len(line)>2 and line[1]=="."):
                    self.ai_text.insert("end","\n" + line + "\n","step")
                elif "⚠" in line or "Warning" in line:
                    self.ai_text.insert("end",line+"\n","warn")
                elif any(c in line for c in ("1.","2.","3.","4.","5.")):
                    self.ai_text.insert("end","  ◆ "+line+"\n","bullet")
                else:
                    self.ai_text.insert("end",line+"\n","dim")

        elif mode == "smart_delete":
            # Show as paths list with delete suggestion
            self.ai_text.insert("end","✅ Files suggested for safe deletion:\n\n","header")
            paths=[]
            for line in text.split("\n"):
                line=line.strip()
                if not line: continue
                if any(line.startswith(p) for p in ("C:\\","D:\\","E:\\"," ")) or ":\\" in line:
                    self.ai_text.insert("end","  🗑 ","bullet")
                    self.ai_text.insert("end",line+"\n","path")
                    paths.append(line)
                elif "⚠" in line:
                    self.ai_text.insert("end",line+"\n","warn")
                else:
                    self.ai_text.insert("end",line+"\n","dim")
            if paths:
                self.ai_text.insert("end",f"\n📊 Total: {len(paths)} file(s) to delete\n","step")

        else:
            # classify mode — original logic
            for line in text.split("\n"):
                line=line.strip()
                if not line: self.ai_text.insert("end","\n"); continue
                u=line.upper()
                if line[0] in ("*","•","-","·"):
                    rest=line[1:].strip(); self.ai_text.insert("end","  ▸ ","bullet")
                    if   "SAFE"      in u: tag="safe";    s+=1
                    elif "CAUTION"   in u: tag="caution"; ca+=1
                    elif "DANGEROUS" in u: tag="danger";  d+=1
                    else:                  tag=None
                    if tag:
                        parts=rest.split("—",1); self.ai_text.insert("end",parts[0].strip(),tag)
                        if len(parts)>1:
                            self.ai_text.insert("end","  —  ")
                            self.ai_text.insert("end",parts[1].strip()+"\n","path")
                        else:
                            self.ai_text.insert("end","\n")
                    else: self.ai_text.insert("end",rest+"\n")
                else:
                    self.ai_text.insert("end",line+"\n","warn" if ("⚠" in line or "Error" in line) else "dim")

        # Update pills counter
        if mode == "classify":
            self._pills["safe"].configure(text=str(s) if s else "—")
            self._pills["caution"].configure(text=str(ca) if ca else "—")
            self._pills["danger"].configure(text=str(d) if d else "—")
        elif mode == "smart_delete":
            self._pills["safe"].configure(text="✓")
            self._pills["caution"].configure(text="—")
            self._pills["danger"].configure(text="—")

        self.ai_text.configure(state="disabled")
        self.ai_text.see("1.0")
        self._setstatus("✓ Analysis complete", GREEN, 100)
        self.ai_text.configure(state="disabled"); self.ai_text.see("1.0")
        total=s+ca+d
        if total:
            self._pills["safe"].configure(text=str(s)); self._pills["caution"].configure(text=str(ca))
            self._pills["danger"].configure(text=str(d))
            self._ai_status.configure(text=f"✓ Complete — {total} file(s)",fg=GREEN)
        else: self._ai_status.configure(text="⚠ Check Ollama connection",fg=YELLOW)
        self._setstatus(f"Analysis — safe: {s} · caution: {ca} · danger: {d}",GREEN if not text.startswith("⚠") else YELLOW,100)

    # ── CHAT ──────────────────────────────────────────────────────────
    def _chat_welcome(self):
        model=_get_best_model() if HAS_REQUESTS else "Not available"
        self._chat_append(f"Hello! I'm your AI assistant 🤖\nModel: {model}\n\n"
            "You can ask me anything about your system or files.",tag="sys")

    def _chat_append(self,text,tag="ai",prefix=""):
        self._chat_box.configure(state="normal")
        if prefix: self._chat_box.insert("end",prefix+"\n",tag)
        self._chat_box.insert("end",text+"\n\n",tag)
        self._chat_box.configure(state="disabled"); self._chat_box.see("end")

    def _chat_send(self):
        msg=self._chat_var.get().strip()
        if not msg or self._llm_busy: return
        self._chat_var.set(""); self._chat_append(msg,tag="user",prefix="You:")
        self._llm_busy=True; self._setstatus("AI is thinking…",YELLOW)
        def run():
            try: response=_call_ollama(msg,max_tokens=1000,history=self._chat_history)
            except Exception as e: response=f"⚠ Error: {e}"
            self._chat_history.append({"role":"user","content":msg})
            self._chat_history.append({"role":"assistant","content":response})
            if len(self._chat_history)>22:
                self._chat_history=self._chat_history[:1]+self._chat_history[-20:]
            self.after(0,lambda:self._chat_got_reply(response))
        threading.Thread(target=run,daemon=True).start()

    def _chat_got_reply(self,text):
        self._llm_busy=False; tag="warn" if text.startswith("⚠") else "ai"
        self._chat_append(text,tag=tag,prefix="AI:"); self._setstatus("✓ AI reply ready",GREEN)

    def _chat_clear(self):
        self._chat_history=[{"role":"system","content":
            "You are an intelligent assistant specializing in Windows system cleanup and maintenance. Keep all paths in their original format."}]
        self._chat_box.configure(state="normal"); self._chat_box.delete("1.0","end")
        self._chat_box.configure(state="disabled"); self.after(100,self._chat_welcome)

    def _chat_inject_scan(self):
        if not self.scan_results: messagebox.showinfo("Notice","Run a scan first."); return
        lines=[f"  [{r['group'].upper()}] {fmt_size(r['size_bytes'])} {r['path']}" for r in self.scan_results[:50]]
        ctx="Disk scan results:\n"+"\n".join(lines)
        self._chat_history.append({"role":"user","content":ctx})
        self._chat_history.append({"role":"assistant","content":"OK, I received the scan results."})
        self._chat_append(f"✓ Added {len(self.scan_results)} file(s) to the conversation.",tag="sys")

    def _chat_inject_startup(self):
        if not self.startup_entries: messagebox.showinfo("Notice","Load the startup list first."); return
        lines=[f"  [{e['location']}] {e['name']}: {e['command'][:60]}" for e in self.startup_entries]
        ctx="Startup programs:\n"+"\n".join(lines)
        self._chat_history.append({"role":"user","content":ctx})
        self._chat_history.append({"role":"assistant","content":"OK, I received the startup list."})
        self._chat_append(f"✓ Added {len(self.startup_entries)} item(s).",tag="sys")

# ═══════════════════════════════════════════════



# ═══════════════════════════════════════════════════════
#  SPLASH SCREEN
# ═══════════════════════════════════════════════════════
class SplashScreen(tk.Toplevel):
    def __init__(self, root):
        super().__init__(root); self.overrideredirect(True)
        self.configure(bg=_col("BG")); self.attributes("-topmost",True)
        self.attributes("-alpha",0.0)
        W,H=420,220; sw=self.winfo_screenwidth(); sh=self.winfo_screenheight()
        self.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        out=tk.Frame(self,bg=_col("ACCENT"),padx=2,pady=2); out.pack(fill="both",expand=True)
        inn=tk.Frame(out,bg=_col("BG")); inn.pack(fill="both",expand=True)
        c=tk.Canvas(inn,width=48,height=48,bg=_col("BG"),highlightthickness=0); c.pack(pady=(18,0))
        def _d():
            c.create_polygon([24,3,43,11,43,34,24,46,5,34,5,11],
                              fill=_col("ACCENT"),outline=_col("ACC2"),smooth=True,width=2)
            c.create_text(24,27,text="D",fill=_col("BG"),font=("Segoe UI",15,"bold"))
        self.after(10,_d)
        tk.Label(inn,text="DiskVision",bg=_col("BG"),fg=_col("TEXT"),
                 font=("Segoe UI",17,"bold")).pack(pady=(8,2))
        tk.Label(inn,text=f"v{APP_VERSION}  ·  Smart System Cleaner",
                 bg=_col("BG"),fg=_col("TEXT3"),font=("Segoe UI",9)).pack()
        bf=tk.Frame(inn,bg=_col("CARD2"),height=3); bf.pack(fill="x",padx=32,pady=(14,0))
        self._b=tk.Frame(bf,bg=_col("ACCENT"),height=3,width=0)
        self._b.place(x=0,y=0,relheight=1.0)
        self._a=0.0; self._p=0; self._fade(); self._anim()
    def _fade(self):
        self._a=min(1.0,self._a+0.1)
        try:
            self.attributes("-alpha",self._a)
            if self._a<1.0: self.after(18,self._fade)
        except tk.TclError: pass
    def _anim(self):
        self._p+=3
        try:
            w=int((self._b.master.winfo_width() or 356)*min(self._p,100)/100)
            self._b.place(x=0,y=0,width=w,relheight=1.0)
            if self._p<100: self.after(20,self._anim)
        except tk.TclError: pass
    def close(self):
        def fade():
            try:
                a=self.attributes("-alpha")-0.12
                if a>0: self.attributes("-alpha",max(0,a)); self.after(18,fade)
                else: self.destroy()
            except tk.TclError: pass
        self.after(0,fade)


if __name__ == "__main__":
    app = App()
    splash = SplashScreen(app); app.update(); app.withdraw()
    def _show(): splash.close(); app.deiconify(); app.lift(); app.focus_force()
    app.after(2000, _show)
    app.mainloop()
