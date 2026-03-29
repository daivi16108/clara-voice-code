# Clara Voice Code

Hands-free voice control for [Claude Code](https://claude.ai/code) in VS Code. Speak commands, hear responses. No keyboard needed.

## Features

- **Push-to-Talk** — Hold the button to record, release to send your voice command to Claude Code
- **Voice Responses** — Claude speaks back using natural TTS (edge-tts)
- **Wake Word** — Say "Clara" (or "Claude") to activate without touching anything
- **Auto Setup** — Extension installs all Python dependencies automatically on first launch
- **Fast Recognition** — Powered by Groq Whisper API (~1 second transcription)
- **No Focus Stealing** — Uses CDP injection to send text without switching windows (~400ms)

## How It Works

```
You speak -> Groq Whisper (STT) -> Claude Code -> Claude responds -> edge-tts (TTS) -> You hear
```

## Quick Start

1. **Install** this extension from VS Code Marketplace
2. **Get a free Groq API key** at [console.groq.com](https://console.groq.com/keys) — the setup wizard will prompt you
3. **Open the Push-to-Talk panel** — it appears in the bottom panel (next to Terminal)
4. **Hold the button** and speak your command
5. **Release** — your voice is transcribed and sent to Claude Code

> On first install, the extension automatically installs required Python packages and configures CDP for text injection. A VS Code restart may be required after initial setup.

## Requirements

- **Windows** (v1 — macOS/Linux support planned)
- **Python 3.10+** with pip
- **Groq API key** (free tier available at [console.groq.com](https://console.groq.com/keys))
- **Claude Code** extension for VS Code

## Voice Input Modes

| Mode | How it works |
|------|-------------|
| **Push-to-Talk** | Hold the PTT button in the panel, speak, release to send |
| **Wake Word** | Say "Clara" or "Claude", then speak your command |
| **Dictation** | All speech goes directly to Claude Code |
| **Off** | Microphone disabled |

## Voice Personas

| Persona | Wake Word | Russian Voice | English Voice |
|---------|-----------|---------------|---------------|
| **Clara** | "Clara" | Svetlana | Jenny |
| **Claude** | "Claude" | Dmitri | Guy |

Switch persona via Command Palette: `Clara Voice: Switch Persona`

## Commands

| Command | Description |
|---------|-------------|
| `Clara Voice: Push-to-Talk` | Toggle recording (also available as panel button) |
| `Clara Voice: Switch Persona` | Switch between Clara and Claude voices |
| `Clara Voice: Run Setup Wizard` | Re-run initial setup (API key, dependencies, CDP) |

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Shift+V` | Push-to-Talk toggle |

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `claraVoice.persona` | `clara` | Voice persona (clara / claude) |
| `claraVoice.language` | `ru` | Interface language (ru / en) |
| `claraVoice.mode` | `wakeWord` | Input mode (wakeWord / dictation / pushToTalk / off) |
| `claraVoice.ttsSpeed` | `1.2` | TTS speech speed (0.8 - 1.5) |
| `claraVoice.ttsVolume` | `75` | TTS volume (0 - 100) |
| `claraVoice.soundFeedback` | `true` | Play sound on wake word detection |

## Architecture

```
clara-voice-code/
  src/extension.ts       — VS Code extension (activation, PTT panel, CDP inject)
  src/mcp/standalone.ts  — MCP server (voice_speak, voice_poll, voice_status)
  scripts/voice-tray.py  — System tray (wake word, STT via Groq Whisper)
  scripts/speak.py       — TTS engine (edge-tts + miniaudio playback)
  scripts/cdp_inject.py  — CDP text injection into Claude Code webview
  sounds/                — Audio feedback WAV files
```

## Troubleshooting

**"cdp_inject failed"** — Restart VS Code. CDP needs `remote-debugging-port` in `~/.vscode/argv.json` (auto-configured by setup wizard).

**No sound on TTS** — Check that no other app is using the audio output device. Try adjusting `claraVoice.ttsVolume`.

**Microphone not detected** — Ensure Python has microphone access. Check Windows Privacy Settings > Microphone.

**Push-to-Talk button not visible** — Open the bottom panel (View > Panel) and look for the "Clara Voice" tab.

## License

MIT
