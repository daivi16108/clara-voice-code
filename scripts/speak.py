"""speak.py — Озвучить текст через Piper (локальный) или edge-tts (сетевой, стриминг).

Движки:
- piper: мгновенная генерация (~0.1s), модель загружается один раз в память
- edge-tts: потоковое воспроизведение, начинает играть пока генерирует
- auto: piper для коротких фраз (<=100 символов), edge-tts стриминг для длинных

Аргументы: speak.py <text> [--lang ru|en] [--engine auto|piper|edge-tts] [--speed ...]
"""
import sys, os, subprocess, tempfile, time, json, argparse, numpy as np

os.environ["CUDA_VISIBLE_DEVICES"] = ""

if sys.platform == "win32":
    home = os.path.expanduser("~")
    for p in [
        os.path.join(home, "AppData", "Local", "Microsoft", "WinGet", "Links"),
        os.path.join(home, "AppData", "Local", "Programs", "Python", "Python312", "Scripts"),
    ]:
        if p not in os.environ.get("PATH", ""):
            os.environ["PATH"] = p + ";" + os.environ.get("PATH", "")

SETTINGS_FILE = os.path.join(tempfile.gettempdir(), "voice-claude-settings.json")
MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "piper")

VOICE_MAP = {
    "ru": "ru-RU-SvetlanaNeural",
    "en": "en-US-JennyNeural",
    "de": "de-DE-ConradNeural",
    "fr": "fr-FR-HenriNeural",
    "uk": "uk-UA-OstapNeural",
}

PERSONA_VOICES = {
    "clara": {"ru": "ru-RU-SvetlanaNeural", "en": "en-US-JennyNeural"},
    "claude": {"ru": "ru-RU-DmitryNeural", "en": "en-US-GuyNeural"},
}

PIPER_MODELS = {
    "ru": "ru_RU-irina-medium.onnx",
}

# Ленивый синглтон для Piper — модель загружается один раз
_piper_cache = {}


def _log_debug(msg):
    """Отладочный лог в temp."""
    try:
        with open(os.path.join(tempfile.gettempdir(), "voice-speak-debug.log"), "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except: pass


def load_settings():
    """Загрузить runtime настройки из файла."""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE) as f:
                return json.load(f)
    except:
        pass
    return {}


def _find_device(name_part):
    """Найти устройство вывода по части имени."""
    import sounddevice as sd
    for i, d in enumerate(sd.query_devices()):
        if d['max_output_channels'] > 0 and name_part.lower() in d['name'].lower():
            return i
    return None


def _get_piper_voice(lang="ru"):
    """Получить загруженную модель Piper (кешируется)."""
    if lang in _piper_cache:
        return _piper_cache[lang]

    model_name = PIPER_MODELS.get(lang)
    if not model_name:
        return None

    model_path = os.path.join(MODELS_DIR, model_name)
    if not os.path.exists(model_path):
        _log_debug(f"Piper model not found: {model_path}")
        return None

    try:
        from piper import PiperVoice
        t0 = time.time()
        voice = PiperVoice.load(model_path)
        _log_debug(f"Piper model loaded: {time.time()-t0:.2f}s")
        _piper_cache[lang] = voice
        return voice
    except Exception as e:
        _log_debug(f"Piper load error: {e}")
        return None


def _play_audio(data, sr, volume=0.75, device=None):
    """Воспроизвести numpy audio через sounddevice."""
    import sounddevice as sd
    data = data * volume
    sd.play(data, sr, device=device, blocking=True)


def _play_piper(text, lang="ru", volume=0.75, device=None):
    """Генерация и воспроизведение через Piper (локальный, ~0.1s)."""
    voice = _get_piper_voice(lang)
    if not voice:
        return False

    t0 = time.time()
    chunks = list(voice.synthesize(text))
    if not chunks:
        return False

    audio = np.concatenate([c.audio_float_array for c in chunks])
    sr = chunks[0].sample_rate
    _log_debug(f"Piper: generated {len(audio)/sr:.2f}s audio in {time.time()-t0:.3f}s")

    _play_audio(audio, sr, volume, device)
    return True


def _play_edge_stream(text, voice="ru-RU-SvetlanaNeural", speed=1.2, volume=0.75, device=None):
    """Воспроизведение через edge-tts библиотеку + miniaudio (без CLI и ffmpeg)."""
    import asyncio, io, miniaudio

    rate = None
    if speed != 1.0:
        pct = round((speed - 1) * 100)
        rate = f"{'+' if pct >= 0 else ''}{pct}%"

    async def _generate():
        import edge_tts
        comm = edge_tts.Communicate(text, voice, rate=rate)
        mp3_buf = io.BytesIO()
        async for chunk in comm.stream():
            if chunk.get('type') == 'audio' and chunk.get('data'):
                mp3_buf.write(chunk['data'])
        return mp3_buf.getvalue()

    try:
        t0 = time.time()
        mp3_data = asyncio.run(_generate())
        _log_debug(f"edge-tts: stream received {len(mp3_data)} bytes in {time.time()-t0:.2f}s")

        if len(mp3_data) < 100:
            _log_debug("edge-tts: too little audio data")
            return False

        # Декодируем MP3 через miniaudio (без ffmpeg!)
        decoded = miniaudio.decode(mp3_data, output_format=miniaudio.SampleFormat.FLOAT32)
        audio = np.frombuffer(decoded.samples, dtype=np.float32)
        sr = decoded.sample_rate
        if decoded.nchannels > 1:
            audio = audio.reshape(-1, decoded.nchannels)
        _log_debug(f"edge-tts: decoded {len(audio)/sr:.2f}s audio, ready in {time.time()-t0:.2f}s")

        _play_audio(audio, sr, volume, device)
        return True
    except Exception as e:
        _log_debug(f"edge-tts stream error: {e}")
        return False


def _mp3_to_wav(mp3_path):
    """Конвертировать MP3 в WAV, вернуть путь или None."""
    wav_path = mp3_path.replace('.mp3', '.wav')
    subprocess.run(['ffmpeg', '-y', '-i', mp3_path, '-ar', '44100', '-ac', '2', wav_path],
                   capture_output=True, timeout=15)
    return wav_path if os.path.exists(wav_path) else None


def _play_to_devices(mp3_path, volume=0.75):
    """Воспроизвести MP3 через VoiceMeeter Input (идёт в наушники A1 + Discord B1)."""
    import sounddevice as sd
    import soundfile as sf

    wav_path = _mp3_to_wav(mp3_path)
    if not wav_path:
        return

    try:
        data, sr = sf.read(wav_path, dtype='float32')
        data = data * volume

        vm_dev = _find_device('Voicemeeter Input')
        if vm_dev is not None:
            sd.play(data, sr, device=vm_dev, blocking=True)
        else:
            sd.play(data, sr, blocking=True)
    except Exception as e:
        print(f"sounddevice error: {e}", file=sys.stderr)
    finally:
        try:
            os.remove(wav_path)
        except:
            pass


# Порог для автовыбора движка (символов)
AUTO_THRESHOLD = 100


def speak(text, voice=None, speed=None, language=None, engine=None):
    settings = load_settings()

    if settings.get("tts_muted", False):
        _log_debug("speak: muted via tray toggle, skipping")
        return

    if engine is None:
        engine = settings.get("engine", "edge-tts")

    if speed is None:
        speed = settings.get("speed", 1.2)

    volume = settings.get("volume", 0.75)
    discord_mode = settings.get("discord_mode", False)

    # Определяем язык
    lang = language or "ru"

    # Определяем устройство
    device = None
    if discord_mode:
        device = _find_device('Voicemeeter Input')

    # Автовыбор движка
    if engine == "auto":
        # Piper для коротких фраз на поддерживаемых языках
        if len(text) <= AUTO_THRESHOLD and lang in PIPER_MODELS:
            engine = "piper"
        else:
            engine = "edge-tts"

    _log_debug(f"speak: engine={engine}, lang={lang}, len={len(text)}, volume={volume}")

    if engine == "piper":
        ok = _play_piper(text, lang=lang, volume=volume, device=device)
        if not ok:
            _log_debug("Piper failed, falling back to edge-tts")
            engine = "edge-tts"

    if engine == "edge-tts":
        # Определяем голос для edge-tts: персона > настройки > карта по языку
        if voice is None:
            persona = settings.get("persona", "clara")
            persona_map = PERSONA_VOICES.get(persona, PERSONA_VOICES["clara"])
            if lang in persona_map:
                voice = persona_map[lang]
            elif lang in VOICE_MAP:
                voice = VOICE_MAP[lang]
            else:
                voice = settings.get("voice", "ru-RU-SvetlanaNeural")

        if discord_mode:
            # Discord mode: генерируем mp3, воспроизводим через VoiceMeeter
            mp3 = os.path.join(tempfile.gettempdir(), f"vc-speak-{int(time.time()*1000)}.mp3")
            rate_arg = []
            if speed != 1.0:
                pct = round((speed - 1) * 100)
                rate_arg = ["--rate", f"{'+' if pct >= 0 else ''}{pct}%"]
            subprocess.run(["edge-tts", "--voice", voice, "--text", text, "--write-media", mp3] + rate_arg,
                           capture_output=True, timeout=30)
            if os.path.exists(mp3) and os.path.getsize(mp3) > 100:
                _play_to_devices(mp3, volume)
                try: os.remove(mp3)
                except: pass
        else:
            _play_edge_stream(text, voice=voice, speed=speed, volume=volume, device=device)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("text", nargs="*", default=[])
    parser.add_argument("--lang", default=None, help="Language code (ru, en, etc.)")
    parser.add_argument("--voice", default=None, help="TTS voice name")
    parser.add_argument("--speed", type=float, default=None, help="Speech speed")
    parser.add_argument("--engine", default=None, choices=["auto", "piper", "edge-tts"], help="TTS engine")
    args = parser.parse_args()

    text = " ".join(args.text) if args.text else sys.stdin.read()
    text = text.strip()
    if text:
        _log_debug(f"START text='{text[:50]}' engine={args.engine} lang={args.lang}")
        try:
            speak(text, voice=args.voice, speed=args.speed, language=args.lang, engine=args.engine)
            _log_debug("DONE ok")
        except Exception as e:
            _log_debug(f"ERROR: {e}")
            raise
