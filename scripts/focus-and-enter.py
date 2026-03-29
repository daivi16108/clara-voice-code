"""Вставить текст в Claude Code и нажать Enter.

Режимы:
  --activate-only    установить clipboard + активировать окно VS Code, вернуть управление
  --paste-only       только Ctrl+V + Enter (окно уже активно)
  --fast --text msg  старый режим (clipboard → activate → Ctrl+L → paste → enter)
  --no-focus         только PostMessage Enter
"""
import ctypes, time, os, sys, tempfile, subprocess

def log(msg):
    try:
        with open(os.path.join(tempfile.gettempdir(), "voice-claude-enter.log"), "a") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except: pass

user32 = ctypes.windll.user32

# --- Разбор аргументов ---
activate_only = "--activate-only" in sys.argv
paste_only    = "--paste-only" in sys.argv
fast_mode     = "--fast" in sys.argv
no_focus      = "--no-focus" in sys.argv
no_ctrl_l     = "--no-ctrl-l" in sys.argv
text = None
if "--text" in sys.argv:
    idx = sys.argv.index("--text")
    if idx + 1 < len(sys.argv):
        text = sys.argv[idx + 1]
target_hwnd = None
if "--target-hwnd" in sys.argv:
    idx = sys.argv.index("--target-hwnd")
    if idx + 1 < len(sys.argv):
        try:
            target_hwnd = int(sys.argv[idx + 1])
        except ValueError:
            pass
workspace = None
if "--workspace" in sys.argv:
    idx = sys.argv.index("--workspace")
    if idx + 1 < len(sys.argv):
        workspace = sys.argv[idx + 1]

# --- SendInput helper ---
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', ctypes.c_ushort), ('wScan', ctypes.c_ushort),
                 ('dwFlags', ctypes.c_ulong), ('time', ctypes.c_ulong),
                 ('dwExtraInfo', ctypes.POINTER(ctypes.c_ulong))]

class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [('ki', KEYBDINPUT)]
    _fields_ = [('type', ctypes.c_ulong), ('ii', _INPUT)]

def send_key_down(vk):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ii.ki.wVk = vk
    inp.ii.ki.dwFlags = 0
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

def send_key_up(vk):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ii.ki.wVk = vk
    inp.ii.ki.dwFlags = KEYEVENTF_KEYUP
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

def send_key(vk):
    send_key_down(vk)
    time.sleep(0.02)
    send_key_up(vk)

def send_hotkey(mod_vk, key_vk):
    send_key_down(mod_vk)
    time.sleep(0.01)
    send_key_down(key_vk)
    time.sleep(0.02)
    send_key_up(key_vk)
    time.sleep(0.01)
    send_key_up(mod_vk)

def activate_window(target_hwnd):
    """Активировать окно, вернуть предыдущее."""
    prev = user32.GetForegroundWindow()
    if prev == target_hwnd:
        return prev
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(target_hwnd)
    return prev

def restore_window(prev_hwnd, target_hwnd):
    """Вернуть фокус предыдущему окну."""
    if prev_hwnd and prev_hwnd != target_hwnd:
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetForegroundWindow(prev_hwnd)

def find_vscode_hwnd():
    """Найти окно VS Code: по target_hwnd, по workspace, или первое найденное."""
    if target_hwnd:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(target_hwnd, buf, 256)
        log(f"Using target hwnd {target_hwnd}: {buf.value!r}")
        return target_hwnd
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    windows = []
    def _enum(h, _):
        b = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(h, b, 256)
        if "Visual Studio Code" in b.value and user32.IsWindowVisible(h):
            windows.append((h, b.value))
        return True
    user32.EnumWindows(EnumWindowsProc(_enum), 0)
    if not windows:
        log("VS Code window not found")
        sys.exit(1)
    log(f"All VS Code windows: {[(h, t) for h,t in windows]}")
    if workspace:
        for h, title in windows:
            if workspace in title:
                log(f"Workspace match '{workspace}': {title!r}")
                return h
    log(f"No workspace match, using first: {windows[0][1]!r}")
    return windows[0][0]

VK_RETURN  = 0x0D
VK_CONTROL = 0x11

# === ACTIVATE-ONLY: clipboard + activate window, return ===
if activate_only:
    hwnd = find_vscode_hwnd()
    if text:
        escaped = text.replace("'", "''")
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", f"Set-Clipboard -Value '{escaped}'"],
            capture_output=True, timeout=3
        )
    activate_window(hwnd)
    time.sleep(0.05)
    log(f"activate-only done, hwnd={hwnd}")

# === PASTE-ONLY: click input area → Ctrl+V + Enter ===
elif paste_only:
    fg = user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(fg, buf, 256)
    log(f"paste-only: foreground is {fg} '{buf.value}'")

    # Click bottom-center of the window to focus Claude Code input area
    import ctypes.wintypes
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(fg, ctypes.byref(rect))
    # Claude Code input is at the bottom of the editor area
    # Approximate: center X, ~120px from bottom (chat input bar)
    click_x = (rect.left + rect.right) // 2
    click_y = rect.bottom - 120
    log(f"paste-only: clicking at ({click_x}, {click_y}), window rect=({rect.left},{rect.top},{rect.right},{rect.bottom})")

    # Save cursor position
    old_pos = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(old_pos))

    # Click to focus input
    user32.SetCursorPos(click_x, click_y)
    time.sleep(0.02)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
    time.sleep(0.15)  # wait for webview focus

    # Paste + Enter
    send_hotkey(VK_CONTROL, 0x56)  # Ctrl+V
    time.sleep(0.05)
    send_key(VK_RETURN)

    # Restore cursor
    user32.SetCursorPos(old_pos.x, old_pos.y)
    log("paste-only done")

# === FAST MODE (legacy): clipboard → activate → focus → paste → enter ===
elif fast_mode and text:
    hwnd = find_vscode_hwnd()
    escaped = text.replace("'", "''")
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", f"Set-Clipboard -Value '{escaped}'"],
        capture_output=True, timeout=3
    )
    prev_hwnd = activate_window(hwnd)
    time.sleep(0.08)
    if not no_ctrl_l:
        send_hotkey(VK_CONTROL, 0x4C)  # Ctrl+L
        time.sleep(0.05)
    send_hotkey(VK_CONTROL, 0x56)  # Ctrl+V
    time.sleep(0.05)
    send_key(VK_RETURN)
    time.sleep(0.03)
    restore_window(prev_hwnd, hwnd)
    log(f"fast mode done, hwnd={hwnd}")

# === NO-FOCUS MODE ===
elif no_focus:
    hwnd = find_vscode_hwnd()
    WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
    user32.PostMessageW(hwnd, WM_KEYDOWN, VK_RETURN, 0)
    time.sleep(0.05)
    user32.PostMessageW(hwnd, WM_KEYUP, VK_RETURN, 0)
    log("no-focus Enter sent")

# === LEGACY MODE ===
else:
    hwnd = find_vscode_hwnd()
    prev_hwnd = user32.GetForegroundWindow()
    if prev_hwnd != hwnd:
        activate_window(hwnd)
        time.sleep(0.5)
    else:
        time.sleep(1.0)
    WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
    user32.PostMessageW(hwnd, WM_KEYDOWN, VK_RETURN, 0)
    time.sleep(0.05)
    user32.PostMessageW(hwnd, WM_KEYUP, VK_RETURN, 0)
    log("legacy Enter sent")
    time.sleep(0.3)
    restore_window(prev_hwnd, hwnd)
