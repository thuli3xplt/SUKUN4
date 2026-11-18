# banner.py — SUKUN4 branding, color, logging helpers
import os
import sys
import datetime

class C:
    RESET = "\033[0m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RED = "\033[38;5;203m"
    GREEN = "\033[38;5;114m"
    YELLOW = "\033[38;5;221m"
    CYAN = "\033[38;5;80m"
    MAGENTA = "\033[38;5;177m"
    BLUE = "\033[38;5;75m"
    WHITE = "\033[38;5;253m"
    GREY = "\033[38;5;245m"

if os.name == "nt":
    os.system("")

NAME = "SUKUN4"
AUTHOR = "thuli3xplt"
TAGLINE = "c2 operator console"

def _read_version():
    here = os.path.dirname(os.path.abspath(__file__))
    vpath = os.path.join(here, "VERSION")
    try:
        with open(vpath, "r", encoding="utf-8") as f:
            return f.read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"

VERSION = _read_version()

_LOGO = r"""
   ███████╗██╗   ██╗██╗  ██╗██╗   ██╗███╗   ██╗██╗  ██╗
   ██╔════╝██║   ██║██║ ██╔╝██║   ██║████╗  ██║██║  ██║
   ███████╗██║   ██║█████╔╝ ██║   ██║██╔██╗ ██║███████║
   ╚════██║██║   ██║██╔═██╗ ██║   ██║██║╚██╗██║╚════██║
   ███████║╚██████╔╝██║  ██╗╚██████╔╝██║ ╚████║     ██║
   ╚══════╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝     ╚═╝
"""

def logo(colored=True):
    if colored:
        return C.CYAN + _LOGO + C.RESET
    return _LOGO

def print_banner():
    print(logo())
    pad = " " * 30
    print(f"{pad}{C.GREY}by {C.WHITE}{AUTHOR}{C.RESET}")
    print()
    print(f"  {C.DIM}type 'help' for commands, 'exit' to quit{C.RESET}")
    print()

def _stamp():
    return datetime.datetime.now().strftime("%H:%M:%S")

def info(msg):
    print(f"{C.GREY}[{_stamp()}]{C.RESET} {C.BLUE}*{C.RESET} {msg}")

def ok(msg):
    print(f"{C.GREY}[{_stamp()}]{C.RESET} {C.GREEN}+{C.RESET} {msg}")

def warn(msg):
    print(f"{C.GREY}[{_stamp()}]{C.RESET} {C.YELLOW}!{C.RESET} {msg}")

def err(msg):
    print(f"{C.GREY}[{_stamp()}]{C.RESET} {C.RED}x{C.RESET} {msg}")

def die(msg, code=1):
    err(msg)
    sys.exit(code)

def session_open(host, port):
    print(f"{C.GREY}[{_stamp()}]{C.RESET} {C.GREEN}+{C.RESET} "
          f"session {C.WHITE}{host}:{port}{C.RESET} {C.GREEN}open{C.RESET}")

def session_closed(host):
    print(f"{C.GREY}[{_stamp()}]{C.RESET} {C.RED}x{C.RESET} "
          f"session {C.WHITE}{host}{C.RESET} {C.RED}closed{C.RESET}")

def prompt(host=None):
    if host:
        return f"{C.CYAN}{NAME}{C.RESET} {C.GREY}@{C.RESET} {C.WHITE}{host}{C.RESET} {C.CYAN}>{C.RESET} "
    return f"{C.CYAN}{NAME}{C.RESET} {C.GREY}listener{C.RESET} {C.CYAN}>{C.RESET} "