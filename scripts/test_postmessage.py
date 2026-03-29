"""
Test script: Send keyboard events via PostMessage/SendMessage to Chrome_RenderWidgetHostHWND
child window of VS Code, WITHOUT requiring the window to be foreground.

Tests three approaches:
  a) PostMessage WM_KEYDOWN/WM_KEYUP for Ctrl+V
  b) SendMessage WM_KEYDOWN/WM_KEYUP for Ctrl+V
  c) PostMessage WM_CHAR for each character

After each approach, reads the UIA "Message input" element to check if text appeared.
"""

import ctypes
import ctypes.wintypes as wintypes
import subprocess
import time
import sys

user32 = ctypes.windll.user32

# ── Windows API constants ──────────────────────────────────────────────────
WM_KEYDOWN = 0x0100
WM_KEYUP   = 0x0101
WM_CHAR    = 0x0102
VK_CONTROL = 0x11
VK_V       = 0x56
VK_RETURN  = 0x0D

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

VSCODE_HWND = 396548
TEST_TEXT = "[Voice] тест PostMessage"


# ── Helper functions ───────────────────────────────────────────────────────

def get_class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value

def get_window_text(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value

def is_visible(hwnd):
    return bool(user32.IsWindowVisible(wintypes.HWND(hwnd)))

def make_lparam(repeat_count, scan_code, extended, context, previous, transition):
    """Build lParam for WM_KEYDOWN/WM_KEYUP messages."""
    return (
        (repeat_count & 0xFFFF) |
        ((scan_code & 0xFF) << 16) |
        ((extended & 1) << 24) |
        ((context & 1) << 29) |
        ((previous & 1) << 30) |
        ((transition & 1) << 31)
    )

def set_clipboard(text):
    """Set clipboard via PowerShell."""
    escaped = text.replace("'", "''")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", f"Set-Clipboard -Value '{escaped}'"],
        capture_output=True, text=True, timeout=5
    )
    if result.returncode != 0:
        print(f"  [ERROR] Failed to set clipboard: {result.stderr}")
        return False
    # Verify
    verify = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard"],
        capture_output=True, text=True, timeout=5
    )
    print(f"  Clipboard set to: {verify.stdout.strip()!r}")
    return True


# ── UIA reader ─────────────────────────────────────────────────────────────

def read_message_input_value():
    """Use comtypes UIA to find 'Message input' element and read its value."""
    try:
        import comtypes
        from comtypes import client as cc
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA
    except Exception as e:
        print(f"  [UIA ERROR] comtypes setup failed: {e}")
        return None

    uia = comtypes.CoCreateInstance(
        UIA.CUIAutomation._reg_clsid_,
        interface=UIA.IUIAutomation,
        clsctx=comtypes.CLSCTX_INPROC_SERVER,
    )

    # Get VS Code element by HWND
    try:
        vscode_elem = uia.ElementFromHandle(VSCODE_HWND)
    except Exception as e:
        print(f"  [UIA ERROR] Cannot get element from HWND {VSCODE_HWND}: {e}")
        return None

    # Search for element with name containing "Message input" or "Message"
    # Try multiple strategies
    walker = uia.RawViewWalker
    found_elements = []

    def walk(element, depth=0, max_depth=20):
        if depth > max_depth or len(found_elements) > 5:
            return
        try:
            name = element.CurrentName or ""
            ct = element.CurrentControlType

            # Look for edit/document controls or anything named "Message"
            if ("message" in name.lower() or "input" in name.lower()) and ct in (50004, 50030, 50025):
                record = {
                    "name": name,
                    "control_type": ct,
                    "depth": depth,
                    "value": None,
                }
                # Try to read value
                try:
                    vp = element.GetCurrentPattern(10002)  # UIA_ValuePatternId
                    if vp:
                        ivp = vp.QueryInterface(UIA.IUIAutomationValuePattern)
                        record["value"] = ivp.CurrentValue or ""
                except:
                    pass
                found_elements.append(record)
        except:
            pass

        # Walk children
        try:
            child = walker.GetFirstChildElement(element)
            while child:
                walk(child, depth + 1, max_depth)
                try:
                    child = walker.GetNextSiblingElement(child)
                except:
                    break
        except:
            pass

    walk(vscode_elem)

    if found_elements:
        for elem in found_elements:
            print(f"    Found: name={elem['name']!r} type={elem['control_type']} value={elem['value']!r}")
        return found_elements
    else:
        print(f"    No 'Message input' element found in UIA tree")
        return []


# ── Find Chrome_RenderWidgetHostHWND ───────────────────────────────────────

def find_chrome_child(parent_hwnd):
    """Find all Chrome_RenderWidgetHostHWND children of the given window."""
    children = []

    def enum_callback(hwnd, _lparam):
        cls = get_class_name(hwnd)
        if cls == "Chrome_RenderWidgetHostHWND":
            vis = is_visible(hwnd)
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            children.append({
                "hwnd": hwnd,
                "class": cls,
                "visible": vis,
                "width": w,
                "height": h,
                "rect": (rect.left, rect.top, rect.right, rect.bottom),
            })
        return True

    user32.EnumChildWindows(
        wintypes.HWND(parent_hwnd),
        WNDENUMPROC(enum_callback),
        0
    )
    return children


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

def find_vscode_hwnd():
    """Find VS Code window HWND, falling back to search by title."""
    global VSCODE_HWND
    title = get_window_text(VSCODE_HWND)
    if title:
        return title

    print(f"\n[WARN] HWND {VSCODE_HWND} not found or has no title.")
    print("       VS Code may have been restarted (new HWND). Searching...")
    found = []
    def enum_top(hwnd, _):
        t = get_window_text(hwnd)
        if "clara-voice-code" in t.lower() or "visual studio code" in t.lower():
            found.append((hwnd, t))
        return True
    user32.EnumWindows(WNDENUMPROC(enum_top), 0)
    if found:
        print(f"  Found alternative windows:")
        for h, t in found:
            print(f"    HWND={h} (0x{h:X}): {t[:80]}")
        VSCODE_HWND = found[0][0]
        print(f"\n  Using HWND={VSCODE_HWND} (0x{VSCODE_HWND:X})")
        return found[0][1]
    else:
        print("  No VS Code window found at all. Exiting.")
        sys.exit(1)


def main():
    print("=" * 80)
    print("PostMessage / SendMessage Keyboard Test")
    print(f"Target VS Code HWND: {VSCODE_HWND} (0x{VSCODE_HWND:X})")
    print(f"Test text: {TEST_TEXT!r}")
    print("=" * 80)

    # Step 1: Verify VS Code window exists
    title = find_vscode_hwnd()

    print(f"\n[OK] VS Code window: {title[:80]}")
    print(f"     Visible: {is_visible(VSCODE_HWND)}")

    # Step 2: Find Chrome_RenderWidgetHostHWND child
    print(f"\n{'=' * 80}")
    print("STEP 1: Finding Chrome_RenderWidgetHostHWND child windows")
    print(f"{'=' * 80}")

    chrome_children = find_chrome_child(VSCODE_HWND)
    print(f"\nFound {len(chrome_children)} Chrome_RenderWidgetHostHWND windows:")
    for i, c in enumerate(chrome_children):
        print(f"  [{i}] HWND={c['hwnd']} (0x{c['hwnd']:X}) Visible={c['visible']} Size={c['width']}x{c['height']} Rect={c['rect']}")

    if not chrome_children:
        print("[ERROR] No Chrome_RenderWidgetHostHWND found!")
        sys.exit(1)

    # Pick the largest visible one (usually the main editor/webview)
    visible_children = [c for c in chrome_children if c["visible"]]
    if not visible_children:
        print("[WARN] No visible Chrome_RenderWidgetHostHWND, using first one")
        target_child = chrome_children[0]
    else:
        target_child = max(visible_children, key=lambda c: c["width"] * c["height"])

    target_hwnd = target_child["hwnd"]
    print(f"\n  Target child: HWND={target_hwnd} (0x{target_hwnd:X}) Size={target_child['width']}x{target_child['height']}")

    # Step 3: Read initial UIA state
    print(f"\n{'=' * 80}")
    print("STEP 2: Reading initial UIA state (Message input)")
    print(f"{'=' * 80}")
    initial_state = read_message_input_value()

    # ── Approach A: PostMessage Ctrl+V ─────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("APPROACH A: PostMessage WM_KEYDOWN/WM_KEYUP for Ctrl+V")
    print(f"{'=' * 80}")

    # Set clipboard first
    print("\n  Setting clipboard...")
    set_clipboard(TEST_TEXT)

    time.sleep(0.2)

    # Build proper lParam values
    # Ctrl key: scan code 0x1D
    ctrl_down_lparam = make_lparam(1, 0x1D, 0, 0, 0, 0)  # key down, no previous
    ctrl_up_lparam = make_lparam(1, 0x1D, 0, 0, 1, 1)     # key up, was down
    # V key: scan code 0x2F
    v_down_lparam = make_lparam(1, 0x2F, 0, 0, 0, 0)
    v_up_lparam = make_lparam(1, 0x2F, 0, 0, 1, 1)

    print(f"\n  Sending to HWND={target_hwnd} (0x{target_hwnd:X}):")
    print(f"    PostMessage WM_KEYDOWN VK_CONTROL (lParam=0x{ctrl_down_lparam:08X})")
    r1 = user32.PostMessageW(wintypes.HWND(target_hwnd), WM_KEYDOWN, VK_CONTROL, ctrl_down_lparam)
    print(f"      -> returned {r1}")

    time.sleep(0.01)

    print(f"    PostMessage WM_KEYDOWN VK_V (lParam=0x{v_down_lparam:08X})")
    r2 = user32.PostMessageW(wintypes.HWND(target_hwnd), WM_KEYDOWN, VK_V, v_down_lparam)
    print(f"      -> returned {r2}")

    time.sleep(0.03)

    print(f"    PostMessage WM_KEYUP VK_V (lParam=0x{v_up_lparam:08X})")
    r3 = user32.PostMessageW(wintypes.HWND(target_hwnd), WM_KEYUP, VK_V, v_up_lparam)
    print(f"      -> returned {r3}")

    time.sleep(0.01)

    print(f"    PostMessage WM_KEYUP VK_CONTROL (lParam=0x{ctrl_up_lparam:08X})")
    r4 = user32.PostMessageW(wintypes.HWND(target_hwnd), WM_KEYUP, VK_CONTROL, ctrl_up_lparam)
    print(f"      -> returned {r4}")

    time.sleep(0.5)  # Wait for processing

    print("\n  Reading UIA state after Approach A:")
    state_a = read_message_input_value()

    # ── Approach B: SendMessage Ctrl+V ─────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("APPROACH B: SendMessage WM_KEYDOWN/WM_KEYUP for Ctrl+V")
    print(f"{'=' * 80}")

    # Re-set clipboard (in case it was consumed)
    print("\n  Setting clipboard...")
    set_clipboard(TEST_TEXT)

    time.sleep(0.2)

    print(f"\n  Sending to HWND={target_hwnd} (0x{target_hwnd:X}):")
    print(f"    SendMessage WM_KEYDOWN VK_CONTROL")
    r1 = user32.SendMessageW(wintypes.HWND(target_hwnd), WM_KEYDOWN, VK_CONTROL, ctrl_down_lparam)
    print(f"      -> returned {r1}")

    time.sleep(0.01)

    print(f"    SendMessage WM_KEYDOWN VK_V")
    r2 = user32.SendMessageW(wintypes.HWND(target_hwnd), WM_KEYDOWN, VK_V, v_down_lparam)
    print(f"      -> returned {r2}")

    time.sleep(0.03)

    print(f"    SendMessage WM_KEYUP VK_V")
    r3 = user32.SendMessageW(wintypes.HWND(target_hwnd), WM_KEYUP, VK_V, v_up_lparam)
    print(f"      -> returned {r3}")

    time.sleep(0.01)

    print(f"    SendMessage WM_KEYUP VK_CONTROL")
    r4 = user32.SendMessageW(wintypes.HWND(target_hwnd), WM_KEYUP, VK_CONTROL, ctrl_up_lparam)
    print(f"      -> returned {r4}")

    time.sleep(0.5)

    print("\n  Reading UIA state after Approach B:")
    state_b = read_message_input_value()

    # ── Approach C: PostMessage WM_CHAR ────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("APPROACH C: PostMessage WM_CHAR for each character")
    print(f"{'=' * 80}")

    short_text = "test123"  # ASCII only for WM_CHAR test
    print(f"\n  Sending text: {short_text!r}")
    print(f"  Target: HWND={target_hwnd} (0x{target_hwnd:X})")

    for i, ch in enumerate(short_text):
        code = ord(ch)
        r = user32.PostMessageW(wintypes.HWND(target_hwnd), WM_CHAR, code, 0)
        status = "OK" if r else "FAIL"
        if i < 5 or i == len(short_text) - 1:
            print(f"    WM_CHAR '{ch}' (0x{code:04X}) -> {status}")
        elif i == 5:
            print(f"    ... ({len(short_text) - 5} more characters)")

    time.sleep(0.5)

    print("\n  Reading UIA state after Approach C:")
    state_c = read_message_input_value()

    # Also try WM_CHAR with Unicode characters
    print(f"\n  Now trying WM_CHAR with Unicode: {TEST_TEXT!r}")
    for i, ch in enumerate(TEST_TEXT):
        code = ord(ch)
        r = user32.PostMessageW(wintypes.HWND(target_hwnd), WM_CHAR, code, 0)
        status = "OK" if r else "FAIL"
        if i < 5 or i == len(TEST_TEXT) - 1:
            print(f"    WM_CHAR '{ch}' (0x{code:04X}) -> {status}")
        elif i == 5:
            print(f"    ... ({len(TEST_TEXT) - 5} more characters)")

    time.sleep(0.5)

    print("\n  Reading UIA state after Unicode WM_CHAR:")
    state_c2 = read_message_input_value()

    # ── Summary ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}")

    print(f"""
  Target VS Code HWND:  {VSCODE_HWND} (0x{VSCODE_HWND:X})
  Chrome child HWND:    {target_hwnd} (0x{target_hwnd:X})
  Chrome child visible: {target_child['visible']}
  Chrome child size:    {target_child['width']}x{target_child['height']}

  Approach A (PostMessage Ctrl+V):
    All PostMessage calls returned non-zero: {all([r1, r2, r3, r4])}
    UIA state changed: {state_a != initial_state}

  Approach B (SendMessage Ctrl+V):
    UIA state changed: {state_b != state_a}

  Approach C (WM_CHAR):
    UIA state changed: {state_c != state_b or state_c2 != state_c}

  NOTES:
  - PostMessage/SendMessage to Chromium renderer windows typically does NOT
    work for keyboard shortcuts like Ctrl+V because Chromium uses its own
    input pipeline (IPC to the renderer process via Mojo, not Win32 messages).
  - WM_CHAR may work for simple character input in some Electron configurations
    but Chromium generally ignores WM_CHAR from external sources.
  - The most reliable background input methods for Chromium-based apps are:
    1. Chrome DevTools Protocol (CDP) via --remote-debugging-port
    2. UI Automation SetValue pattern (if accessibility is enabled)
    3. Brief focus steal + SendInput (current approach in focus-and-enter.py)
""")


if __name__ == "__main__":
    main()
