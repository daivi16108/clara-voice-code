# Changelog

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
