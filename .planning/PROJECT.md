# Clara Voice Code

## What This Is

VS Code расширение для полностью hands-free голосового управления Claude Code. Пользователь говорит команды, Clara распознаёт через Groq Whisper и отправляет в Claude Code. Claude отвечает голосом через edge-tts. Двусторонняя голосовая связь без рук, устанавливается одним кликом из VS Code Marketplace.

## Core Value

Разработчик говорит команду — Claude выполняет и отвечает голосом. Без рук, без клавиатуры.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Голосовой ввод: wake word "Клара"/"Claude", диктовка, push-to-talk
- [ ] Голосовой вывод: edge-tts (Светлана/RU, Jenny/EN)
- [ ] Две персоны: Клара (женский) и Клод (мужской)
- [ ] Два языка: русский и английский (авто-определение)
- [ ] MCP сервер авторегистрируется при установке расширения
- [ ] Мастер установки: Python check, pip install, Groq API key
- [ ] Groq API key через VS Code SecretStorage
- [ ] Статус-бар в VS Code (listening/processing/speaking/off)
- [ ] Голосовые подтверждения да/нет для действий Claude
- [ ] Трей приложение запускается автоматически с VS Code
- [ ] Публикация в VS Code Marketplace

### Out of Scope

- macOS / Linux — Windows only v1
- Диктовка в редактор кода — только в Claude Code chat
- Локальный Whisper — только Groq API
- Piper TTS — плохое произношение русского
- Кастомные голосовые модели — только edge-tts
- Мульти-оконный режим — один VS Code одновременно
- Voice commands для VS Code — только Claude Code

## Context

Проект создан из прототипа VoiceCoding. VSIX 0.1.0 уже собирается (42.6KB). Архитектура проверена: edge-tts + miniaudio + sounddevice работает без ffmpeg, focus-and-enter.py вставляет текст за ~150ms, file-based IPC через voice-result.json атомарен.

Ключевые технические решения зафиксированы: edge-tts библиотека (не CLI), miniaudio вместо ffmpeg, sounddevice вместо ffplay, PostMessage для Enter, динамический таймаут MCP (15s + len/6 + 5s).

## Constraints

- **Platform**: Windows only v1 — используется ctypes, SendInput, SetForegroundWindow
- **STT**: Groq Whisper только — требует интернет и API key
- **TTS**: edge-tts только — требует интернет (Microsoft API, бесплатно)
- **Python**: 3.10+ обязателен — sounddevice, edge-tts, miniaudio, groq, pystray
- **Voice RU**: Голос Светлана (Clara), Дмитрий (Claude)
- **Voice EN**: Jenny (Clara), Guy (Claude)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| edge-tts библиотека, не CLI | Работает из subprocess с `stdio: ignore` | ✓ Good |
| miniaudio вместо ffmpeg | Нет внешней зависимости, 0.003s декодирование | ✓ Good |
| sounddevice вместо ffplay | Работает без OS window focus | ✓ Good |
| PostMessage для Enter | Не требует SetForegroundWindow | ✓ Good |
| --fast mode focus-and-enter.py | ~150ms focus steal вместо ~2.7s | ✓ Good |
| File-based IPC voice-result.json | Атомарная запись, без TCP портов | ✓ Good |
| Динамический таймаут MCP | 15s + len/6 + 5s предотвращает обрыв длинных фраз | ✓ Good |
| Piper TTS отключён | Плохое произношение русского | ✓ Good |

---
*Last updated: 2026-03-27 — initial GSD setup*
