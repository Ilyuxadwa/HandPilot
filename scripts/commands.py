import os
import glob
import shutil
import ctypes
import ctypes.wintypes
import winreg
import psutil
import webbrowser
from PIL import ImageGrab
from comtypes import CLSCTX_ALL
from datetime import datetime
from ctypes import cast, POINTER
from urllib.parse import quote_plus
from rapidfuzz import fuzz, process
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

APP_ALIASES = {
    "browser": "chrome",
}

FUZZY_THRESHOLD = 70
SCREENSHOT_DIR = "screenshots"

COMMON_FOLDERS = {
    "downloads": "Downloads",
    "documents": "Documents",
    "desktop": "Desktop",
    "pictures": "Pictures",
    "music": "Music",
    "videos": "Videos",
}

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


def find_executable(app_name):
    return shutil.which(app_name) or shutil.which(f"{app_name}.exe")


def open_app(args):
    if not args:
        return
    app_name = " ".join(args).lower()
    resolved_name = APP_ALIASES.get(app_name, app_name)

    exe_path = find_executable(resolved_name)
    if exe_path:
        os.startfile(exe_path)
        print(f"[commands] Opened (on PATH): {resolved_name}")
        return

    shortcut = find_installed_app(resolved_name)
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


def set_volume(args):
    if not args or not args[0].isdigit():
        print("[commands] set_volume needs a number 0-100")
        return
    percent = max(0, min(100, int(args[0])))
    get_volume_interface().SetMasterVolumeLevelScalar(percent / 100.0, None)
    print(f"[commands] Volume set to {percent}%")


def media_play_pause(args):
    import keyboard
    keyboard.send("play/pause media")
    print("[commands] Media play/pause")


def media_next(args):
    import keyboard
    keyboard.send("next track")
    print("[commands] Media next track")


def media_previous(args):
    import keyboard
    keyboard.send("previous track")
    print("[commands] Media previous track")


def screenshot(args):
    mode = args[0].lower() if args else "full"
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    filename = f"{SCREENSHOT_DIR}/screenshot_{datetime.now():%Y%m%d_%H%M%S}.png"

    if mode == "window":
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        bbox = (rect.left, rect.top, rect.right, rect.bottom)
        ImageGrab.grab(bbox=bbox).save(filename)
    else:
        if mode != "full":
            print(f"[commands] Unknown screenshot mode '{mode}', defaulting to full")
        ImageGrab.grab().save(filename)

    print(f"[commands] Screenshot ({mode if mode in ('full', 'window') else 'full'}) saved: {filename}")


def switch_mode(args):
    if not args or args[0].lower() not in ("light", "dark"):
        print("[commands] switch mode needs 'light' or 'dark'")
        return

    mode = args[0].lower()
    value = 1 if mode == "light" else 0
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, value)
            winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, value)
    except OSError as e:
        print(f"[commands] Failed to switch mode: {e}")
        return

    # Broadcast the setting change so already-open apps (Explorer, taskbar)
    # pick it up without a manual restart/relog.
    HWND_BROADCAST = 0xFFFF
    WM_SETTINGCHANGE = 0x001A
    SMTO_ABORTIFHUNG = 0x0002
    ctypes.windll.user32.SendMessageTimeoutW(
        HWND_BROADCAST, WM_SETTINGCHANGE, 0, "ImmersiveColorSet",
        SMTO_ABORTIFHUNG, 100, None
    )
    print(f"[commands] Switched to {mode} mode")


def create_folder(args):
    if not args:
        print("[commands] create folder needs a name")
        return
    name = " ".join(args)
    path = name if os.path.isabs(name) else os.path.join(os.path.expanduser("~"), "Desktop", name)
    os.makedirs(path, exist_ok=True)
    print(f"[commands] Created folder: {path}")


def create_file(args):
    if not args:
        print("[commands] create file needs a name")
        return
    name = " ".join(args)
    path = name if os.path.isabs(name) else os.path.join(os.path.expanduser("~"), "Desktop", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "a").close()
    print(f"[commands] Created file: {path}")


def open_folder(args):
    if not args:
        print("[commands] open folder needs a name or path")
        return
    name = " ".join(args)
    if os.path.isabs(name) or os.path.exists(name):
        path = name
    else:
        folder = COMMON_FOLDERS.get(name.lower())
        path = os.path.join(os.path.expanduser("~"), folder) if folder else os.path.join(os.path.expanduser("~"), "Desktop", name)

    if not os.path.exists(path):
        print(f"[commands] Folder not found: {path}")
        return
    os.startfile(path)
    print(f"[commands] Opened folder: {path}")


def snap_left(args):
    import keyboard
    keyboard.send("windows+left")
    print("[commands] Snapped active window left")


def snap_right(args):
    import keyboard
    keyboard.send("windows+right")
    print("[commands] Snapped active window right")


def mic_mute(args):
    try:
        mic = AudioUtilities.GetMicrophone()
        interface = mic.EndpointVolume
        interface.SetMute(1, None)
        print("[commands] Microphone muted")
    except AttributeError:
        print("[commands] Microphone control not supported by this pycaw version")


def mic_unmute(args):
    try:
        mic = AudioUtilities.GetMicrophone()
        interface = mic.EndpointVolume
        interface.SetMute(0, None)
        print("[commands] Microphone unmuted")
    except AttributeError:
        print("[commands] Microphone control not supported by this pycaw version")


def type_text(args):
    if not args:
        return
    import keyboard
    text = " ".join(args)
    keyboard.write(text)
    print(f"[commands] Typed: {text}")


def lock_pc(args):
    ctypes.windll.user32.LockWorkStation()
    print("[commands] Locked workstation")


def sleep_pc(args):
    os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
    print("[commands] Sleeping")


def shutdown_pc(args):
    # 15s delay so a misheard command can be caught with "cancel shutdown"
    os.system("shutdown /s /t 15")
    print("[commands] Shutdown scheduled in 15s (say 'cancel shutdown' to abort)")


def restart_pc(args):
    os.system("shutdown /r /t 15")
    print("[commands] Restart scheduled in 15s (say 'cancel shutdown' to abort)")


def cancel_shutdown(args):
    os.system("shutdown /a")
    print("[commands] Cancelled pending shutdown/restart")


def show_desktop(args):
    import keyboard
    keyboard.send("windows+d")
    print("[commands] Toggled show desktop")


def close_active_window(args):
    WM_CLOSE = 0x0010
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    print("[commands] Closed active window")


def empty_recycle_bin(args):
    SHERB_NOCONFIRMATION = 0x00000001
    SHERB_NOPROGRESSUI = 0x00000002
    SHERB_NOSOUND = 0x00000004
    ctypes.windll.shell32.SHEmptyRecycleBinW(
        None, None,
        SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
    )
    print("[commands] Emptied recycle bin")


COMMANDS = {
    "open": open_app,
    "close": close_app,
    "search": search,
    "mute": mute,
    "unmute": unmute,
    "volume up": volume_up,
    "volume down": volume_down,
    "set volume": set_volume,
    "screenshot": screenshot,
    "media play pause": media_play_pause,
    "media next": media_next,
    "media previous": media_previous,
    "lock": lock_pc,
    "sleep": sleep_pc,
    "shutdown": shutdown_pc,
    "restart": restart_pc,
    "cancel shutdown": cancel_shutdown,
    "show desktop": show_desktop,
    "close active window": close_active_window,
    "empty recycle bin": empty_recycle_bin,
    "switch mode to": switch_mode,
    "create folder": create_folder,
    "create file": create_file,
    "open folder": open_folder,
    "snap left": snap_left,
    "snap right": snap_right,
    "mic mute": mic_mute,
    "mic unmute": mic_unmute,
    "type text": type_text,
}