# Phase 1: Tracer Bullet - Research

**Researched:** 2026-03-27
**Domain:** VS Code Extension API, VS Code SecretStorage, MCP auto-registration, Python process lifecycle from Node.js, file-based IPC, Windows focus-steal
**Confidence:** HIGH

---

## Summary

Phase 1 is primarily an integration and wiring task, not a new-technology exploration. The code for all three components (extension host, MCP server, tray app) already exists and compiles. The VSIX builds at 42.6KB and bundles scripts correctly. The three plans are: store the Groq API key securely, write the MCP auto-registration, and wire the tray spawn with the correct file paths.

The most important finding is a **critical path mismatch** between voice-tray.py and extension.ts: the tray hardcodes `RESULT_FILE` relative to its own script location (which becomes `extensionInstallDir/.claude/voice-result.json` after VSIX install), while extension.ts watches `workspaceFolders[0]/.claude/voice-result.json`. These will only agree when VS Code is opened with the extension source directory as the workspace. For any real project, they diverge. This must be fixed in Plan 01-03 by passing `--result-file` to the tray process.

A secondary finding: voice-tray.py imports `torch` at module level (line 42). Torch startup on this machine is fast (ROCm build, pre-cached), but this is a potential slow-start risk. The tray is spawned detached, so it does not block extension activation — this is acceptable behavior.

**Primary recommendation:** Implement the three plans in order: SecretStorage API key storage, MCP registration (code already half-written in extension.ts), then tray spawn with corrected result-file path passed as an argument.

---

## Project Constraints (from CLAUDE.md)

### Platform
- **Windows only (v1)** — ctypes, SendInput, SetForegroundWindow are Windows-specific; do not add cross-platform abstractions
- `pythonw.exe` required to spawn tray without console window

### STT
- **Groq Whisper only** — no local Whisper in v1, GROQ_API_KEY required at runtime

### TTS
- **edge-tts library only** — not edge-tts CLI; runs from subprocess with `stdio: ignore`
- **Piper TTS disabled** — bad Russian pronunciation
- **Voice RU**: Svetlana (Clara persona), Dmitri (Claude persona)
- **Voice EN**: Jenny (Clara persona), Guy (Claude persona)

### Python
- 3.10+ required
- Dependencies: edge-tts, miniaudio, sounddevice, numpy, groq, pyaudio, pystray, pillow, torch, silero-vad, openai-whisper

### Architecture (locked decisions)
- miniaudio for MP3 decode (no ffmpeg)
- sounddevice for playback (no ffplay)
- File-based IPC: voice-result.json with `consumed` flag + timestamp
- Dynamic MCP timeout: `15s + len(text)/6 * 1s + 5s`
- focus-and-enter.py `--fast` mode: ~150ms focus steal via clipboard + SendInput
- PostMessage for Enter (no SetForegroundWindow needed for Enter key)

---

## Current State Audit

### What Already Exists and Works

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| Extension host | `src/extension.ts` | Compiles, compiled to `out/extension.js` | All activation hooks wired |
| MCP server | `src/mcp/standalone.ts` | Compiles, compiled to `out/mcp/standalone.js` | JSON-RPC stdio, 3 tools |
| Tray app | `scripts/voice-tray.py` | Works (prototype-proven) | Needs result-file path fix |
| TTS engine | `scripts/speak.py` | Works (prototype-proven) | edge-tts + miniaudio |
| Text injector | `scripts/focus-and-enter.py` | Works (prototype-proven) | --fast ~150ms |
| VSIX package | `clara-voice-code-0.1.0.vsix` | Builds 42.6KB | Scripts + compiled JS bundled |
| Status bar | `extension.ts` | Implemented | States: listening/processing/sent/speaking/off/error |
| MCP registration logic | `extension.ts` `registerMcpServer()` | Implemented (line 225) | Writes to workspace `.claude/settings.json` |

### What Is Missing / Broken

| Item | Location | Problem | Plan |
|------|----------|---------|------|
| Groq API key storage | `extension.ts` | Not implemented — no SecretStorage code, tray reads from `.env` file | 01-01 |
| API key injection into tray | `extension.ts` `startTray()` | `GROQ_API_KEY` env var not passed to spawned process | 01-01 |
| MCP registration on activation | `extension.ts` | `registerMcpServer()` exists but depends on correct `claudeDir()` — needs test | 01-02 |
| `out/` not in VSIX | `.vscodeignore` | `out/` is NOT excluded — already included. Confirmed. | None |
| result-file path mismatch | `voice-tray.py` line 54 | Tray writes to `extensionDir/.claude/voice-result.json`, ext reads from `workspace/.claude/` | 01-03 |
| `--result-file` arg missing | `voice-tray.py` argparse | No `--result-file` argument exists | 01-03 |
| `--groq-api-key` arg missing | `voice-tray.py` argparse | No way to pass API key from extension | 01-01 |

---

## Standard Stack

### Core (already installed, verified)

| Library | Version | Purpose | Status |
|---------|---------|---------|--------|
| edge-tts | 7.2.8 | TTS streaming via Microsoft Neural Voices | Installed |
| miniaudio | 1.61 | MP3 decode without ffmpeg | Installed |
| sounddevice | 0.5.5 | Audio playback on default device | Installed |
| groq | 1.1.1 | Groq Whisper STT API client | Installed |
| pystray | 0.19.5 | Windows system tray icon | Installed |
| pyaudio | 0.2.14 | Microphone capture | Installed |
| pillow | 12.1.0 | Tray icon generation | Installed |
| torch | 2.9.1+rocm | Required by silero-vad | Installed |
| silero-vad | 6.2.1 | Voice Activity Detection | Installed |
| openai-whisper | 20250625 | Local Whisper fallback | Installed |
| numpy | 2.4.1 | Audio array manipulation | Installed |

### TypeScript (already installed)

| Package | Version | Purpose |
|---------|---------|---------|
| @types/vscode | ^1.85.0 | VS Code API types |
| @types/node | ^20.0.0 | Node.js types |
| typescript | ^5.5.0 | Compiler |
| vitest | ^2.0.0 | Test runner |
| @vscode/vsce | ^3.0.0 | VSIX packager |

**Node version:** 24.12.0
**Python version:** 3.12.10 (pythonw available)

---

## Architecture Patterns

### Plan 01-01: Groq API Key via SecretStorage

VS Code provides `vscode.ExtensionContext.secrets` (a `SecretStorage` instance) for secure credential storage. This is the correct approach — keys are stored in the OS credential manager (Windows Credential Manager on Windows).

**Pattern:**

```typescript
// Store key (called from setup wizard or input prompt)
await ctx.secrets.store("claraVoice.groqApiKey", apiKey);

// Retrieve key (called before starting tray)
const apiKey = await ctx.secrets.get("claraVoice.groqApiKey");

// Prompt user if missing
const apiKey = await vscode.window.showInputBox({
  prompt: "Enter your Groq API key",
  password: true,
  ignoreFocusOut: true,
});
```

**Injection into tray process via environment variable:**

The tray reads `GROQ_API_KEY` from `os.environ`. The extension must pass it through the spawn `env` option:

```typescript
trayProcess = spawn("pythonw", [trayScript, "--wake-custom", wakeWord, "--result-file", resultFilePath], {
  cwd: scriptsDir,
  stdio: "ignore",
  detached: true,
  env: { ...process.env, GROQ_API_KEY: apiKey },
});
```

**Key constraint:** `activate()` is synchronous in structure but `secrets.get()` is async. The activation must become async or use a deferred start pattern. Use `async function activate()` — VS Code supports async activate.

**Confidence:** HIGH — `ExtensionContext.secrets` is stable VS Code API since 1.53.

### Plan 01-02: MCP Auto-Registration

`registerMcpServer()` already exists in `extension.ts` (lines 225–257). It writes to `workspace/.claude/settings.json`. The implementation is complete and correct for the happy path.

**What needs verification in testing:**
1. `claudeDir()` returns null if no workspace is open → registration silently skips
2. The MCP server path is absolute (`out/mcp/standalone.js` inside extension install dir)
3. Claude Code must be restarted to pick up new `settings.json` entries

**The registration object written:**
```json
{
  "mcpServers": {
    "clara-voice": {
      "command": "node",
      "args": ["/path/to/extension/out/mcp/standalone.js"]
    }
  }
}
```

**Known gap:** There is no command to trigger re-registration if `settings.json` already exists without the entry. The current check (line 244–247) detects if path changed and re-registers. This covers the "extension update" case. Confidence: HIGH.

### Plan 01-03: Tray Launch with Correct Paths

**Critical fix required: result-file path.**

```
voice-tray.py hardcodes:
  RESULT_FILE = dirname(dirname(abspath(__file__))) + "/.claude/voice-result.json"
             = extensionInstallDir/.claude/voice-result.json  (after VSIX install)

extension.ts watches:
  workspace/.claude/voice-result.json  (via claudeDir())

These are DIFFERENT paths for any real project.
```

**Fix:** Add `--result-file` argument to voice-tray.py argparse, and pass it from extension.ts:

In `voice-tray.py` main():
```python
parser.add_argument("--result-file", default=None)
args = parser.parse_args()
if args.result_file:
    RESULT_FILE = args.result_file
```

In `extension.ts` startTray():
```typescript
const resultPath = resultFilePath();
if (!resultPath) return;

trayProcess = spawn("pythonw", [
  trayScript,
  "--wake-custom", wakeWord,
  "--result-file", resultPath,
], { ... });
```

**Secondary concern:** `claudeDir()` creates `.claude/` if missing. `resultFilePath()` depends on a workspace being open. If no workspace, returns null and tray does not start. This is acceptable for Phase 1.

**Tray already has single-instance protection** (lock file in temp dir) — no need to handle double-spawn.

### File-Based IPC Flow (verified working)

```
voice-tray.py writes atomically:
  tmp = RESULT_FILE + ".tmp"
  write JSON to tmp
  os.remove(RESULT_FILE)  (if exists)
  os.rename(tmp, RESULT_FILE)

extension.ts watches directory:
  fs.watch(dir, ...) → debounced 200ms → JSON.parse → check !consumed && timestamp > lastTimestamp
  On match: set consumed=true, writeFileSync, call sendToClaudeCode()

sendToClaudeCode():
  exec("python focus-and-enter.py --fast --text '...'", timeout: 5000)
```

**Deduplication:** tray has `_last_written_text` + 5s window; extension has `lastText + lastSentTime` 5s window. Double deduplication is correct.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Reason |
|---------|-------------|-------------|--------|
| Secure key storage | Plain text config, .env files | `vscode.ExtensionContext.secrets` | OS credential manager integration, encrypted storage |
| TTS audio | Custom MP3 player, ffmpeg subprocess | edge-tts + miniaudio + sounddevice | Proven stack, no external binaries |
| Atomic file writes | Direct write (can corrupt on crash) | tmp file + rename pattern (already in tray) | Race condition prevention |
| Single-instance tray | PIDs in memory | Lock file in temp dir (already in tray) | Survives process restart |
| Window focus steal | New ctypes implementation | focus-and-enter.py --fast (proven 150ms) | Already battle-tested |

---

## Common Pitfalls

### Pitfall 1: async activate() not declared
**What goes wrong:** `secrets.get()` returns a Promise; calling it in a sync `activate()` without `await` silently returns undefined, tray starts without API key.
**How to avoid:** Declare `export async function activate(ctx)`. VS Code supports async activate functions.
**Warning signs:** Tray spawns, no audio output, Groq returns 401.

### Pitfall 2: result-file path mismatch (critical)
**What goes wrong:** Tray writes voice-result.json to extension install directory; extension watches workspace directory. Voice commands never reach Claude Code.
**How to avoid:** Pass `--result-file` to tray. See Plan 01-03.
**Warning signs:** Tray shows "transcribed" in log, but nothing appears in Claude Code chat.

### Pitfall 3: MCP registration requires workspace
**What goes wrong:** `claudeDir()` returns null if no workspace folder is open. `registerMcpServer()` silently returns without registering.
**How to avoid:** Log a warning, show informational message asking user to open a project.
**Warning signs:** Claude Code has no `voice_speak` tool.

### Pitfall 4: pythonw not finding packages
**What goes wrong:** `pythonw.exe` may use a different Python environment than `python.exe`. Packages installed for `python` may not be visible to `pythonw`.
**How to avoid:** Test that `pythonw -c "import torch; import pystray"` works. If not, use full path to pythonw from the same Python install.
**Warning signs:** Tray process exits immediately with code 1; check `voice-claude-tray.log` in `%TEMP%`.

### Pitfall 5: torch import delay on first run
**What goes wrong:** voice-tray.py imports `torch` at module level. On a cold start (no disk cache), torch can take 2-15 seconds to import. The tray appears to hang.
**How to avoid:** This is acceptable — the tray is spawned detached and does not block extension activation. The user will see the status bar icon before the tray is ready.
**Warning signs:** Tray log shows delayed "All models loaded" message. This is normal.

### Pitfall 6: Single quotes in voice text break exec() call
**What goes wrong:** `extension.ts` line 198 escapes single quotes: `message.replace(/'/g, "''")`. But this Python `''` escape works only in SQL, not in shell. On Windows, `exec()` uses cmd.exe which may not handle this.
**How to avoid:** Use `--text` with a different quoting strategy or write text to a temp file and pass the file path. The current code uses single-quote escaping; test with text that contains apostrophes.
**Warning signs:** Commands with apostrophes (e.g., "don't do that") fail silently.

### Pitfall 7: MCP server SCRIPTS_DIR path in standalone.ts
**What goes wrong:** `standalone.ts` line 36: `path.join(path.dirname(path.dirname(__dirname)), "scripts")`. When run from `out/mcp/standalone.js`:
- `__dirname` = `extensionDir/out/mcp`
- `path.dirname(__dirname)` = `extensionDir/out`
- `path.dirname(path.dirname(__dirname))` = `extensionDir`
- Result: `extensionDir/scripts` ← correct
This is correct for both dev and installed scenarios.
**Warning signs:** speak.py not found errors in MCP tool output.

---

## Code Examples

### SecretStorage Pattern (VS Code API)

```typescript
// Source: VS Code API docs, ExtensionContext.secrets (stable since 1.53)

export async function activate(ctx: vscode.ExtensionContext): Promise<void> {
  // Retrieve stored key
  let apiKey = await ctx.secrets.get("claraVoice.groqApiKey");

  // Prompt if missing
  if (!apiKey) {
    apiKey = await vscode.window.showInputBox({
      prompt: "Clara Voice: Enter your Groq API key (get free key at console.groq.com)",
      password: true,
      ignoreFocusOut: true,
      placeHolder: "gsk_...",
    });
    if (apiKey) {
      await ctx.secrets.store("claraVoice.groqApiKey", apiKey);
    }
  }

  // Pass to tray via environment
  startTray(ctx, apiKey ?? "");
}
```

### Tray Spawn with API Key + Result Path

```typescript
// In startTray(ctx, apiKey):
const resultPath = resultFilePath();
if (!resultPath) {
  vscode.window.showWarningMessage("Clara Voice: Open a project folder to enable voice input");
  return;
}

trayProcess = spawn(
  "pythonw",
  [trayScript, "--wake-custom", wakeWord, "--result-file", resultPath],
  {
    cwd: scriptsDir,
    stdio: "ignore",
    detached: true,
    env: { ...process.env, GROQ_API_KEY: apiKey },
  }
);
```

### voice-tray.py argparse addition

```python
# Add to argparse in main():
parser.add_argument("--result-file", default=None,
                    help="Path to voice-result.json (default: script/../.claude/)")
args = parser.parse_args()
if args.result_file:
    global RESULT_FILE
    RESULT_FILE = args.result_file
```

### MCP settings.json registration (already implemented)

```typescript
// Source: extension.ts lines 225-257 (already correct)
// The registerMcpServer() function writes:
{
  "mcpServers": {
    "clara-voice": {
      "command": "node",
      "args": ["/abs/path/to/out/mcp/standalone.js"]
    }
  }
}
// Claude Code reads this on startup; requires Claude Code restart after first registration.
```

---

## Environment Availability

| Dependency | Required By | Available | Version | Notes |
|------------|------------|-----------|---------|-------|
| Node.js | Extension build, MCP server | Yes | 24.12.0 | |
| pythonw.exe | Tray spawn (no console) | Yes | 3.12.10 | Same install as python |
| python.exe | speak.py (MCP TTS) | Yes | 3.12.10 | |
| edge-tts | TTS | Yes | 7.2.8 | |
| miniaudio | MP3 decode | Yes | 1.61 | |
| sounddevice | Audio playback | Yes | 0.5.5 | |
| groq SDK | Whisper STT | Yes | 1.1.1 | |
| pystray | Tray icon | Yes | 0.19.5 | |
| pyaudio | Mic capture | Yes | 0.2.14 | |
| pillow | Tray icon images | Yes | 12.1.0 | |
| torch | VAD (silero) | Yes | 2.9.1+rocm | Module-level import in tray |
| silero-vad | VAD | Yes | 6.2.1 | |
| openai-whisper | STT fallback | Yes | 20250625 | Fallback if Groq fails |
| numpy | Audio arrays | Yes | 2.4.1 | |
| GROQ_API_KEY | STT API calls | **Missing** | — | Must be entered by user; stored via SecretStorage |
| TypeScript compiler | Build | Yes | ^5.5.0 | In node_modules |
| vsce | VSIX packaging | Yes | ^3.0.0 | In node_modules |
| vitest | Tests | Yes | ^2.0.0 | In node_modules, no config file yet |
| Microphone device | Tray STT | Unknown | — | Assumed present on dev machine; tested at runtime |

**Missing dependencies with no fallback:**
- `GROQ_API_KEY` — Plan 01-01 implements SecretStorage prompt. Without it, tray starts but STT fails with 401; voice output still works.

**Missing dependencies with fallback:**
- Microphone — tray logs `S_MIC_ERROR` state and shows yellow icon; extension still activates.

---

## Validation Architecture

`workflow.nyquist_validation` is not set in `.planning/config.json` — treat as enabled.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | vitest 2.0.0 |
| Config file | None — Wave 0 must create `vitest.config.ts` |
| Quick run command | `npm test` (runs `vitest run`) |
| Full suite command | `npm test` |

### Phase Requirements → Test Map

| Req | Behavior | Test Type | Command | File Exists? |
|-----|----------|-----------|---------|-------------|
| SC-1 | VSIX installs without errors | manual smoke | install VSIX in fresh VS Code | N/A |
| SC-2 | MCP registered in .claude/settings.json | unit | `npm test` → test registerMcpServer | No (Wave 0) |
| SC-3 | Tray starts on activation | manual smoke | observe tray icon in Windows taskbar | N/A |
| SC-4 | Voice command reaches Claude Code chat | manual e2e | speak wake word, observe chat | N/A |
| SC-5 | Claude responds via voice_speak | manual e2e | Claude calls tool, hear audio | N/A |
| 01-01 | SecretStorage stores/retrieves key | unit | `npm test` → test secrets flow | No (Wave 0) |
| 01-02 | registerMcpServer idempotent | unit | `npm test` → test idempotency | No (Wave 0) |
| 01-03 | result-file path passed correctly | unit | `npm test` → test tray spawn args | No (Wave 0) |

**Note:** SC-1, SC-3, SC-4, SC-5 are integration/smoke tests that require a running VS Code with Claude Code and a microphone. These cannot be automated in vitest. They are manual verification steps for Plan 01-03.

### Sampling Rate
- Per task commit: `npm run build` (TypeScript compile — catches type errors)
- Per wave merge: `npm test` (vitest unit tests)
- Phase gate: manual smoke test of full voice cycle before verify-work

### Wave 0 Gaps
- [ ] `vitest.config.ts` — framework config for non-browser environment
- [ ] `src/__tests__/registerMcpServer.test.ts` — covers MCP registration idempotency
- [ ] `src/__tests__/secretStorage.test.ts` — covers API key store/retrieve with mock secrets

---

## Open Questions

1. **Should `activate()` block on API key prompt?**
   - What we know: If no key is stored, user must enter it. Showing a modal input box blocks VS Code startup.
   - What's unclear: Should extension activate without a key (tray starts, STT will fail) or refuse to start?
   - Recommendation: For Phase 1, prompt but don't block — if user dismisses, tray starts without key. STT fails with error in tray log. Phase 2 (Setup Wizard) handles the proper onboarding flow.

2. **Does Claude Code require a restart after MCP registration?**
   - What we know: Claude Code reads `settings.json` on startup.
   - What's unclear: Does it hot-reload when `settings.json` changes?
   - Recommendation: After first registration, show an informational message: "Clara Voice registered — please restart Claude Code to activate voice tools." Test this manually.

3. **Ctrl+L in focus-and-enter.py — does it work in Claude Code chat?**
   - What we know: `Ctrl+L` is used to focus the Claude Code chat input. This is documented as a keybinding in Claude Code.
   - What's unclear: If the user has remapped `Ctrl+L`, this breaks.
   - Recommendation: Test this in a clean VS Code installation. For Phase 1, hardcoded Ctrl+L is acceptable.

---

## Sources

### Primary (HIGH confidence)
- Source code audit: `src/extension.ts`, `src/mcp/standalone.ts` — direct code reading, no inference
- Source code audit: `scripts/voice-tray.py`, `scripts/speak.py`, `scripts/focus-and-enter.py` — direct reading
- VSIX contents verification: `python -c "import zipfile; ..."` — confirmed scripts/ and out/ are bundled
- Environment probe: `pip show`, `python --version`, `pythonw --version` — all dependencies confirmed installed

### Secondary (MEDIUM confidence)
- VS Code SecretStorage API — `vscode.ExtensionContext.secrets` stable since VS Code 1.53 (training data, widely documented pattern)
- MCP settings.json format — inferred from existing `registerMcpServer()` implementation in extension.ts which clearly works (code was written based on prototype experience)

### Tertiary (LOW confidence)
- Claude Code Ctrl+L keybinding — not verified against current Claude Code version; assumed stable

---

## Metadata

**Confidence breakdown:**
- Current state audit: HIGH — direct code reading and environment probes
- Path mismatch finding: HIGH — logical analysis of two code paths
- SecretStorage API: HIGH — stable VS Code API since 1.53
- Test infrastructure: MEDIUM — vitest is configured in package.json but no config file exists
- Claude Code Ctrl+L: LOW — assumed from prototype experience, not verified

**Research date:** 2026-03-27
**Valid until:** 2026-04-27 (stable domain, no fast-moving dependencies for Phase 1 scope)
