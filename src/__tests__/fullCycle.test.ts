/**
 * Integration test for the full activation sequence.
 *
 * Verifies that activate() calls secrets.get, registerMcpServer (writeFileSync),
 * startWatcher (fs.watch), and startTray (spawn) with all required arguments and
 * environment variables in one cohesive flow.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import type { ExtensionContext } from "vscode";

// ---------------------------------------------------------------------------
// Module mocks — must be declared before any imports from the module under test
// ---------------------------------------------------------------------------

vi.mock("vscode", () => ({
  StatusBarAlignment: { Left: 1, Right: 2 },
  ConfigurationTarget: { Global: 1, Workspace: 2, WorkspaceFolder: 3 },
  workspace: {
    workspaceFolders: [{ uri: { fsPath: "/test/workspace" } }],
    getConfiguration: vi.fn().mockReturnValue({
      get: vi.fn().mockReturnValue("clara"),
      update: vi.fn().mockResolvedValue(undefined),
    }),
  },
  window: {
    showInputBox: vi.fn(),
    showInformationMessage: vi.fn(),
    showWarningMessage: vi.fn(),
    showQuickPick: vi.fn(),
    createStatusBarItem: vi.fn().mockReturnValue({
      text: "",
      tooltip: "",
      command: "",
      show: vi.fn(),
      hide: vi.fn(),
      dispose: vi.fn(),
    }),
  },
  commands: {
    registerCommand: vi.fn().mockReturnValue({ dispose: vi.fn() }),
    executeCommand: vi.fn(),
  },
}));

vi.mock("child_process", () => ({
  spawn: vi.fn().mockReturnValue({ pid: 99999, on: vi.fn(), kill: vi.fn() }),
  exec: vi.fn(),
}));

vi.mock("fs", () => ({
  // tray script exists, settings.json does NOT (so MCP registration writes)
  existsSync: vi.fn().mockImplementation((p: string) => {
    if (String(p).endsWith("voice-tray.py")) return true;
    if (String(p).endsWith(".claude")) return true;
    return false;
  }),
  mkdirSync: vi.fn(),
  writeFileSync: vi.fn(),
  readFileSync: vi.fn().mockReturnValue("{}"),
  watch: vi.fn().mockReturnValue({ close: vi.fn() }),
}));

// ---------------------------------------------------------------------------
// Imports (after mocks)
// ---------------------------------------------------------------------------

import * as vscode from "vscode";
import * as childProcess from "child_process";
import * as fs from "fs";
import { activate, deactivate } from "../extension";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeMockContext(apiKey: string): ExtensionContext {
  return {
    extensionPath: "/test/extension",
    secrets: {
      get: vi.fn().mockResolvedValue(apiKey),
      store: vi.fn().mockResolvedValue(undefined),
      delete: vi.fn().mockResolvedValue(undefined),
      onDidChange: vi.fn(),
    },
    subscriptions: [],
  } as unknown as ExtensionContext;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Full activation sequence integration", () => {
  beforeEach(() => {
    // Reset trayProcess module state so each test starts fresh
    deactivate();
    vi.clearAllMocks();

    // Restore mocks after clearAllMocks
    vi.mocked(childProcess.spawn).mockReturnValue({
      pid: 99999,
      on: vi.fn(),
      kill: vi.fn(),
    } as unknown as ReturnType<typeof childProcess.spawn>);

    vi.mocked(fs.existsSync).mockImplementation((p: fs.PathLike) => {
      if (String(p).endsWith("voice-tray.py")) return true;
      if (String(p).endsWith(".claude")) return true;
      return false;
    });

    vi.mocked(fs.readFileSync).mockReturnValue("{}");
    vi.mocked(fs.watch).mockReturnValue({
      close: vi.fn(),
    } as unknown as ReturnType<typeof fs.watch>);

    (vscode.window.createStatusBarItem as ReturnType<typeof vi.fn>).mockReturnValue({
      text: "",
      tooltip: "",
      command: "",
      show: vi.fn(),
      hide: vi.fn(),
      dispose: vi.fn(),
    });

    (vscode.workspace.getConfiguration as ReturnType<typeof vi.fn>).mockReturnValue({
      get: vi.fn().mockReturnValue("clara"),
      update: vi.fn().mockResolvedValue(undefined),
    });

    (vscode.commands.registerCommand as ReturnType<typeof vi.fn>).mockReturnValue({
      dispose: vi.fn(),
    });
  });

  it("calls secrets.get, writes settings.json (MCP), starts fs.watch, and spawns tray in order", async () => {
    const ctx = makeMockContext("gsk_test_key");
    const callOrder: string[] = [];

    // Instrument the key calls to track order
    (ctx.secrets.get as ReturnType<typeof vi.fn>).mockImplementation(async (key: string) => {
      callOrder.push(`secrets.get(${key})`);
      return "gsk_test_key";
    });

    vi.mocked(fs.writeFileSync).mockImplementation(() => {
      callOrder.push("fs.writeFileSync");
    });

    vi.mocked(fs.watch).mockImplementation(() => {
      callOrder.push("fs.watch");
      return { close: vi.fn() } as unknown as ReturnType<typeof fs.watch>;
    });

    vi.mocked(childProcess.spawn).mockImplementation(() => {
      callOrder.push("spawn");
      return { pid: 99999, on: vi.fn(), kill: vi.fn() } as unknown as ReturnType<typeof childProcess.spawn>;
    });

    await activate(ctx);

    // secrets.get must happen before MCP write and tray spawn
    expect(callOrder[0]).toBe("secrets.get(claraVoice.groqApiKey)");
    expect(callOrder).toContain("fs.writeFileSync");
    expect(callOrder).toContain("fs.watch");
    expect(callOrder).toContain("spawn");
  });

  it("spawn args include --wake-custom and --result-file with correct workspace path", async () => {
    const ctx = makeMockContext("gsk_test_key");

    await activate(ctx);

    expect(childProcess.spawn).toHaveBeenCalled();
    const spawnArgs = vi.mocked(childProcess.spawn).mock.calls[0][1] as string[];

    expect(spawnArgs).toContain("--wake-custom");
    expect(spawnArgs).toContain("--result-file");

    const resultFileIndex = spawnArgs.indexOf("--result-file");
    const resultFilePath = spawnArgs[resultFileIndex + 1];

    expect(resultFilePath).toBeTruthy();
    // Must point to workspace/.claude/voice-result.json
    expect(resultFilePath).toContain("voice-result.json");
    expect(resultFilePath).toContain(".claude");
    expect(resultFilePath).toContain("test"); // "/test/workspace" path fragment
  });

  it("spawn env contains GROQ_API_KEY injected from SecretStorage", async () => {
    const ctx = makeMockContext("gsk_test_key");

    await activate(ctx);

    expect(childProcess.spawn).toHaveBeenCalled();
    const spawnOptions = vi.mocked(childProcess.spawn).mock.calls[0][2] as {
      env?: Record<string, string>;
    };

    expect(spawnOptions?.env).toBeDefined();
    expect(spawnOptions.env!.GROQ_API_KEY).toBe("gsk_test_key");
  });

  it("MCP registration writes settings.json with correct clara-voice entry", async () => {
    const ctx = makeMockContext("gsk_test_key");

    await activate(ctx);

    expect(fs.writeFileSync).toHaveBeenCalled();

    // Find the settings.json write (the one that includes 'clara-voice')
    const settingsWrite = vi
      .mocked(fs.writeFileSync)
      .mock.calls.find(
        ([, data]) => typeof data === "string" && (data as string).includes("clara-voice")
      );

    expect(settingsWrite).toBeTruthy();
    const writtenSettings = JSON.parse(settingsWrite![1] as string) as {
      mcpServers?: { "clara-voice"?: { command: string; args: string[] } };
    };
    expect(writtenSettings.mcpServers?.["clara-voice"]).toBeDefined();
    const claraEntry = writtenSettings.mcpServers?.["clara-voice"];
    expect(claraEntry?.command).toBe("node");
    expect(claraEntry?.args[0]).toContain("standalone.js");
  });
});
