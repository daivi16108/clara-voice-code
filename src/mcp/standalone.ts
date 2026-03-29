/**
 * Clara Voice Code — Standalone MCP Server
 *
 * Provides voice tools for Claude Code via JSON-RPC over stdio:
 * - voice_speak(text, language, priority) — TTS via speak.py
 * - voice_poll(timeout) — long-poll for voice input from tray app
 * - voice_status() — current voice system state
 */
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { createInterface } from "node:readline";
import os from "node:os";
import path from "node:path";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface McpToolResult {
  content: Array<{ type: string; text: string }>;
  isError?: boolean;
}

interface JsonRpcRequest {
  jsonrpc: string;
  id?: number | string;
  method: string;
  params?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

// __dirname = out/mcp/ → scripts/ is at ../../scripts/
const SCRIPTS_DIR = path.join(path.dirname(path.dirname(__dirname)), "scripts");
const SPEAK_SCRIPT = path.join(SCRIPTS_DIR, "speak.py");

function findPython(): string {
  const home = os.homedir();
  const candidates = [
    path.join(home, "AppData", "Local", "Programs", "Python", "Python312", "python.exe"),
    path.join(home, "AppData", "Local", "Programs", "Python", "Python311", "python.exe"),
    "python",
  ];
  for (const p of candidates) {
    if (p === "python" || existsSync(p)) return p;
  }
  return "python";
}

const PYTHON = findPython();
const SHARED_SETTINGS_FILE = path.join(os.tmpdir(), "voice-claude-settings.json");

function getDefaultLanguage(): string {
  try {
    if (existsSync(SHARED_SETTINGS_FILE)) {
      const s = JSON.parse(readFileSync(SHARED_SETTINGS_FILE, "utf-8"));
      if (s.language === "en" || s.language === "ru") return s.language;
    }
  } catch { /* ignore */ }
  return "en";
}

function isTtsMuted(): boolean {
  try {
    if (existsSync(SHARED_SETTINGS_FILE)) {
      const s = JSON.parse(readFileSync(SHARED_SETTINGS_FILE, "utf-8"));
      return s.tts_muted === true;
    }
  } catch { /* ignore */ }
  return false;
}

// ---------------------------------------------------------------------------
// Voice MCP Server
// ---------------------------------------------------------------------------

class ClaraVoiceMcpServer {
  private currentSpeakProc: ChildProcess | null = null;

  // --- Tool definitions ---

  private toolDefinitions() {
    return [
      {
        name: "voice_speak",
        description:
          "Speak a message to the user via TTS. Use for important updates, questions, or task completion. Keep text concise — it will be listened to, not read.",
        inputSchema: {
          type: "object" as const,
          properties: {
            text: { type: "string", description: "Text to speak. Avoid code, paths, hashes." },
            language: { type: "string", enum: ["ru", "en"], description: "Text language" },
            priority: {
              type: "string",
              enum: ["low", "normal", "high"],
              description: "low=background, normal=reply, high=interrupts current speech",
            },
          },
          required: ["text"],
        },
      },
      {
        name: "voice_poll",
        description: "Wait for voice input from the user. Returns transcribed text or empty on timeout.",
        inputSchema: {
          type: "object" as const,
          properties: {
            timeout: {
              type: "number",
              description: "Max wait time in seconds (default 60)",
            },
          },
        },
      },
      {
        name: "voice_ask",
        description:
          "Ask the user a question by voice and wait for their spoken answer. Use for confirmations (yes/no), choices, or any question that needs a voice reply. Speaks the question first, then listens for the answer.",
        inputSchema: {
          type: "object" as const,
          properties: {
            question: { type: "string", description: "Question to ask the user. Keep it short and clear." },
            language: { type: "string", enum: ["ru", "en"], description: "Question language" },
            timeout: {
              type: "number",
              description: "Max wait time for answer in seconds (default 30)",
            },
          },
          required: ["question"],
        },
      },
      {
        name: "voice_status",
        description: "Get current voice system status: state, TTS speaking, active mode.",
        inputSchema: { type: "object" as const, properties: {} },
      },
    ];
  }

  // --- Tool handlers ---

  private async handleToolCall(name: string, args: Record<string, unknown>): Promise<McpToolResult> {
    switch (name) {
      case "voice_speak":
        return this.toolSpeak(args);
      case "voice_ask":
        return this.toolAsk(args);
      case "voice_poll":
        return this.toolPoll(args);
      case "voice_status":
        return this.toolStatus();
      default:
        return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
    }
  }

  private async toolSpeak(args: Record<string, unknown>): Promise<McpToolResult> {
    const text = String(args["text"] ?? "");
    const language = (args["language"] as string | undefined) ?? getDefaultLanguage();

    if (!text.trim()) {
      return { content: [{ type: "text", text: "Error: empty text" }], isError: true };
    }

    if (isTtsMuted()) {
      const preview = text.substring(0, 80) + (text.length > 80 ? "..." : "");
      return {
        content: [{
          type: "text",
          text: `TTS muted — text only mode. Your message was not spoken aloud. Content: "${preview}"`,
        }],
      };
    }

    const safeText = text.length > 2000 ? text.substring(0, 2000) + "..." : text;
    await this.speakViaPython(safeText, language);

    const preview = text.substring(0, 80) + (text.length > 80 ? "..." : "");
    const priority = (args["priority"] as string) ?? "normal";
    return { content: [{ type: "text", text: `Spoken (${priority}): "${preview}"` }] };
  }

  private async toolAsk(args: Record<string, unknown>): Promise<McpToolResult> {
    const question = String(args["question"] ?? "");
    const language = args["language"] as string | undefined;
    const timeoutSec = Number(args["timeout"] ?? 30);

    if (!question.trim()) {
      return { content: [{ type: "text", text: "Error: empty question" }], isError: true };
    }

    // Step 1: Speak the question (unless muted)
    if (!isTtsMuted()) {
      await this.speakViaPython(question, language);
    }

    // Step 2: Clear any old result so we only get a fresh answer
    const resultFile = this.findResultFile();
    if (resultFile && existsSync(resultFile)) {
      try {
        const data = JSON.parse(readFileSync(resultFile, "utf-8"));
        data.consumed = true;
        writeFileSync(resultFile, JSON.stringify(data));
      } catch { /* ignore */ }
    }

    // Step 3: Wait for voice answer
    const pollIntervalMs = 1000;
    const deadline = Date.now() + timeoutSec * 1000;

    if (!resultFile) {
      return { content: [{ type: "text", text: "No answer (no result file path)" }] };
    }

    while (Date.now() < deadline) {
      try {
        if (existsSync(resultFile)) {
          const data = JSON.parse(readFileSync(resultFile, "utf-8"));
          if (!data.consumed && data.text) {
            data.consumed = true;
            writeFileSync(resultFile, JSON.stringify(data));
            const answer = String(data.text).trim();
            return { content: [{ type: "text", text: answer }] };
          }
        }
      } catch { /* ignore */ }

      await new Promise((r) => setTimeout(r, pollIntervalMs));
    }

    return { content: [{ type: "text", text: "(no answer — timeout)" }] };
  }

  private speakViaPython(text: string, language?: string): Promise<void> {
    const pyArgs = [SPEAK_SCRIPT, text];
    if (language) pyArgs.push("--lang", language);

    const estimatedDuration = 15_000 + Math.ceil(text.length / 6) * 1000 + 5_000;

    return new Promise((resolve) => {
      const proc = spawn(PYTHON, pyArgs, {
        stdio: "ignore",
        cwd: SCRIPTS_DIR,
      });

      this.currentSpeakProc = proc;
      const timer = setTimeout(() => {
        proc.kill();
        this.currentSpeakProc = null;
        resolve();
      }, Math.max(estimatedDuration, 30_000));

      proc.on("close", () => {
        clearTimeout(timer);
        this.currentSpeakProc = null;
        resolve();
      });

      proc.on("error", () => {
        clearTimeout(timer);
        this.currentSpeakProc = null;
        resolve();
      });
    });
  }

  private async toolPoll(args: Record<string, unknown>): Promise<McpToolResult> {
    const timeoutSec = Number(args["timeout"] ?? 60);
    const pollIntervalMs = 2000;
    const deadline = Date.now() + timeoutSec * 1000;

    const resultFile = this.findResultFile();
    if (!resultFile) {
      return { content: [{ type: "text", text: "" }] };
    }

    while (Date.now() < deadline) {
      try {
        if (existsSync(resultFile)) {
          const data = JSON.parse(readFileSync(resultFile, "utf-8"));
          if (!data.consumed && data.text) {
            data.consumed = true;
            writeFileSync(resultFile, JSON.stringify(data));
            return { content: [{ type: "text", text: data.text }] };
          }
        }
      } catch { /* ignore */ }

      await new Promise((r) => setTimeout(r, pollIntervalMs));
    }

    return { content: [{ type: "text", text: "" }] };
  }

  private toolStatus(): McpToolResult {
    const speaking = this.currentSpeakProc !== null;
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            state: speaking ? "speaking" : "idle",
            tts_speaking: speaking,
            mode: "voice",
            tts_muted: isTtsMuted(),
          }),
        },
      ],
    };
  }

  private findResultFile(): string | null {
    const candidates = [
      path.join(process.cwd(), ".claude", "voice-result.json"),
      path.join(os.homedir(), ".claude", "voice-result.json"),
    ];
    for (const c of candidates) {
      const dir = path.dirname(c);
      if (existsSync(dir)) return c;
    }
    return candidates[0];
  }

  // --- JSON-RPC stdio transport ---

  start(): void {
    const rl = createInterface({ input: process.stdin });

    rl.on("line", async (line: string) => {
      let request: JsonRpcRequest;
      try {
        request = JSON.parse(line);
      } catch {
        return;
      }

      const response = await this.handleRequest(request);
      if (response && request.id !== undefined) {
        process.stdout.write(JSON.stringify(response) + "\n");
      }
    });

    process.stderr.write("Clara Voice MCP server started\n");
  }

  private async handleRequest(req: JsonRpcRequest): Promise<Record<string, unknown> | null> {
    const base = { jsonrpc: "2.0", id: req.id };

    switch (req.method) {
      case "initialize":
        return {
          ...base,
          result: {
            protocolVersion: "2024-11-05",
            capabilities: { tools: {} },
            serverInfo: { name: "clara-voice", version: "0.1.0" },
          },
        };

      case "notifications/initialized":
        return null;

      case "tools/list":
        return {
          ...base,
          result: { tools: this.toolDefinitions() },
        };

      case "tools/call": {
        const params = req.params ?? {};
        const name = params["name"] as string;
        const args = (params["arguments"] as Record<string, unknown>) ?? {};
        const result = await this.handleToolCall(name, args);
        return { ...base, result };
      }

      case "resources/list":
        return { ...base, result: { resources: [] } };

      case "prompts/list":
        return { ...base, result: { prompts: [] } };

      case "ping":
        return { ...base, result: {} };

      default:
        return {
          ...base,
          error: { code: -32601, message: `Method not found: ${req.method}` },
        };
    }
  }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

const server = new ClaraVoiceMcpServer();
server.start();
