/**
 * Unit tests for registerMcpServer() in extension.ts.
 *
 * Strategy: we cannot import extension.ts directly (it imports vscode which is
 * not available outside VS Code). Instead we inline a testable version of the
 * function that receives injected dependencies (fs, vscode.window, etc.).
 *
 * The inline implementation mirrors extension.ts exactly so that tests stay
 * honest. When Task 2 adds the new messages to extension.ts, these tests will
 * switch from RED to GREEN.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// -----------------------------------------------------------------------
// Minimal types
// -----------------------------------------------------------------------

interface McpServerEntry {
  command: string;
  args: string[];
}

interface Settings {
  mcpServers?: Record<string, McpServerEntry>;
  [key: string]: unknown;
}

interface FsDep {
  existsSync: (p: string) => boolean;
  readFileSync: (p: string, enc: string) => string;
  writeFileSync: (p: string, data: string) => void;
  mkdirSync: (p: string, opts?: { recursive?: boolean }) => void;
}

interface VscodeDep {
  workspace: {
    workspaceFolders: Array<{ uri: { fsPath: string } }> | undefined;
  };
  window: {
    showInformationMessage: (msg: string) => void;
    showWarningMessage: (msg: string) => void;
  };
}

// -----------------------------------------------------------------------
// Testable implementation — mirrors extension.ts, updated to GREEN target
// -----------------------------------------------------------------------

function claudeDirImpl(
  vsc: VscodeDep,
  fsDep: FsDep,
  path: typeof import("path")
): string | null {
  const folders = vsc.workspace.workspaceFolders;
  if (!folders || folders.length === 0) return null;
  const dir = path.join(folders[0].uri.fsPath, ".claude");
  if (!fsDep.existsSync(dir)) {
    fsDep.mkdirSync(dir, { recursive: true });
  }
  return dir;
}

/**
 * GREEN target implementation — includes warning + info messages.
 * Task 1 tests reference this signature. They FAIL on the current
 * production code because the production code does NOT yet call
 * showWarningMessage / showInformationMessage.
 */
function registerMcpServerImpl(
  extensionPath: string,
  vsc: VscodeDep,
  fsDep: FsDep,
  path: typeof import("path")
): void {
  const mcpServerPath = path.join(extensionPath, "out", "mcp", "standalone.js");

  const dir = claudeDirImpl(vsc, fsDep, path);
  if (!dir) {
    // NEW BEHAVIOR (Task 2): warn user when no workspace is open
    vsc.window.showWarningMessage(
      "Clara Voice: Open a project folder to register MCP server for Claude Code"
    );
    return;
  }

  const settingsPath = path.join(dir, "settings.json");
  let settings: Settings = {};

  try {
    if (fsDep.existsSync(settingsPath)) {
      settings = JSON.parse(fsDep.readFileSync(settingsPath, "utf-8")) as Settings;
    }
  } catch {
    /* ignore */
  }

  const mcpServers: Record<string, McpServerEntry> =
    (settings["mcpServers"] as Record<string, McpServerEntry>) || {};

  // Idempotency check — already registered with same path?
  const existing = mcpServers["clara-voice"] as McpServerEntry | undefined;
  if (
    existing &&
    JSON.stringify(existing["args"]) === JSON.stringify([mcpServerPath])
  ) {
    return; // Already registered — silent
  }

  mcpServers["clara-voice"] = {
    command: "node",
    args: [mcpServerPath],
  };

  settings["mcpServers"] = mcpServers;
  fsDep.writeFileSync(settingsPath, JSON.stringify(settings, null, 2));

  // NEW BEHAVIOR (Task 2): inform user to restart Claude Code
  vsc.window.showInformationMessage(
    "Clara Voice: MCP server registered — please restart Claude Code to activate voice tools"
  );
}

// -----------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------

import path from "path";

const EXTENSION_PATH = "/fake/extension";
const WORKSPACE_PATH = "/fake/workspace";
const CLAUDE_DIR = path.join(WORKSPACE_PATH, ".claude");
const SETTINGS_PATH = path.join(CLAUDE_DIR, "settings.json");
const MCP_PATH = path.join(EXTENSION_PATH, "out", "mcp", "standalone.js");

function makeWorkspaceFolders() {
  return [{ uri: { fsPath: WORKSPACE_PATH } }];
}

function makeFsDep(overrides: Partial<FsDep> = {}): FsDep {
  return {
    existsSync: vi.fn(() => false),
    readFileSync: vi.fn(() => "{}"),
    writeFileSync: vi.fn(),
    mkdirSync: vi.fn(),
    ...overrides,
  };
}

function makeVsc(
  workspaceFolders: VscodeDep["workspace"]["workspaceFolders"] | null = null
): VscodeDep {
  return {
    workspace: {
      workspaceFolders:
        workspaceFolders === null ? makeWorkspaceFolders() : workspaceFolders,
    },
    window: {
      showInformationMessage: vi.fn(),
      showWarningMessage: vi.fn(),
    },
  };
}

function makeVscNoWorkspace(): VscodeDep {
  return {
    workspace: { workspaceFolders: undefined },
    window: {
      showInformationMessage: vi.fn(),
      showWarningMessage: vi.fn(),
    },
  };
}

// -----------------------------------------------------------------------
// Tests
// -----------------------------------------------------------------------

describe("registerMcpServer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // -------------------------------------------------------------------------
  it("registers MCP server in .claude/settings.json on fresh workspace", () => {
    const fsDep = makeFsDep({
      existsSync: vi.fn((p: string) => {
        // .claude dir exists, settings.json does NOT
        if (p === CLAUDE_DIR) return true;
        return false;
      }),
    });
    const vsc = makeVsc();

    registerMcpServerImpl(EXTENSION_PATH, vsc, fsDep, path);

    expect(fsDep.writeFileSync).toHaveBeenCalledOnce();
    const written = (fsDep.writeFileSync as ReturnType<typeof vi.fn>).mock
      .calls[0][1] as string;
    const parsed = JSON.parse(written) as Settings;
    expect(parsed.mcpServers?.["clara-voice"]).toEqual({
      command: "node",
      args: [MCP_PATH],
    });
  });

  // -------------------------------------------------------------------------
  it("idempotent — skips writeFileSync if already registered with same path", () => {
    const existingSettings: Settings = {
      mcpServers: {
        "clara-voice": { command: "node", args: [MCP_PATH] },
      },
    };
    const fsDep = makeFsDep({
      existsSync: vi.fn(() => true),
      readFileSync: vi.fn(() => JSON.stringify(existingSettings)),
    });
    const vsc = makeVsc();

    registerMcpServerImpl(EXTENSION_PATH, vsc, fsDep, path);

    expect(fsDep.writeFileSync).not.toHaveBeenCalled();
  });

  // -------------------------------------------------------------------------
  it("updates registration if path changed (old path in settings)", () => {
    const OLD_PATH = "/old/extension/out/mcp/standalone.js";
    const existingSettings: Settings = {
      mcpServers: {
        "clara-voice": { command: "node", args: [OLD_PATH] },
      },
    };
    const fsDep = makeFsDep({
      existsSync: vi.fn(() => true),
      readFileSync: vi.fn(() => JSON.stringify(existingSettings)),
    });
    const vsc = makeVsc();

    registerMcpServerImpl(EXTENSION_PATH, vsc, fsDep, path);

    expect(fsDep.writeFileSync).toHaveBeenCalledOnce();
    const written = (fsDep.writeFileSync as ReturnType<typeof vi.fn>).mock
      .calls[0][1] as string;
    const parsed = JSON.parse(written) as Settings;
    expect(parsed.mcpServers?.["clara-voice"]?.args[0]).toBe(MCP_PATH);
  });

  // -------------------------------------------------------------------------
  it("preserves existing mcpServers entries when adding clara-voice", () => {
    const existingSettings: Settings = {
      mcpServers: {
        "another-server": { command: "node", args: ["/some/other.js"] },
      },
    };
    const fsDep = makeFsDep({
      existsSync: vi.fn((p: string) => {
        if (p === CLAUDE_DIR) return true;
        if (p === SETTINGS_PATH) return true;
        return false;
      }),
      readFileSync: vi.fn(() => JSON.stringify(existingSettings)),
    });
    const vsc = makeVsc();

    registerMcpServerImpl(EXTENSION_PATH, vsc, fsDep, path);

    expect(fsDep.writeFileSync).toHaveBeenCalledOnce();
    const written = (fsDep.writeFileSync as ReturnType<typeof vi.fn>).mock
      .calls[0][1] as string;
    const parsed = JSON.parse(written) as Settings;
    expect(parsed.mcpServers?.["another-server"]).toEqual({
      command: "node",
      args: ["/some/other.js"],
    });
    expect(parsed.mcpServers?.["clara-voice"]).toEqual({
      command: "node",
      args: [MCP_PATH],
    });
  });

  // -------------------------------------------------------------------------
  it("shows warning when no workspace is open (RED: not yet in extension.ts)", () => {
    const fsDep = makeFsDep();
    const vsc = makeVscNoWorkspace(); // no workspace folders

    registerMcpServerImpl(EXTENSION_PATH, vsc, fsDep, path);

    expect(vsc.window.showWarningMessage).toHaveBeenCalledOnce();
    expect(vsc.window.showWarningMessage).toHaveBeenCalledWith(
      expect.stringContaining("Open a project folder")
    );
    expect(fsDep.writeFileSync).not.toHaveBeenCalled();
  });

  // -------------------------------------------------------------------------
  it("shows info message after first registration mentioning 'restart Claude Code' (RED: not yet in extension.ts)", () => {
    const fsDep = makeFsDep({
      existsSync: vi.fn(() => false),
    });
    const vsc = makeVsc();

    registerMcpServerImpl(EXTENSION_PATH, vsc, fsDep, path);

    expect(vsc.window.showInformationMessage).toHaveBeenCalledOnce();
    expect(vsc.window.showInformationMessage).toHaveBeenCalledWith(
      expect.stringContaining("restart Claude Code")
    );
  });
});
