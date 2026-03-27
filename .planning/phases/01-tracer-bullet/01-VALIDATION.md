---
phase: 1
slug: tracer-bullet
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-27
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | vitest 2.0.0 |
| **Config file** | none — Wave 0 installs `vitest.config.ts` |
| **Quick run command** | `npm run build` (TypeScript compile — per task) |
| **Full suite command** | `npm test` (vitest run) |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `npm run build`
- **After every plan wave:** Run `npm test`
- **Before `/gsd:verify-work`:** Full suite must be green + manual smoke test
- **Max feedback latency:** ~5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 0 | Wave 0 infra | unit | `npm run build` | ❌ W0 | ⬜ pending |
| 1-01-02 | 01 | 1 | SecretStorage store/get | unit | `npm test` | ❌ W0 | ⬜ pending |
| 1-01-03 | 01 | 1 | API key injected into tray env | unit | `npm test` | ❌ W0 | ⬜ pending |
| 1-02-01 | 02 | 1 | MCP registerMcpServer writes settings.json | unit | `npm test` | ❌ W0 | ⬜ pending |
| 1-02-02 | 02 | 1 | registerMcpServer idempotent | unit | `npm test` | ❌ W0 | ⬜ pending |
| 1-03-01 | 03 | 1 | --result-file arg added to voice-tray.py | unit | `npm run build` + manual | ❌ W0 | ⬜ pending |
| 1-03-02 | 03 | 1 | Tray spawn passes --result-file path | unit | `npm test` | ❌ W0 | ⬜ pending |
| 1-03-03 | 03 | 2 | Full voice cycle smoke test | manual e2e | speak wake word → chat → voice_speak | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `vitest.config.ts` — framework config for non-browser (Node) environment
- [ ] `src/__tests__/secretStorage.test.ts` — stubs for SecretStorage store/retrieve with mock
- [ ] `src/__tests__/registerMcpServer.test.ts` — stubs for MCP registration idempotency

*Wave 0 must complete before any Plan 01 unit tests can run.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| VSIX installs without errors | SC-1 | Requires live VS Code install | Install VSIX in fresh VS Code, check no error notifications |
| Tray icon appears in Windows taskbar | SC-3 | Requires running Python + tray process | Activate extension, look for Clara tray icon |
| Voice command reaches Claude Code chat | SC-4 | Requires microphone + Claude Code running | Say wake word, observe text in chat input |
| Claude responds via voice_speak | SC-5 | Requires audio output + Claude Code running | Claude calls voice_speak tool, hear audio |
| Claude Code picks up MCP after restart | SC-2b | Requires Claude Code restart | Restart Claude Code, run `/voice_status` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
