---
phase: 01-tracer-bullet
plan: 01
subsystem: extension-core
tags: [vitest, testing, secret-storage, groq-api, tray-spawn, tdd]
dependency_graph:
  requires: []
  provides: [test-infrastructure, groq-key-storage, tray-env-injection]
  affects: [src/extension.ts, scripts/voice-tray.py]
tech_stack:
  added: [vitest@2.1.9]
  patterns: [TDD red-green, vscode-mock, vi.mock factory]
key_files:
  created:
    - vitest.config.ts
    - src/__tests__/secretStorage.test.ts
    - src/__tests__/traySpawn.test.ts
    - src/__tests__/__mocks__/vscode.ts
  modified:
    - src/extension.ts
    - scripts/voice-tray.py
decisions:
  - "Use deactivate() in beforeEach to reset trayProcess module state between tray spawn tests"
  - "vi.mock factory approach for vscode (no separate __mocks__ file needed in tests)"
  - "Cast spawn mock return value with 'as unknown as ChildProcess' for type safety"
metrics:
  duration_seconds: 276
  completed_date: "2026-03-27"
  tasks_completed: 2
  files_created: 4
  files_modified: 2
---

# Phase 01 Plan 01: Vitest Infrastructure + SecretStorage API Key Management Summary

**One-liner:** vitest test infrastructure with SecretStorage-backed Groq API key prompt and GROQ_API_KEY+--result-file injection into tray spawn.

## What Was Built

### Task 1: Wave 0 — Create vitest config and test stubs (RED)

Created the test infrastructure and failing test stubs:

- `vitest.config.ts` — vitest config with `environment: "node"`, `include: ["src/__tests__/**/*.test.ts"]`, `globals: true`
- `src/__tests__/__mocks__/vscode.ts` — comprehensive vscode module mock with window, workspace, commands, StatusBarAlignment, ConfigurationTarget
- `src/__tests__/secretStorage.test.ts` — 3 RED tests for SecretStorage lifecycle: secrets.get call, showInputBox prompt + secrets.store, dismissal without store
- `src/__tests__/traySpawn.test.ts` — 2 RED tests for tray spawn: GROQ_API_KEY in env, --result-file in args

All 5 new tests failed as expected (RED phase).

### Task 2: Implement SecretStorage + API key injection + --result-file arg (GREEN)

Modified `src/extension.ts`:
- Changed `activate()` from `void` to `async function activate(): Promise<void>`
- Added `ctx.secrets.get("claraVoice.groqApiKey")` at top of activate
- Added `vscode.window.showInputBox` prompt when key is undefined, then `ctx.secrets.store` if user provides value
- Changed `startTray(ctx)` signature to `startTray(ctx, apiKey: string)`
- Added `resultFilePath()` check in startTray with warning if no workspace
- Added `--result-file` and `resultPath` to spawn args array
- Added `env: { ...process.env, GROQ_API_KEY: apiKey }` to spawn options

Modified `scripts/voice-tray.py`:
- Added `parser.add_argument("--result-file", default=None, ...)` to argparse
- Added `if args.result_file: global RESULT_FILE; RESULT_FILE = args.result_file; os.makedirs(...)` after parse

All 11 tests (6 pre-existing + 5 new) pass (GREEN phase). TypeScript builds clean.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] trayProcess module state persisting between tests**
- **Found during:** Task 2 (GREEN phase)
- **Issue:** The module-level `trayProcess` variable in `extension.ts` is set by the first test run. The second test in traySpawn.test.ts calls `startTray` which returns early (`if (trayProcess) return`) because the variable from the previous test is still set.
- **Fix:** Added `deactivate()` call in the second test to reset `trayProcess` to null before calling `activate()` again. Also added `vi.mocked(childProcess.spawn).mockClear()` after deactivate.
- **Files modified:** `src/__tests__/traySpawn.test.ts`
- **Commit:** 0df1883

**2. [Rule 1 - Bug] TypeScript type error in spawn mock return value**
- **Found during:** Task 2 (build phase)
- **Issue:** `vi.fn().mockReturnValue({ pid, on, kill })` couldn't be directly cast to `ChildProcess` type due to missing properties.
- **Fix:** Used `as unknown as ReturnType<typeof childProcess.spawn>` double-cast in beforeEach.
- **Files modified:** `src/__tests__/traySpawn.test.ts`
- **Commit:** 0df1883

## Known Stubs

None — this plan does not introduce UI-visible stubs. The showInputBox prompt is a real functional prompt, not a stub.

## Commits

| Task | Commit | Message |
|------|--------|---------|
| Task 1 (RED) | bccfda8 | test(01-01): add failing tests for SecretStorage and tray spawn (RED) |
| Task 2 (GREEN) | 0df1883 | feat(01-01): async activate with SecretStorage and --result-file tray injection |

## Self-Check: PASSED

All files exist and commits are verified (see below).
