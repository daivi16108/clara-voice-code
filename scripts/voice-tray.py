"""
voice-tray.py — System tray VoiceClaude.

Wake word detection через OpenWakeWord (нейросеть, как Siri/Google).
STT через Silero VAD + Whisper.
Микрофон через PyAudio.

Цвета:
  Серый   — выключено
  Зелёный — слушаю (ждём wake word)
  Синий   — wake word! Говори команду...
  Красный — записываю речь
  Жёлтый  — распознаю
"""

import sys, os, json, time, struct, wave, tempfile, threading, argparse, math, subprocess, ctypes
from collections import deque

# Загрузить .env
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["HIP_VISIBLE_DEVICES"] = ""
os.environ["ROCR_VISIBLE_DEVICES"] = ""

if sys.platform == "win32":
    home = os.path.expanduser("~")
    for p in [
        os.path.join(home, "AppData", "Local", "Microsoft", "WinGet", "Links"),
        os.path.join(home, "AppData", "Local", "Programs", "Python", "Python312", "Scripts"),
    ]:
        if p not in os.environ.get("PATH", ""):
            os.environ["PATH"] = p + ";" + os.environ.get("PATH", "")

import torch
import numpy as np
import pyaudio
from PIL import Image, ImageDraw, ImageFont
import pystray
from pystray import MenuItem, Menu

if sys.platform == "win32":
    import winsound

LOG_FILE = os.path.join(tempfile.gettempdir(), "voice-claude-tray.log")
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULT_FILE = os.path.join(_PROJECT_DIR, ".claude", "voice-result.json")
STATUS_FILE = os.path.join(tempfile.gettempdir(), "voice-claude-daemon-status.json")

def log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except: pass

# States
S_DISABLED = "disabled"
S_IDLE = "idle"           # Ждём wake word
S_ACTIVATED = "activated"  # Wake word detected, ждём команду
S_RECORDING = "recording"  # Записываем речь
S_TRANSCRIBING = "transcribing"
S_MIC_ERROR = "mic_error"  # Микрофон не работает

COLORS = {
    S_DISABLED: (128,128,128),
    S_IDLE: (0,180,0),
    S_ACTIVATED: (30,100,220),
    S_RECORDING: (220,30,30),
    S_TRANSCRIBING: (220,180,0),
    S_MIC_ERROR: (255,200,0),
}
TIPS_RU = {
    S_DISABLED: "Clara Voice — выкл",
    S_IDLE: "Clara Voice — ждёт wake word",
    S_ACTIVATED: "Clara Voice — говори команду!",
    S_RECORDING: "Clara Voice — ЗАПИСЬ",
    S_TRANSCRIBING: "Clara Voice — распознаю",
    S_MIC_ERROR: "Clara Voice — микрофон не работает!",
}
TIPS_EN = {
    S_DISABLED: "Clara Voice — off",
    S_IDLE: "Clara Voice — waiting for wake word",
    S_ACTIVATED: "Clara Voice — speak your command!",
    S_RECORDING: "Clara Voice — RECORDING",
    S_TRANSCRIBING: "Clara Voice — transcribing",
    S_MIC_ERROR: "Clara Voice — microphone error!",
}

def get_tips():
    return TIPS_EN if language == "en" else TIPS_RU

# Globals
whisper_model = None
vad_model = None
tray_icon = None
enabled = True
language = "en"
wake_word_enabled = True
wake_custom = None  # Имя кастомного wake word (для аудио-классификатора, опционально)
dictation_mode = False  # Режим диктовки — всё идёт без wake word

# Command history (last 10)
command_history = deque(maxlen=10)

# Runtime settings (changeable from tray)
SETTINGS_FILE = os.path.join(tempfile.gettempdir(), "voice-claude-settings.json")
tts_volume = 0.75
tts_speed = 1.2
tts_voice = "ru-RU-SvetlanaNeural"
tts_muted = False
persona = "clara"

# Cancel phrases
CANCEL_PHRASES = ["отмена", "стоп", "cancel", "stop", "отмени", "замолчи"]

RATE = 16000
CHANNELS = 1
VAD_CHUNK = 512    # Silero VAD requires 512 samples


def play_beep():
    """Короткий звук подтверждения wake word (respects sound_feedback setting)."""
    try:
        settings = {}
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE) as f:
                settings = json.load(f)
        if not settings.get("sound_feedback", True):
            return
        if sys.platform == "win32":
            threading.Thread(target=lambda: winsound.Beep(1200, 150), daemon=True).start()
        else:
            sys.stdout.write("\x07")
    except:
        pass


def cancel_current_playback():
    """Остановить текущую TTS (убить ffplay)."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/IM", "ffplay.exe"],
                           capture_output=True, timeout=3)
        else:
            subprocess.run(["pkill", "-f", "ffplay"], capture_output=True, timeout=3)
        log("TTS playback cancelled")
    except:
        pass
    # Сигнал для MCP сервера
    try:
        cancel_file = os.path.join(_PROJECT_DIR, ".claude", "voice-cancel.json")
        with open(cancel_file, "w") as f:
            json.dump({"cancel": True, "timestamp": time.time()}, f)
    except:
        pass


def save_settings():
    """Сохранить настройки в файл для speak.py и MCP сервера.
    Reads existing file first to preserve keys set by extension (e.g. persona).
    """
    try:
        existing = {}
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE) as f:
                existing = json.load(f)
        existing.update({
            "volume": tts_volume,
            "speed": tts_speed,
            "voice": tts_voice,
            "tts_muted": tts_muted,
            "persona": persona,
        })
        with open(SETTINGS_FILE, "w") as f:
            json.dump(existing, f)
    except:
        pass


def load_settings_from_file():
    """Загрузить настройки из файла."""
    global tts_volume, tts_speed, tts_voice, tts_muted, persona, language
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE) as f:
                s = json.load(f)
            tts_volume = s.get("volume", tts_volume)
            tts_speed = s.get("speed", tts_speed)
            tts_voice = s.get("voice", tts_voice)
            tts_muted = s.get("tts_muted", tts_muted)
            persona = s.get("persona", persona)
            language = s.get("language", language)
    except:
        pass


def make_icon(state, size=64):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = COLORS.get(state, (128,128,128))
    m = 4
    d.ellipse([m, m, size-m, size-m], fill=c)
    cx, cy, r = size//2, size//2, size//6
    if state in (S_IDLE, S_RECORDING, S_ACTIVATED):
        d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(255,255,255,200))
    elif state == S_TRANSCRIBING:
        for i in range(3):
            x = size//4 + i*(size//4)
            d.ellipse([x-3, cy-3, x+3, cy+3], fill=(255,255,255,200))
    elif state == S_DISABLED:
        d.line([m+8, m+8, size-m-8, size-m-8], fill=(255,255,255,180), width=3)
    elif state == S_MIC_ERROR:
        # Восклицательный знак
        d.rectangle([cx-2, cy-12, cx+2, cy+4], fill=(255,255,255,200))
        d.ellipse([cx-3, cy+7, cx+3, cy+13], fill=(255,255,255,200))
    return img

def update_tray(state):
    if tray_icon:
        tray_icon.icon = make_icon(state)
        tray_icon.title = get_tips().get(state, "Clara Voice")

def write_status(state, **kw):
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump({
                "state": state,
                "timestamp": time.time(),
                "pid": os.getpid(),
                "dictation_mode": dictation_mode,
                "wake_word_enabled": wake_word_enabled,
                "language": language,
                **kw,
            }, f)
    except: pass

_last_written_text = ""
_last_written_time = 0

def write_result(text, lang="", workspace="", target_file=""):
    """Записать результат атомарно. Дедупликация — не пишем тот же текст в течение 5 секунд."""
    global _last_written_text, _last_written_time
    now = time.time()
    if text == _last_written_text and now - _last_written_time < 5:
        return  # Дубликат
    _last_written_text = text
    _last_written_time = now
    command_history.appendleft(f"[{time.strftime('%H:%M')}] {text[:50]}")
    # PTT: use target_file (workspace-specific). Wake-word/dictation: use global file.
    GLOBAL_RESULT_FILE = os.path.join(tempfile.gettempdir(), "voice-claude-result-global.json")
    out_file = target_file if target_file else GLOBAL_RESULT_FILE
    try:
        os.makedirs(os.path.dirname(out_file), exist_ok=True)
        tmp = out_file + ".tmp"
        foreground_hwnd = ctypes.windll.user32.GetForegroundWindow()
        data = {"text": text, "language": lang, "timestamp": now, "consumed": False, "foreground_hwnd": foreground_hwnd}
        if workspace:
            data["workspace"] = workspace
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        # Атомарная замена — избегаем race condition
        if os.path.exists(out_file):
            os.remove(out_file)
        os.rename(tmp, out_file)
        log(f"Result written to {out_file}: '{text[:60]}'")
    except Exception as e:
        log(f"write_result error: {e}")


def send_to_vscode(text):
    """Отправить текст в чат Claude Code через симуляцию клавиатуры."""
    try:
        import pyautogui
        import pygetwindow as gw

        # Находим окно VS Code
        vscode_windows = [w for w in gw.getWindowsWithTitle("Visual Studio Code") if w.visible]
        if not vscode_windows:
            log("VS Code window not found")
            write_result(text)  # Fallback на файл
            return False

        win = vscode_windows[0]

        # Сохраняем текущее окно
        try:
            current = gw.getActiveWindow()
        except:
            current = None

        # Фокусируем VS Code
        try:
            if win.isMinimized:
                win.restore()
            win.activate()
            time.sleep(0.3)
        except:
            log("Failed to activate VS Code")
            write_result(text)
            return False

        # Фокусируем чат Claude Code: Ctrl+Shift+P -> "Claude: Focus Chat"
        # Проще — используем кастомный keybinding или просто кликаем в поле ввода
        # Самый надёжный: Ctrl+L фокусирует input в Claude Code chat
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.5)

        # Копируем текст в буфер обмена и вставляем
        import subprocess
        escaped = text.replace("'", "''")
        subprocess.run(["powershell.exe", "-Command", f"Set-Clipboard -Value '{escaped}'"],
                       capture_output=True, timeout=3)
        time.sleep(0.1)

        # Ctrl+V чтобы вставить
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.3)

        # Enter чтобы отправить
        pyautogui.press("enter")

        log(f"Sent to VS Code: '{text[:60]}'")

        # Возвращаем фокус если был другой
        if current and current.title != win.title:
            try:
                time.sleep(0.5)
                current.activate()
            except:
                pass

        return True
    except Exception as e:
        log(f"send_to_vscode error: {e}")
        write_result(text)  # Fallback
        return False

def send_enter_key():
    """Активировать окно VS Code и отправить Enter."""
    try:
        import ctypes
        user32 = ctypes.windll.user32

        # Найти и активировать окно VS Code
        EnumWindows = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
        titles = []
        def foreach_window(hwnd, lParam):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                if "Visual Studio Code" in buff.value and user32.IsWindowVisible(hwnd):
                    titles.append((hwnd, buff.value))
            return True
        user32.EnumWindows(EnumWindows(foreach_window), 0)

        if titles:
            hwnd = titles[0][0]
            # Alt trick для получения права на foreground
            user32.keybd_event(0x12, 0, 0, 0)  # Alt down
            user32.keybd_event(0x12, 0, 2, 0)  # Alt up
            time.sleep(0.05)
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.5)

        # Enter
        VK_RETURN = 0x0D
        user32.keybd_event(VK_RETURN, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(VK_RETURN, 0, 2, 0)
        log("Enter key sent via ctypes (with focus)")
    except Exception as e:
        log(f"send_enter_key error: {e}")


def save_wav(frames, path):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(CHANNELS); wf.setsampwidth(2); wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))


# ─── Models ───

def load_vad():
    """Silero VAD — детекция речи."""
    global vad_model
    if vad_model: return vad_model
    from silero_vad import load_silero_vad
    vad_model = load_silero_vad()
    log("Silero VAD loaded")
    return vad_model

def load_whisper():
    """Whisper — транскрипция."""
    global whisper_model
    if whisper_model: return whisper_model
    log("Loading Whisper...")
    update_tray(S_TRANSCRIBING)
    import whisper
    whisper_model = whisper.load_model("base", device="cpu")
    log("Whisper loaded")
    return whisper_model

def check_speech_vad(audio_bytes):
    """Silero VAD: есть ли речь?"""
    model = load_vad()
    n = len(audio_bytes) // 2
    samples = struct.unpack(f"<{n}h", audio_bytes[:n*2])
    tensor = torch.FloatTensor(samples) / 32768.0
    prob = model(tensor, RATE).item()
    return prob > 0.35

def transcribe_groq(wav_path):
    """Транскрипция через Groq Whisper API — быстро и точно."""
    from groq import Groq
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise ValueError("GROQ_API_KEY not set")

    # Use language from settings if available (improves accuracy)
    stt_language = None
    if language and language != "auto":
        stt_language = language  # e.g. "ru", "en"

    client = Groq(api_key=api_key)
    with open(wav_path, "rb") as f:
        result = client.audio.transcriptions.create(
            file=(os.path.basename(wav_path), f.read()),
            model="whisper-large-v3-turbo",
            language=stt_language,
            response_format="verbose_json",
            prompt=None,  # Без initial_prompt — иначе Groq галлюцинирует wake word
        )
    text = result.text.strip() if hasattr(result, "text") else ""
    lang = getattr(result, "language", "") or ""
    if not lang and stt_language:
        lang = stt_language
    return {"text": text, "language": lang}


def transcribe_whisper_local(wav_path):
    """Локальный whisper — fallback."""
    model = load_whisper()
    opts = {
        "fp16": False,
        # Без initial_prompt — иначе whisper галлюцинирует wake word
    }
    # Always auto-detect speech language
    result = model.transcribe(wav_path, **opts)
    return {"text": result.get("text", "").strip(), "language": result.get("language", "")}


_groq_failures = 0  # Счётчик последовательных ошибок Groq

def transcribe_audio(wav_path):
    """Groq API с retry + экспоненциальным backoff + автофоллбэком на локальный whisper."""
    global _groq_failures

    if os.environ.get("GROQ_API_KEY") and _groq_failures < 10:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                t0 = time.time()
                result = transcribe_groq(wav_path)
                elapsed = time.time() - t0
                log(f"Groq STT: {elapsed:.1f}s '{result['text'][:60]}'")
                _groq_failures = 0  # Reset on success
                write_status("transcribing", groq_available=True)
                return result
            except Exception as e:
                wait = (2 ** attempt) * 0.5  # 0.5s, 1s, 2s
                log(f"Groq attempt {attempt+1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(wait)
                else:
                    _groq_failures += 1
                    log(f"Groq exhausted ({_groq_failures} consecutive failures), fallback to local whisper")
                    write_status("transcribing", groq_available=False)
    elif _groq_failures >= 10:
        # После 10 провалов — пробуем Groq снова раз в минуту
        if time.time() % 60 < 2:
            _groq_failures = 0
            log("Resetting Groq failure counter, will retry next time")

    # Fallback: локальный whisper
    t0 = time.time()
    result = transcribe_whisper_local(wav_path)
    log(f"Local STT: {time.time()-t0:.1f}s '{result['text'][:60]}'")
    return result


# ─── Main loop ───

def listening_loop():
    """
    Основной цикл:
    1. Silero VAD детектирует речь
    2. Если wake_word_enabled:
       a) Собираем первые 0.8с речи
       b) Проверяем кастомным классификатором — "Клара" ли это?
       c) Если да — продолжаем запись до конца фразы, транскрибируем
       d) Если нет — сбрасываем, ждём дальше
    3. Если wake_word выключен — записываем всё подряд
    """
    global enabled, dictation_mode

    # Загрузка моделей
    load_vad()
    load_whisper()

    pa = pyaudio.PyAudio()
    update_tray(S_IDLE)
    write_status("idle")
    log("All models loaded. Listening...")

    stream = None
    state = S_IDLE
    speech_frames = []
    silence_chunks = 0

    silence_limit = int(1.5 * RATE / VAD_CHUNK)
    max_speech_chunks = int(15 * RATE / VAD_CHUNK)

    # Pre-buffer: хранит последние 0.5с аудио чтобы не терять начало фразы
    pre_buffer_size = int(0.5 * RATE / VAD_CHUNK)  # ~15 чанков
    pre_buffer = deque(maxlen=pre_buffer_size)

    # Mic monitoring
    last_audio_time = time.time()
    MIC_TIMEOUT = 5.0
    MIC_RECOVERY_TIMEOUT = 10.0

    _last_settings_check = time.time()
    _ptt_file = os.path.join(tempfile.gettempdir(), "voice-claude-ptt.json")
    _ptt_active = False
    _ptt_frames = []
    _ptt_last_ts = 0

    try:
        while True:
            # Reload settings every 2 seconds to pick up VS Code changes
            now = time.time()
            if now - _last_settings_check >= 2:
                _last_settings_check = now
                load_settings_from_file()

            # Check push-to-talk command file
            try:
                if os.path.exists(_ptt_file):
                    with open(_ptt_file) as f:
                        ptt_cmd = json.load(f)
                    ptt_ts = ptt_cmd.get("timestamp", 0)
                    _ptt_workspace = ptt_cmd.get("workspace", "")
                    _ptt_result_file = ptt_cmd.get("result_file", "")
                    if ptt_ts != _ptt_last_ts:
                        _ptt_last_ts = ptt_ts
                        ptt_command = ptt_cmd.get("command", "")

                        # Handle dictation toggle
                        if ptt_command == "dictation_toggle":
                            dictation_mode = not dictation_mode
                            log(f"DICTATION: {'ON' if dictation_mode else 'OFF'} (via inline button)")
                            write_status("idle", dictation_mode_changed=True)
                            if dictation_mode:
                                play_beep()
                            continue

                        # Handle TTS mute toggle (processed by extension, tray just ignores)
                        if ptt_command == "tts_mute_toggle":
                            tts_muted = not tts_muted
                            log(f"TTS MUTE: {'ON' if tts_muted else 'OFF'} (via inline button)")
                            save_settings()
                            continue

                        if not _ptt_active:
                            # Start recording
                            _ptt_active = True
                            _ptt_frames = []
                            play_beep()
                            log(f"PTT: recording started (ws={_ptt_workspace})")
                            update_tray(S_LISTENING)
                        else:
                            # Stop recording and transcribe
                            _ptt_active = False
                            log(f"PTT: recording stopped, {len(_ptt_frames)} frames (ws={_ptt_workspace})")
                            if _ptt_frames:
                                update_tray(S_TRANSCRIBING)
                                wav_path = os.path.join(tempfile.gettempdir(), f"vc-ptt-{int(time.time()*1000)}.wav")
                                save_wav(_ptt_frames, wav_path)
                                try:
                                    result = transcribe_audio(wav_path)
                                    text = result.get("text", "").strip()
                                    detected_lang = result.get("language", language) or language
                                    if text and len(text) > 1:
                                        log(f"PTT TRANSCRIBED: '{text}' (lang={detected_lang}, ws={_ptt_workspace})")
                                        write_result(text, detected_lang, workspace=_ptt_workspace, target_file=_ptt_result_file)
                                except Exception as e:
                                    log(f"PTT transcription error: {e}")
                                finally:
                                    try: os.remove(wav_path)
                                    except: pass
                            _ptt_frames = []
                            update_tray(S_IDLE)
                    os.remove(_ptt_file)
            except Exception:
                pass

            if not enabled:
                if stream:
                    stream.stop_stream(); stream.close(); stream = None
                update_tray(S_DISABLED)
                write_status("disabled")
                time.sleep(0.3)
                continue

            if not stream:
                try:
                    stream = pa.open(format=pyaudio.paInt16, channels=CHANNELS,
                                     rate=RATE, input=True, frames_per_buffer=VAD_CHUNK)
                except Exception as e:
                    log(f"Stream error: {e}")
                    time.sleep(2)
                    continue

            try:
                data = stream.read(VAD_CHUNK, exception_on_overflow=False)
                last_audio_time = time.time()
            except:
                elapsed = time.time() - last_audio_time
                if elapsed > MIC_TIMEOUT and state == S_IDLE:
                    log(f"WARNING: No audio data for {elapsed:.0f}s")
                    update_tray(S_MIC_ERROR)
                    write_status("mic_error")
                if elapsed > MIC_RECOVERY_TIMEOUT:
                    log("Attempting mic stream recovery...")
                    try:
                        stream.stop_stream(); stream.close()
                    except: pass
                    stream = None
                    last_audio_time = time.time()
                time.sleep(0.05)
                continue

            # PTT mode: collect frames while active
            if _ptt_active:
                _ptt_frames.append(data)
                continue

            has_speech = check_speech_vad(data)

            if state == S_IDLE:
                pre_buffer.append(data)
                if has_speech:
                    state = S_RECORDING
                    speech_frames = list(pre_buffer) + [data]
                    pre_buffer.clear()
                    silence_chunks = 0
                    update_tray(S_RECORDING)
                    write_status("recording")

            elif state == S_RECORDING:
                speech_frames.append(data)

                if has_speech:
                    silence_chunks = 0
                else:
                    silence_chunks += 1

                if silence_chunks >= silence_limit or len(speech_frames) >= max_speech_chunks:
                    update_tray(S_TRANSCRIBING)
                    write_status("transcribing")
                    log(f"Speech ended, {len(speech_frames)} chunks")

                    wav_path = os.path.join(tempfile.gettempdir(), f"vc-{int(time.time()*1000)}.wav")
                    save_wav(speech_frames, wav_path)
                    speech_frames = []
                    silence_chunks = 0

                    try:
                        result = transcribe_audio(wav_path)
                        text = result.get("text", "").strip()
                        detected_lang = result.get("language", language) or language
                        log(f"TRANSCRIBED: '{text}' (lang={detected_lang})")

                        if text and len(text) > 1:
                            lower = text.lower()
                            # Wake word проверка по ТЕКСТУ
                            if persona == "claude":
                                wake_words = ["клод", "claude", "клод,", "cloud", "клот"]
                            else:
                                wake_words = ["клара", "clara", "клар,", "клара,", "клэр", "клэр,", "clair", "claire"]
                            # Also accept custom wake word if set
                            if wake_custom and wake_custom.lower() not in wake_words:
                                wake_words.append(wake_custom.lower())
                            has_wake = dictation_mode or not wake_word_enabled or any(w in lower for w in wake_words)

                            if has_wake:
                                # Звуковой feedback — подтверждение wake word
                                if not dictation_mode:
                                    play_beep()

                                if dictation_mode:
                                    # Режим диктовки — отправляем всё как есть
                                    clean = text
                                else:
                                    # Убираем wake word из текста
                                    clean = lower
                                    for w in sorted(wake_words, key=len, reverse=True):
                                        clean = clean.replace(w, "").strip()
                                    clean = clean.lstrip(" ,.:;!?").strip()

                                # Проверка на голосовую отмену
                                if clean and any(p in clean.lower() for p in CANCEL_PHRASES):
                                    log(f"CANCEL command: '{clean}'")
                                    cancel_current_playback()
                                    play_beep()  # Двойной бип = отмена
                                    time.sleep(0.2)
                                    play_beep()
                                elif clean:
                                    log(f"WAKE OK, sending: '{clean}'")
                                    write_result(clean, detected_lang)
                                    # Enter отправляет VS Code расширение
                                else:
                                    log(f"Wake word only, no command")
                            else:
                                log(f"No wake word in: '{text[:60]}'")
                    except Exception as e:
                        log(f"Transcribe error: {e}")
                    finally:
                        try: os.remove(wav_path)
                        except: pass

                    state = S_IDLE
                    update_tray(S_IDLE)
                    write_status("idle")

    except Exception as e:
        log(f"Loop error: {e}")
    finally:
        if stream:
            stream.stop_stream(); stream.close()
        pa.terminate()


# ─── Tray ───

def toggle_enabled(icon, item):
    global enabled
    enabled = not enabled
    update_tray(S_IDLE if enabled else S_DISABLED)

def set_lang(l):
    def _s(icon, item):
        global language
        language = l
        # Persist to shared settings so extension and MCP pick it up
        try:
            existing = {}
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE) as f:
                    existing = json.load(f)
            existing["language"] = l
            with open(SETTINGS_FILE, "w") as f:
                json.dump(existing, f)
        except:
            pass
        update_tray(S_IDLE if enabled else S_DISABLED)
    return _s

def toggle_wake(icon, item):
    global wake_word_enabled; wake_word_enabled = not wake_word_enabled

def toggle_dictation(icon, item):
    global dictation_mode; dictation_mode = not dictation_mode


def toggle_tts_muted(icon, item):
    global tts_muted; tts_muted = not tts_muted; save_settings()

def set_persona(p):
    def _s(icon, item):
        global persona; persona = p; save_settings()
    return _s

def quit_app(icon, item):
    write_status("stopped"); remove_lock(); icon.stop(); os._exit(0)

# ─── Settings setters ───

def _set_volume(v):
    def _s(icon, item):
        global tts_volume; tts_volume = v; save_settings()
    return _s

def _set_speed(s):
    def _s(icon, item):
        global tts_speed; tts_speed = s; save_settings()
    return _s

def _set_voice(v):
    def _s(icon, item):
        global tts_voice; tts_voice = v; save_settings()
    return _s

def _t(ru, en):
    """Return localized string based on current language."""
    return lambda item=None: en if language == "en" else ru

def create_menu():
    return Menu(
        MenuItem(lambda item: ("● Listening" if language == "en" else "● Слушаю") if enabled
                 else ("○ Off" if language == "en" else "○ Выключено"), toggle_enabled),
        Menu.SEPARATOR,
        MenuItem(
            lambda item: ("🎙 DICTATION ON" if language == "en" else "🎙 ДИКТОВКА (всё → Клара)") if dictation_mode
            else ("🎙 Dictation off" if language == "en" else "🎙 Диктовка выкл"),
            toggle_dictation,
        ),
        MenuItem(
            lambda item: ("✓ Wake: Clara" if language == "en" else "✓ Wake: Клара") if wake_word_enabled
            else ("✗ Wake: off" if language == "en" else "✗ Wake: выкл"),
            toggle_wake,
        ),
        Menu.SEPARATOR,
        MenuItem(_t("Персона", "Persona"), Menu(
            MenuItem("Clara", set_persona("clara"), checked=lambda item: persona == "clara"),
            MenuItem("Claude", set_persona("claude"), checked=lambda item: persona == "claude"),
        )),
        MenuItem(_t("Язык", "Language"), Menu(
            MenuItem("English", set_lang("en"), checked=lambda item: language == "en"),
            MenuItem("Русский", set_lang("ru"), checked=lambda item: language == "ru"),
        )),
        Menu.SEPARATOR,
        MenuItem(_t("Настройки", "Settings"), Menu(
            MenuItem(_t("Громкость", "Volume"), Menu(
                MenuItem("25%", _set_volume(0.25), checked=lambda item: abs(tts_volume - 0.25) < 0.01),
                MenuItem("50%", _set_volume(0.5), checked=lambda item: abs(tts_volume - 0.5) < 0.01),
                MenuItem("75%", _set_volume(0.75), checked=lambda item: abs(tts_volume - 0.75) < 0.01),
                MenuItem("100%", _set_volume(1.0), checked=lambda item: abs(tts_volume - 1.0) < 0.01),
            )),
            MenuItem(_t("Скорость речи", "Speech speed"), Menu(
                MenuItem("0.8x", _set_speed(0.8), checked=lambda item: abs(tts_speed - 0.8) < 0.01),
                MenuItem("1.0x", _set_speed(1.0), checked=lambda item: abs(tts_speed - 1.0) < 0.01),
                MenuItem("1.2x", _set_speed(1.2), checked=lambda item: abs(tts_speed - 1.2) < 0.01),
                MenuItem("1.5x", _set_speed(1.5), checked=lambda item: abs(tts_speed - 1.5) < 0.01),
            )),
            MenuItem(_t("Голос", "Voice"), Menu(
                MenuItem("Svetlana (ru)", _set_voice("ru-RU-SvetlanaNeural"),
                         checked=lambda item: tts_voice == "ru-RU-SvetlanaNeural"),
                MenuItem("Jenny (en)", _set_voice("en-US-JennyNeural"),
                         checked=lambda item: tts_voice == "en-US-JennyNeural"),
                MenuItem("Guy (en)", _set_voice("en-US-GuyNeural"),
                         checked=lambda item: tts_voice == "en-US-GuyNeural"),
            )),
        )),
        Menu.SEPARATOR,
        MenuItem(
            lambda item: ("🔇 Responses: OFF" if language == "en" else "🔇 Ответы: ВЫКЛ") if tts_muted
            else ("🔊 Responses: on" if language == "en" else "🔊 Ответы: вкл"),
            toggle_tts_muted,
        ),
        Menu.SEPARATOR,
        MenuItem(_t("История", "History"), Menu(lambda: (
            [MenuItem(cmd, None) for cmd in command_history]
            if command_history
            else [MenuItem("(empty)" if language == "en" else "(пусто)", None)]
        ))),
        Menu.SEPARATOR,
        MenuItem(_t("Выход", "Quit"), quit_app),
    )

LOCK_FILE = os.path.join(tempfile.gettempdir(), "voice-claude-tray.lock")

def is_already_running():
    """Проверить есть ли уже запущенный экземпляр. Если да — не запускаемся."""
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE) as f:
                old_pid = int(f.read().strip())
            # Проверяем жив ли процесс
            if sys.platform == "win32":
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(0x1000, False, old_pid)  # PROCESS_QUERY_LIMITED_INFORMATION
                if handle:
                    kernel32.CloseHandle(handle)
                    return True  # Процесс жив
            else:
                os.kill(old_pid, 0)
                return True
    except (ValueError, OSError, ProcessLookupError):
        pass  # Процесс мёртв или lock битый
    return False

def write_lock():
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))

def remove_lock():
    try:
        os.remove(LOCK_FILE)
    except:
        pass

def main():
    global tray_icon, enabled, language, wake_word_enabled, wake_custom

    if is_already_running():
        log("Another instance already running, exiting.")
        sys.exit(0)
    write_lock()

    import atexit
    atexit.register(remove_lock)

    parser = argparse.ArgumentParser()
    parser.add_argument("--language", default="en")
    parser.add_argument("--no-wake-word", action="store_true")
    parser.add_argument("--wake-custom", default=None, help="Custom wake word name (unused, kept for compat)")
    parser.add_argument("--start-disabled", action="store_true")
    parser.add_argument("--result-file", default=None,
                        help="Path to voice-result.json (overrides default)")
    args = parser.parse_args()

    if args.result_file:
        global RESULT_FILE
        RESULT_FILE = args.result_file
        # Ensure parent directory exists
        os.makedirs(os.path.dirname(RESULT_FILE), exist_ok=True)

    language = args.language
    wake_word_enabled = not args.no_wake_word
    wake_custom = args.wake_custom
    enabled = not args.start_disabled
    load_settings_from_file()

    t = threading.Thread(target=listening_loop, daemon=True)
    t.start()

    tray_icon = pystray.Icon("VoiceClaude",
        icon=make_icon(S_IDLE if enabled else S_DISABLED),
        title=get_tips()[S_IDLE if enabled else S_DISABLED],
        menu=create_menu())
    tray_icon.run()

if __name__ == "__main__":
    main()
