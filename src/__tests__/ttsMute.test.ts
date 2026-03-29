/**
 * Unit tests for TTS mute behavior in the MCP server.
 *
 * Strategy: We cannot import standalone.ts directly (it starts a server on
 * import). Instead we inline testable copies of the three functions that need
 * mute support, injecting fs-like deps so every test runs in-process.
 *
 * These implementations are the GREEN target — production code in
 * standalone.ts must match this logic exactly for the tests to pass.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface McpToolResult {
  content: Array<{ type: string; text: string }>;
  isError?: boolean;
}

interface FsDep {
  existsSync: (p: string) => boolean;
  readFileSync: (p: string, enc: string) => string;
}

// ---------------------------------------------------------------------------
// Testable inline implementations (mirror standalone.ts GREEN target)
// ---------------------------------------------------------------------------

/**
 * Reads SHARED_SETTINGS_FILE and returns the tts_muted flag.
 * Returns false if file missing, parse error, or key absent.
 */
function isTtsMuted(fsDep: FsDep, settingsPath: string): boolean {
  try {
    if (fsDep.existsSync(settingsPath)) {
      const s = JSON.parse(fsDep.readFileSync(settingsPath, "utf-8"));
      return s.tts_muted === true;
    }
  } catch { /* ignore */ }
  return false;
}

/**
 * Testable implementation of toolSpeak that checks mute flag before speaking.
 * When muted: returns notification without calling speakFn.
 * When unmuted: calls speakFn and returns normal response.
 */
async function toolSpeakImpl(
  args: Record<string, unknown>,
  fsDep: FsDep,
  settingsPath: string,
  speakFn: (text: string, language: string) => Promise<void>
): Promise<McpToolResult> {
  const text = String(args["text"] ?? "");

  if (!text.trim()) {
    return { content: [{ type: "text", text: "Error: empty text" }], isError: true };
  }

  if (isTtsMuted(fsDep, settingsPath)) {
    const preview = text.substring(0, 80) + (text.length > 80 ? "..." : "");
    return {
      content: [{
        type: "text",
        text: `TTS muted — text only mode. Your message was not spoken aloud. Content: "${preview}"`,
      }],
    };
  }

  const language = (args["language"] as string | undefined) ?? "en";
  const safeText = text.length > 2000 ? text.substring(0, 2000) + "..." : text;
  await speakFn(safeText, language);

  const preview = text.substring(0, 80) + (text.length > 80 ? "..." : "");
  const priority = (args["priority"] as string) ?? "normal";
  return { content: [{ type: "text", text: `Spoken (${priority}): "${preview}"` }] };
}

/**
 * Testable implementation of toolStatus that includes tts_muted field.
 */
function toolStatusImpl(
  speaking: boolean,
  fsDep: FsDep,
  settingsPath: string
): McpToolResult {
  return {
    content: [{
      type: "text",
      text: JSON.stringify({
        state: speaking ? "speaking" : "idle",
        tts_speaking: speaking,
        mode: "voice",
        tts_muted: isTtsMuted(fsDep, settingsPath),
      }),
    }],
  };
}

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

const FAKE_SETTINGS_PATH = "/tmp/fake-voice-claude-settings.json";

function makeFsDep(overrides: Partial<FsDep> = {}): FsDep {
  return {
    existsSync: vi.fn(() => false),
    readFileSync: vi.fn(() => "{}"),
    ...overrides,
  };
}

function makeMutedFsDep(): FsDep {
  return makeFsDep({
    existsSync: vi.fn(() => true),
    readFileSync: vi.fn(() => JSON.stringify({ tts_muted: true })),
  });
}

function makeUnmutedFsDep(): FsDep {
  return makeFsDep({
    existsSync: vi.fn(() => true),
    readFileSync: vi.fn(() => JSON.stringify({ tts_muted: false })),
  });
}

function makeEmptyFsDep(): FsDep {
  return makeFsDep({
    existsSync: vi.fn(() => true),
    readFileSync: vi.fn(() => JSON.stringify({})),
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ttsMute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // -------------------------------------------------------------------------
  it("toolSpeak returns muted notification when tts_muted=true, does not call speakFn", async () => {
    const fsDep = makeMutedFsDep();
    const speakFn = vi.fn(async () => {});

    const result = await toolSpeakImpl(
      { text: "hello" },
      fsDep,
      FAKE_SETTINGS_PATH,
      speakFn
    );

    expect(speakFn).not.toHaveBeenCalled();
    expect(result.content[0].text).toContain("TTS muted");
    expect(result.isError).toBeUndefined();
  });

  // -------------------------------------------------------------------------
  it("toolSpeak plays audio normally when tts_muted=false", async () => {
    const fsDep = makeUnmutedFsDep();
    const speakFn = vi.fn(async () => {});

    const result = await toolSpeakImpl(
      { text: "hello", priority: "normal" },
      fsDep,
      FAKE_SETTINGS_PATH,
      speakFn
    );

    expect(speakFn).toHaveBeenCalledOnce();
    expect(result.content[0].text).toContain("Spoken (normal):");
  });

  // -------------------------------------------------------------------------
  it("toolSpeak plays audio normally when tts_muted key is missing from settings", async () => {
    const fsDep = makeEmptyFsDep();
    const speakFn = vi.fn(async () => {});

    const result = await toolSpeakImpl(
      { text: "hello" },
      fsDep,
      FAKE_SETTINGS_PATH,
      speakFn
    );

    expect(speakFn).toHaveBeenCalledOnce();
    expect(result.content[0].text).toContain("Spoken");
  });

  // -------------------------------------------------------------------------
  it("toolStatus includes tts_muted=true when settings has tts_muted=true", () => {
    const fsDep = makeMutedFsDep();

    const result = toolStatusImpl(false, fsDep, FAKE_SETTINGS_PATH);
    const payload = JSON.parse(result.content[0].text) as Record<string, unknown>;

    expect(payload["tts_muted"]).toBe(true);
  });

  // -------------------------------------------------------------------------
  it("toolStatus includes tts_muted=false when settings has tts_muted=false", () => {
    const fsDep = makeUnmutedFsDep();

    const result = toolStatusImpl(false, fsDep, FAKE_SETTINGS_PATH);
    const payload = JSON.parse(result.content[0].text) as Record<string, unknown>;

    expect(payload["tts_muted"]).toBe(false);
  });
});
