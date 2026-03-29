"""Diagnostic: find all Claude Code chat inputs across all VS Code windows.

Reports:
- Element location, size, bounding rect
- All available UIA patterns
- Test SetValue, LegacySetValue, TextPattern insert
- Does NOT steal focus, click, or send keys
"""
import ctypes, ctypes.wintypes, sys, json, time, comtypes, comtypes.client

comtypes.CoInitialize()
tlb = comtypes.client.GetModule("UIAutomationCore.dll")
uia = comtypes.CoCreateInstance(tlb.CUIAutomation._reg_clsid_, interface=tlb.IUIAutomation)
user32 = ctypes.windll.user32

# --- Pattern IDs and names ---
PATTERNS = {
    10002: ("ValuePattern", tlb.IUIAutomationValuePattern),
    10003: ("RangeValuePattern", None),
    10005: ("TextPattern", None),
    10006: ("TogglePattern", None),
    10009: ("ScrollPattern", None),
    10010: ("SelectionPattern", None),
    10012: ("GridPattern", None),
    10013: ("DockPattern", None),
    10015: ("InvokePattern", tlb.IUIAutomationInvokePattern),
    10018: ("LegacyIAccessiblePattern", tlb.IUIAutomationLegacyIAccessiblePattern),
    10024: ("TextPattern2", None),
    10029: ("TextEditPattern", None),
}

# --- Find all VS Code windows ---
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
vscode_windows = []

def enum_cb(hwnd, _):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    if "Visual Studio Code" in buf.value and user32.IsWindowVisible(hwnd):
        vscode_windows.append((hwnd, buf.value))
    return True

user32.EnumWindows(EnumWindowsProc(enum_cb), 0)

print(f"=== Found {len(vscode_windows)} VS Code windows ===\n")

results = []

for win_hwnd, win_title in vscode_windows:
    print(f"--- Window: {win_hwnd} ---")
    print(f"    Title: {win_title[:80]}")

    t0 = time.perf_counter()
    root = uia.ElementFromHandle(win_hwnd)
    cond = uia.CreateAndCondition(
        uia.CreatePropertyCondition(30003, 50004),   # ControlType=Edit
        uia.CreatePropertyCondition(30005, "Message input")  # Name
    )
    el = root.FindFirst(4, cond)  # TreeScope_Descendants
    t_find = time.perf_counter() - t0

    if not el:
        print(f"    'Message input' NOT FOUND ({t_find:.3f}s)")
        results.append({"hwnd": win_hwnd, "title": win_title, "found": False, "search_time": t_find})
        print()
        continue

    # --- Element properties ---
    rect = el.CurrentBoundingRectangle
    class_name = el.CurrentClassName
    auto_id = el.CurrentAutomationId
    is_enabled = el.CurrentIsEnabled
    is_offscreen = el.CurrentIsOffscreen

    info = {
        "hwnd": win_hwnd,
        "title": win_title,
        "found": True,
        "search_time": round(t_find, 3),
        "class": class_name,
        "automation_id": auto_id,
        "enabled": bool(is_enabled),
        "offscreen": bool(is_offscreen),
        "rect": {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom},
        "size": {"w": rect.right - rect.left, "h": rect.bottom - rect.top},
        "center": {"x": (rect.left + rect.right) // 2, "y": (rect.top + rect.bottom) // 2},
        "patterns": {},
    }

    print(f"    FOUND in {t_find:.3f}s")
    print(f"    Class: {class_name}")
    print(f"    AutomationId: {auto_id}")
    print(f"    Enabled: {is_enabled}, Offscreen: {is_offscreen}")
    print(f"    Rect: ({rect.left},{rect.top})-({rect.right},{rect.bottom})  Size: {rect.right-rect.left}x{rect.bottom-rect.top}")

    # --- Check all patterns ---
    print(f"    Patterns:")
    for pat_id, (pat_name, pat_iface) in PATTERNS.items():
        try:
            raw = el.GetCurrentPattern(pat_id)
            if raw:
                info["patterns"][pat_name] = {"available": True}
                detail = ""

                if pat_iface:
                    obj = raw.QueryInterface(pat_iface)

                    if pat_name == "ValuePattern":
                        val = obj.CurrentValue
                        ro = obj.CurrentIsReadOnly
                        info["patterns"][pat_name]["value"] = val
                        info["patterns"][pat_name]["readonly"] = bool(ro)
                        detail = f"value={val!r}, readonly={ro}"

                    elif pat_name == "LegacyIAccessiblePattern":
                        try:
                            lval = obj.CurrentValue
                            lname = obj.CurrentName
                            lrole = obj.CurrentRole
                            info["patterns"][pat_name]["value"] = lval
                            info["patterns"][pat_name]["name"] = lname
                            info["patterns"][pat_name]["role"] = lrole
                            detail = f"value={lval!r}, name={lname!r}, role={lrole}"
                        except Exception as e:
                            detail = f"query failed: {e}"

                    elif pat_name == "InvokePattern":
                        detail = "invokable"

                print(f"      ✓ {pat_name}: {detail}")
            else:
                info["patterns"][pat_name] = {"available": False}
        except Exception:
            info["patterns"][pat_name] = {"available": False}

    # --- Test SetValue (non-destructive: write, read back, restore) ---
    print(f"    SetValue test:")
    if "ValuePattern" in info["patterns"] and info["patterns"]["ValuePattern"].get("available"):
        try:
            raw = el.GetCurrentPattern(10002)
            vp = raw.QueryInterface(tlb.IUIAutomationValuePattern)
            original = vp.CurrentValue
            test_text = "__UIA_DIAG_TEST__"
            vp.SetValue(test_text)
            time.sleep(0.05)
            readback = vp.CurrentValue
            vp.SetValue(original)  # restore
            success = readback == test_text
            info["setvalue_test"] = {"success": success, "wrote": test_text, "readback": readback}
            print(f"      Write '{test_text}' → readback='{readback}' → {'OK' if success else 'MISMATCH'}")
        except Exception as e:
            info["setvalue_test"] = {"success": False, "error": str(e)}
            print(f"      FAILED: {e}")
    else:
        print(f"      SKIPPED (no ValuePattern)")

    # --- Test LegacyIAccessible SetValue ---
    print(f"    LegacySetValue test:")
    if "LegacyIAccessiblePattern" in info["patterns"] and info["patterns"]["LegacyIAccessiblePattern"].get("available"):
        try:
            raw = el.GetCurrentPattern(10018)
            lap = raw.QueryInterface(tlb.IUIAutomationLegacyIAccessiblePattern)
            test_text = "__LEGACY_DIAG_TEST__"
            lap.SetValue(test_text)
            time.sleep(0.05)
            # Read back via ValuePattern
            raw2 = el.GetCurrentPattern(10002)
            vp2 = raw2.QueryInterface(tlb.IUIAutomationValuePattern)
            readback = vp2.CurrentValue
            vp2.SetValue("")  # restore
            success = readback == test_text
            info["legacy_setvalue_test"] = {"success": success, "wrote": test_text, "readback": readback}
            print(f"      Write '{test_text}' → readback='{readback}' → {'OK' if success else 'MISMATCH'}")
        except Exception as e:
            info["legacy_setvalue_test"] = {"success": False, "error": str(e)}
            print(f"      FAILED: {e}")
    else:
        print(f"      SKIPPED (no LegacyIAccessiblePattern)")

    # --- Look for a Submit button nearby ---
    print(f"    Submit button search:")
    try:
        cond_btn = uia.CreatePropertyCondition(30003, 50000)  # ControlType=Button
        all_btns = root.FindAll(4, cond_btn)
        submit_found = False
        for i in range(all_btns.Length):
            btn = all_btns.GetElement(i)
            btn_name = btn.CurrentName
            if btn_name and ("send" in btn_name.lower() or "submit" in btn_name.lower() or "отправ" in btn_name.lower()):
                btn_rect = btn.CurrentBoundingRectangle
                print(f"      ✓ Button: '{btn_name}' at ({btn_rect.left},{btn_rect.top})-({btn_rect.right},{btn_rect.bottom})")
                submit_found = True
                info["submit_button"] = {"name": btn_name, "rect": {"left": btn_rect.left, "top": btn_rect.top, "right": btn_rect.right, "bottom": btn_rect.bottom}}
        if not submit_found:
            print(f"      No send/submit button found among {all_btns.Length} buttons")
            info["submit_button"] = None
    except Exception as e:
        print(f"      Search failed: {e}")

    results.append(info)
    print()

# --- Save full results to JSON ---
out_path = "D:\\Code\\clara-voice-code\\scripts\\uia_diagnose_results.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"Full results saved to {out_path}")
