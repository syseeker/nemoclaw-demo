---
name: aiq-research
description: Run a multi-agent deep-research query against the AI-Q Blueprint backend (intent classification, shallow/deep research, web search, citations) and return a concise answer with sources. Use for any "research", "deep dive", "investigate", or "find citations" request.
user-invocable: true
---

# AI-Q deep research

## Purpose

Answer research-style questions by delegating to the **AI-Q Blueprint**
multi-agent pipeline running on the host. AI-Q handles intent classification,
shallow/deep research, web search (Tavily), and citation synthesis. You return
a tight summary plus every source AI-Q cites.

## Use when

- The user asks to **research**, **do a deep dive**, **investigate**, **look
  into**, or **find citations** on a topic.
- The user runs **`/research <query>`** or **`/deep-research <query>`**.
- Automation invokes you with: *use skill **aiq-research**, query = …*.
- The user asks a question that benefits from **web sources + citations**
  (current events, comparisons, literature review, product research).

Do **not** use this skill for:

- Code edits, shell commands, or anything the sandbox tools already handle.
- Single-fact lookups that the base model answers confidently.
- Private/internal questions — AI-Q does public web search.

## Endpoint

AI-Q is reachable from inside the sandbox at:

```
http://172.18.0.1:8000
```

This IP matches the host Docker gateway added in the **`aiq-local`** network
policy (see [Demo 4.0](../../4.0-aiq-blueprint.md), Steps 3–4). If the policy
uses a different IP, substitute it everywhere below.

Endpoints used:

| Path | Method | Use |
| --- | --- | --- |
| `/health` | GET | Sanity check (`{"status":"healthy"}`) |
| `/generate` | POST | One-shot research, returns JSON with answer + citations |
| `/generate/stream` | POST | Server-sent streaming — use only when the user wants live output |

## How to run a query

Use the `exec` tool with a **single** `curl` call per attempt. Prefer
non-streaming for clean JSON; only use streaming if the user explicitly asks
for live output or the query is expected to take a long time.

**Non-streaming (default):**

```bash
curl -sS --max-time 180 -X POST http://172.18.0.1:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"query": "<USER_QUERY>"}'
```

**Streaming:**

```bash
curl -N --max-time 300 -X POST http://172.18.0.1:8000/generate/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "<USER_QUERY>"}'
```

Substitute `<USER_QUERY>` with the user's actual question. Escape embedded
double quotes; if the query contains shell metacharacters, build the JSON body
with `python3 -c 'import json,sys; print(json.dumps({"query": sys.argv[1]}))' "..."`
and pipe it to `curl --data-binary @-`.

## Error handling

Before the first real query, probe health:

```bash
curl -sS --max-time 5 http://172.18.0.1:8000/health
```

If health fails or any `/generate*` call returns non-2xx / empty body:

1. State plainly that AI-Q is unreachable — do **not** silently fall back to
   guesses or the built-in search.
2. Suggest the user verify `docker ps | grep aiq-agent` on the host and that
   the `aiq-local` network policy is applied.
3. Stop. Do not retry more than twice.

## Output contract

Return **two sections**, in this order, plain Markdown:

### Answer

A 3–6 sentence summary of AI-Q's response in the user's language. No preamble
("Here is what I found:"). No bullet points in this section unless AI-Q's
answer is inherently a list.

### Sources

Every citation AI-Q returned, one per line:

```
- [<title>](<url>)
```

If AI-Q returns zero citations, write `- (no citations returned)` — never
fabricate URLs. Preserve AI-Q's order; do not deduplicate across identical
URLs unless titles also match.

Do **not** add:

- A third section ("Further reading", "My thoughts").
- Markdown headers above `### Answer`.
- Your own opinions or corrections on top of AI-Q's output.

## Slash command hints

- `/research <query>` — non-streaming, default.
- `/deep-research <query>` — same as above; AI-Q's intent classifier decides
  shallow vs deep.
- `/research --stream <query>` — use `/generate/stream`.

## Quality bar

- One `curl` per attempt; no shell pipelines that mask the exit code.
- Never call `/generate` without `--max-time`; AI-Q deep runs can exceed
  default timeouts.
- Keep the **Answer** section under ~800 characters when possible.
- If the user's query is ambiguous, ask **one** clarifying question before
  calling AI-Q — you don't want to spend a deep-research budget on the wrong
  topic.
