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
- [ ] **P1** Local LLM: guide for installing an LLM on a remote GPU instance (Ollama, vLLM) as an alternative to NVIDIA NIM endpoints
- [x] **P2** Prerequisites checklist (Node.js, Docker, NVIDIA API key)
- [x] **P2** DNS / CoreDNS fix steps for Brev / Linux Docker (moved to FAQ)

### 3. `demo/` — Demo Scenarios & Integration Guides

- [~] **P1** Core demo: sandbox policy enforcement (deny-by-default, approve/deny flow) → `demo/1.0-basic.md`
- [~] **P1** Network control: egress policy, `openshell term` monitoring, finance preset → `demo/1.0-basic.md`
- [~] **P1** Telegram integration: setup and usage guide → `demo/2.0-telegram-bridge.md`
- [~] **P2** Migrate current `demo-plan.md` walkthrough (phases 1–4, cheat sheet, talking points) → `demo/1.0-basic.md`
- [ ] **P1** Resource control: filesystem restrictions, sandbox isolation
- [ ] **P1** With vs without NemoClaw policy comparison
- [ ] **P1** NAT integration: how to integrate with a coding agent (e.g. Cursor, Cline)
- [ ] **P2** Skill development: how to develop and register different skills
