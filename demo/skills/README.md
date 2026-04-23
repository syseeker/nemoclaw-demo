# OpenClaw skills (demo pack)

Skills here are **AgentSkills-style** `SKILL.md` trees for use **inside the
NemoClaw sandbox** (OpenClaw).

Install each skill under both:

- `/sandbox/.openclaw/skills/<skill-id>/SKILL.md`
- `~/.openclaw/skills/<skill-id>/SKILL.md` (inside the sandbox, usually
  `/home/sandbox`)

so the CLI and gateway agree on the same path. See
[Demo 2.2](../2.2-telegram-hourly-nudge.md) for copy/install and cron wiring,
and [Demo 4.0](../4.0-aiq-blueprint.md) for the AI-Q research skill.

| Skill | Directory |
| --- | --- |
| Sandbox heartbeat (health summary for Telegram) | [sandbox-heartbeat/](sandbox-heartbeat/) |
| Philosopher nudge (LLM-themed Telegram line) | [philosopher-nudge/](philosopher-nudge/) |
| AI-Q research (multi-agent deep research via AI-Q Blueprint) | [aiq-research/](aiq-research/) |
