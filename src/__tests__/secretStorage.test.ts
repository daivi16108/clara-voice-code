import { describe, it, expect, vi, beforeEach } from "vitest";

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

// Mock child_process to prevent real process spawning
vi.mock("child_process", () => ({
  spawn: vi.fn().mockReturnValue({
    pid: 12345,
    on: vi.fn(),
    kill: vi.fn(),
  }),
  exec: vi.fn(),
}));

// Mock fs to avoid real file system side effects
vi.mock("fs", () => ({
  existsSync: vi.fn().mockReturnValue(false),
  mkdirSync: vi.fn(),
  writeFileSync: vi.fn(),
  readFileSync: vi.fn().mockReturnValue("{}"),
  watch: vi.fn().mockReturnValue({ close: vi.fn() }),
}));

import { activate } from "../extension";
import * as vscode from "vscode";

function makeMockContext(secretsGetReturn: string | undefined): vscode.ExtensionContext {
  return {
    extensionPath: "C:/fake/extension",
    secrets: {
      get: vi.fn().mockResolvedValue(secretsGetReturn),
      store: vi.fn().mockResolvedValue(undefined),
      delete: vi.fn().mockResolvedValue(undefined),
      onDidChange: vi.fn(),
    },
    subscriptions: [],
  } as unknown as vscode.ExtensionContext;
}

describe("SecretStorage — Groq API key management", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Restore default mocks
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

  it("retrieves stored API key on activation", async () => {
    const ctx = makeMockContext("gsk_test123");

    await activate(ctx);

    expect(ctx.secrets.get).toHaveBeenCalledWith("claraVoice.groqApiKey");
  });

  it("prompts user when no key is stored and stores the provided key", async () => {
    const ctx = makeMockContext(undefined);
    (vscode.window.showInputBox as ReturnType<typeof vi.fn>).mockResolvedValue("gsk_new_key");

    await activate(ctx);

    expect(vscode.window.showInputBox).toHaveBeenCalled();
    expect(ctx.secrets.store).toHaveBeenCalledWith("claraVoice.groqApiKey", "gsk_new_key");
  });

  it("does not store key when user dismisses the prompt", async () => {
    const ctx = makeMockContext(undefined);
    (vscode.window.showInputBox as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);

    await activate(ctx);

    expect(vscode.window.showInputBox).toHaveBeenCalled();
    expect(ctx.secrets.store).not.toHaveBeenCalled();
  });
});
