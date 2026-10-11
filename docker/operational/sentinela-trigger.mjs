#!/usr/bin/env node
"use strict";

const net = require("net");

const SOCKET_PATH = "/run/sentinela/operational.sock";
const PROTOCOL = "json_line_v1";
const WATCHDOG_MS = 1020 * 1000;

const allowedTiers = new Set([
  "urgent",
  "coastal_forecast",
  "satellite_catalog",
  "contextual",
]);

function fail(message, code = 1) {
  process.stderr.write(`SENTINELA_TRIGGER_ERROR=${message}\n`);
  process.exit(code);
}

if (process.argv.length !== 3) {
  fail("exactly_one_tier_required");
}

const tier = process.argv[2];

if (!allowedTiers.has(tier)) {
  fail("unknown_tier");
}

const client = net.createConnection({ path: SOCKET_PATH });
let buffer = "";
let settled = false;

const timer = setTimeout(() => {
  if (settled) return;
  settled = true;
  client.destroy();
  fail("bridge_watchdog_timeout_manual_reconciliation_required");
}, WATCHDOG_MS);

client.setEncoding("utf8");

client.on("connect", () => {
  client.write(
    JSON.stringify({
      protocol: PROTOCOL,
      tier,
    }) + "\n"
  );
});

client.on("data", (chunk) => {
  if (settled) return;

  buffer += chunk;

  if (buffer.length > 4096) {
    settled = true;
    clearTimeout(timer);
    client.destroy();
    fail("bridge_response_too_large");
  }

  const newline = buffer.indexOf("\n");

  if (newline === -1) return;

  const raw = buffer.slice(0, newline);

  let response;

  try {
    response = JSON.parse(raw);
  } catch {
    settled = true;
    clearTimeout(timer);
    client.destroy();
    fail("invalid_bridge_response");
  }

  if (
    response.protocol !== PROTOCOL ||
    response.tier !== tier ||
    !Number.isInteger(response.exit_code)
  ) {
    settled = true;
    clearTimeout(timer);
    client.destroy();
    fail("invalid_bridge_contract");
  }

  settled = true;
  clearTimeout(timer);
  client.end();

  process.stdout.write(JSON.stringify(response) + "\n");

  const code = [0, 1, 2, 3].includes(response.exit_code)
    ? response.exit_code
    : 1;

  process.exit(code);
});

client.on("error", () => {
  if (settled) return;
  settled = true;
  clearTimeout(timer);
  fail("bridge_connection_error");
});

client.on("end", () => {
  if (settled) return;
  settled = true;
  clearTimeout(timer);
  fail("bridge_closed_without_response");
});
