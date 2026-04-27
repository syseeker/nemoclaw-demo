# TODO

> **Status**: `[ ]` open | `[~]` draft (content written, not tested) | `[x]` done | `[-]` dropped
> **Priority**: `P0` critical | `P1` high | `P2` normal | `P3` low

---

## Documentation Restructure

Split the current monolithic content into focused documents.

### 1. Content split — `INSTALL.md`, `DEMO.md`, `FAQ.md`

- [x] **P1** Extract installation content from `demo-plan.md` into `INSTALL.md`
- [x] **P1** Extract demo walkthrough content into `DEMO.md`
- [x] **P2** Create `FAQ.md` with basic conceptual questions and troubleshooting (what is `inference.local`, how inference routing works, `web_fetch` vs `exec`, binary restrictions, DNS cache, etc.)
- [x] **P2** Update `README.md` to link to the new docs
- [x] **P3** Archive `demo-plan.md` / `demo-plan-simple.md` → `archive/`

### 2. `INSTALL.md` — Installation & Environment Setup

- [x] **P1** Brev setup: how to provision a GPU instance and install NemoClaw
- [x] **P1** Code Server: how to install and run code-server on a remote instance
- [x] **P1** Remote GPU / self-hosted NIM: hot-swap guide with `nim-swap.sh` and `nim-remote-swap.sh` → `demo/remote-gpu/`
- [x] **P2** Prerequisites checklist (Node.js, Docker, NVIDIA API key)
- [x] **P2** DNS / CoreDNS fix steps for Brev / Linux Docker (moved to FAQ)

### 3. `demo/` — Demo Scenarios & Integration Guides

- [~] **P1** Core demo: sandbox policy enforcement (deny-by-default, approve/deny flow) → `demo/basic/`
- [~] **P1** Network control: egress policy, `openshell term` monitoring, finance preset → `demo/basic/`
- [~] **P1** Telegram integration: setup and usage guide → `demo/telegram-bridge/`
- [~] **P2** Migrate current `demo-plan.md` walkthrough (phases 1–4, cheat sheet, talking points) → `demo/basic/`
- [ ] **P1** Resource control: filesystem restrictions, sandbox isolation
- [ ] **P1** With vs without NemoClaw policy comparison
- [ ] **P1** NAT integration: how to integrate with a coding agent (e.g. Cursor, Cline)
- [x] **P2** Telegram hourly nudge: chinese-jokes skill, `AGENTS.md` template, joke cron pipeline → `demo/telegram-hourly-nudge/`
- [ ] **P2** Skill development: how to develop and register different skills

### 4. Upcoming demos

- [ ] **P1** AI-Q Blueprint: integrate AI-Q blueprint with NemoClaw → `demo/aiq-blueprint/`
- [ ] **P1** cuOpt scheduling: cuOpt as MCP service for route/schedule optimization → `demo/cuopt-mcp/`
- [~] **P2** Nemotron voice agent: voice-driven agent demo scaffolded with `install.sh`, OpenClaw bridge, and Jewel tour-guide workspace → `demo/voice-agent/`
- [ ] **P2** Gaming example: GOG / Blender gaming demo (based on `demo-nvidia-official/gog-demo/`, `blender-demo/`) → `demo/gaming/`
- [ ] **P2** Google Calendar: test OpenClaw connecting to Google Calendar API
- [ ] **P2** Outlook web login: OpenClaw opens web Outlook, logs in, and downloads files
- [ ] **P2** NAT profiler: token counting and model usage tracking for cost/performance profiling
