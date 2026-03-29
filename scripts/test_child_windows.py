"""
Test script: Enumerate child windows of VS Code to find Chromium renderer HWNDs.
Goal: Find the Claude Code webview's child window for text injection.
"""

import ctypes
import ctypes.wintypes as wintypes
from collections import defaultdict

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Windows API constants
WM_PASTE = 0x0302
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
GWL_STYLE = -16
WS_VISIBLE = 0x10000000

# Callback type for EnumWindows/EnumChildWindows
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

def get_window_text(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value

def get_class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value

def is_visible(hwnd):
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    return bool(style & WS_VISIBLE)

def get_window_rect(hwnd):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)

def get_window_pid(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


# ── Step 1: Find all VS Code top-level windows ──────────────────────────

print("=" * 80)
print("STEP 1: Finding VS Code top-level windows")
print("=" * 80)

vscode_windows = []

def enum_top_windows(hwnd, _lparam):
    title = get_window_text(hwnd)
    if "Visual Studio Code" in title:
        cls = get_class_name(hwnd)
        pid = get_window_pid(hwnd)
        vis = is_visible(hwnd)
        rect = get_window_rect(hwnd)
        vscode_windows.append({
            "hwnd": hwnd,
            "title": title,
            "class": cls,
            "pid": pid,
            "visible": vis,
            "rect": rect,
        })
    return True

user32.EnumWindows(WNDENUMPROC(enum_top_windows), 0)

for i, w in enumerate(vscode_windows):
    marker = " <<<< TARGET" if "clara-voice-code" in w["title"] else ""
    print(f"\n  [{i}] HWND={w['hwnd']} (0x{w['hwnd']:X})")
    print(f"      Class: {w['class']}")
    print(f"      Title: {w['title'][:100]}")
    print(f"      PID: {w['pid']}  Visible: {w['visible']}  Rect: {w['rect']}{marker}")

print(f"\nTotal VS Code windows: {len(vscode_windows)}")


# ── Step 2: Pick target window (clara-voice-code or fallback) ───────────

target = None
# Try specific HWND first
for w in vscode_windows:
    if w["hwnd"] == 396548:
        target = w
        break
# Fallback: look for clara-voice-code in title
if not target:
    for w in vscode_windows:
        if "clara-voice-code" in w["title"]:
            target = w
            break
# Fallback: first visible
if not target and vscode_windows:
    for w in vscode_windows:
        if w["visible"]:
            target = w
            break

if not target:
    print("\nERROR: No VS Code window found!")
    exit(1)

print(f"\n{'=' * 80}")
print(f"STEP 2: Enumerating child windows of HWND={target['hwnd']} (0x{target['hwnd']:X})")
print(f"        Title: {target['title'][:80]}")
print(f"{'=' * 80}")


# ── Step 3: Enumerate ALL child windows recursively ─────────────────────

child_windows = []

def enum_child_windows(hwnd, _lparam):
    cls = get_class_name(hwnd)
    title = get_window_text(hwnd)
    vis = is_visible(hwnd)
    rect = get_window_rect(hwnd)
    w = rect[2] - rect[0]
    h = rect[3] - rect[1]
    child_windows.append({
        "hwnd": hwnd,
        "class": cls,
        "title": title[:120] if title else "",
        "visible": vis,
        "rect": rect,
        "width": w,
        "height": h,
    })
    return True

user32.EnumChildWindows(
    wintypes.HWND(target["hwnd"]),
    WNDENUMPROC(enum_child_windows),
    0
)

print(f"\nTotal child windows: {len(child_windows)}")

# Group by class name
class_counts = defaultdict(int)
for c in child_windows:
    class_counts[c["class"]] += 1

print(f"\nChild window classes (sorted by count):")
for cls, count in sorted(class_counts.items(), key=lambda x: -x[1]):
    print(f"  {cls}: {count}")


# ── Step 4: Identify interesting windows ────────────────────────────────

INTERESTING_CLASSES = [
    "Chrome_RenderWidgetHostHWND",
    "Intermediate D3D Window",
    "Edit",
    "RichEdit",
    "RichEdit20W",
    "RichEdit20A",
    "RICHEDIT50W",
    "Scintilla",
    "Chrome_WidgetWin_1",
    "Chrome_WidgetWin_0",
]

print(f"\n{'=' * 80}")
print("STEP 3: Interesting child windows (Chromium renderers, edit controls, etc.)")
print(f"{'=' * 80}")

interesting = []
for c in child_windows:
    is_interesting = False
    for icls in INTERESTING_CLASSES:
        if icls.lower() in c["class"].lower():
            is_interesting = True
            break
    # Also flag any with "edit" or "input" in class name
    if "edit" in c["class"].lower() or "input" in c["class"].lower():
        is_interesting = True
    if is_interesting:
        interesting.append(c)

for c in interesting:
    print(f"\n  HWND={c['hwnd']} (0x{c['hwnd']:X})")
    print(f"    Class: {c['class']}")
    print(f"    Title: {c['title'][:100] if c['title'] else '(none)'}")
    print(f"    Visible: {c['visible']}  Size: {c['width']}x{c['height']}  Rect: {c['rect']}")

if not interesting:
    print("  (none found)")


# ── Step 5: Deep dive on Chrome_RenderWidgetHostHWND ────────────────────

print(f"\n{'=' * 80}")
print("STEP 4: Chrome_RenderWidgetHostHWND details")
print(f"{'=' * 80}")

chrome_renderers = [c for c in child_windows if c["class"] == "Chrome_RenderWidgetHostHWND"]
print(f"\nFound {len(chrome_renderers)} Chrome_RenderWidgetHostHWND windows:")

for i, c in enumerate(chrome_renderers):
    print(f"\n  [{i}] HWND={c['hwnd']} (0x{c['hwnd']:X})")
    print(f"      Visible: {c['visible']}  Size: {c['width']}x{c['height']}")
    print(f"      Rect: {c['rect']}")
    print(f"      Title: '{c['title']}'")

    # Try to get the parent chain
    parent = user32.GetParent(wintypes.HWND(c["hwnd"]))
    if parent:
        parent_cls = get_class_name(parent)
        parent_title = get_window_text(parent)
        print(f"      Parent: HWND={parent} (0x{parent:X}) Class={parent_cls} Title='{parent_title[:60]}'")
        grandparent = user32.GetParent(wintypes.HWND(parent))
        if grandparent:
            gp_cls = get_class_name(grandparent)
            gp_title = get_window_text(grandparent)
            print(f"      Grandparent: HWND={grandparent} (0x{grandparent:X}) Class={gp_cls} Title='{gp_title[:60]}'")


# ── Step 6: Also look for Intermediate D3D Window ───────────────────────

print(f"\n{'=' * 80}")
print("STEP 5: Intermediate D3D Window details")
print(f"{'=' * 80}")

d3d_windows = [c for c in child_windows if "Intermediate D3D" in c["class"]]
print(f"\nFound {len(d3d_windows)} Intermediate D3D windows:")
for i, c in enumerate(d3d_windows):
    print(f"  [{i}] HWND={c['hwnd']} (0x{c['hwnd']:X}) Visible={c['visible']} Size={c['width']}x{c['height']}")


# ── Step 7: Test WM_PASTE on Chrome_RenderWidgetHostHWND ────────────────

print(f"\n{'=' * 80}")
print("STEP 6: Testing WM_PASTE on Chrome_RenderWidgetHostHWND windows")
print("        (clipboard should contain test text before running)")
print(f"{'=' * 80}")

# Put test text on clipboard
import subprocess
test_text = "[test_child_windows probe]"
# Use PowerShell to set clipboard
subprocess.run(
    ["powershell", "-Command", f"Set-Clipboard -Value '{test_text}'"],
    capture_output=True
)
print(f"\nClipboard set to: {test_text}")

for i, c in enumerate(chrome_renderers):
    if not c["visible"]:
        print(f"\n  [{i}] HWND={c['hwnd']} — SKIPPED (not visible)")
        continue

    print(f"\n  [{i}] HWND={c['hwnd']} (0x{c['hwnd']:X}) — Sending WM_PASTE...")
    result = user32.SendMessageW(
        wintypes.HWND(c["hwnd"]),
        WM_PASTE,
        0,
        0
    )
    print(f"      SendMessage returned: {result}")

    # Also try PostMessage (async)
    result2 = user32.PostMessageW(
        wintypes.HWND(c["hwnd"]),
        WM_PASTE,
        0,
        0
    )
    print(f"      PostMessage returned: {result2}")


# ── Step 8: Try WM_SETTEXT on all interesting windows ──────────────────

print(f"\n{'=' * 80}")
print("STEP 7: Testing WM_SETTEXT on interesting windows")
print(f"{'=' * 80}")

for c in interesting:
    if not c["visible"]:
        continue
    result = user32.SendMessageW(
        wintypes.HWND(c["hwnd"]),
        WM_SETTEXT,
        0,
        test_text
    )
    print(f"  HWND={c['hwnd']} Class={c['class'][:40]} — WM_SETTEXT returned: {result}")


# ── Step 9: Full child window dump (first 50) ──────────────────────────

print(f"\n{'=' * 80}")
print(f"STEP 8: Full child window dump (all {len(child_windows)} windows)")
print(f"{'=' * 80}")

# Show all, grouped by visibility
visible_children = [c for c in child_windows if c["visible"]]
hidden_children = [c for c in child_windows if not c["visible"]]

print(f"\n--- Visible children: {len(visible_children)} ---")
for c in visible_children:
    title_part = f" Title='{c['title'][:50]}'" if c['title'] else ""
    print(f"  HWND=0x{c['hwnd']:X} Class={c['class']:<45s} {c['width']:>5}x{c['height']:<5}{title_part}")

print(f"\n--- Hidden children: {len(hidden_children)} ---")
for c in hidden_children[:30]:
    title_part = f" Title='{c['title'][:50]}'" if c['title'] else ""
    print(f"  HWND=0x{c['hwnd']:X} Class={c['class']:<45s} {c['width']:>5}x{c['height']:<5}{title_part}")
if len(hidden_children) > 30:
    print(f"  ... and {len(hidden_children) - 30} more hidden windows")


print(f"\n{'=' * 80}")
print("DONE")
print(f"{'=' * 80}")
