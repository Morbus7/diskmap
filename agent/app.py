"""Diskmap-agent: skanner diskbruk lokalt og viser resultatet via et lite HTTP-API.

Leser bare mappeinformasjon (scandir/lstat). Åpner aldri filer, og endrer eller sletter ingenting.
Kun standardbiblioteket.
"""
import ctypes
import gzip
import heapq
import hmac
import json
import os
import platform
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

VERSION = "1.0.1"


# ---------- Oppsett fra miljøvariabler ----------

def env_bool(name, default=False):
    v = os.environ.get(name)
    return default if v is None or v == "" else v.strip().lower() in ("1", "true", "yes", "ja", "on")


def env_int(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def parse_roots(text):
    """«/data/volume1:volume1,/host:xubu» -> [(sti, visningsnavn)]. Uten navn brukes siste del av stien."""
    roots = []
    for part in filter(None, (p.strip() for p in text.replace(";", ",").split(","))):
        path, _, name = part.rpartition(":") if ":" in part else (part, "", "")
        path = path or part
        name = (name or os.path.basename(path.rstrip("/")) or "root").replace("/", "_")
        roots.append((os.path.abspath(path), name))
    return roots


AGENT_NAME = os.environ.get("AGENT_NAME") or socket.gethostname()
ROOTS = parse_roots(os.environ.get("ROOTS", ""))
EXCLUDE = {e.strip() for e in os.environ.get("EXCLUDE", "#snapshot,@sharesnap").split(",") if e.strip()}
ONE_FILESYSTEM = env_bool("ONE_FILESYSTEM", False)
SCAN_AT = [t.strip() for t in os.environ.get("SCAN_AT", "").split(",") if t.strip()]
API_TOKEN = os.environ.get("API_TOKEN", "")
MIN_ENTRY = env_int("MIN_ENTRY_MB", 50) * 1024 * 1024
MAX_CHILDREN = env_int("MAX_CHILDREN", 40)
TOP_FILES = env_int("TOP_FILES", 200)
MAX_TYPES = 300
PORT = env_int("PORT", 8787)
DATA_DIR = os.environ.get("DATA_DIR", "/data")
SCAN_ON_START = env_bool("SCAN_ON_START", True)  # skann ved oppstart hvis det ikke finnes noen skanning fra før


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


# ---------- Lav prioritet ----------

def lower_priority():
    """Laveste CPU-prioritet og IO-klassen «idle» for skannetråden (Linux, der det er mulig)."""
    tid = threading.get_native_id()
    try:
        os.setpriority(os.PRIO_PROCESS, tid, 19)
    except OSError as err:
        log("Fikk ikke senket CPU-prioritet:", err)
    nr = {"x86_64": 251, "aarch64": 30, "armv7l": 314, "i686": 289}.get(platform.machine())
    if nr is None:
        return
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        # ioprio_set(IOPRIO_WHO_PROCESS=1, tråd, IOPRIO_CLASS_IDLE=3 << 13)
        if libc.syscall(nr, 1, tid, 3 << 13) != 0:
            log("Fikk ikke satt IO-prioritet, errno", ctypes.get_errno())
    except Exception as err:  # noqa: BLE001 – ikke kritisk
        log("Fikk ikke satt IO-prioritet:", err)


# ---------- Monteringspunkter (ONE_FILESYSTEM) ----------

def mount_points():
    """Alle monteringspunkter sett fra containeren. Btrfs-subvolumer (Synology) har egen st_dev uten å være
    egne monteringer, så vi bruker monteringstabellen og ikke st_dev."""
    points = set()
    try:
        with open("/proc/self/mountinfo", encoding="utf-8", errors="replace") as f:
            for line in f:
                p = line.split()[4].replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")
                points.add(p)
    except OSError:
        return None
    return points


# ---------- Skanning ----------

class Scan:
    """Én skanning. Treet beskjæres underveis så minnebruken holder seg lav også med millioner av filer."""

    def __init__(self, status):
        self.status = status
        self.seen_inodes = set()   # hardlenker telles én gang: (st_dev, st_ino)
        self.top = []              # min-heap med (størrelse, sti, endret)
        self.types = {}            # filendelse -> [byte, antall]
        self.errors = 0
        self.mounts = mount_points() if ONE_FILESYSTEM else None
        self.root_dev = None
        self.counter = 0

    def skip_mount(self, path, st_dev):
        if not ONE_FILESYSTEM:
            return False
        if self.mounts is not None:
            return path in self.mounts
        return st_dev != self.root_dev  # reserve når monteringstabellen ikke kan leses

    def add_file(self, path, name, size, mtime):
        ext = os.path.splitext(name)[1].lower()[1:]
        if not ext or len(ext) > 12 or " " in ext:
            ext = ""
        t = self.types.get(ext)
        if t:
            t[0] += size
            t[1] += 1
        else:
            self.types[ext] = [size, 1]
        if TOP_FILES > 0:
            if len(self.top) < TOP_FILES:
                heapq.heappush(self.top, (size, path, mtime))
            elif size > self.top[0][0]:
                heapq.heapreplace(self.top, (size, path, mtime))

    def scan_dir(self, path, rel, name, own_size):
        """Skanner én mappe og gir en beskåret node: n=navn, t=type (d/f/o), s=byte, f=filer, c=barn."""
        size, files, small = own_size, 0, [0, 0, 0]  # small: byte, filer, antall elementer
        kids = []
        try:
            it = os.scandir(path)
        except OSError:
            self.errors += 1
            return {"n": name, "t": "d", "s": size, "f": 0, "err": 1}
        with it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    self.errors += 1
                    continue
                child_rel = rel + "/" + e.name
                if e.is_dir(follow_symlinks=False):
                    if e.name in EXCLUDE or self.skip_mount(e.path, st.st_dev):
                        continue
                    node = self.scan_dir(e.path, child_rel, e.name, st.st_blocks * 512)
                    size += node["s"]
                    files += node["f"]
                    if node["s"] >= MIN_ENTRY:
                        kids.append(node)
                    else:
                        small[0] += node["s"]
                        small[1] += node["f"]
                        small[2] += 1
                    continue
                # Filer, symlenker og spesialfiler: diskplassen de faktisk bruker (blokker)
                if st.st_nlink > 1:
                    key = (st.st_dev, st.st_ino)
                    if key in self.seen_inodes:
                        continue
                    self.seen_inodes.add(key)
                fsize = st.st_blocks * 512
                size += fsize
                files += 1
                if e.is_file(follow_symlinks=False):
                    self.add_file(child_rel, e.name, fsize, int(st.st_mtime))
                if fsize >= MIN_ENTRY:
                    kids.append({"n": e.name, "t": "f", "s": fsize, "f": 1})
                else:
                    small[0] += fsize
                    small[1] += 1
                    small[2] += 1
                self.counter += 1
                if self.counter % 2000 == 0:
                    self.status.progress(files=self.counter, current=rel)
        kids.sort(key=lambda k: k["s"], reverse=True)
        if len(kids) > MAX_CHILDREN:
            for k in kids[MAX_CHILDREN:]:
                small[0] += k["s"]
                small[1] += k["f"]
                small[2] += 1
            kids = kids[:MAX_CHILDREN]
        if small[2]:
            kids.append({"n": f"({small[2]} mindre elementer)", "t": "o", "s": small[0], "f": small[1], "k": small[2]})
        node = {"n": name, "t": "d", "s": size, "f": files}
        if kids:
            node["c"] = kids
        return node

    def run(self):
        roots = []
        for path, name in ROOTS:
            self.status.progress(root=name, current=name)
            cap = capacity(path)
            try:
                st = os.lstat(path)
            except OSError as err:
                log("Kan ikke lese roten", path, err)
                roots.append({"n": name, "t": "d", "s": 0, "f": 0, "err": 1, "cap": cap, "path": path})
                continue
            self.root_dev = st.st_dev
            node = self.scan_dir(path, name, name, 0)
            node["path"] = path
            node["cap"] = cap
            if cap:
                cap["hidden"] = max(0, cap["used"] - node["s"])  # brukt men ikke synlig: snapshots, utelatte mapper o.l.
            roots.append(node)
            self.status.progress(done_bytes=node["s"])
        top = sorted(self.top, reverse=True)
        types = sorted(([k, v[0], v[1]] for k, v in self.types.items()), key=lambda x: x[1], reverse=True)
        return {
            "tree": {"n": AGENT_NAME, "t": "d", "s": sum(r["s"] for r in roots), "f": sum(r["f"] for r in roots), "c": roots},
            "top_files": [{"p": p, "s": s, "m": m} for s, p, m in top],
            "types": [{"x": x, "s": s, "f": f} for x, s, f in types[:MAX_TYPES]],
            "errors": self.errors,
        }


def capacity(path):
    try:
        v = os.statvfs(path)
    except OSError:
        return None
    total = v.f_blocks * v.f_frsize
    return {"total": total, "used": (v.f_blocks - v.f_bfree) * v.f_frsize, "free": v.f_bavail * v.f_frsize}


def flat_sizes(node, prefix="", out=None):
    """sti -> størrelse for alle mapper og filer i et tre (til beregning av vekst)."""
    out = {} if out is None else out
    path = prefix + "/" + node["n"] if prefix else node["n"]
    if node["t"] != "o":
        out[path] = node["s"]
    for c in node.get("c", ()):
        flat_sizes(c, path, out)
    return out


def add_growth(node, prev, prefix=""):
    """g = endring i byte siden forrige skanning, new = fantes ikke (eller var for liten til å være med) sist."""
    path = prefix + "/" + node["n"] if prefix else node["n"]
    if node["t"] != "o":
        if path in prev:
            node["g"] = node["s"] - prev[path]
        else:
            node["new"] = 1
    for c in node.get("c", ()):
        add_growth(c, prev, path)


# ---------- Tilstand og lagring ----------

class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.result = None       # siste ferdige skanning
        self.tree_gz = None      # siste resultat som gzip-JSON (til /api/tree)
        self.running = False
        self.info = {}

    def progress(self, files=None, current=None, root=None, done_bytes=None):
        with self.lock:
            if files is not None:
                self.info["files"] = files
            if current is not None:
                self.info["current"] = current
            if root is not None:
                self.info["root"] = root
            if done_bytes is not None:
                self.info["done_bytes"] = self.info.get("done_bytes", 0) + done_bytes

    def status(self):
        with self.lock:
            s = {"running": self.running, **self.info}
        if self.running:
            # Fremdrift: antall filer mot forrige skanning (beste anslag), ellers ukjent
            prev_files = self.result["tree"]["f"] if self.result else 0
            s["percent"] = min(99, round(100 * s.get("files", 0) / prev_files)) if prev_files else None
        return s


STATE = State()
CURRENT = os.path.join(DATA_DIR, "scan.json.gz")


def load_saved():
    try:
        with gzip.open(CURRENT, "rt", encoding="utf-8") as f:
            res = json.load(f)
        set_result(res)
        log("Lastet forrige skanning", res.get("scan_id"))
    except FileNotFoundError:
        pass
    except Exception as err:  # noqa: BLE001
        log("Kunne ikke lese lagret skanning:", err)


def set_result(res):
    data = gzip.compress(json.dumps(res, ensure_ascii=False, separators=(",", ":")).encode(), 6)
    with STATE.lock:
        STATE.result = res
        STATE.tree_gz = data
    return data


def save(data):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = CURRENT + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, CURRENT)
    except OSError as err:
        log("Kunne ikke lagre skanningen:", err)


def scan_worker():
    lower_priority()
    started = time.time()
    log("Skanning startet")
    try:
        res = Scan(STATE).run()
        prev = STATE.result
        if prev:
            add_growth(res["tree"], flat_sizes(prev["tree"]))
            res["prev_scan_id"] = prev.get("scan_id")
            res["prev_scanned_at"] = prev.get("scanned_at")
        res["scan_id"] = time.strftime("%Y%m%dT%H%M%S", time.localtime(started))
        res["started_at"] = int(started)
        res["scanned_at"] = int(time.time())
        res["duration"] = round(time.time() - started, 1)
        save(set_result(res))
        STATE.progress(files=res["tree"]["f"], current="")
        log(f"Skanning ferdig på {res['duration']} s: {res['tree']['f']} filer, {res['errors']} feil")
    except Exception as err:  # noqa: BLE001
        log("Skanningen feilet:", repr(err))
        with STATE.lock:
            STATE.info["last_error"] = repr(err)
    finally:
        with STATE.lock:
            STATE.running = False


def start_scan():
    with STATE.lock:
        if STATE.running:
            return False
        STATE.running = True
        STATE.info = {"started_at": int(time.time()), "files": 0, "done_bytes": 0}
    threading.Thread(target=scan_worker, name="scan", daemon=True).start()
    return True


def scheduler():
    """Starter skanning på tidspunktene i SCAN_AT (lokal tid, TZ)."""
    done = set()
    while True:
        now = time.localtime()
        hm, day = time.strftime("%H:%M", now), time.strftime("%Y-%m-%d", now)
        for t in SCAN_AT:
            if t == hm and (day, t) not in done:
                done.add((day, t))
                if start_scan():
                    log("Planlagt skanning", t)
        time.sleep(20)


# ---------- Svar fra API-et ----------

def summary():
    with STATE.lock:
        res = STATE.result
    out = {"name": AGENT_NAME, "version": VERSION, "running": STATE.running, "scan_id": None, "roots": []}
    if not res:
        out["roots"] = [{"name": n, "path": p, "cap": capacity(p)} for p, n in ROOTS]
        return out
    out.update({k: res.get(k) for k in ("scan_id", "scanned_at", "started_at", "duration", "errors", "prev_scanned_at")})
    out["files"] = res["tree"]["f"]
    for r in res["tree"]["c"]:
        cap = capacity(r["path"]) or r.get("cap")  # kapasitet nå, «ikke synlig» fra skanningen
        if cap and r.get("cap"):
            cap["hidden"] = r["cap"].get("hidden", 0)
        out["roots"].append({
            "name": r["n"], "path": r["path"], "size": r["s"], "files": r["f"], "cap": cap,
            "top": [{k: c[k] for k in ("n", "t", "s", "f", "g", "new", "k") if k in c} for c in r.get("c", ())],
        })
    return out


def subtree(res, path, depth):
    """Del av treet: path = navn skilt med «/» (f.eks. «volume1/photo»), depth = antall nivåer under."""
    node = res["tree"]
    for part in filter(None, path.split("/")):
        node = next((c for c in node.get("c", ()) if c["n"] == part and c["t"] != "o"), None)
        if node is None:
            return None

    def cut(n, d):
        m = {k: v for k, v in n.items() if k != "c"}
        if "c" in n:
            if d > 0:
                m["c"] = [cut(c, d - 1) for c in n["c"]]
            else:
                m["more"] = len(n["c"])
        return m
    return cut(node, depth) if depth is not None else node


class Handler(BaseHTTPRequestHandler):
    server_version = "diskmap/" + VERSION

    def log_message(self, fmt, *args):  # bare feil i loggen, ikke hvert kall
        pass

    def authorized(self):
        h = self.headers.get("Authorization", "")
        return h.startswith("Bearer ") and hmac.compare_digest(h[7:].strip().encode(), API_TOKEN.encode())

    def send(self, code, body=None, gz=None):
        if gz is not None and "gzip" in self.headers.get("Accept-Encoding", ""):
            data, enc = gz, "gzip"
        else:
            data = gzip.decompress(gz) if gz is not None else json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
            enc = None
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if enc:
            self.send_header("Content-Encoding", enc)
        self.end_headers()
        self.wfile.write(data)

    def route(self, method):
        url = urlparse(self.path)
        if url.path == "/healthz":
            return self.send(200, {"ok": True})
        if not self.authorized():
            return self.send(401, {"error": "unauthorized"})
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if method == "GET" and url.path == "/api/info":
            return self.send(200, {"name": AGENT_NAME, "version": VERSION, "roots": [{"name": n, "path": p} for p, n in ROOTS],
                                   "scan_at": SCAN_AT, "one_filesystem": ONE_FILESYSTEM, "exclude": sorted(EXCLUDE)})
        if method == "GET" and url.path == "/api/summary":
            return self.send(200, summary())
        if method == "GET" and url.path == "/api/status":
            return self.send(200, STATE.status())
        if method == "GET" and url.path == "/api/tree":
            with STATE.lock:
                res, gz = STATE.result, STATE.tree_gz
            if not res:
                return self.send(404, {"error": "no_scan"})
            if "path" not in q and "depth" not in q:
                return self.send(200, gz=gz)
            try:
                depth = int(q["depth"]) if "depth" in q else None
            except ValueError:
                return self.send(400, {"error": "bad_depth"})
            node = subtree(res, q.get("path", ""), depth)
            if node is None:
                return self.send(404, {"error": "no_path"})
            return self.send(200, {"scan_id": res["scan_id"], "path": q.get("path", ""), "node": node})
        if method == "POST" and url.path == "/api/scan":
            started = start_scan()
            return self.send(202 if started else 409, {"started": started, "status": STATE.status()})
        return self.send(404, {"error": "not_found"})

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")


def main():
    if len(API_TOKEN) < 16:
        sys.exit("API_TOKEN mangler eller er for kort (minst 16 tegn).")
    if not ROOTS:
        sys.exit("ROOTS mangler, f.eks. ROOTS=/volume1:volume1")
    sys.setrecursionlimit(20000)
    threading.stack_size(256 * 1024 * 1024)  # dype mappetrær i skannetråden
    log(f"Diskmap-agent {VERSION} «{AGENT_NAME}»: røtter {ROOTS}, unntak {sorted(EXCLUDE)}, "
        f"ett filsystem: {ONE_FILESYSTEM}, skanner kl. {SCAN_AT or 'bare manuelt'}, port {PORT}")
    load_saved()
    if SCAN_AT:
        threading.Thread(target=scheduler, name="scheduler", daemon=True).start()
    if SCAN_ON_START and STATE.result is None:
        start_scan()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
