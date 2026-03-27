import { vi } from "vitest";

export const StatusBarAlignment = { Left: 1, Right: 2 };

export const ConfigurationTarget = { Global: 1, Workspace: 2, WorkspaceFolder: 3 };

export const workspace = {
  workspaceFolders: [
    { uri: { fsPath: "C:/fake/workspace" } },
  ],
  getConfiguration: vi.fn().mockReturnValue({
    get: vi.fn().mockReturnValue("clara"),
    update: vi.fn().mockResolvedValue(undefined),
  }),
};

export const window = {
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
};

export const commands = {
  registerCommand: vi.fn().mockReturnValue({ dispose: vi.fn() }),
  executeCommand: vi.fn(),
};

export const ExtensionContext = {};
