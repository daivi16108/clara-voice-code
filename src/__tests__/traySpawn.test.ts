import { describe, it, expect, vi, beforeEach } from "vitest";
import type { ExtensionContext } from "vscode";

// Mock vscode before importing the module under test
vi.mock("vscode", () => ({
  StatusBarAlignment: { Left: 1, Right: 2 },
  ConfigurationTarget: { Global: 1, Workspace: 2, WorkspaceFolder: 3 },
  workspace: {
    workspaceFolders: [{ uri: { fsPath: "C:/fake/workspace" } }],
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
  spawn: vi.fn().mockReturnValue({ pid: 12345, on: vi.fn(), kill: vi.fn() }),
  exec: vi.fn(),
}));

// Mock fs — tray script and .claude dir must appear to exist so startTray proceeds
vi.mock("fs", () => ({
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

import * as vscode from "vscode";
import * as childProcess from "child_process";
import * as fs from "fs";
import { activate } from "../extension";

function makeMockContext(apiKey: string): ExtensionContext {
  return {
    extensionPath: "C:/fake/extension",
    secrets: {
      get: vi.fn().mockResolvedValue(apiKey),
      store: vi.fn().mockResolvedValue(undefined),
      delete: vi.fn().mockResolvedValue(undefined),
      onDidChange: vi.fn(),
    },
    subscriptions: [],
  } as unknown as ExtensionContext;
}

describe("Tray spawn — API key and result-file injection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Restore mocks cleared by clearAllMocks
    vi.mocked(childProcess.spawn).mockReturnValue({ pid: 12345, on: vi.fn(), kill: vi.fn() } as unknown as ReturnType<typeof childProcess.spawn>);
    vi.mocked(fs.existsSync).mockImplementation((p: fs.PathLike) => {
      if (String(p).endsWith("voice-tray.py")) return true;
      if (String(p).endsWith(".claude")) return true;
      return false;
    });
    vi.mocked(fs.readFileSync).mockReturnValue("{}");
    vi.mocked(fs.watch).mockReturnValue({ close: vi.fn() } as unknown as ReturnType<typeof fs.watch>);
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
    (vscode.commands.registerCommand as ReturnType<typeof vi.fn>).mockReturnValue({ dispose: vi.fn() });
  });

  it("passes GROQ_API_KEY in the spawn environment", async () => {
    const ctx = makeMockContext("gsk_test_key_123");

    await activate(ctx);

    expect(childProcess.spawn).toHaveBeenCalled();
    const spawnCall = vi.mocked(childProcess.spawn).mock.calls[0];
    const spawnOptions = spawnCall[2] as { env?: Record<string, string> };
    expect(spawnOptions?.env?.GROQ_API_KEY).toBe("gsk_test_key_123");
  });

  it("passes --result-file argument in spawn args", async () => {
    // Deactivate any running tray from previous test by calling deactivate
    const { deactivate } = await import("../extension");
    deactivate();

    const ctx = makeMockContext("gsk_test_key_abc");
    // Reset spawn call count after deactivate
    vi.mocked(childProcess.spawn).mockClear();

    await activate(ctx);

    expect(childProcess.spawn).toHaveBeenCalled();
    const spawnCall = vi.mocked(childProcess.spawn).mock.calls[0];
    const spawnArgs = spawnCall[1] as string[];
    expect(spawnArgs).toContain("--result-file");
    const resultFileIndex = spawnArgs.indexOf("--result-file");
    expect(spawnArgs[resultFileIndex + 1]).toBeTruthy();
    expect(String(spawnArgs[resultFileIndex + 1])).toContain("voice-result.json");
  });
});
