"""Тест всех методов вставки текста в Claude Code чат.

Запуск: python uia_insert_test.py
        (лучше из ВНЕШНЕГО терминала, не из VS Code)
"""
import ctypes, ctypes.wintypes, sys, time, subprocess, comtypes, comtypes.client

comtypes.CoInitialize()
tlb = comtypes.client.GetModule("UIAutomationCore.dll")
uia = comtypes.CoCreateInstance(tlb.CUIAutomation._reg_clsid_, interface=tlb.IUIAutomation)
user32 = ctypes.windll.user32

# --- Найти все VS Code окна с "Message input" ---
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
windows = []
def enum_cb(hwnd, _):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    if "Visual Studio Code" in buf.value and user32.IsWindowVisible(hwnd):
        windows.append((hwnd, buf.value))
    return True
user32.EnumWindows(EnumWindowsProc(enum_cb), 0)

print(f"Найдено {len(windows)} окон VS Code:")
targets = []
for hwnd, title in windows:
    root = uia.ElementFromHandle(hwnd)
    cond = uia.CreateAndCondition(
        uia.CreatePropertyCondition(30003, 50004),
        uia.CreatePropertyCondition(30005, "Message input")
    )
    el = root.FindFirst(4, cond)
    has_input = "✓" if el else "✗"
    print(f"  {hwnd}: {has_input} {title[:70]}")
    if el:
        targets.append((hwnd, title, root, el))

if not targets:
    print("\nНет окон с Claude Code чатом!"); sys.exit(1)

# Выбираем первое окно с input
HWND, TITLE, ROOT, EL = targets[0]
print(f"\nТестируем окно: {HWND} — {TITLE[:60]}")

COND = uia.CreateAndCondition(
    uia.CreatePropertyCondition(30003, 50004),
    uia.CreatePropertyCondition(30005, "Message input")
)

def get_value():
    raw = EL.GetCurrentPattern(10002)
    vp = raw.QueryInterface(tlb.IUIAutomationValuePattern)
    return vp.CurrentValue

def clear():
    raw = EL.GetCurrentPattern(10002)
    vp = raw.QueryInterface(tlb.IUIAutomationValuePattern)
    vp.SetValue("")
    time.sleep(0.05)

# --- SendInput ---
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

# =====================================================================
print("\n" + "=" * 60)
print("ТЕСТ 1: TextEditPattern")
print("=" * 60)
try:
    raw = EL.GetCurrentPattern(10029)
    if raw:
        tep = raw.QueryInterface(tlb.IUIAutomationTextEditPattern)
        print("  TextEditPattern доступен, но это read-only паттерн (мониторинг IME)")
        print("  ❌ Не подходит для вставки")
    else:
        print("  Паттерн вернул None")
except Exception as e:
    print(f"  ❌ Ошибка: {e}")

# =====================================================================
print("\n" + "=" * 60)
print("ТЕСТ 2: ValuePattern.SetValue")
print("=" * 60)
try:
    clear()
    test_text = "[Voice] тест SetValue"
    raw = EL.GetCurrentPattern(10002)
    vp = raw.QueryInterface(tlb.IUIAutomationValuePattern)
    vp.SetValue(test_text)
    time.sleep(0.2)
    readback = get_value()
    print(f"  Записано: '{test_text}'")
    print(f"  Прочитано обратно: '{readback}'")
    print(f"  Совпадение: {readback == test_text}")
    print()
    print("  👀 Посмотри на окно VS Code — виден ли текст в поле ввода чата?")
    input("  [Нажми Enter когда посмотришь] ")
    ans = input("  Текст ВИДЕН в поле ввода? (д/н): ").strip().lower()
    visible = ans in ('д', 'y', 'да', 'yes')
    print(f"  → {'✅ React увидел изменение' if visible else '❌ React НЕ увидел изменение'}")
    clear()
except Exception as e:
    print(f"  ❌ Ошибка: {e}")

# =====================================================================
print("\n" + "=" * 60)
print("ТЕСТ 3: LegacyIAccessible.SetValue")
print("=" * 60)
try:
    clear()
    test_text = "[Voice] тест Legacy"
    raw = EL.GetCurrentPattern(10018)
    lap = raw.QueryInterface(tlb.IUIAutomationLegacyIAccessiblePattern)
    lap.SetValue(test_text)
    time.sleep(0.2)
    readback = get_value()
    print(f"  Записано: '{test_text}'")
    print(f"  Прочитано обратно: '{readback}'")
    print()
    print("  👀 Посмотри на окно VS Code — виден ли текст в поле ввода чата?")
    input("  [Нажми Enter когда посмотришь] ")
    ans = input("  Текст ВИДЕН в поле ввода? (д/н): ").strip().lower()
    visible = ans in ('д', 'y', 'да', 'yes')
    print(f"  → {'✅ React увидел' if visible else '❌ React НЕ увидел'}")
    clear()
except Exception as e:
    print(f"  ❌ Ошибка: {e}")

# =====================================================================
print("\n" + "=" * 60)
print("ТЕСТ 4: UIA SetFocus + буфер обмена (Ctrl+V)")
print("=" * 60)
print("  ⚠️  Этот тест украдёт фокус у текущего окна!")
input("  [Нажми Enter чтобы начать] ")
try:
    clear()
    test_text = "[Voice] тест фокус+вставка"
    escaped = test_text.replace("'", "''")
    subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                     f"Set-Clipboard -Value '{escaped}'"], capture_output=True, timeout=3)

    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(HWND)
    time.sleep(0.1)

    EL.SetFocus()
    time.sleep(0.15)

    fg = user32.GetForegroundWindow()
    print(f"  Foreground: {fg} ({'совпадает' if fg==HWND else 'НЕ совпадает'} с {HWND})")

    send(0x11); time.sleep(0.01)
    send(0x56); time.sleep(0.02)
    send(0x56, KEYEVENTF_KEYUP); time.sleep(0.01)
    send(0x11, KEYEVENTF_KEYUP)
    time.sleep(0.2)

    readback = get_value()
    print(f"  Прочитано после Ctrl+V: '{readback}'")
    print()
    print("  👀 Посмотри на окно VS Code — виден ли текст в поле ввода чата?")
    input("  [Нажми Enter когда посмотришь] ")
    ans = input("  Текст ВИДЕН в поле ввода? (д/н): ").strip().lower()
    visible = ans in ('д', 'y', 'да', 'yes')
    submitted = False
    if visible:
        print("  Отправляю Enter...")
        send(0x0D); time.sleep(0.02); send(0x0D, KEYEVENTF_KEYUP)
        time.sleep(0.5)
        input("  [Нажми Enter когда проверишь] ")
        ans = input("  Сообщение ОТПРАВИЛОСЬ в Claude? (д/н): ").strip().lower()
        submitted = ans in ('д', 'y', 'да', 'yes')
    print(f"  → Виден: {'✅' if visible else '❌'}, Отправлен: {'✅' if submitted else '❌'}")
    clear()
except Exception as e:
    print(f"  ❌ Ошибка: {e}")

# =====================================================================
print("\n" + "=" * 60)
print("ТЕСТ 5: Клик по координатам элемента + Ctrl+V")
print("=" * 60)
print("  ⚠️  Этот тест кликнет мышью и украдёт фокус!")
input("  [Нажми Enter чтобы начать] ")
try:
    clear()
    test_text = "[Voice] тест клик+вставка"
    escaped = test_text.replace("'", "''")
    subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                     f"Set-Clipboard -Value '{escaped}'"], capture_output=True, timeout=3)

    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(HWND)
    time.sleep(0.1)

    el2 = ROOT.FindFirst(4, COND)
    rect = el2.CurrentBoundingRectangle
    cx = (rect.left + rect.right) // 2
    cy = (rect.top + rect.bottom) // 2
    print(f"  Координаты: ({rect.left},{rect.top})-({rect.right},{rect.bottom}), клик в ({cx},{cy})")

    old_pos = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(old_pos))

    user32.SetCursorPos(cx, cy)
    time.sleep(0.03)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.01)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.2)

    fg = user32.GetForegroundWindow()
    print(f"  Foreground: {fg} ({'совпадает' if fg==HWND else 'НЕ совпадает'} с {HWND})")

    send(0x11); time.sleep(0.01)
    send(0x56); time.sleep(0.02)
    send(0x56, KEYEVENTF_KEYUP); time.sleep(0.01)
    send(0x11, KEYEVENTF_KEYUP)
    time.sleep(0.2)

    user32.SetCursorPos(old_pos.x, old_pos.y)

    readback = get_value()
    print(f"  Прочитано после клика+Ctrl+V: '{readback}'")
    print()
    print("  👀 Посмотри на окно VS Code — виден ли текст в поле ввода чата?")
    input("  [Нажми Enter когда посмотришь] ")
    ans = input("  Текст ВИДЕН в поле ввода? (д/н): ").strip().lower()
    visible = ans in ('д', 'y', 'да', 'yes')
    submitted = False
    if visible:
        user32.SetForegroundWindow(HWND)
        time.sleep(0.05)
        el2.SetFocus()
        time.sleep(0.05)
        print("  Отправляю Enter...")
        send(0x0D); time.sleep(0.02); send(0x0D, KEYEVENTF_KEYUP)
        time.sleep(0.5)
        input("  [Нажми Enter когда проверишь] ")
        ans = input("  Сообщение ОТПРАВИЛОСЬ в Claude? (д/н): ").strip().lower()
        submitted = ans in ('д', 'y', 'да', 'yes')
    print(f"  → Виден: {'✅' if visible else '❌'}, Отправлен: {'✅' if submitted else '❌'}")
except Exception as e:
    print(f"  ❌ Ошибка: {e}")

# =====================================================================
print("\n" + "=" * 60)
print("ИТОГО")
print("=" * 60)
print("Проверь результаты выше — рабочий метод будет интегрирован в расширение.")
