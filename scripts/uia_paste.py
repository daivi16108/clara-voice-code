"""UIA-based text insertion into Claude Code chat input.

Usage: python uia_paste.py --hwnd 396548 --text "hello"
       python uia_paste.py --active --text "hello"
"""
import ctypes, ctypes.wintypes, sys, time, subprocess, comtypes, comtypes.client

# --- Args ---
text = hwnd = None
if "--text" in sys.argv:
    i = sys.argv.index("--text")
    if i + 1 < len(sys.argv): text = sys.argv[i + 1]
if "--hwnd" in sys.argv:
    i = sys.argv.index("--hwnd")
    if i + 1 < len(sys.argv): hwnd = int(sys.argv[i + 1])
if "--active" in sys.argv:
    hwnd = ctypes.windll.user32.GetForegroundWindow()
if not text or not hwnd:
    print("Usage: uia_paste.py --hwnd <HWND> --text <text>"); sys.exit(1)

t0 = time.perf_counter()
user32 = ctypes.windll.user32

# --- UIA: find "Message input" ---
comtypes.CoInitialize()
tlb = comtypes.client.GetModule("UIAutomationCore.dll")
uia = comtypes.CoCreateInstance(tlb.CUIAutomation._reg_clsid_, interface=tlb.IUIAutomation)
root = uia.ElementFromHandle(hwnd)
cond = uia.CreateAndCondition(
    uia.CreatePropertyCondition(30003, 50004),  # ControlType=Edit
    uia.CreatePropertyCondition(30005, "Message input")  # Name
)
el = root.FindFirst(4, cond)  # TreeScope_Descendants
t_find = time.perf_counter() - t0

if not el:
    print(f"ERROR: 'Message input' not found ({t_find:.3f}s)"); sys.exit(1)

# --- Get element center coordinates ---
rect = el.CurrentBoundingRectangle
cx = (rect.left + rect.right) // 2
cy = (rect.top + rect.bottom) // 2
print(f"Found at ({cx}, {cy}), rect=({rect.left},{rect.top},{rect.right},{rect.bottom}) in {t_find:.3f}s")

# --- Set clipboard ---
escaped = text.replace("'", "''")
subprocess.run(["powershell.exe", "-NoProfile", "-Command", f"Set-Clipboard -Value '{escaped}'"],
               capture_output=True, timeout=3)

# --- Activate window ---
user32.keybd_event(0x12, 0, 0, 0)
user32.keybd_event(0x12, 0, 2, 0)
user32.SetForegroundWindow(hwnd)
time.sleep(0.05)

# --- Click on the input element to give it REAL focus ---
user32.SetCursorPos(cx, cy)
time.sleep(0.02)
user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
time.sleep(0.1)

# --- Ctrl+V + Enter ---
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

def send(vk, flags=0):
    inp = INPUT(); inp.type = INPUT_KEYBOARD; inp.ii.ki.wVk = vk; inp.ii.ki.dwFlags = flags
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

send(0x11); time.sleep(0.01)  # Ctrl down
send(0x56); time.sleep(0.02)  # V down
send(0x56, KEYEVENTF_KEYUP); time.sleep(0.01)  # V up
send(0x11, KEYEVENTF_KEYUP); time.sleep(0.05)  # Ctrl up
send(0x0D); time.sleep(0.02)  # Enter down
send(0x0D, KEYEVENTF_KEYUP)  # Enter up

t_total = time.perf_counter() - t0
print(f"OK: {t_total:.3f}s total")
