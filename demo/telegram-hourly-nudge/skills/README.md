# OpenClaw skills (demo pack)

Skills here are **AgentSkills-style** `SKILL.md` trees for use **inside the
NemoClaw sandbox** (OpenClaw).

Install each skill under both:

- `/sandbox/.openclaw/skills/<skill-id>/SKILL.md`
- `~/.openclaw/skills/<skill-id>/SKILL.md` (inside the sandbox, usually
  `/home/sandbox`)

so the CLI and gateway agree on the same path. See
[Telegram hourly nudge demo](../) for copy/install and cron wiring.

| Skill | Directory |
| --- | --- |
| Philosopher nudge (LLM-themed Telegram line) | [philosopher-nudge/](philosopher-nudge/) |
| Chinese jokes (中文笑话 for Telegram, with dialect flavor) | [chinese-jokes/](chinese-jokes/) |
