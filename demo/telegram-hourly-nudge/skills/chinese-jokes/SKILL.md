---
name: chinese-jokes
description: Generate a single Chinese joke for Telegram — pick a random topic, then deliver the joke entirely in 中文 with optional dialect flavor.
user-invocable: true
---

# Chinese jokes nudge (Telegram)

## Purpose

Produce a short, fun **localized Chinese-language joke** that a Malaysian or
Singaporean Chinese reader would **smile at and relate to** — the kind of
joke you'd share in a family WhatsApp group or over kopi at the kopitiam.

The humor should be rooted in **shared everyday experiences** of living in
Malaysia / Singapore: the weather (热到要命), food culture (char kway teow
uncle, economy rice aunty, Grab Food 等到花都谢了), kampung memories,
kiasu/kiasi moments, "aiyoh" situations, mum's logic, 安娣 bargain hunting,
school canteen flashbacks, NS/BMT (SG), balik kampung traffic jams (MY),
pasar malam haggling, and the eternal "吃饱没？" greeting.

The audience speaks **Mandarin** but many also use **Hokkien (闽南语)**,
**Teochew (潮州话)**, or **Cantonese (广东话)** at home. Dialect-flavored
humor is strongly encouraged — transliterating a well-known dialect saying
into Mandarin, playing on how a Hokkien/Cantonese phrase sounds in Putonghua,
or mixing in familiar Singlish/Manglish particles (lah, lor, leh, meh, one,
can or not, bo jio, jialat, walao) to make the joke feel local and alive.

## Use when

- The user runs **`/chinese-jokes`** with optional topic override.
- The user asks for a **joke nudge**, **笑话**, or **Chinese joke** for
  Telegram.
- Automation invokes you with: *use skill **chinese-jokes**, topic = …*.

## Before generating — check memory

Before composing a joke, **read** the daily memory logs
(`~/.openclaw/memory/`) and `~/.openclaw/workspace/MEMORY.md` (if they
exist). Look for:

- **Topics that got positive feedback** — lean toward those categories.
- **Topics that fell flat or were disliked** — avoid repeating them.
- **Specific requests** from users (e.g. "more kopitiam jokes", "try
  Cantonese wordplay") — honor them in this invocation.
- **Recently used topics** — pick something different so jokes stay fresh.

If no memory is available (first run or empty logs), just pick a random
category as usual.

## Topic categories (pick one at random each time)

| Category | Examples |
| --- | --- |
| **生活** (daily life) | Economy rice 加菜, Grab driver 兜路, aircon vs 电费, "吃饱没？", laundry vs 突然下雨 |
| **人物** (people) | 安娣 bargain queen, kiasu parent, office 八卦 colleague, mum's "穿多一点", 阿公讲古 |
| **地方** (places) | Kopitiam, hawker centre chope seat, MRT/LRT, pasar malam, JB weekend trip, Batu Caves, Gardens by the Bay |
| **时事** (trending) | Viral moments, bubble tea trends, AI vs uncle, cashless payment 安娣, relatable current events (keep light, non-political) |
| **人生阶段** (life stages) | PSLE/UPSR stress, NS/BMT (SG), uni life, dating + "见家长", BTO/wedding 红包, parenthood, retirement tai chi |
| **兴趣爱好** (hobbies) | Mobile gaming, 钓鱼, cooking 煮到烧焦, baking fail, photography uncle, 4D/Toto |
| **方言梗** (dialect humor) | Hokkien / Teochew / Cantonese wordplay, sayings, transliterations, dialect-vs-Mandarin misunderstandings, Singlish/Manglish mashup |
| **吃的** (food culture) | Char kway teow, roti canai, nasi lemak, bak kut teh, 奶茶 vs kopi, 加饭 free or not, chilli sauce debate |
| **家庭** (family dynamics) | 过年 ang pow rates, mum's 唠叨, dad's dad jokes, cousin gathering 比较, 回外婆家 |

If no topic is given, **randomly choose** one category per invocation — vary
the pick so consecutive jokes feel fresh.

## Output contract (strict)

Return a message block in this exact shape:

1. **Joke body** — the joke itself (1–20 lines, no blank lines within).
   Dialogue format (`A：… B：…`) works well. Jump straight into the joke
   with no header, no timestamp, and no topic label.
2. **Last line** — end with exactly **`哈哈`** or **`Meow~~`** on its own
   line. Alternate between the two across invocations.

Example:

```
老板：你要 kopi-O 还是 kopi-C？
我：我要 kopi-Ctrl+Z，刚才讲的话可以撤回吗？
哈哈
```

Another example (dialect humor):

```
阿嫲讲 "紧叫紧无"（Hokkien: kín kiò kín bô）
孙子以为是在说 Wi-Fi 信号
越急着连，越连不上
Meow~~
```

Rules:

- The **entire message** must be in **Chinese** (Mandarin characters). Dialect
  romanization (e.g. kopi, lah, leh, simi, bo jio) and English loanwords may
  appear where they add flavor, but surrounding text stays in Chinese.
- Keep the joke **short** — fits comfortably on a phone screen without
  scrolling.
- Aim for **clever wordplay**, **relatable situations**, or **gentle
  absurdity** that makes a native Chinese speaker smile or chuckle.
- Do **not** add Markdown formatting, bullet points, or quotation marks around
  the whole block.
- Do **not** add any preamble ("这是你的笑话：") or explanation after the joke.
- Do **not** include blank lines inside the joke body.
- No offensive, discriminatory, political, or religious content.

## Slash command hints

- `/chinese-jokes` — random topic.
- `/chinese-jokes 方言梗` — dialect humor specifically.
- `/chinese-jokes 人生阶段 dating` — life-stage jokes about dating.

## Quality bar

- The joke must feel **local** — a Malaysian or Singaporean Chinese reader
  should think "哈哈 这个很像我们的生活 leh". If a joke could come from
  any country, it's not local enough.
- Prefer **wordplay**, **situational humor**, or **relatable 安娣/uncle
  moments** over generic slapstick.
- Dialect jokes should be understandable to a Mandarin speaker with minimal
  dialect knowledge — provide just enough context in the joke itself.
- Sprinkle in Singlish/Manglish particles naturally (lah, lor, meh, one,
  walao, jialat) — don't force them, but don't avoid them either.
- Vary structure: sometimes a one-liner, sometimes a short dialogue, sometimes
  a mini-scenario. Do not always use the same template.
- Reference **real local touchpoints**: brands (Milo, Maggi, Tiger, 100 Plus),
  places (Johor Bahru, Penang, Orchard Road, Bugis), foods (roti prata,
  nasi lemak, cendol), habits (chope seat with tissue, queue for everything).
