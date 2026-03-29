"""
Test script: Enumerate UI Automation tree of VS Code to find text input controls.
Goal: Find the Claude Code chat input inside a webview panel.

Approach:
1. Direct comtypes UIA with TreeWalker (more thorough than FindAll)
2. pywinauto with 'uia' backend
3. Check for Chromium accessibility flag
4. Try RawViewWalker which sees everything including off-screen elements
"""

import sys
import os
import json
import ctypes
import ctypes.wintypes
from datetime import datetime

# ============================================================
# PART 1: Check Chromium accessibility flag
# ============================================================

def check_chromium_accessibility():
    """Check if VS Code was launched with --force-renderer-accessibility."""
    import subprocess
    print("\n" + "=" * 70)
    print("PART 1: Checking Chromium accessibility flags")
    print("=" * 70)

    # Check running VS Code process command line
    try:
        result = subprocess.run(
            ["wmic", "process", "where", "name='Code.exe'", "get", "CommandLine", "/format:list"],
            capture_output=True, text=True, timeout=10
        )
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        # Just show first process
        for line in lines[:5]:
            print(f"  {line}")

        has_flag = "--force-renderer-accessibility" in result.stdout
        print(f"\n  --force-renderer-accessibility present: {has_flag}")

        if not has_flag:
            print("\n  [!] IMPORTANT: Without --force-renderer-accessibility,")
            print("      Chromium does NOT expose web content to UI Automation.")
            print("      The entire renderer is a single opaque pane.")
            print()
            print("      To enable, add to VS Code argv.json or shortcut:")
            print('        code --force-renderer-accessibility')
            print("      Or set in VS Code settings:")
            print('        "editor.accessibilitySupport": "on"')

        return has_flag
    except Exception as e:
        print(f"  [WARN] Could not check: {e}")
        return None


# ============================================================
# PART 2: comtypes UIA with RawViewWalker (sees everything)
# ============================================================

def run_comtypes_deep_scan():
    print("\n" + "=" * 70)
    print("PART 2: Deep UIA scan with RawViewWalker")
    print("=" * 70)

    try:
        import comtypes
        from comtypes import client as cc
        # Force regeneration
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA
    except Exception as e:
        print(f"  [ERROR] comtypes setup failed: {e}")
        return []

    CONTROL_TYPE_NAMES = {
        50000: "Button", 50001: "Calendar", 50002: "CheckBox",
        50003: "ComboBox", 50004: "Edit", 50005: "Hyperlink",
        50006: "Image", 50007: "ListItem", 50008: "List",
        50009: "Menu", 50010: "MenuBar", 50011: "MenuItem",
        50012: "ProgressBar", 50013: "RadioButton", 50014: "ScrollBar",
        50015: "Slider", 50016: "Spinner", 50017: "StatusBar",
        50018: "Tab", 50019: "TabItem", 50020: "Text",
        50021: "ToolBar", 50022: "ToolTip", 50023: "Tree",
        50024: "TreeItem", 50025: "Custom", 50026: "Group",
        50027: "Thumb", 50028: "DataGrid", 50029: "DataItem",
        50030: "Document", 50031: "SplitButton", 50032: "Window",
        50033: "Pane", 50034: "Header", 50035: "HeaderItem",
        50036: "Table", 50037: "TitleBar", 50038: "Separator",
    }

    uia = comtypes.CoCreateInstance(
        UIA.CUIAutomation._reg_clsid_,
        interface=UIA.IUIAutomation,
        clsctx=comtypes.CLSCTX_INPROC_SERVER,
    )

    # Find VS Code window
    root = uia.GetRootElement()
    condition = uia.CreatePropertyCondition(
        UIA.UIA_ControlTypePropertyId, 50032  # Window
    )
    children = root.FindAll(UIA.TreeScope_Children, condition)
    vscode = None
    for i in range(children.Length):
        child = children.GetElement(i)
        name = child.CurrentName or ""
        if "Visual Studio Code" in name:
            vscode = child
            print(f"  [OK] Found: {name}")
            break

    if not vscode:
        # Try HWND
        try:
            vscode = uia.ElementFromHandle(396548)
            print(f"  [OK] Found by HWND: {vscode.CurrentName}")
        except:
            print("  [ERROR] VS Code not found")
            return []

    # Use RawViewWalker to traverse everything
    walker = uia.RawViewWalker
    results = []
    count = [0]

    def walk_raw(element, depth=0, max_depth=25):
        if depth > max_depth:
            return
        count[0] += 1
        if count[0] > 5000:  # Safety limit
            return

        try:
            name = element.CurrentName or ""
            ct = element.CurrentControlType
            ct_name = CONTROL_TYPE_NAMES.get(ct, f"Unknown({ct})")
            auto_id = element.CurrentAutomationId or ""
            class_name = element.CurrentClassName or ""

            record = {
                "depth": depth,
                "name": name[:150],
                "control_type": ct_name,
                "control_type_id": ct,
                "automation_id": auto_id[:150],
                "class_name": class_name,
            }

            # Check Value pattern
            try:
                vp = element.GetCurrentPattern(10002)  # UIA_ValuePatternId
                if vp:
                    ivp = vp.QueryInterface(UIA.IUIAutomationValuePattern)
                    record["has_value_pattern"] = True
                    try:
                        record["current_value"] = (ivp.CurrentValue or "")[:200]
                    except:
                        pass
                    try:
                        record["is_readonly"] = ivp.CurrentIsReadOnly
                    except:
                        pass
            except:
                pass

            results.append(record)

        except Exception as e:
            results.append({"depth": depth, "error": str(e)[:100]})

        # Walk children via RawViewWalker
        try:
            child = walker.GetFirstChildElement(element)
            while child:
                walk_raw(child, depth + 1, max_depth)
                try:
                    child = walker.GetNextSiblingElement(child)
                except:
                    break
        except:
            pass

    print("  [INFO] Walking with RawViewWalker (max 5000 elements)...")
    walk_raw(vscode)
    print(f"  [INFO] Found {len(results)} elements total")

    return results


# ============================================================
# PART 3: pywinauto approach
# ============================================================

def run_pywinauto_scan():
    print("\n" + "=" * 70)
    print("PART 3: pywinauto UIA backend scan")
    print("=" * 70)

    try:
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        # Find VS Code window
        windows = desktop.windows(title_re=".*Visual Studio Code.*")
        if not windows:
            print("  [ERROR] No VS Code window found via pywinauto")
            return

        win = windows[0]
        print(f"  [OK] Found: {win.window_text()}")
        print(f"  [INFO] Control count (immediate children): {len(win.children())}")

        # Try to find edit controls
        print("\n  Looking for Edit controls...")
        try:
            edits = win.descendants(control_type="Edit")
            print(f"  Found {len(edits)} Edit controls")
            for e in edits[:20]:
                print(f"    - name='{e.window_text()[:60]}' class='{e.element_info.class_name}' aid='{e.element_info.automation_id[:40]}'")
        except Exception as ex:
            print(f"  [WARN] Edit search failed: {ex}")

        # Try to find Document controls
        print("\n  Looking for Document controls...")
        try:
            docs = win.descendants(control_type="Document")
            print(f"  Found {len(docs)} Document controls")
            for d in docs[:20]:
                print(f"    - name='{d.window_text()[:60]}' class='{d.element_info.class_name}' aid='{d.element_info.automation_id[:40]}'")
        except Exception as ex:
            print(f"  [WARN] Document search failed: {ex}")

        # Total descendant count
        print("\n  Counting all descendants (may be slow)...")
        try:
            all_desc = win.descendants()
            print(f"  Total descendants: {len(all_desc)}")

            # Group by control type
            type_counts = {}
            for d in all_desc:
                ct = d.element_info.control_type or "None"
                type_counts[ct] = type_counts.get(ct, 0) + 1

            print("\n  Control type distribution:")
            for ct, count in sorted(type_counts.items(), key=lambda x: -x[1]):
                print(f"    {ct}: {count}")

        except Exception as ex:
            print(f"  [WARN] Descendant count failed: {ex}")

    except ImportError:
        print("  [ERROR] pywinauto not available")
    except Exception as e:
        print(f"  [ERROR] {e}")


# ============================================================
# PART 4: Check VS Code settings for accessibility
# ============================================================

def check_vscode_settings():
    print("\n" + "=" * 70)
    print("PART 4: VS Code accessibility settings")
    print("=" * 70)

    # Check argv.json
    appdata = os.environ.get("APPDATA", "")
    argv_path = os.path.join(appdata, "Code", "argv.json")
    if os.path.exists(argv_path):
        try:
            with open(argv_path, "r") as f:
                content = f.read()
            print(f"  argv.json ({argv_path}):")
            print(f"  {content[:500]}")
            if "force-renderer-accessibility" in content:
                print("  [OK] --force-renderer-accessibility is in argv.json")
            else:
                print("  [!] --force-renderer-accessibility NOT in argv.json")
        except Exception as e:
            print(f"  [WARN] Could not read argv.json: {e}")
    else:
        print(f"  argv.json not found at {argv_path}")

    # Check user settings
    settings_path = os.path.join(appdata, "Code", "User", "settings.json")
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r") as f:
                content = f.read()
            if "accessibilitySupport" in content:
                # Find the line
                for line in content.splitlines():
                    if "accessibilitySupport" in line:
                        print(f"  settings.json: {line.strip()}")
            else:
                print("  settings.json: editor.accessibilitySupport not set (default: auto)")
        except Exception as e:
            print(f"  [WARN] Could not read settings.json: {e}")
    else:
        print(f"  settings.json not found at {settings_path}")


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("UI Automation Research: VS Code Webview Text Input")
    print(f"Time: {datetime.now().isoformat()}")
    print("Python: " + sys.executable)
    print("=" * 70)

    check_vscode_settings()
    has_flag = check_chromium_accessibility()

    results = run_comtypes_deep_scan()

    # Analyze results
    if results:
        print("\n" + "=" * 70)
        print("ANALYSIS: Elements by control type")
        print("=" * 70)
        type_counts = {}
        for r in results:
            ct = r.get("control_type", "error")
            type_counts[ct] = type_counts.get(ct, 0) + 1
        for ct, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f"  {ct}: {count}")

        print("\n" + "=" * 70)
        print("ANALYSIS: Elements with ValuePattern (settable text)")
        print("=" * 70)
        valued = [r for r in results if r.get("has_value_pattern")]
        if valued:
            for r in valued:
                print(f"  depth={r['depth']} {r['control_type']} name='{r['name'][:60]}' class='{r['class_name']}' readonly={r.get('is_readonly', '?')}")
                if r.get("current_value"):
                    print(f"    value='{r['current_value'][:80]}'")
        else:
            print("  (none found)")

        print("\n" + "=" * 70)
        print("ANALYSIS: Edit/Document controls")
        print("=" * 70)
        edits = [r for r in results if r.get("control_type_id") in (50004, 50030)]
        if edits:
            for r in edits:
                print(f"  depth={r['depth']} {r['control_type']} name='{r['name'][:60]}' class='{r['class_name']}' aid='{r['automation_id'][:40]}'")
        else:
            print("  (none found)")

        # Max depth reached
        max_depth = max(r.get("depth", 0) for r in results)
        print(f"\n  Max depth reached: {max_depth}")

        # Dump to JSON
        json_path = "D:/Code/clara-voice-code/scripts/test_uia_results.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False, default=str)
        print(f"  Results saved to {json_path}")

    run_pywinauto_scan()

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY & RECOMMENDATIONS")
    print("=" * 70)

    total = len(results)
    edits_found = len([r for r in results if r.get("control_type_id") in (50004, 50030)])
    valued_found = len([r for r in results if r.get("has_value_pattern")])

    print(f"""
  Total UIA elements found: {total}
  Edit/Document controls:   {edits_found}
  Elements with ValuePattern: {valued_found}

  If very few elements were found (<50), the Chromium renderer is opaque.
  This means UI Automation CANNOT see inside the webview.

  OPTIONS TO INSERT TEXT INTO CLAUDE CODE CHAT:

  1. ENABLE ACCESSIBILITY (recommended to test):
     Add to %APPDATA%/Code/argv.json:
       "enable-proposed-api": ["*"],
     And launch with: code --force-renderer-accessibility
     Or set: "editor.accessibilitySupport": "on" in settings.json
     Then re-run this script to see if web elements appear.

  2. CLIPBOARD + KEYBOARD (current approach, works):
     clipboard -> Ctrl+L (focus chat) -> Ctrl+V (paste) -> Enter
     Requires ~150ms focus steal. Already implemented in focus-and-enter.py.

  3. VS CODE EXTENSION API (most reliable):
     Use vscode.commands.executeCommand() from extension.ts
     to programmatically insert text via the extension host.
     No UIA needed, no focus steal, works from background.

  4. CDP (Chrome DevTools Protocol):
     Connect to VS Code's built-in CDP port (--remote-debugging-port)
     Execute JavaScript directly in the webview context.
     Can find and set textarea value without UIA at all.
""")


if __name__ == "__main__":
    main()
