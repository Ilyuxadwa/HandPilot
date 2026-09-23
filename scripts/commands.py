import os
import glob
import psutil
import webbrowser
from PIL import ImageGrab
from comtypes import CLSCTX_ALL
from datetime import datetime
from ctypes import cast, POINTER
from urllib.parse import quote_plus
from rapidfuzz import fuzz, process
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume


APP_PATHS = {
    "browser": "chrome",
    "chrome": "chrome",
    "notepad": "notepad",
    "explorer": "explorer",
    "calculator": "calc"
}

APP_PROCESS_NAMES = {
    "browser": "chrome.exe",
    "chrome": "chrome.exe",
    "notepad": "notepad.exe",
    "calculator": "CalculatorApp.exe"
}

FUZZY_THRESHOLD = 70
SCREENSHOT_DIR = "screenshots"

shortcut_index = None



def build_shortcut_index():
    global shortcut_index
    if shortcut_index is not None:
        return shortcut_index

    search_dirs = [
        os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%AppData%\Microsoft\Windows\Start Menu\Programs")
    ]

    index = {}
    for base in search_dirs:
        for path in glob.glob(f"{base}/**/*.lnk", recursive=True):
            name = os.path.splitext(os.path.basename(path))[0].lower()
            index[name] = path
    shortcut_index = index
    print(f"[commands] Indexed {len(index)} Start Menu shortcuts")
    return index


def find_installed_app(app_name):
    index = build_shortcut_index()
    if not index:
        return None
    best = process.extractOne(app_name, list(index.keys()), scorer=fuzz.WRatio)
    if best and best[1] >= FUZZY_THRESHOLD:
        return index[best[0]]
    return None


def open_app(args):
    if not args:
        return
    app_name = " ".join(args).lower()

    target = APP_PATHS.get(app_name)
    if target:
        os.startfile(target)
        print(f"[commands] Opened (registered): {app_name}")
        return

    shortcut = find_installed_app(app_name)
    if shortcut:
        os.startfile(shortcut)
        print(f"[commands] Opened (found on system): {os.path.basename(shortcut)}")
        return

    print(f"[commands] Could not find any app matching: '{app_name}'")


def find_running_process(app_name):
    names = {p.info["name"] for p in psutil.process_iter(["name"]) if p.info["name"]}
    if not names:
        return None
    candidates = {n.rsplit(".", 1)[0].lower(): n for n in names}  # strip .exe for matching
    best = process.extractOne(app_name, list(candidates.keys()), scorer=fuzz.WRatio)
    if best and best[1] >= FUZZY_THRESHOLD:
        return candidates[best[0]]
    return None


def close_app(args):
    if not args:
        return
    app_name = " ".join(args).lower()

    # Tier 1: registered process name
    process_name = APP_PROCESS_NAMES.get(app_name)

    # Tier 2: search currently running processes
    if not process_name:
        process_name = find_running_process(app_name)

    if not process_name:
        print(f"[commands] Could not find a running app matching: '{app_name}'")
        return

    os.system(f"taskkill /IM {process_name} /F >nul 2>&1")
    print(f"[commands] Closed: {process_name}")


def search(args):
    if not args:
        return
    query = " ".join(args)
    webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}")
    print(f"[commands] Searching: {query}")



def get_volume_interface():
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def mute(args):
    get_volume_interface().SetMute(1, None)
    print("[commands] Muted")


def unmute(args):
    get_volume_interface().SetMute(0, None)
    print("[commands] Unmuted")


def volume_up(args):
    import keyboard
    presses = int(args[0]) if args and args[0].isdigit() else 2
    for _ in range(presses):
        keyboard.send("volume up")
    print(f"[commands] Volume up x{presses}")


def volume_down(args):
    import keyboard
    presses = int(args[0]) if args and args[0].isdigit() else 2
    for _ in range(presses):
        keyboard.send("volume down")
    print(f"[commands] Volume down x{presses}")


def screenshot(args):
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    filename = f"{SCREENSHOT_DIR}/screenshot_{datetime.now():%Y%m%d_%H%M%S}.png"
    ImageGrab.grab().save(filename)
    print(f"[commands] Screenshot saved: {filename}")


COMMANDS = {
    "open": open_app,
    "close": close_app,
    "search": search,
    "mute": mute,
    "unmute": unmute,
    "volume up": volume_up,
    "volume down": volume_down,
    "screenshot": screenshot,
}