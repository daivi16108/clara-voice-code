# Changelog

## [0.9.9] - 2026-03-29

### Fixed
- MCP path guard: detects and auto-restores stable MCP path if overwritten by old extension versions in other VS Code windows
- Uses fs.watch + 30s interval to prevent stale versioned paths from breaking voice tools

## [0.10.5] - 2026-03-29

### Fixed
- MCP registers in `~/.claude.json` (primary) — Claude Code reads MCP config from here
- Scripts (speak.py etc.) copied to stable `~/.clara-voice/scripts/` path
- MCP path guard watches both `~/.claude.json` and `~/.claude/settings.json`
- Mute button in inline mode (CDP inject) — was missing, now injected alongside mic and dictation
- Mute toggle no longer triggers phantom voice recording in tray
- Unified icon style: all three buttons use SVG stroke icons 20x20

### Added
- Mute TTS button in inline chat mode (next to mic and dictation buttons)
- Speaker icon with sound waves (unmuted) / speaker with X (muted)

## [0.9.8] - 2026-03-29

### Added
- Mute TTS button in PTT panel — toggle voice responses on/off
- When muted, voice_speak returns "TTS muted" so Claude adapts to text-only mode
- Status bar shows mute indicator when TTS is disabled
- voice_status reports tts_muted state

## [0.9.7] - 2026-03-29

### Added
- LICENSE (MIT) for Marketplace compliance
- CHANGELOG.md with version history
- GitHub repository link in package.json

## [0.9.6] - 2026-03-29

### Fixed
- MCP server path registration now uses normalized forward slashes, preventing stale versioned paths from breaking voice tools across sessions

## [0.9.5] - 2026-03-29

### Added
- Push-to-Talk webview panel with hold-to-record UX
- CDP-based text injection into Claude Code chat (~400ms, no focus stealing)
- Status bar indicator with recording state

### Changed
- MCP server deployed to stable path `~/.clara-voice/mcp/` instead of versioned extension directory

## [0.5.9] - 2026-03-28

### Added
- Initial release
- Groq Whisper STT integration (free API, ~1s transcription)
- edge-tts voice responses with miniaudio playback
- MCP server with `voice_speak`, `voice_poll`, `voice_ask`, `voice_status` tools
- Wake word detection ("Clara" / "Claude")
- System tray app with VAD (voice activity detection)
- Auto-registration of MCP server in Claude Code settings
- Groq API key storage via VS Code SecretStorage
