import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";
import { ChildProcess, spawn, exec } from "child_process";

let trayProcess: ChildProcess | null = null;
let statusBar: vscode.StatusBarItem | null = null;
let resultWatcher: fs.FSWatcher | null = null;
let lastTimestamp = 0;
let lastText = "";
let lastSentTime = 0;

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
// Status bar
// ---------------------------------------------------------------------------

type StatusState = "listening" | "processing" | "sent" | "speaking" | "off" | "error";

function updateStatus(state: StatusState): void {
  if (!statusBar) return;
  const config = vscode.workspace.getConfiguration("claraVoice");
  const persona = config.get<string>("persona", "clara");
  const name = persona === "claude" ? "Claude" : "Clara";

  switch (state) {
    case "listening":
      statusBar.text = `$(mic) ${name}`;
      statusBar.tooltip = `${name} Voice: listening`;
      break;
    case "processing":
      statusBar.text = `$(sync~spin) ${name}`;
      statusBar.tooltip = `${name} Voice: processing`;
      break;
    case "sent":
      statusBar.text = `$(check) ${name}`;
      statusBar.tooltip = `${name} Voice: sent`;
      setTimeout(() => updateStatus("listening"), 2000);
      break;
    case "speaking":
      statusBar.text = `$(unmute) ${name}`;
      statusBar.tooltip = `${name} Voice: speaking`;
      break;
    case "off":
      statusBar.text = `$(mute) ${name}`;
      statusBar.tooltip = `${name} Voice: off`;
      break;
    case "error":
      statusBar.text = `$(warning) ${name}`;
      statusBar.tooltip = `${name} Voice: error`;
      setTimeout(() => updateStatus("listening"), 3000);
      break;
  }
}

// ---------------------------------------------------------------------------
// Tray process lifecycle
// ---------------------------------------------------------------------------

function startTray(ctx: vscode.ExtensionContext, apiKey: string): void {
  if (trayProcess) return;

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
  const wakeWord = config.get<string>("wakeWord", "") || persona;

  trayProcess = spawn("pythonw", [
    trayScript,
    "--wake-custom", wakeWord,
    "--result-file", resultPath,
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
}

// ---------------------------------------------------------------------------
// Voice result watcher
// ---------------------------------------------------------------------------

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

  resultWatcher = fs.watch(dir, (_, filename) => {
    if (filename === "voice-result.json") {
      setTimeout(() => checkForNewResult(ctx), 200);
    }
  });

  console.log("Clara Voice: watching", filePath);
}

function checkForNewResult(ctx: vscode.ExtensionContext): void {
  const filePath = resultFilePath();
  if (!filePath || !fs.existsSync(filePath)) return;

  try {
    const raw = fs.readFileSync(filePath, "utf-8");
    const data = JSON.parse(raw);

    if (!data.consumed && data.text && data.timestamp > lastTimestamp) {
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

      sendToClaudeCode(ctx, text);
    }
  } catch { /* ignore parse errors */ }
}

// ---------------------------------------------------------------------------
// Send text to Claude Code
// ---------------------------------------------------------------------------

async function sendToClaudeCode(ctx: vscode.ExtensionContext, text: string): Promise<void> {
  const message = `[Voice] ${text}`;
  updateStatus("processing");

  try {
    const scriptPath = path.join(extensionScriptsDir(ctx), "focus-and-enter.py");

    if (!fs.existsSync(scriptPath)) {
      throw new Error("focus-and-enter.py not found");
    }

    const escaped = message.replace(/'/g, "''");
    await new Promise<void>((resolve) => {
      exec(
        `python "${scriptPath}" --fast --text '${escaped}'`,
        { timeout: 5000 },
        (err) => {
          if (err) console.log("Clara Voice: send failed:", err.message);
          else console.log("Clara Voice: sent via fast mode");
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
// MCP auto-registration
// ---------------------------------------------------------------------------

function registerMcpServer(ctx: vscode.ExtensionContext): void {
  const mcpServerPath = path.join(ctx.extensionPath, "out", "mcp", "standalone.js");

  // Register in workspace .claude/settings.json if workspace exists
  const dir = claudeDir();
  if (!dir) {
    vscode.window.showWarningMessage(
      "Clara Voice: Open a project folder to register MCP server for Claude Code"
    );
    return;
  }

  const settingsPath = path.join(dir, "settings.json");
  let settings: Record<string, unknown> = {};

  try {
    if (fs.existsSync(settingsPath)) {
      settings = JSON.parse(fs.readFileSync(settingsPath, "utf-8"));
    }
  } catch { /* ignore */ }

  const mcpServers = (settings["mcpServers"] as Record<string, unknown>) || {};

  // Check if already registered with correct path
  const existing = mcpServers["clara-voice"] as Record<string, unknown> | undefined;
  if (existing && JSON.stringify(existing["args"]) === JSON.stringify([mcpServerPath])) {
    return; // Already registered
  }

  mcpServers["clara-voice"] = {
    command: "node",
    args: [mcpServerPath],
  };

  settings["mcpServers"] = mcpServers;
  fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2));
  console.log("Clara Voice: MCP server registered in", settingsPath);
  vscode.window.showInformationMessage(
    "Clara Voice: MCP server registered — please restart Claude Code to activate voice tools"
  );
}

// ---------------------------------------------------------------------------
// Activation / Deactivation
// ---------------------------------------------------------------------------

export async function activate(ctx: vscode.ExtensionContext): Promise<void> {
  console.log("Clara Voice Code activating...");

  // Retrieve stored Groq API key
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

  // Status bar
  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBar.command = "claraVoice.toggle";
  updateStatus("listening");
  statusBar.show();
  ctx.subscriptions.push(statusBar);

  // Commands
  ctx.subscriptions.push(
    vscode.commands.registerCommand("claraVoice.toggle", () => {
      const config = vscode.workspace.getConfiguration("claraVoice");
      const currentMode = config.get<string>("mode", "wakeWord");
      const newMode = currentMode === "off" ? "wakeWord" : "off";
      config.update("mode", newMode, vscode.ConfigurationTarget.Global);
      updateStatus(newMode === "off" ? "off" : "listening");

      const persona = config.get<string>("persona", "clara");
      const name = persona === "claude" ? "Claude" : "Clara";
      vscode.window.showInformationMessage(
        newMode === "off" ? `${name} Voice off` : `${name} Voice on`
      );
    })
  );

  ctx.subscriptions.push(
    vscode.commands.registerCommand("claraVoice.switchMode", async () => {
      const modes = [
        { label: "$(mic) Wake Word", value: "wakeWord" },
        { label: "$(comment) Dictation", value: "dictation" },
        { label: "$(record) Push-to-Talk", value: "pushToTalk" },
        { label: "$(mute) Off", value: "off" },
      ];
      const picked = await vscode.window.showQuickPick(modes, {
        placeHolder: "Select voice input mode",
      });
      if (picked) {
        const config = vscode.workspace.getConfiguration("claraVoice");
        config.update("mode", picked.value, vscode.ConfigurationTarget.Global);
        updateStatus(picked.value === "off" ? "off" : "listening");
      }
    })
  );

  ctx.subscriptions.push(
    vscode.commands.registerCommand("claraVoice.setup", () => {
      vscode.window.showInformationMessage("Clara Voice: Setup wizard (coming in Phase 2)");
    })
  );

  // Register MCP server
  registerMcpServer(ctx);

  // Start file watcher
  startWatcher(ctx);

  // Start tray
  startTray(ctx, apiKey ?? "");

  // Cleanup on dispose
  ctx.subscriptions.push({
    dispose: () => {
      if (resultWatcher) {
        resultWatcher.close();
        resultWatcher = null;
      }
      stopTray();
    },
  });

  console.log("Clara Voice Code activated");
}

export function deactivate(): void {
  stopTray();
  if (resultWatcher) {
    resultWatcher.close();
    resultWatcher = null;
  }
}
