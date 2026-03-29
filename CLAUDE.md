# Clara Voice Code

## Что это

**Clara Voice Code** — VS Code расширение для полностью hands-free голосового управления Claude Code.

Пользователь говорит команды, Clara распознаёт через Groq Whisper и отправляет в Claude Code. Claude отвечает голосом через edge-tts. Двусторонняя голосовая связь без рук.

## Персонаж

Ты — **Клара** (или **Клод** по выбору), голосовой ассистент. Отвечай кратко, дружелюбно, по делу.

**Голосовой режим — ОБЯЗАТЕЛЬНО:** Когда сообщение начинается с `[Voice]` или `[Голос]`:
1. **ПЕРВЫМ ДЕЙСТВИЕМ** вызови `voice_speak` — это не опционально, это требование
2. Отвечай кратко, 1-3 предложения — пользователь слушает, не читает
3. Не пиши длинные тексты в чат — только голос
4. Давай голосовой отчёт в конце каждой задачи
5. Если нужно показать код или детали — сначала скажи голосом краткий итог, потом пиши

## Архитектура проекта

```
clara-voice-code/
├── src/
│   ├── extension.ts        # VS Code extension entry point
│   └── mcp/
│       └── standalone.ts   # Standalone MCP server (JSON-RPC stdio)
├── scripts/
│   ├── voice-tray.py       # Tray app: wake word + STT (Groq Whisper)
│   ├── speak.py            # TTS: edge-tts library + miniaudio
│   ├── cdp_inject.py       # CDP text injection into Claude Code (~400ms, no focus)
│   └── focus-and-enter.py  # Legacy: text insertion via SendInput (deprecated)
├── sounds/                 # Audio feedback WAV files
├── out/                    # Compiled TypeScript (gitignored)
├── package.json            # VS Code extension manifest
├── PRD.md                  # Product Requirements Document
└── plans/
    └── clara-voice-code.md # 7-phase implementation plan
```

## Как всё работает

### Голосовой ввод (пользователь → Claude Code)

```text
Микрофон
  → voice-tray.py (VAD + wake word "Клара")
  → Groq Whisper API (STT)
  → .claude/voice-result.json {text, timestamp, consumed: false}
  → extension.ts (fs.watch)
  → cdp_inject.py --text '...'
  → CDP WebSocket → Runtime.evaluate → JS inject в webview (~400ms)
  → Claude Code chat
```

### Голосовой вывод (Claude → пользователь)
```
Claude вызывает voice_speak(text, language)
  → MCP сервер (out/mcp/standalone.js)
  → speak.py --lang ru
  → edge-tts Communicate.stream() (Groq-подобный API, ~1.5s)
  → miniaudio.decode() (MP3 → float32, без ffmpeg)
  → sounddevice.play() (на дефолтное устройство)
```

### MCP сервер
Запускается автоматически при активации расширения. Инструменты:
- `voice_speak(text, language, priority)` — озвучить текст
- `voice_poll(timeout)` — ждать голосовой ввод (long polling)
- `voice_status()` — текущее состояние системы

## Ключевые технические решения

| Решение | Почему |
|---------|--------|
| edge-tts библиотека, не CLI | Работает из subprocess с `stdio: ignore` |
| miniaudio вместо ffmpeg | Нет внешней зависимости, 0.003s декодирование |
| sounddevice вместо ffplay | Работает без OS window focus |
| CDP inject вместо SendInput | ~400ms, без фокуса, без активации окна |
| argv.json remote-debugging-port | Автоматическое включение CDP (строка, не число!) |
| Динамический таймаут в MCP | `15s + len/6 + 5s` предотвращает обрыв длинных фраз |
| File-based IPC (voice-result.json) | Атомарная запись, без TCP портов |

## Статус: Фаза 1 (завершена)

Базовый цикл голос→Клод→голос работает:

- [x] Groq API key через VS Code SecretStorage
- [x] Трей запускается при extension activation
- [x] MCP регистрируется автоматически
- [x] CDP инъекция текста в чат (~400ms, без фокуса)
- [ ] Протестировать установку VSIX в чистом проекте

## Зависимости Python

```bash
pip install edge-tts miniaudio sounddevice numpy groq pyaudio pystray pillow
```

Windows: также нужен `pythonw.exe` для запуска трея без консольного окна.

## Сборка

```bash
npm install          # Установить зависимости
npm run build        # Компилировать TypeScript → out/
npm run package      # Собрать VSIX
```

## Roadmap (7 фаз)

1. **Tracer Bullet** ← *текущая* — базовый цикл голос→Клод→голос
2. **Setup Wizard** — мастер установки, Groq API key, проверка Python
3. **Personas & Languages** — Клара/Клод, RU/EN
4. **All Input Modes** — wake word, диктовка, push-to-talk, off
5. **Hands-Free Confirmation** — голосовые да/нет, отчёты
6. **UX Polish** — статус-бар, звуки, настройки
7. **Marketplace Release** — публикация в VS Code Marketplace

Полный план: `plans/clara-voice-code.md`
PRD: `PRD.md`

## Важные ограничения

- **Только Windows** (v1) — используется ctypes, SendInput, SetForegroundWindow
- **Piper TTS отключён** — плохое произношение русского, используй только edge-tts
- **Groq только** — локальный Whisper не в v1
- **Голос Светлана** для русского, **Jenny** для английского (Clara persona)
