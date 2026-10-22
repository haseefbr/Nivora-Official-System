# NIVORA

@AGENTS.md

## Claude Code
- `blueprint.json` is the source of truth; AGENTS.md says how to use it.
- Start each milestone in plan mode (Shift+Tab) and wait for approval before editing.
- Permissions are in `.claude/settings.json`: the agent asks before every change; the tests and read-only Git run without asking; installs, commits, pushes and deletes ask first; `.env` is never read.
- After every edit, a hook runs the tests (`.claude/hooks/run-tests.sh`). When they fail, you are shown the failures: fix them before you go on.
- Before each commit, run `/verify` (`.claude/skills/verify/SKILL.md`).
