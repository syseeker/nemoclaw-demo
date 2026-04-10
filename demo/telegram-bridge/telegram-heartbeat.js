#!/usr/bin/env node
// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Proactive Telegram health pings for NemoClaw.
 *
 * Sends periodic status to a fixed chat: sandbox phase, gateway inference
 * (model + provider), and gateway connectivity. Stops posting healthy pings
 * when the sandbox is gone or not Ready (alerts instead).
 *
 * Env:
 *   TELEGRAM_BOT_TOKEN           — required (same as bridge)
 *   TELEGRAM_HEARTBEAT_CHAT_ID   — required; your numeric chat id (private or group)
 *   SANDBOX_NAME                 — default nemoclaw
 *   HEARTBEAT_INTERVAL_SEC       — default 300 (min 10)
 *   HEARTBEAT_POLICY_LOG         — set to 1 to scan recent sandbox logs for denial markers (slower)
 *   HEARTBEAT_MARKDOWN_FILE      — optional path to a UTF-8 .md file (see below)
 *   HEARTBEAT_MARKDOWN_AS_PLAIN_APPEND — set to 1 to append file text to the health message (no Telegram formatting)
 *
 * Markdown file: if HEARTBEAT_MARKDOWN_FILE is set and the file exists, each tick after the health
 * summary we send one or more follow-up messages with parse_mode Markdown (Telegram legacy Markdown).
 * If parsing fails, we retry without parse_mode. Use HEARTBEAT_MARKDOWN_AS_PLAIN_APPEND=1 to merge
 * the file into the same message as plain text instead (underscores etc. stay literal).
 *
 * Get chat id: message @userinfobot, or read the id from telegram-bridge.log
 * when you DM the bot ([381233314] Name: ... → 381233314).
 */

const https = require("https");
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const { resolveOpenshell } = require("../bin/lib/resolve-openshell");
const { validateName } = require("../bin/lib/runner");

const TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const CHAT_ID_RAW = process.env.TELEGRAM_HEARTBEAT_CHAT_ID || process.env.HEARTBEAT_TELEGRAM_CHAT_ID;
const SANDBOX = process.env.SANDBOX_NAME || "nemoclaw";
const INTERVAL_SEC = Math.max(10, parseInt(process.env.HEARTBEAT_INTERVAL_SEC || "300", 10) || 300);

try {
  validateName(SANDBOX, "SANDBOX_NAME");
} catch (e) {
  console.error(e.message);
  process.exit(1);
}

if (!TOKEN) {
  console.error("TELEGRAM_BOT_TOKEN required");
  process.exit(1);
}
if (!CHAT_ID_RAW || !String(CHAT_ID_RAW).trim()) {
  console.error("TELEGRAM_HEARTBEAT_CHAT_ID required (your Telegram user or group id)");
  process.exit(1);
}

const CHAT_ID = String(CHAT_ID_RAW).trim();

const HEARTBEAT_MD_FILE = (process.env.HEARTBEAT_MARKDOWN_FILE || process.env.TELEGRAM_HEARTBEAT_MARKDOWN_FILE || "").trim();
const HEARTBEAT_MD_PLAIN_APPEND = process.env.HEARTBEAT_MARKDOWN_AS_PLAIN_APPEND === "1";

const OPENSHELL = resolveOpenshell();
if (!OPENSHELL) {
  console.error("openshell not found on PATH or in common locations");
  process.exit(1);
}

function stripAnsi(s) {
  return String(s).replace(/\x1b\[[0-9;]*m/g, "");
}

function openshell(args, opts = {}) {
  const r = spawnSync(OPENSHELL, args, {
    encoding: "utf-8",
    maxBuffer: 4 * 1024 * 1024,
    env: process.env,
    timeout: opts.timeout ?? 0,
  });
  const out = stripAnsi(`${r.stdout || ""}${r.stderr || ""}`);
  if (r.error && r.error.code === "ETIMEDOUT") {
    return { code: 124, out: "", timedOut: true };
  }
  return { code: r.status ?? 1, out };
}

function tgApi(method, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const req = https.request(
      {
        hostname: "api.telegram.org",
        path: `/bot${TOKEN}/${method}`,
        method: "POST",
        headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(data) },
      },
      (res) => {
        let buf = "";
        res.on("data", (c) => (buf += c));
        res.on("end", () => {
          try {
            resolve(JSON.parse(buf));
          } catch {
            resolve({ ok: false, error: buf });
          }
        });
      },
    );
    req.on("error", reject);
    req.write(data);
    req.end();
  });
}

function pickLine(text, label) {
  const m = text.match(new RegExp(`^\\s*${label}:\\s*(.+)$`, "im"));
  return m ? m[1].trim() : "";
}

function collectHealth() {
  const sb = openshell(["sandbox", "get", SANDBOX]);
  const phase = pickLine(sb.out, "Phase") || (sb.code !== 0 ? "(unknown)" : "");
  const sandboxOk = sb.code === 0 && /^Ready\b/i.test(phase);

  const inf = openshell(["inference", "get"]);
  const provider = pickLine(inf.out, "Provider") || "—";
  const model = pickLine(inf.out, "Model") || "—";

  const st = openshell(["status"]);
  const stClean = st.out.replace(/\s+/g, " ").trim().slice(0, 400);
  const connected = /Status:\s*Connected/i.test(st.out);
  const gatewayLine = pickLine(st.out, "Gateway") || pickLine(st.out, "Active gateway") || "";

  let policyHint = "Policy / egress: use `openshell term` for pending approvals and live denials.";
  if (sandboxOk && process.env.HEARTBEAT_POLICY_LOG === "1") {
    const logs = openshell(["logs", SANDBOX], { timeout: 12000 });
    if (logs.timedOut) {
      policyHint = "Policy log: timeout reading logs (sandbox busy or huge log).";
    } else if (logs.code === 0 && logs.out) {
      const tail = logs.out.slice(-12000);
      const denials = (tail.match(/CONNECT action=deny|l7_decision=deny/gi) || []).length;
      if (denials > 0) {
        policyHint = `Policy: ${denials} denial marker(s) in recent log tail (see openshell term).`;
      } else {
        policyHint = "Policy log tail: no recent denial markers.";
      }
    }
  }

  const lines = [
    sandboxOk ? "NemoClaw heartbeat OK" : "NemoClaw heartbeat ALERT",
    `Sandbox: ${SANDBOX}  phase: ${phase || "not found"}`,
    `Inference: ${provider} / ${model}`,
    `Gateway: ${connected ? "connected" : "not connected"}${gatewayLine ? ` (${gatewayLine})` : ""}`,
    policyHint,
    `Host: ${require("os").hostname()}  interval: ${INTERVAL_SEC}s`,
  ];

  let body = lines.join("\n");

  if (HEARTBEAT_MD_FILE && HEARTBEAT_MD_PLAIN_APPEND) {
    try {
      const resolved = path.resolve(HEARTBEAT_MD_FILE);
      if (fs.existsSync(resolved)) {
        const extra = fs.readFileSync(resolved, "utf8").trimEnd();
        if (extra) {
          body += `\n\n---\n\n${extra}`;
        }
      }
    } catch (e) {
      body += `\n\n---\n\n(heartbeat file: ${e.message})`;
    }
  }

  // Telegram hard limit 4096; trim plain-append if needed
  if (body.length > 4096) {
    body = `${body.slice(0, 4080)}\n…(truncated)`;
  }

  return { ok: sandboxOk, text: body, phase, provider, model };
}

function readMarkdownFileForFollowUp() {
  if (!HEARTBEAT_MD_FILE || HEARTBEAT_MD_PLAIN_APPEND) {
    return null;
  }
  try {
    const resolved = path.resolve(HEARTBEAT_MD_FILE);
    if (!fs.existsSync(resolved)) {
      return null;
    }
    return fs.readFileSync(resolved, "utf8").trimEnd();
  } catch (e) {
    return `(Could not read HEARTBEAT_MARKDOWN_FILE: ${e.message})`;
  }
}

async function sendFollowUpMarkdown(chunks) {
  for (const chunk of chunks) {
    if (!chunk) continue;
    let res = await tgApi("sendMessage", {
      chat_id: CHAT_ID,
      text: chunk,
      parse_mode: "Markdown",
    });
    if (!res.ok) {
      res = await tgApi("sendMessage", { chat_id: CHAT_ID, text: chunk });
    }
    if (!res.ok) {
      console.error("[heartbeat] follow-up sendMessage failed:", JSON.stringify(res));
    }
  }
}

async function sendHeartbeat() {
  let payload;
  try {
    payload = collectHealth();
  } catch (err) {
    payload = {
      ok: false,
      text: `NemoClaw heartbeat ERROR\n${err.message}`,
    };
  }

  const res = await tgApi("sendMessage", {
    chat_id: CHAT_ID,
    text: payload.text,
  });

  if (!res.ok) {
    console.error("[heartbeat] sendMessage failed:", JSON.stringify(res));
  } else {
    console.log(new Date().toISOString(), payload.ok ? "heartbeat sent (ok)" : "heartbeat sent (alert)");
  }

  const md = readMarkdownFileForFollowUp();
  if (md) {
    const pieces = [];
    for (let i = 0; i < md.length; i += 3500) {
      pieces.push(md.slice(i, i + 3500));
    }
    await sendFollowUpMarkdown(pieces);
  }
}

async function main() {
  const me = await tgApi("getMe", {});
  if (!me.ok) {
    console.error("Telegram getMe failed:", JSON.stringify(me));
    process.exit(1);
  }

  console.log("");
  console.log("  NemoClaw Telegram heartbeat");
  console.log(`  Bot @${me.result.username}  →  chat ${CHAT_ID}`);
  console.log(`  Sandbox ${SANDBOX}  every ${INTERVAL_SEC}s`);
  if (HEARTBEAT_MD_FILE) {
    console.log(
      `  Markdown file: ${HEARTBEAT_MD_FILE} (${HEARTBEAT_MD_PLAIN_APPEND ? "plain append" : "follow-up Markdown"})`,
    );
  }
  console.log("");

  await sendHeartbeat();
  setInterval(() => {
    sendHeartbeat().catch((e) => console.error("[heartbeat]", e.message));
  }, INTERVAL_SEC * 1000);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
