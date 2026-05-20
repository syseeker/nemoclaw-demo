---
name: philosopher-nudge
description: Generate a single “Ting tong, <time> — <question>” nudge for Telegram, with a theme (life, work, games, love, hobby, nature, or custom).
user-invocable: true
---

# Philosopher nudge (Telegram)

## Purpose

Produce **one line** of plain text suitable for a scheduled Telegram ping: a
playful bell (**Ting tong**), the **current local time**, and **one short
question** in the spirit of philosophical inquiry—scoped to a **theme** the
user chooses.

## Use when

- The user runs **`/philosopher-nudge`** with optional theme and notes (e.g.
  `/philosopher-nudge work`, `/philosopher-nudge love focused on long
  distance`).
- The user asks for an **hourly nudge**, **cron message**, or **philosophy
  ping** for Telegram.
- Automation invokes you with: *use skill **philosopher-nudge**, theme = …*.

## Themes (pick one per nudge)

Map the user’s wording to the closest bucket, or use **custom** when they name
something else.

| Theme | Focus |
| --- | --- |
| **life** | Meaning, habits, mortality, freedom, authenticity, the good life. |
| **work** | Craft, ambition, rest, leadership, purpose vs pay, attention at work. |
| **games** | Rules, fairness, play, competition, luck vs skill, why we keep score. |
| **love** | Care, attachment, trust, boundaries, vulnerability, different kinds of love. |
| **hobby** | Practice, mastery for its own sake, leisure, identity outside productivity. |
| **nature** | World beyond the human, reciprocity, beauty, limits, our place in systems. |
| **custom** | Whatever the user specifies (e.g. friendship, money, music, parenting). Stay on that topic only. |

If the theme is ambiguous, default to **life** unless the user’s last message
clearly points elsewhere.

## Output contract (strict)

Return **exactly one line** of plain text:

1. Begin with the literal words **`Ting tong, `** (comma + space).
2. Immediately after, write the **current time in GMT+8** (**Asia/Singapore** /
   **Asia/Taipei** style offset) in a human-readable form (e.g.
   `2026-04-04 15:00 GMT+8`). The automation sets **`TZ=Asia/Singapore`** so
   “local time” in the shell **is** GMT+8 unless the user explicitly asked for
   another zone.
3. Then **` — `** (space–em dash–space).
4. End with **one** short question (no second sentence). The question must
   unmistakably belong to the chosen **theme** and sound like something a
   thoughtful philosopher might ask—not a trivia fact, not a therapy prompt,
   not a joke punchline.

Do **not** add:

- Markdown, bullets, or quotation marks around the whole line
- Preamble (“Here is your nudge:”)
- Explanations before or after the line
- More than one question

## Slash command hints

- `/philosopher-nudge` — theme **life** (default).
- `/philosopher-nudge work` — **work** theme.
- `/philosopher-nudge games` — **games** theme.
- `/philosopher-nudge custom friendship and loyalty` — **custom**; stay on
  friendship and loyalty.

## Quality bar

- Keep the question under ~160 characters when possible (mobile-friendly).
- Prefer **open** questions that invite reflection, not yes/no.
- Avoid naming living public figures; keep it timeless and inclusive.
