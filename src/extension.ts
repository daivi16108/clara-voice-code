import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";
import * as os from "os";
import { ChildProcess, spawn, exec } from "child_process";

let trayProcess: ChildProcess | null = null;
let pttListenerProcess: ChildProcess | null = null;
let statusBar: vscode.StatusBarItem | null = null;
let resultWatcher: fs.FSWatcher | null = null;
let lastTimestamp = 0;
let lastText = "";
let lastSentTime = 0;
let ttsMuted = false; // Ephemeral — resets on restart

// ---------------------------------------------------------------------------
// Debug log (same file as Python, merged timeline)
// ---------------------------------------------------------------------------
const LOG_FILE = path.join(os.tmpdir(), "voice-claude-enter.log");
function dlog(msg: string) {
  const ts = new Date().toTimeString().slice(0, 8);
  try { fs.appendFileSync(LOG_FILE, `[${ts}] EXT: ${msg}\n`); } catch {}
}

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------

function extensionScriptsDir(ctx: vscode.ExtensionContext): string {
  return path.join(ctx.extensionPath, "scripts");
}

function claudeDir(): string | null {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) return null;
  const dir = path.join(folders[0].uri.fsPath, ".claude");
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
  return dir;
}

function resultFilePath(): string | null {
  const dir = claudeDir();
  return dir ? path.join(dir, "voice-result.json") : null;
}

// ---------------------------------------------------------------------------
// Push-to-Talk WebviewView (mousedown/mouseup support)
// ---------------------------------------------------------------------------

type PttState = "loading" | "ready" | "recording" | "processing" | "sent" | "error";

const i18n = {
  ru: {
    loading: "Загрузка...",
    holdToTalk: "Зажми и говори",
    recording: "Запись...",
    sending: "Отправка...",
    sent: "Отправлено!",
    error: "Ошибка",
    mute: "Без звука",
    unmute: "Со звуком",
    statusLoading: "$(sync~spin) Загрузка",
    statusReady: "$(mic) Голос",
    statusRec: "$(primitive-dot) ЗАПИСЬ",
    statusSending: "$(sync~spin) Отправка",
    statusSent: "$(check) Отправлено",
    statusError: "$(warning) Ошибка",
    tooltipLoading: "Загрузка моделей...",
    tooltipReady: "Push to Talk — готов",
    tooltipRec: "Идёт запись...",
    tooltipSending: "Обработка голоса...",
  },
  en: {
    loading: "Loading...",
    holdToTalk: "Hold to Talk",
    recording: "Recording...",
    sending: "Sending...",
    sent: "Sent!",
    error: "Error",
    mute: "Mute TTS",
    unmute: "Unmute TTS",
    statusLoading: "$(sync~spin) Loading",
    statusReady: "$(mic) Voice",
    statusRec: "$(primitive-dot) REC",
    statusSending: "$(sync~spin) Sending",
    statusSent: "$(check) Sent",
    statusError: "$(warning) Error",
    tooltipLoading: "Loading models...",
    tooltipReady: "Push to Talk ready",
    tooltipRec: "Recording...",
    tooltipSending: "Processing voice...",
  },
};

function getLang(): "ru" | "en" {
  const config = vscode.workspace.getConfiguration("claraVoice");
  return config.get<string>("language", "en") === "en" ? "en" : "ru";
}

function t() { return i18n[getLang()]; }

class PttViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewTypePanel = "claraVoice.pttViewPanel";
  public static readonly viewTypeSidebar = "claraVoice.pttViewSidebar";
  private _view?: vscode.WebviewView;
  private _onPttStart: () => void;
  private _onPttStop: () => void;
  private _currentState: PttState;

  constructor(onStart: () => void, onStop: () => void, initialState: PttState = "loading") {
    this._onPttStart = onStart;
    this._onPttStop = onStop;
    this._currentState = initialState;
  }

  resolveWebviewView(view: vscode.WebviewView) {
    this._view = view;
    view.webview.options = { enableScripts: true };
    // Render with current state (may have changed from "loading" to "ready" before view resolved)
    view.webview.html = this._getHtml(this._currentState);

    view.webview.onDidReceiveMessage((msg) => {
      if (msg.type === "ptt_start") {
        this._onPttStart();
        this.setState("recording");
      } else if (msg.type === "ptt_stop") {
        this._onPttStop();
        this.setState("processing");
      } else if (msg.type === "tts_mute_toggle") {
        ttsMuted = !ttsMuted;
        syncMuteState();
        this._view?.webview.postMessage({ type: "mute_state", muted: ttsMuted });
      }
    });
  }

  setState(state: PttState) {
    this._currentState = state;
    const l = t();
    this._view?.webview.postMessage({ type: "state", state, labels: {
      loading: l.loading, ready: l.holdToTalk, recording: l.recording,
      processing: l.sending, sent: l.sent, error: l.error,
      mute: l.mute, unmute: l.unmute,
    }});
    if (statusBar) {
      switch (state) {
        case "loading":
          statusBar.text = l.statusLoading;
          statusBar.tooltip = l.tooltipLoading;
          statusBar.color = undefined;
          statusBar.backgroundColor = undefined;
          break;
        case "ready":
          statusBar.text = ttsMuted ? `${l.statusReady} $(mute)` : l.statusReady;
          statusBar.tooltip = l.tooltipReady;
          statusBar.color = undefined;
          statusBar.backgroundColor = undefined;
          break;
        case "recording":
          statusBar.text = l.statusRec;
          statusBar.tooltip = l.tooltipRec;
          statusBar.color = new vscode.ThemeColor("statusBarItem.warningForeground");
          statusBar.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
          break;
        case "processing":
          statusBar.text = l.statusSending;
          statusBar.tooltip = l.tooltipSending;
          statusBar.color = undefined;
          statusBar.backgroundColor = undefined;
          break;
        case "sent":
          statusBar.text = l.statusSent;
          statusBar.color = undefined;
          statusBar.backgroundColor = undefined;
          setTimeout(() => this.setState("ready"), 2000);
          break;
        case "error":
          statusBar.text = l.statusError;
          statusBar.color = undefined;
          statusBar.backgroundColor = undefined;
          setTimeout(() => this.setState("ready"), 3000);
          break;
      }
    }
  }

  refreshLanguage() {
    if (this._view) {
      this._view.webview.html = this._getHtml("ready");
    }
    this.setState("ready");
  }

  private _getHtml(initialState: PttState): string {
    const initialMuted = ttsMuted;
    return /*html*/ `<!DOCTYPE html>
<html><head><style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    display: flex; justify-content: center; align-items: center;
    height: 100vh; background: transparent;
    font-family: var(--vscode-font-family);
    user-select: none; -webkit-user-select: none;
  }
  .controls { display: flex; gap: 8px; width: 100%; }
  #ptt {
    flex: 1; padding: 12px 16px;
    border: 2px solid var(--vscode-button-border, var(--vscode-button-background));
    border-radius: 6px;
    background: var(--vscode-button-background);
    color: var(--vscode-button-foreground);
    font-size: 13px; font-weight: 600;
    cursor: pointer; transition: all 0.15s;
    display: flex; align-items: center; justify-content: center; gap: 8px;
  }
  #ptt:hover:not(.loading) { background: var(--vscode-button-hoverBackground); }
  #ptt.loading { opacity: 0.5; cursor: wait; pointer-events: none; }
  #ptt.recording {
    background: var(--vscode-inputValidation-errorBackground, #d32f2f);
    border-color: var(--vscode-inputValidation-errorBorder, #f44336);
    animation: pulse 1s infinite;
  }
  #ptt.processing { opacity: 0.7; cursor: wait; }
  #ptt.sent { background: var(--vscode-testing-iconPassed, #388e3c); }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; }
  }
  .dot { width: 10px; height: 10px; border-radius: 50%; }
  .dot.ready { background: var(--vscode-button-foreground); }
  .dot.recording { background: #ff5252; }
  #mute-btn {
    padding: 12px 12px;
    border: 2px solid var(--vscode-button-border, var(--vscode-button-background));
    border-radius: 6px;
    background: var(--vscode-button-secondaryBackground);
    color: var(--vscode-button-secondaryForeground);
    font-size: 13px; cursor: pointer; transition: all 0.15s;
    display: flex; align-items: center; justify-content: center;
    min-width: 40px;
  }
  #mute-btn:hover { background: var(--vscode-button-secondaryHoverBackground); }
  #mute-btn.muted {
    background: var(--vscode-inputValidation-warningBackground, #f9a825);
    border-color: var(--vscode-inputValidation-warningBorder, #fdd835);
    color: var(--vscode-inputValidation-warningForeground, #000);
  }
</style></head><body>
  <div class="controls">
    <button id="ptt" class="${initialState}">
      <span class="dot ${initialState}" id="dot"></span>
      <span id="label">${initialState === "loading" ? t().loading : t().holdToTalk}</span>
    </button>
    <button id="mute-btn" class="${initialMuted ? 'muted' : ''}" title="${initialMuted ? t().unmute : t().mute}">
      ${initialMuted ? '&#x1F507;' : '&#x1F50A;'}
    </button>
  </div>
  <script>
    const vscode = acquireVsCodeApi();
    const btn = document.getElementById('ptt');
    const dot = document.getElementById('dot');
    const label = document.getElementById('label');
    const muteBtn = document.getElementById('mute-btn');
    let state = '${initialState}';
    let muted = ${initialMuted ? 'true' : 'false'};

    function startRec() {
      if (state !== 'ready') return;
      vscode.postMessage({ type: 'ptt_start' });
    }
    function stopRec() {
      if (state !== 'recording') return;
      vscode.postMessage({ type: 'ptt_stop' });
    }

    btn.addEventListener('mousedown', (e) => { e.preventDefault(); startRec(); });
    btn.addEventListener('mouseup', (e) => { e.preventDefault(); stopRec(); });
    btn.addEventListener('mouseleave', () => { if (state === 'recording') stopRec(); });
    btn.addEventListener('touchstart', (e) => { e.preventDefault(); startRec(); });
    btn.addEventListener('touchend', (e) => { e.preventDefault(); stopRec(); });

    // Keyboard: Space/Enter held
    btn.addEventListener('keydown', (e) => {
      if ((e.code === 'Space' || e.code === 'Enter') && !e.repeat) {
        e.preventDefault(); startRec();
      }
    });
    btn.addEventListener('keyup', (e) => {
      if (e.code === 'Space' || e.code === 'Enter') {
        e.preventDefault(); stopRec();
      }
    });

    muteBtn.addEventListener('click', () => {
      vscode.postMessage({ type: 'tts_mute_toggle' });
    });

    let labels = {
      loading: '${t().loading}',
      ready: '${t().holdToTalk}',
      recording: '${t().recording}',
      processing: '${t().sending}',
      sent: '${t().sent}',
      error: '${t().error}',
      mute: '${t().mute}',
      unmute: '${t().unmute}',
    };

    window.addEventListener('message', (e) => {
      if (e.data.type === 'state') {
        state = e.data.state;
        if (e.data.labels) labels = e.data.labels;
        btn.className = state;
        dot.className = 'dot ' + state;
        label.textContent = labels[state] || state;
      } else if (e.data.type === 'mute_state') {
        muted = e.data.muted;
        muteBtn.innerHTML = muted ? '&#x1F507;' : '&#x1F50A;';
        muteBtn.className = muted ? 'muted' : '';
        muteBtn.title = muted ? (labels.unmute || 'Unmute TTS') : (labels.mute || 'Mute TTS');
      }
    });
  </script>
</body></html>`;
  }
}

let pttProvider: PttViewProvider | null = null;

function updateStatus(state: PttState): void {
  if (pttProvider) pttProvider.setState(state);
}

// ---------------------------------------------------------------------------
// Tray process lifecycle
// ---------------------------------------------------------------------------

function killOrphanTray(): void {
  const lockFile = path.join(os.tmpdir(), "voice-claude-tray.lock");
  try {
    if (fs.existsSync(lockFile)) {
      const oldPid = parseInt(fs.readFileSync(lockFile, "utf-8").trim(), 10);
      if (oldPid && !isNaN(oldPid)) {
        try {
          process.kill(oldPid, 0); // check if alive
          process.kill(oldPid); // kill it
          dlog(`killed orphan tray pid=${oldPid}`);
        } catch { /* already dead */ }
      }
      fs.unlinkSync(lockFile);
    }
  } catch { /* ignore */ }
}

function startTray(ctx: vscode.ExtensionContext, apiKey: string): void {
  if (trayProcess) return;
  killOrphanTray();

  const scriptsDir = extensionScriptsDir(ctx);
  const trayScript = path.join(scriptsDir, "voice-tray.py");

  if (!fs.existsSync(trayScript)) {
    console.log("Clara Voice: tray script not found:", trayScript);
    return;
  }

  const resultPath = resultFilePath();
  if (!resultPath) {
    vscode.window.showWarningMessage("Clara Voice: Open a project folder to enable voice input");
    return;
  }

  const config = vscode.workspace.getConfiguration("claraVoice");
  const persona = config.get<string>("persona", "clara");
  const language = config.get<string>("language", "en");
  const wakeWord = config.get<string>("wakeWord", "") || persona;

  trayProcess = spawn("pythonw", [
    trayScript,
    "--wake-custom", wakeWord,
    "--result-file", resultPath,
    "--language", language,
  ], {
    cwd: scriptsDir,
    stdio: "ignore",
    detached: true,
    env: { ...process.env, GROQ_API_KEY: apiKey },
  });

  trayProcess.on("error", (err) => {
    console.log("Clara Voice: tray error:", err.message);
    trayProcess = null;
    updateStatus("error");
  });

  trayProcess.on("close", (code) => {
    console.log("Clara Voice: tray exited with code:", code);
    trayProcess = null;
  });

  console.log("Clara Voice: tray started, pid:", trayProcess.pid);
}

function stopTray(): void {
  if (trayProcess) {
    trayProcess.kill();
    trayProcess = null;
    console.log("Clara Voice: tray stopped");
  }
  killOrphanTray();
}

// ---------------------------------------------------------------------------
// Voice result watcher
// ---------------------------------------------------------------------------

let globalResultWatcher: fs.FSWatcher | null = null;

function startWatcher(ctx: vscode.ExtensionContext): void {
  const filePath = resultFilePath();
  if (!filePath) return;

  const dir = path.dirname(filePath);

  // Initialize timestamp from existing file
  try {
    if (fs.existsSync(filePath)) {
      const data = JSON.parse(fs.readFileSync(filePath, "utf-8"));
      lastTimestamp = data.timestamp || 0;
    }
  } catch { /* ignore */ }

  // Watch workspace-specific result file (for PTT)
  resultWatcher = fs.watch(dir, (_, filename) => {
    if (filename === "voice-result.json") {
      setTimeout(() => checkForNewResult(ctx), 200);
    }
  });

  // Watch global result file in temp (for wake-word / dictation)
  const globalFileName = "voice-claude-result-global.json";
  try {
    globalResultWatcher = fs.watch(os.tmpdir(), (_, filename) => {
      if (filename === globalFileName) {
        setTimeout(() => checkForNewResult(ctx), 200);
      }
    });
  } catch { /* ignore - temp dir watch may fail */ }

  console.log("Clara Voice: watching", filePath, "and global");
}

function processResultFile(ctx: vscode.ExtensionContext, filePath: string): void {
  if (!fs.existsSync(filePath)) return;

  try {
    const raw = fs.readFileSync(filePath, "utf-8");
    const data = JSON.parse(raw);

    if (!data.consumed && data.text && data.timestamp > lastTimestamp) {
      const resultWorkspace: string = data.workspace ?? "";
      const thisWorkspace = vscode.workspace.workspaceFolders?.[0]?.name ?? "";

      if (resultWorkspace) {
        // PTT result — only process if workspace matches
        if (thisWorkspace && resultWorkspace !== thisWorkspace) {
          return; // Not for this window
        }
      } else {
        // Wake-word / dictation result — only process if this window is focused
        if (!vscode.window.state.focused) {
          return; // Not the active window
        }
      }

      const text: string = data.text;
      const now = Date.now();

      // Deduplication
      if (text === lastText && now - lastSentTime < 5000) {
        data.consumed = true;
        fs.writeFileSync(filePath, JSON.stringify(data, null, 0));
        return;
      }

      lastTimestamp = data.timestamp;
      lastText = text;
      lastSentTime = now;

      data.consumed = true;
      fs.writeFileSync(filePath, JSON.stringify(data, null, 0));

      const foregroundHwnd: number | undefined = data.foreground_hwnd;
      sendToClaudeCode(ctx, text, foregroundHwnd);
    }
  } catch { /* ignore parse errors */ }
}

function checkForNewResult(ctx: vscode.ExtensionContext): void {
  // Check workspace-specific result file (for PTT)
  const wsFile = resultFilePath();
  if (wsFile) processResultFile(ctx, wsFile);

  // Also check global result file (for wake-word / dictation)
  const globalFile = path.join(os.tmpdir(), "voice-claude-result-global.json");
  processResultFile(ctx, globalFile);
}

// ---------------------------------------------------------------------------
// Send text to Claude Code
// ---------------------------------------------------------------------------

async function sendToClaudeCode(ctx: vscode.ExtensionContext, text: string, foregroundHwnd?: number): Promise<void> {
  const message = `[Voice] ${text}`;
  updateStatus("processing");

  try {
    dlog(`--- sendToClaudeCode start: "${text.substring(0, 50)}"`);

    // CDP inject with window title matching for correct window targeting
    const cdpScript = path.join(extensionScriptsDir(ctx), "cdp_inject.py");
    const escaped = message.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    const wsName = vscode.workspace.workspaceFolders?.[0]?.name ?? "";
    const wsArg = wsName ? ` --workspace "${wsName}"` : "";
    await new Promise<void>((resolve) => {
      exec(
        `python "${cdpScript}" --text "${escaped}"${wsArg}`,
        { timeout: 10000 },
        (err, stdout) => {
          if (err) {
            dlog(`cdp_inject failed: ${err.message}`);
          } else {
            dlog(`cdp_inject: ${stdout.trim()}`);
          }
          resolve();
        }
      );
    });

    console.log("Clara Voice: sent:", text.substring(0, 60));
    updateStatus("sent");
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    console.log("Clara Voice: failed:", msg);
    vscode.window.showInformationMessage(`Clara Voice: ${text}`);
    updateStatus("error");
  }
}

// ---------------------------------------------------------------------------
// Inline PTT: inject mic button into Claude Code chat via CDP
// ---------------------------------------------------------------------------

function injectInlineButton(ctx: vscode.ExtensionContext): void {
  const scriptsDir = extensionScriptsDir(ctx);
  const injectScript = path.join(scriptsDir, "cdp_inject_button.py");
  const wsName = vscode.workspace.workspaceFolders?.[0]?.name ?? "";
  const wsArg = wsName ? ` --workspace "${wsName}"` : "";

  exec(
    `python "${injectScript}"${wsArg}`,
    { timeout: 15000 },
    (err, stdout) => {
      if (err) {
        dlog(`inline button inject failed: ${err.message}`);
      } else {
        dlog(`inline button: ${stdout.trim()}`);
        // Start listener AFTER button is injected (cache is now valid)
        startPttListener(ctx);
      }
    }
  );
}

function startPttListener(ctx: vscode.ExtensionContext): void {
  if (pttListenerProcess) return;

  const scriptsDir = extensionScriptsDir(ctx);
  const listenerScript = path.join(scriptsDir, "cdp_ptt_listener.py");
  const wsName = vscode.workspace.workspaceFolders?.[0]?.name ?? "";
  const myResultFile = resultFilePath() ?? "";

  pttListenerProcess = spawn("python", [
    listenerScript,
    "--workspace", wsName,
    "--result-file", myResultFile,
  ], {
    cwd: scriptsDir,
    stdio: ["ignore", "pipe", "ignore"],
  });

  pttListenerProcess.stdout?.on("data", (data: Buffer) => {
    const line = data.toString().trim();
    if (line === "LISTENING") {
      dlog("ptt listener connected");
    }
  });

  pttListenerProcess.on("error", (err) => {
    dlog(`ptt listener error: ${err.message}`);
    pttListenerProcess = null;
  });

  pttListenerProcess.on("close", (code) => {
    dlog(`ptt listener exited: ${code}`);
    pttListenerProcess = null;
  });

  dlog("ptt listener started");
}

function stopPttListener(): void {
  if (pttListenerProcess) {
    pttListenerProcess.kill();
    pttListenerProcess = null;
    dlog("ptt listener stopped");
  }
}

// ---------------------------------------------------------------------------
// Voice instructions for Claude (global CLAUDE.md)
// ---------------------------------------------------------------------------

const VOICE_INSTRUCTIONS_MARKER = "## Clara Voice";
const VOICE_INSTRUCTIONS = `
## Clara Voice — Hands-Free Voice Mode

Clara Voice Code extension is installed. When a message starts with \`[Voice]\` or \`[Голос]\`:
1. **ALWAYS call \`voice_speak\` FIRST** before any other action — the user is listening, not reading
2. Keep voice responses short (1-3 sentences) — concise and to the point
3. After completing a task, give a brief voice summary of what was done
4. If the user speaks in Russian, respond in Russian. If in English, respond in English.
5. The \`voice_speak\` tool is always available — use it proactively for important updates
`;

function ensureVoiceInstructions(): void {
  const claudeMdPath = path.join(os.homedir(), ".claude", "CLAUDE.md");
  try {
    let content = "";
    if (fs.existsSync(claudeMdPath)) {
      content = fs.readFileSync(claudeMdPath, "utf-8");
    }
    if (content.includes(VOICE_INSTRUCTIONS_MARKER)) {
      return; // Already installed
    }
    // Prepend voice instructions at the top or after first heading
    const firstHeadingMatch = content.match(/^(# .+\n)/m);
    if (firstHeadingMatch && firstHeadingMatch.index !== undefined) {
      const insertPos = firstHeadingMatch.index + firstHeadingMatch[0].length;
      content = content.slice(0, insertPos) + VOICE_INSTRUCTIONS + content.slice(insertPos);
    } else {
      content = VOICE_INSTRUCTIONS + "\n" + content;
    }
    fs.writeFileSync(claudeMdPath, content, "utf-8");
    dlog("voice instructions installed in global CLAUDE.md");
  } catch (e) {
    dlog(`failed to install voice instructions: ${e}`);
  }
}

// ---------------------------------------------------------------------------
// MCP auto-registration
// ---------------------------------------------------------------------------

function registerMcpServer(ctx: vscode.ExtensionContext): void {
  // Copy MCP server to a fixed path that doesn't change with extension version.
  // This way Claude Code sessions survive extension upgrades without losing MCP.
  const stableMcpDir = path.join(os.homedir(), ".clara-voice", "mcp");
  if (!fs.existsSync(stableMcpDir)) {
    fs.mkdirSync(stableMcpDir, { recursive: true });
  }

  const sourceMcpDir = path.join(ctx.extensionPath, "out", "mcp");
  const stableMcpPath = path.join(stableMcpDir, "standalone.js");

  // Always copy latest version
  try {
    for (const file of fs.readdirSync(sourceMcpDir)) {
      fs.copyFileSync(path.join(sourceMcpDir, file), path.join(stableMcpDir, file));
    }
    dlog(`MCP files copied to ${stableMcpDir}`);
  } catch (e) {
    dlog(`MCP copy failed: ${e}`);
  }

  // Step 1: Remove project-level MCP registration if it exists (legacy cleanup)
  const projectDir = claudeDir();
  if (projectDir) {
    const projectSettingsPath = path.join(projectDir, "settings.json");
    try {
      if (fs.existsSync(projectSettingsPath)) {
        const projSettings = JSON.parse(fs.readFileSync(projectSettingsPath, "utf-8"));
        const projMcp = projSettings["mcpServers"] as Record<string, unknown> | undefined;
        if (projMcp && projMcp["clara-voice"]) {
          delete projMcp["clara-voice"];
          if (Object.keys(projMcp).length === 0) {
            delete projSettings["mcpServers"];
          }
          fs.writeFileSync(projectSettingsPath, JSON.stringify(projSettings, null, 2));
          dlog("removed legacy project-level MCP registration");
        }
      }
    } catch { /* ignore */ }
  }

  // Step 2: Register stable path in global ~/.claude/settings.json
  const globalClaudeDir = path.join(os.homedir(), ".claude");
  if (!fs.existsSync(globalClaudeDir)) {
    fs.mkdirSync(globalClaudeDir, { recursive: true });
  }
  const globalSettingsPath = path.join(globalClaudeDir, "settings.json");

  let settings: Record<string, unknown> = {};
  try {
    if (fs.existsSync(globalSettingsPath)) {
      settings = JSON.parse(fs.readFileSync(globalSettingsPath, "utf-8"));
    }
  } catch { /* ignore */ }

  const mcpServers = (settings["mcpServers"] as Record<string, unknown>) || {};

  // Normalize to forward slashes for consistent comparison (Windows backslash fix)
  const stableNorm = stableMcpPath.replace(/\\/g, "/");

  const existing = mcpServers["clara-voice"] as Record<string, unknown> | undefined;
  if (existing) {
    const existingArgs = existing["args"] as string[] | undefined;
    const existingPath = existingArgs?.[0]?.replace(/\\/g, "/") || "";
    // Already registered with stable path — nothing to do
    if (existingPath === stableNorm) {
      dlog("MCP already registered with stable path");
      return;
    }
    dlog(`MCP path mismatch: "${existingPath}" vs "${stableNorm}", updating`);
  }

  // Always use forward slashes in settings.json for cross-platform consistency
  mcpServers["clara-voice"] = {
    command: "node",
    args: [stableNorm],
  };

  settings["mcpServers"] = mcpServers;
  fs.writeFileSync(globalSettingsPath, JSON.stringify(settings, null, 2));
  dlog(`MCP server registered globally: ${stableNorm}`);
  console.log("Clara Voice: MCP server registered in", globalSettingsPath);
}

// ---------------------------------------------------------------------------
// Shared settings (synced to temp file for Python scripts)
// ---------------------------------------------------------------------------

const SHARED_SETTINGS_FILE = path.join(os.tmpdir(), "voice-claude-settings.json");

function syncAllSettings(): void {
  const config = vscode.workspace.getConfiguration("claraVoice");
  const persona = config.get<string>("persona", "clara");
  const language = config.get<string>("language", "en");
  const speed = config.get<number>("ttsSpeed", 1.2);
  const volume = config.get<number>("ttsVolume", 75) / 100; // VS Code: 0-100, Python: 0-1
  const soundFeedback = config.get<boolean>("soundFeedback", true);

  try {
    let settings: Record<string, unknown> = {};
    if (fs.existsSync(SHARED_SETTINGS_FILE)) {
      settings = JSON.parse(fs.readFileSync(SHARED_SETTINGS_FILE, "utf-8"));
    }
    let changed = false;
    if (settings["persona"] !== persona) { settings["persona"] = persona; changed = true; }
    if (settings["language"] !== language) { settings["language"] = language; changed = true; }
    if (settings["speed"] !== speed) { settings["speed"] = speed; changed = true; }
    if (settings["volume"] !== volume) { settings["volume"] = volume; changed = true; }
    if (settings["sound_feedback"] !== soundFeedback) { settings["sound_feedback"] = soundFeedback; changed = true; }

    if (changed) {
      fs.writeFileSync(SHARED_SETTINGS_FILE, JSON.stringify(settings));
      dlog(`syncSettings: persona=${persona} lang=${language} speed=${speed} volume=${volume} sound=${soundFeedback}`);
    }
  } catch { /* ignore */ }
}

function syncMuteState(): void {
  try {
    let settings: Record<string, unknown> = {};
    if (fs.existsSync(SHARED_SETTINGS_FILE)) {
      settings = JSON.parse(fs.readFileSync(SHARED_SETTINGS_FILE, "utf-8"));
    }
    settings["tts_muted"] = ttsMuted;
    fs.writeFileSync(SHARED_SETTINGS_FILE, JSON.stringify(settings));
    dlog(`syncMuteState: tts_muted=${ttsMuted}`);
  } catch { /* ignore */ }
}

// Keep backward compat alias
function syncPersonaSetting(): void {
  syncAllSettings();
}

// ---------------------------------------------------------------------------
// Setup Wizard
// ---------------------------------------------------------------------------

const REQUIRED_PIP_PACKAGES = [
  "edge-tts", "miniaudio", "sounddevice", "numpy",
  "groq", "pyaudio", "pystray", "pillow",
];

interface SetupResult {
  pythonOk: boolean;
  pipOk: boolean;
  apiKeyOk: boolean;
  cdpOk: boolean;
  apiKey: string | undefined;
}

function execPromise(cmd: string, timeout = 10000): Promise<{ stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    exec(cmd, { timeout }, (err, stdout, stderr) => {
      if (err) reject(err);
      else resolve({ stdout: stdout.toString(), stderr: stderr.toString() });
    });
  });
}

async function checkPython(): Promise<{ ok: boolean; version: string; path: string }> {
  for (const cmd of ["python", "python3", "py"]) {
    try {
      const { stdout } = await execPromise(`${cmd} --version`);
      const ver = stdout.trim().replace("Python ", "");
      const { stdout: pyPath } = await execPromise(`${cmd} -c "import sys; print(sys.executable)"`);
      return { ok: true, version: ver, path: pyPath.trim() };
    } catch { /* try next */ }
  }
  return { ok: false, version: "", path: "" };
}

async function checkPipPackages(): Promise<{ installed: string[]; missing: string[] }> {
  try {
    const { stdout } = await execPromise("python -m pip list --format=json", 15000);
    const pkgs = JSON.parse(stdout) as { name: string }[];
    const names = new Set(pkgs.map((p) => p.name.toLowerCase()));
    const installed: string[] = [];
    const missing: string[] = [];
    for (const pkg of REQUIRED_PIP_PACKAGES) {
      // pip list uses normalized names (underscores → hyphens)
      const normalized = pkg.toLowerCase().replace(/_/g, "-");
      if (names.has(normalized)) installed.push(pkg);
      else missing.push(pkg);
    }
    return { installed, missing };
  } catch {
    return { installed: [], missing: [...REQUIRED_PIP_PACKAGES] };
  }
}

async function installPipPackages(packages: string[]): Promise<boolean> {
  return vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "Clara Voice: Installing Python packages...", cancellable: false },
    async (progress) => {
      try {
        progress.report({ message: packages.join(", ") });
        await execPromise(`python -m pip install ${packages.join(" ")}`, 120000);
        return true;
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        vscode.window.showErrorMessage(`Clara Voice: pip install failed: ${msg}`);
        return false;
      }
    }
  );
}

function checkCdpArgv(): { ok: boolean; filePath: string } {
  const argvPath = path.join(os.homedir(), ".vscode", "argv.json");
  try {
    if (fs.existsSync(argvPath)) {
      const content = fs.readFileSync(argvPath, "utf-8");
      // argv.json may have comments — strip them
      const stripped = content.replace(/\/\/.*$/gm, "");
      const parsed = JSON.parse(stripped);
      if (parsed["remote-debugging-port"]) {
        return { ok: true, filePath: argvPath };
      }
    }
  } catch { /* ignore */ }
  return { ok: false, filePath: argvPath };
}

async function ensureCdpArgv(argvPath: string): Promise<boolean> {
  try {
    let parsed: Record<string, unknown> = {};
    if (fs.existsSync(argvPath)) {
      const content = fs.readFileSync(argvPath, "utf-8");
      const stripped = content.replace(/\/\/.*$/gm, "");
      parsed = JSON.parse(stripped);
    }
    if (!parsed["remote-debugging-port"]) {
      parsed["remote-debugging-port"] = "9222";
    }
    if (!parsed["remote-allow-origins"]) {
      parsed["remote-allow-origins"] = "*";
    }
    fs.writeFileSync(argvPath, JSON.stringify(parsed, null, "\t"));
    return true;
  } catch {
    return false;
  }
}

async function runSetupWizard(ctx: vscode.ExtensionContext): Promise<SetupResult> {
  const result: SetupResult = { pythonOk: false, pipOk: false, apiKeyOk: false, cdpOk: false, apiKey: undefined };

  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "Clara Voice: Setting up...", cancellable: false },
    async (progress) => {

      // Step 1: Check Python
      progress.report({ message: "Checking Python..." });
      dlog("setup: checking Python...");
      const py = await checkPython();
      if (!py.ok) {
        vscode.window.showErrorMessage(
          "Clara Voice: Python 3.10+ is required. Install from python.org and restart VS Code."
        );
        vscode.env.openExternal(vscode.Uri.parse("https://www.python.org/downloads/"));
        return;
      }
      result.pythonOk = true;
      dlog(`setup: Python ${py.version} at ${py.path}`);

      // Step 2: Auto-install pip packages
      progress.report({ message: "Checking packages..." });
      dlog("setup: checking pip packages...");
      const pkgs = await checkPipPackages();
      if (pkgs.missing.length > 0) {
        progress.report({ message: `Installing ${pkgs.missing.length} packages...` });
        dlog(`setup: auto-installing: ${pkgs.missing.join(", ")}`);
        const ok = await installPipPackages(pkgs.missing);
        result.pipOk = ok;
        if (!ok) {
          vscode.window.showErrorMessage(
            `Clara Voice: Failed to install packages. Run manually: pip install ${pkgs.missing.join(" ")}`
          );
        }
      } else {
        result.pipOk = true;
        dlog("setup: all pip packages installed");
      }

      // Step 3: API key (only thing that requires user input)
      result.apiKey = await ctx.secrets.get("claraVoice.groqApiKey");
      if (!result.apiKey) {
        dlog("setup: requesting Groq API key");
        vscode.env.openExternal(vscode.Uri.parse("https://console.groq.com/keys"));
        result.apiKey = await vscode.window.showInputBox({
          prompt: "Paste your Groq API key (starts with gsk_). Get one free at console.groq.com",
          password: true,
          ignoreFocusOut: true,
          placeHolder: "gsk_...",
        });
        if (result.apiKey) {
          await ctx.secrets.store("claraVoice.groqApiKey", result.apiKey);
          result.apiKeyOk = true;
        }
      } else {
        result.apiKeyOk = true;
        dlog("setup: Groq API key found in SecretStorage");
      }

      // Step 4: CDP (argv.json) — auto-configure, no questions
      progress.report({ message: "Configuring CDP..." });
      const cdp = checkCdpArgv();
      if (!cdp.ok) {
        dlog("setup: CDP not configured, adding to argv.json");
        const ok = await ensureCdpArgv(cdp.filePath);
        if (ok) {
          result.cdpOk = true;
          dlog("setup: CDP configured, restart needed");
        }
      } else {
        result.cdpOk = true;
        dlog("setup: CDP already configured");
      }
    }
  );

  // Mark setup complete
  if (result.pythonOk && result.pipOk && result.apiKeyOk && result.cdpOk) {
    await ctx.globalState.update("claraVoice.setupComplete", true);
    vscode.window.showInformationMessage("Clara Voice: Ready! Reload window if this is first install.");
    dlog("setup: wizard complete!");
  }

  return result;
}

// ---------------------------------------------------------------------------
// Activation / Deactivation
// ---------------------------------------------------------------------------

export async function activate(ctx: vscode.ExtensionContext): Promise<void> {
  console.log("Clara Voice Code activating...");
  dlog(`=== EXTENSION ACTIVATED, ws=${vscode.workspace.workspaceFolders?.[0]?.name}, tmpdir=${os.tmpdir()} ===`);

  // Remove conflicting/obsolete extensions
  const CONFLICTING_EXTENSIONS = [
    "voiceclaude.voice-bridge",
    "fultonmarketaistudio.claude-code-voice",
  ];
  for (const extId of CONFLICTING_EXTENSIONS) {
    if (vscode.extensions.getExtension(extId)) {
      dlog(`setup: uninstalling conflicting extension ${extId}`);
      try {
        await vscode.commands.executeCommand("workbench.extensions.uninstallExtension", extId);
        vscode.window.showInformationMessage(
          `Clara Voice: Removed conflicting extension "${extId}". Please reload.`
        );
      } catch (e) {
        dlog(`setup: failed to uninstall ${extId}: ${e}`);
      }
    }
  }

  // Run setup wizard on first launch or if not complete
  const setupDone = ctx.globalState.get<boolean>("claraVoice.setupComplete", false);
  let apiKey: string | undefined;

  if (!setupDone) {
    const result = await runSetupWizard(ctx);
    apiKey = result.apiKey;
  } else {
    apiKey = await ctx.secrets.get("claraVoice.groqApiKey");
  }

  // Status bar (read-only indicator, no command — PTT is in the webview panel)
  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBar.text = t().statusLoading;
  statusBar.tooltip = t().tooltipLoading;
  statusBar.command = "claraVoice.pushToTalk";
  statusBar.show();
  ctx.subscriptions.push(statusBar);

  // Push-to-Talk webview panel (mousedown/mouseup = true hold-to-talk)
  const cmdFile = path.join(os.tmpdir(), "voice-claude-ptt.json");
  const myWorkspace = vscode.workspace.workspaceFolders?.[0]?.name ?? "";
  const myResultFile = resultFilePath() ?? "";
  pttProvider = new PttViewProvider(
    () => {
      // PTT start — include result_file path so tray writes to the correct workspace
      fs.writeFileSync(cmdFile, JSON.stringify({ command: "ptt_start", timestamp: Date.now(), workspace: myWorkspace, result_file: myResultFile }));
      dlog("pushToTalk: recording started");
    },
    () => {
      // PTT stop
      fs.writeFileSync(cmdFile, JSON.stringify({ command: "ptt_stop", timestamp: Date.now(), workspace: myWorkspace, result_file: myResultFile }));
      dlog("pushToTalk: recording stopped");
    }
  );
  ctx.subscriptions.push(
    vscode.window.registerWebviewViewProvider(PttViewProvider.viewTypePanel, pttProvider),
    vscode.window.registerWebviewViewProvider(PttViewProvider.viewTypeSidebar, pttProvider),
  );

  // Fallback command for keybinding (toggle mode)
  let isRecording = false;
  ctx.subscriptions.push(
    vscode.commands.registerCommand("claraVoice.pushToTalk", () => {
      isRecording = !isRecording;
      if (isRecording) {
        fs.writeFileSync(cmdFile, JSON.stringify({ command: "ptt_start", timestamp: Date.now(), workspace: myWorkspace }));
        updateStatus("recording");
        dlog("pushToTalk: recording started (keybinding)");
      } else {
        fs.writeFileSync(cmdFile, JSON.stringify({ command: "ptt_stop", timestamp: Date.now(), workspace: myWorkspace }));
        updateStatus("processing");
        dlog("pushToTalk: recording stopped (keybinding)");
      }
    })
  );

  ctx.subscriptions.push(
    vscode.commands.registerCommand("claraVoice.switchPersona", async () => {
      const personas = [
        { label: "$(person) Clara", description: "Female voice (Svetlana RU / Jenny EN)", value: "clara" },
        { label: "$(person) Claude", description: "Male voice (Dmitri RU / Guy EN)", value: "claude" },
      ];
      const picked = await vscode.window.showQuickPick(personas, {
        placeHolder: "Select voice persona",
      });
      if (picked) {
        const config = vscode.workspace.getConfiguration("claraVoice");
        await config.update("persona", picked.value, vscode.ConfigurationTarget.Global);
        syncPersonaSetting();
        stopTray();
        const key = await ctx.secrets.get("claraVoice.groqApiKey");
        startTray(ctx, key ?? "");
        updateStatus("ready");
        const name = picked.value === "claude" ? "Клод" : "Клара";
        vscode.window.showInformationMessage(`Clara Voice: Persona switched to ${name}`);
      }
    })
  );

  ctx.subscriptions.push(
    vscode.commands.registerCommand("claraVoice.setup", async () => {
      await ctx.globalState.update("claraVoice.setupComplete", false);
      const result = await runSetupWizard(ctx);
      if (result.pythonOk && result.pipOk && result.apiKeyOk && result.cdpOk) {
        vscode.window.showInformationMessage("Clara Voice: Setup complete! Reload window to apply.");
      }
    })
  );

  // -------------------------------------------------------------------------
  // Test commands for investigating text injection into Claude Code webview
  // -------------------------------------------------------------------------

  // Test 1: "type" command after claude-vscode.focus
  ctx.subscriptions.push(
    vscode.commands.registerCommand("claraVoice.testTypeCommand", async () => {
      const log = (msg: string) => {
        console.log(`[testTypeCommand] ${msg}`);
        dlog(`testTypeCommand: ${msg}`);
      };

      log("=== START ===");

      // Step 1: focus Claude Code chat
      try {
        await vscode.commands.executeCommand("claude-vscode.focus");
        log("claude-vscode.focus succeeded");
      } catch (e: unknown) {
        log(`claude-vscode.focus FAILED: ${e instanceof Error ? e.message : String(e)}`);
        vscode.window.showErrorMessage("testTypeCommand: claude-vscode.focus failed");
        return;
      }

      // Step 2: wait 300ms for focus to settle
      await new Promise<void>((r) => setTimeout(r, 300));
      log("waited 300ms");

      // Step 3: try "type" command
      try {
        await vscode.commands.executeCommand("type", { text: "[Voice] тест type command\n" });
        log("type command SUCCEEDED");
        vscode.window.showInformationMessage("testTypeCommand: type command succeeded!");
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        log(`type command FAILED: ${msg}`);
        vscode.window.showWarningMessage(`testTypeCommand: type command failed: ${msg}`);
      }

      log("=== END ===");
    })
  );

  // Test 2: clipboardPasteAction after claude-vscode.focus
  ctx.subscriptions.push(
    vscode.commands.registerCommand("claraVoice.testPasteCommand", async () => {
      const log = (msg: string) => {
        console.log(`[testPasteCommand] ${msg}`);
        dlog(`testPasteCommand: ${msg}`);
      };

      log("=== START ===");

      // Step 1: set clipboard
      const testText = "[Voice] тест paste command\n";
      await vscode.env.clipboard.writeText(testText);
      log("clipboard set");

      // Step 2: focus Claude Code chat
      try {
        await vscode.commands.executeCommand("claude-vscode.focus");
        log("claude-vscode.focus succeeded");
      } catch (e: unknown) {
        log(`claude-vscode.focus FAILED: ${e instanceof Error ? e.message : String(e)}`);
        vscode.window.showErrorMessage("testPasteCommand: claude-vscode.focus failed");
        return;
      }

      // Step 3: wait 300ms
      await new Promise<void>((r) => setTimeout(r, 300));
      log("waited 300ms");

      // Step 4: try editor.action.clipboardPasteAction
      try {
        await vscode.commands.executeCommand("editor.action.clipboardPasteAction");
        log("clipboardPasteAction SUCCEEDED");
        vscode.window.showInformationMessage("testPasteCommand: clipboardPasteAction succeeded!");
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        log(`clipboardPasteAction FAILED: ${msg}`);
        vscode.window.showWarningMessage(`testPasteCommand: clipboardPasteAction failed: ${msg}`);
      }

      log("=== END ===");
    })
  );

  // Test 3: list all commands containing "type", "paste", or "insert"
  ctx.subscriptions.push(
    vscode.commands.registerCommand("claraVoice.listCommands", async () => {
      const log = (msg: string) => {
        console.log(`[listCommands] ${msg}`);
        dlog(`listCommands: ${msg}`);
      };

      log("=== START: fetching all commands ===");

      try {
        const allCommands = await vscode.commands.getCommands(true);
        const keywords = ["type", "paste", "insert", "clipboard", "input", "text"];
        const matched = allCommands.filter((cmd) =>
          keywords.some((kw) => cmd.toLowerCase().includes(kw))
        );

        matched.sort();

        log(`Found ${matched.length} matching commands out of ${allCommands.length} total:`);
        for (const cmd of matched) {
          log(`  - ${cmd}`);
        }

        // Also show in output channel for easy viewing
        const output = vscode.window.createOutputChannel("Clara Voice Commands");
        output.clear();
        output.appendLine(`=== VS Code commands matching: ${keywords.join(", ")} ===`);
        output.appendLine(`Total commands: ${allCommands.length}`);
        output.appendLine(`Matching commands: ${matched.length}`);
        output.appendLine("");
        for (const cmd of matched) {
          output.appendLine(cmd);
        }

        // Also list claude-related commands
        const claudeCommands = allCommands.filter((cmd) =>
          cmd.toLowerCase().includes("claude")
        );
        claudeCommands.sort();
        output.appendLine("");
        output.appendLine(`=== Claude-related commands (${claudeCommands.length}) ===`);
        for (const cmd of claudeCommands) {
          output.appendLine(cmd);
        }

        output.show();
        vscode.window.showInformationMessage(
          `Found ${matched.length} type/paste/insert commands, ${claudeCommands.length} claude commands. See output panel.`
        );
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        log(`FAILED: ${msg}`);
        vscode.window.showErrorMessage(`listCommands failed: ${msg}`);
      }

      log("=== END ===");
    })
  );

  // Register MCP server and voice instructions
  registerMcpServer(ctx);
  ensureVoiceInstructions();

  // Sync all settings (persona, speed, volume, sound) to shared file for Python scripts
  syncAllSettings();

  // Re-sync when user changes settings
  ctx.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration(async (e) => {
      if (e.affectsConfiguration("claraVoice")) {
        syncAllSettings();
        if (e.affectsConfiguration("claraVoice.language")) {
          if (pttProvider) pttProvider.refreshLanguage();
          // Restart tray immediately so it picks up new language
          stopTray();
          const key = await ctx.secrets.get("claraVoice.groqApiKey");
          startTray(ctx, key ?? "");
          dlog("language changed, tray restarted");
        }
        if (e.affectsConfiguration("claraVoice.persona")) {
          stopTray();
          const key = await ctx.secrets.get("claraVoice.groqApiKey");
          startTray(ctx, key ?? "");
          dlog("persona changed, tray restarted");
        }
        dlog("settings changed, synced to shared file");
      }
    })
  );

  // Start file watcher
  startWatcher(ctx);

  // Start tray
  startTray(ctx, apiKey ?? "");

  // Watch daemon status — unlock PTT button when tray is ready
  const daemonStatusFile = path.join(os.tmpdir(), "voice-claude-daemon-status.json");
  let daemonWatcher: fs.FSWatcher | null = null;

  function checkDaemonReady(): void {
    try {
      if (!fs.existsSync(daemonStatusFile)) return;
      const data = JSON.parse(fs.readFileSync(daemonStatusFile, "utf-8"));
      if (data.state === "idle" && data.pid) {
        // Verify process is still alive
        try { process.kill(data.pid, 0); } catch { return; }
        dlog("daemon ready, unlocking PTT");
        updateStatus("ready");

        // Inject inline mic button if pttMode is "inline"
        const pttMode = vscode.workspace.getConfiguration("claraVoice").get<string>("pttMode", "inline");
        if (pttMode === "inline") {
          // Small delay to ensure Claude Code webview is fully loaded
          // injectInlineButton will start listener after successful inject
          setTimeout(() => injectInlineButton(ctx), 2000);
        }

        if (daemonWatcher) {
          daemonWatcher.close();
          daemonWatcher = null;
        }
      }
    } catch { /* ignore */ }
  }

  // Watch for daemon to become ready
  try {
    daemonWatcher = fs.watch(os.tmpdir(), (_, filename) => {
      if (filename === "voice-claude-daemon-status.json") {
        setTimeout(checkDaemonReady, 200);
      }
    });
  } catch { /* ignore */ }

  // Check immediately (tray may already be running from previous session)
  checkDaemonReady();

  // Cleanup on dispose
  ctx.subscriptions.push({
    dispose: () => {
      if (resultWatcher) {
        resultWatcher.close();
        resultWatcher = null;
      }
      if (daemonWatcher) {
        daemonWatcher.close();
        daemonWatcher = null;
      }
      stopTray();
      stopPttListener();
    },
  });

  console.log("Clara Voice Code activated");
}

export function deactivate(): void {
  stopTray();
  stopPttListener();
  if (resultWatcher) {
    resultWatcher.close();
    resultWatcher = null;
  }
  if (globalResultWatcher) {
    globalResultWatcher.close();
    globalResultWatcher = null;
  }
}
