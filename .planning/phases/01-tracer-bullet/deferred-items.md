# Deferred Items — Phase 01 Tracer Bullet

## Pre-existing Issues (Out of Scope)

### traySpawn.test.ts: "passes --result-file argument in spawn args" fails

**File:** `src/__tests__/traySpawn.test.ts` line 99
**Discovered during:** Plan 01-02, Task 2
**Root cause:** The global `trayProcess` variable in `extension.ts` retains state between test runs. After the first test in the describe block calls `activate()`, `trayProcess` is set. The second test calls `vi.clearAllMocks()` (resets call counts) but NOT module-level state. When the second test calls `activate()` again, `startTray()` returns early because `if (trayProcess) return` — so `spawn` is never called.
**Fix needed:** The test file needs to reset `trayProcess` between tests OR the test should use `vi.resetModules()` to reload the extension module.
**Owner:** Plan 01-01 (this test belongs to that plan's work)
