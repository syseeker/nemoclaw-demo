#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Send a plain-text message to Telegram. Reads from stdin, CLI arg, or env.

Reusable sender for any demo (heartbeat, nudge, alerts, etc.).

Usage:
  echo "hello" | python3 send_telegram_message.py --stdin
  python3 send_telegram_message.py "hello world"

Environment:
  TELEGRAM_BOT_TOKEN    — required
  TELEGRAM_CHAT_ID      — required (numeric chat or group id)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a message to Telegram.")
    parser.add_argument("text", nargs="?", default="", help="Message text")
    parser.add_argument("--stdin", action="store_true", help="Read message from stdin")
    args = parser.parse_args()

    text = (args.text or "").strip()
    if not text and args.stdin:
        text = sys.stdin.read().strip()
    if not text:
        text = os.environ.get("TELEGRAM_MESSAGE_TEXT", "").strip()
    if not text:
        sys.stderr.write("No message text. Provide as arg, --stdin, or TELEGRAM_MESSAGE_TEXT.\n")
        raise SystemExit(2)

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
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

    print("send_telegram_message: OK", file=sys.stderr)


if __name__ == "__main__":
    main()
