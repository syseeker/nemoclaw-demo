#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Send a Telegram message built elsewhere (e.g. OpenClaw + philosopher-nudge skill).

Typical pipeline (host cron):
  NVIDIA_API_KEY=... SANDBOX_NAME=... PHILOSOPHER_THEME=work \\
    bash run_philosopher_nudge_llm.sh | python3 hourly_telegram_nudge.py --stdin

Or set TELEGRAM_NUDGE_TEXT / pass a single CLI argument.

Environment:
  TELEGRAM_BOT_TOKEN
  TELEGRAM_NUDGE_CHAT_ID
  TELEGRAM_NUDGE_REPLY_HINT — set to "0" to omit the reply hint footer.
  TELEGRAM_NUDGE_REPLY_HINT_TEXT — optional custom footer (plain language for Telegram readers).
  TELEGRAM_NUDGE_SILENT — set to "1" to hide the success line on stderr.

Optional:
  TZ — timezone for any future use (message text comes from stdin/args).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _load_text(args: argparse.Namespace) -> str:
    if args.text:
        return args.text.strip()
    raw = os.environ.get("TELEGRAM_NUDGE_TEXT", "").strip()
    if raw:
        return raw
    if args.stdin:
        data = sys.stdin.read()
        return data.strip()
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Post a pre-built nudge line to Telegram (use run_philosopher_nudge_llm.sh for LLM text).",
    )
    parser.add_argument("text", nargs="?", default="", help="Message body (optional if --stdin or env)")
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read message body from stdin (e.g. pipe from run_philosopher_nudge_llm.sh)",
    )
    args = parser.parse_args()
    args.text = args.text or ""

    text = _load_text(args)
    if not text:
        sys.stderr.write(
            "No message text. Provide argv, TELEGRAM_NUDGE_TEXT, or --stdin "
            "(see demo/telegram-hourly-nudge/scripts/run_philosopher_nudge_llm.sh).\n",
        )
        raise SystemExit(2)

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_raw = os.environ.get("TELEGRAM_NUDGE_CHAT_ID")
    if not token or not chat_raw:
        raise SystemExit(
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_NUDGE_CHAT_ID (see demo/telegram-hourly-nudge.md).",
        )

    try:
        chat_id: int | str = int(chat_raw)
    except ValueError:
        chat_id = chat_raw

    if os.environ.get("TELEGRAM_NUDGE_REPLY_HINT", "1") not in ("0", "false", "no"):
        custom = (os.environ.get("TELEGRAM_NUDGE_REPLY_HINT_TEXT") or "").strip()
        if custom:
            text += "\n\n" + custom
        else:
            text += (
                "\n\nReply here to chat with this bot — the assistant reads "
                "messages in this chat."
            )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Telegram API HTTP {e.code}: {err}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"Request failed: {e}") from e

    if not payload.get("ok"):
        raise SystemExit(f"Telegram API error: {payload}")

    if os.environ.get("TELEGRAM_NUDGE_SILENT", "").lower() not in ("1", "true", "yes"):
        print("hourly_telegram_nudge: OK — message sent to Telegram.", file=sys.stderr)


if __name__ == "__main__":
    main()
