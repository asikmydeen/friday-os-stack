"use strict";

const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const path = require("path");

const REQUIRED = ["BOARD_PASSWORD", "FRIDAY_NOTIFY_TOKEN", "BOARD_APPROVAL_TOKEN"];

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

const FULL_PACK = [
  "advisor", "architect", "backend", "buyer", "content", "faith", "family",
  "fetcher", "health", "legal", "mentor", "mobile", "product", "program",
  "researcher", "reviewer", "shopper", "tester", "travel", "web",
];
const FULL_SET = new Set(FULL_PACK);
const BLOCKED_ROLES = new Set(["family"]);
const FULL_MOUNTS = new Set([
  "full",
  "./full",
  "charters/full",
  "./charters/full",
  "/soul/agents/full",
  "charters/full/",
  "./charters/full/",
  "/soul/agents/full/",
]);
const charterBooks = new WeakMap();
const soulBooks = new WeakMap();
const SOUL_FILES = new Set(["SOUL.md", "CHAPTER.md"]);

const STARTERS = [
  ["cfo", "CFO"],
  ["chief", "Chief"],
  ["coach", "Coach"],
  ["cto", "CTO"],
  ["home", "Home"],
  ["media", "Media"],
];
const STARTER_IDS = new Set(STARTERS.map(([id]) => id));
const ENGINES = new Set(["claude-code", "gsd"]);
const COLLECTION = "cabinet_working";
const TOOL_NAME = /^[a-z][a-z0-9_-]{0,63}$/;
const SECRET_NAME = /^[A-Za-z][A-Za-z0-9_-]{0,63}$/;
const TRAINS = ["stable", "community"];
const APP_NAME = /^[a-z0-9][a-z0-9-]{0,63}$/;
const TASK_STATES = new Set(["ready", "running", "waiting", "done", "blocked"]);
const STEP_STATES = new Set(["pending", "running", "done", "blocked"]);
const ROLE_NAME = /^[a-z][a-z0-9_-]{0,31}$/;
const STEP_NAME = /^[a-z][a-z0-9_-]{0,63}$/;
const TASK_ID = /^[A-Za-z0-9-]{1,64}$/;
const LIFE_ACTIONS = new Set(["send", "pay", "delete", "publish"]);
const APPROVAL_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const REASON_CODE = /^[a-z_]{1,32}$/;
const EVENT_SENTENCE = {
  grab: "A download was grabbed.",
  failure: "A download failed.",
  health: "An app health state changed.",
  other: "An app sent an event.",
};
const EVENT_SOURCES = new Set(["jellyfin", "radarr", "sonarr"]);

function discoverRows(root) {
  const empty = (reason) => ({reason, rows: []});
  if (typeof root !== "string" || root === "") return empty("catalog_missing");
  let base;
  try {
    const info = fs.lstatSync(root);
    if (!info.isDirectory() || info.isSymbolicLink()) return empty("catalog_missing");
    base = path.resolve(root);
  } catch (_error) {
    return empty("catalog_missing");
  }
  const rows = [];
  try {
    for (const train of TRAINS) {
      const trainDir = path.join(base, "ix-dev", train);
      let info;
      try {
        info = fs.lstatSync(trainDir);
      } catch (_error) {
        continue;
      }
      if (!info.isDirectory() || info.isSymbolicLink()) continue;
      const names = fs.readdirSync(trainDir, {withFileTypes: true})
        .filter((entry) => entry.isDirectory() && !entry.isSymbolicLink() && APP_NAME.test(entry.name))
        .map((entry) => entry.name)
        .sort();
      for (const name of names) {
        const appDir = path.join(trainDir, name);
        if (path.resolve(appDir) !== appDir) continue;
        let yaml;
        try {
          yaml = fs.lstatSync(path.join(appDir, "app.yaml"));
        } catch (_error) {
          continue;
        }
        if (!yaml.isFile() || yaml.isSymbolicLink()) continue;
        rows.push({name, train, install: "refused"});
      }
    }
  } catch (_error) {
    return empty("catalog_missing");
  }
  if (rows.length === 0) return empty("upstream_not_copied");
  return {reason: "listed", rows};
}

function freshShelf() {
  return {baseline: {}, extra: {}, shown: {}, secrets: {}, engines: {}, durable: {}, collections: {}};
}

const shelves = new WeakMap();

function shelfState(env) {
  const existing = shelves.get(env);
  if (existing) return existing;
  const provided = env.shelf;
  const state = provided !== null && typeof provided === "object" ? provided : freshShelf();
  shelves.set(env, state);
  return state;
}

function isTool(value) {
  return typeof value === "string" && TOOL_NAME.test(value);
}

function toolList(value) {
  if (value === undefined) return [];
  if (!Array.isArray(value)) return null;
  const found = [];
  for (const item of value) {
    if (!isTool(item)) return null;
    if (!found.includes(item)) found.push(item);
  }
  return found;
}

function remember(map, role, name) {
  if (!map[role]) map[role] = [];
  if (!map[role].includes(name)) map[role].push(name);
}

function toolRows(state, role) {
  const shown = state.shown[role] || {tools: [], deny: [], offered: []};
  const named = shown.tools.filter(isTool);
  const extras = shown.offered.filter(isTool);
  const denied = new Set(shown.deny.filter(isTool));
  const accepted = new Set([...(state.baseline[role] || []), ...(state.extra[role] || [])]);
  const extraOnly = [...new Set(extras.filter((name) => !named.includes(name)))].sort();
  const rows = [];
  const seen = new Set();
  for (const name of [...named, ...extraOnly]) {
    if (seen.has(name)) continue;
    seen.add(name);
    rows.push({name, state: !denied.has(name) && accepted.has(name) ? "on" : "off"});
  }
  return rows;
}

function computeOf(state, id) {
  const engines = state.engines || {};
  const homes = state.durable || {};
  const collections = state.collections || {};
  const row = engines[id];
  const durable = homes[id] === true;
  const names = Array.isArray(collections[id]) ? collections[id].filter((name) => name === COLLECTION) : [];
  return {
    engine: row && ENGINES.has(row.engine) ? row.engine : "",
    budget: row && Number.isInteger(row.budget) ? row.budget : null,
    durable,
    home: durable ? "agent-" + id : "",
    collections: names,
  };
}

function shelfView(state) {
  return STARTERS.map(([id, name]) => {
    const compute = computeOf(state, id);
    return {
      id,
      name,
      job_cap: 0,
      tools: toolRows(state, id),
      secrets: Object.keys((state.secrets || {})[id] || {}).sort(),
      engine: compute.engine,
      budget: compute.budget,
      durable: compute.durable,
      home: compute.home,
      collections: compute.collections,
      started: false,
    };
  });
}

function quietCompute(reason) {
  return {outcome: "refused", reason, cap: 0, started: false, created: false};
}

function recordEngine(env, body) {
  if (!boardActor(body)) return json(403, quietCompute("actor_cannot_approve"));
  if (!STARTER_IDS.has(body.role)) return json(403, quietCompute("role_name"));
  if (!ENGINES.has(body.engine)) return json(403, quietCompute("engine"));
  const budget = body.budget;
  if (typeof budget !== "number" || !Number.isInteger(budget) || budget < 5 || budget > 180) {
    return json(403, quietCompute("budget"));
  }
  const state = shelfState(env);
  if (!state.engines) state.engines = {};
  state.engines[body.role] = {engine: body.engine, budget};
  return json(200, {
    outcome: "recorded",
    reason: "not_started",
    name: body.engine,
    cap: 0,
    started: false,
    created: false,
  });
}

function recordDurable(env, body) {
  if (!boardActor(body)) return json(403, quietCompute("actor_cannot_approve"));
  if (!STARTER_IDS.has(body.role) || typeof body.on !== "boolean") {
    return json(403, quietCompute("role_name"));
  }
  const state = shelfState(env);
  if (!state.durable) state.durable = {};
  state.durable[body.role] = body.on;
  return json(200, {
    outcome: "recorded",
    reason: "not_started",
    name: body.on ? "agent-" + body.role : "",
    cap: 0,
    started: false,
    created: false,
  });
}

const GRANT_ROLES = new Set(["friday", "cfo", "chief", "coach", "cto", "home", "media"]);
const grantBooks = new WeakMap();

function grantState(env) {
  const existing = grantBooks.get(env);
  if (existing) return existing;
  const state = {rows: []};
  grantBooks.set(env, state);
  return state;
}

function grantQuiet(reason) {
  return {outcome: "refused", reason, prompt: [], started: false, called: false};
}

function grantView(row) {
  const accepted = new Set(row.accepted);
  return {
    server: row.server,
    role: row.role,
    secret_ref: row.secret_ref,
    tools: row.tools.map((name) => ({name, state: accepted.has(name) ? "on" : "off"})),
    prompt: [...row.accepted].sort(),
    started: false,
    called: false,
  };
}

function grantIpv4(text) {
  const parts = text.split(".");
  if (parts.length < 1 || parts.length > 4) return null;
  const numbers = [];
  for (const part of parts) {
    let number = null;
    if (part.startsWith("0x")) {
      const digits = part.slice(2);
      if (digits === "" || /[^0-9a-f]/.test(digits)) return null;
      number = Number.parseInt(digits, 16);
    } else if (part.startsWith("0") && part.length > 1) {
      if (/[^0-7]/.test(part)) return null;
      number = Number.parseInt(part, 8);
    } else if (part === "" || !/^\d+$/.test(part)) {
      return null;
    } else {
      number = Number(part);
    }
    if (!Number.isSafeInteger(number)) return null;
    numbers.push(number);
  }
  let value = null;
  if (numbers.length === 4) {
    if (numbers.some((number) => number > 255)) return null;
    value = (numbers[0] * 16777216) + (numbers[1] * 65536) + (numbers[2] * 256) + numbers[3];
  } else if (numbers.length === 3) {
    if (numbers[0] > 255 || numbers[1] > 255 || numbers[2] > 65535) return null;
    value = (numbers[0] * 16777216) + (numbers[1] * 65536) + numbers[2];
  } else if (numbers.length === 2) {
    if (numbers[0] > 255 || numbers[1] > 16777215) return null;
    value = (numbers[0] * 16777216) + numbers[1];
  } else if (numbers[0] > 0xffffffff) {
    return null;
  } else {
    value = numbers[0];
  }
  return value >>> 0;
}

function grantHostReason(host) {
  const text = String(host || "").trim().replace(/\.$/, "").toLowerCase();
  if (CORE_GUESTS.has(text) || text === "webhooks" || text === "taskrunner") return "core_closed";
  if (text === "metadata.google.internal" || text.endsWith(".metadata.google.internal")) return "metadata";
  if (text === "localhost" || text.endsWith(".localhost")) return "loopback";
  if (text.includes(":")) {
    const bare = text.split("%")[0];
    if (bare === "::1" || bare === "::") return "loopback";
    if (bare.startsWith("fe80:")) return "link_local";
    return "";
  }
  const address = grantIpv4(text);
  if (address === null) return "";
  if ((address >>> 24) === 127 || address === 0) return "loopback";
  if ((address >>> 16) === 0xa9fe) return "link_local";
  return "";
}

function grantServerReason(value) {
  if (typeof value !== "string" || value === "" || value !== value.trim() || /[\s%]/.test(value) || value.length > 256) {
    return "url";
  }
  if (hiddenText(value)) return "credential";
  let parsed;
  try {
    parsed = new URL(value);
  } catch (_error) {
    return "url";
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "url";
  if (parsed.username || parsed.password || parsed.search || parsed.hash || value.includes("@")) return "url";
  return grantHostReason(parsed.hostname);
}

function grantTools(value) {
  if (!Array.isArray(value) || value.length === 0 || value.length > 8) return null;
  const names = [];
  for (const item of value) {
    if (!isTool(item) || hiddenText(item)) return null;
    if (!names.includes(item)) names.push(item);
  }
  return names;
}

function suppliedSecret(body) {
  for (const field of [body.secret, body.value, body.token, body.password]) {
    if (field === undefined || field === null || field === "" || field === "The password is kept outside the machine") {
      continue;
    }
    if (typeof field === "string" && hiddenText(field)) return "credential";
    return "caller_value";
  }
  return "";
}

function recordGrant(env, body) {
  const supplied = suppliedSecret(body);
  if (supplied === "credential"
    || hiddenText(body.server) || hiddenText(body.role) || hiddenText(body.secret_ref)
    || (Array.isArray(body.tools) && body.tools.some((item) => hiddenText(item)))) {
    return json(403, grantQuiet("credential"));
  }
  if (!boardActor(body)) return json(403, grantQuiet("actor_cannot_approve"));
  if (supplied) return json(403, grantQuiet(supplied));
  if (body.role === "family") return json(403, grantQuiet("family_blocked"));
  const serverReason = grantServerReason(body.server);
  if (serverReason) return json(403, grantQuiet(serverReason === "credential" ? "credential" : serverReason));
  if (!GRANT_ROLES.has(body.role)) return json(403, grantQuiet("role_name"));
  if (typeof body.secret_ref !== "string" || !SECRET_NAME.test(body.secret_ref) || hiddenText(body.secret_ref)) {
    return json(403, grantQuiet(hiddenText(body.secret_ref) ? "credential" : "secret_ref"));
  }
  const tools = grantTools(body.tools);
  if (tools === null) return json(403, grantQuiet("tool_name"));
  const state = grantState(env);
  const held = state.rows.find((row) => row.server === body.server);
  if (held) {
    return json(200, {outcome: "recorded", reason: "kept", ...grantView(held)});
  }
  const row = {
    server: body.server,
    role: body.role,
    secret_ref: body.secret_ref,
    tools,
    accepted: [],
  };
  state.rows.push(row);
  return json(200, {outcome: "recorded", reason: "prompt", ...grantView(row)});
}

function acceptGrant(env, body) {
  if (hiddenText(body.server) || hiddenText(body.tool)) return json(403, grantQuiet("credential"));
  if (!boardActor(body)) return json(403, grantQuiet("actor_cannot_approve"));
  const serverReason = grantServerReason(body.server);
  if (serverReason) return json(403, grantQuiet(serverReason));
  if (!isTool(body.tool)) return json(403, grantQuiet("tool_name"));
  const held = grantState(env).rows.find((row) => row.server === body.server);
  if (!held) return json(403, grantQuiet("unknown_server"));
  if (!held.tools.includes(body.tool)) {
    return json(403, {outcome: "refused", reason: "not_offered", ...grantView(held)});
  }
  if (!held.accepted.includes(body.tool)) held.accepted.push(body.tool);
  return json(200, {outcome: "accepted", reason: "owner_accepted", name: body.tool, ...grantView(held)});
}

function grantsApi(request, env) {
  const method = request.method || "GET";
  const path = request.path || "/";
  const body = request.body || {};
  if (path === "/api/grants" && method === "GET") {
    return json(200, {
      outcome: "ok",
      reason: "grants",
      started: false,
      called: false,
      grants: grantState(env).rows.map(grantView),
    });
  }
  if (path === "/api/grants" && method === "POST") return recordGrant(env, body);
  if (path === "/api/grants/accept" && method === "POST") return acceptGrant(env, body);
  return json(404, grantQuiet("unknown_path"));
}

function recordCollections(env, body) {
  if (!boardActor(body)) {
    return json(403, {outcome: "refused", reason: "actor_cannot_approve", started: false, created: false});
  }
  if (!STARTER_IDS.has(body.role) || typeof body.names === "string" || !Array.isArray(body.names)) {
    return json(403, {outcome: "refused", reason: "collection_closed", started: false, created: false});
  }
  const cleaned = [];
  for (const name of body.names) {
    if (name !== COLLECTION) {
      return json(403, {outcome: "refused", reason: "collection_closed", started: false, created: false});
    }
    if (!cleaned.includes(name)) cleaned.push(name);
  }
  const state = shelfState(env);
  if (!state.collections) state.collections = {};
  state.collections[body.role] = cleaned;
  return json(200, {
    outcome: "recorded",
    reason: cleaned.length ? COLLECTION : "none",
    started: false,
    created: false,
    collections: cleaned,
  });
}

function advisorForms() {
  return STARTERS.map(([id, name]) => {
    const label = escapeHtml(name);
    return `<li>${label} <span>Job cap 0</span>
      <form class="advisor-ask" data-advisor="${id}">
        <label>Ask ${label} <textarea name="text" rows="2"></textarea></label>
        <button type="submit">Ask ${label}</button>
      </form>
    </li>`;
  }).join("\n");
}

function advisorAsk(body) {
  if (!Object.prototype.hasOwnProperty.call(body, "role") || body.role === "") {
    return {text: String(body.text || ""), bootstrap: body.bootstrap === true};
  }
  if (!STARTER_IDS.has(body.role)) return {error: "role_name"};
  if (typeof body.text !== "string") return {error: "empty"};
  const text = body.text.replace(/\s+/g, " ").trim().slice(0, 1200);
  if (text === "") return {error: "empty"};
  const line = `ask my ${body.role} ${text}`;
  if (hiddenText(text) || hiddenText(line)) return {error: "credential"};
  return {text: line, bootstrap: false};
}

function boardActor(body) {
  return body.actor === "board";
}

const CORE_GUESTS = new Set([
  "friday", "board", "qdrant", "ollama", "postgres", "memory-mcp", "executor", "gateway",
]);

function wholeBytes(value) {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && Number.isSafeInteger(value);
}

function hasRoom(body) {
  return body.declared !== undefined || body.free !== undefined || body.running !== undefined || body.app_id !== undefined;
}

function roomQuiet(outcome, reason, declared, free) {
  const decision = {
    outcome,
    reason,
    which: null,
    said: "",
    stopped: false,
    pulled: false,
    started: false,
    offered: false,
  };
  if (declared !== undefined) {
    decision.declared = declared;
    decision.free = free;
  }
  return decision;
}

function roomSaid(outcome, reason, which, declared, free) {
  const lead = reason === "stop_other"
    ? "Stop " + which + "."
    : reason === "machine_larger"
      ? "The machine is too small."
      : "It fits.";
  return {
    outcome,
    reason,
    which,
    declared,
    free,
    said: lead + " Declared " + declared + ". Free " + free + ". These numbers are not a hardware measurement.",
    stopped: false,
    pulled: false,
    started: false,
    offered: false,
  };
}

function guestName(item) {
  const hasId = Object.prototype.hasOwnProperty.call(item, "id");
  const hasApp = Object.prototype.hasOwnProperty.call(item, "app_id");
  if (hasId && hasApp && item.id !== item.app_id) return {error: "missing_declared"};
  const raw = hasId ? item.id : item.app_id;
  if (typeof raw !== "string" || raw.trim() === "") return {error: "missing_declared"};
  const text = raw.trim();
  if (hiddenText(text)) return {error: "credential"};
  return {name: text};
}

function roomRows(running) {
  const rows = running === undefined ? [] : running;
  if (typeof rows === "string" || !Array.isArray(rows)) return {error: "missing_declared"};
  const found = [];
  for (const item of rows) {
    if (item === null || typeof item !== "object" || Array.isArray(item)) return {error: "missing_declared"};
    const named = guestName(item);
    if (named.error) return {error: named.error};
    if (!wholeBytes(item.declared)) return {error: "missing_declared"};
    let locked = Object.prototype.hasOwnProperty.call(item, "core") && item.core !== false;
    if (CORE_GUESTS.has(named.name.toLowerCase())) locked = true;
    found.push({name: named.name, size: item.declared, locked});
  }
  return {rows: found};
}

function roomSkip(appId) {
  if (appId === undefined || appId === "") return {key: ""};
  if (typeof appId !== "string" || appId.trim() === "") return {error: "missing_app"};
  const text = appId.trim();
  if (hiddenText(text)) return {error: "credential"};
  return {key: text.toLowerCase()};
}

function roomDecision(body) {
  if (!wholeBytes(body.declared) || !wholeBytes(body.free)) return roomQuiet("refused", "ram_does_not_fit");
  if (body.declared <= body.free) return roomSaid("fits", "within_free_ram", null, body.declared, body.free);
  const rows = roomRows(body.running);
  if (rows.error) return roomQuiet("refused", rows.error, body.declared, body.free);
  const skip = roomSkip(body.app_id);
  if (skip.error) return roomQuiet("refused", skip.error, body.declared, body.free);
  const deficit = body.declared - body.free;
  let best = null;
  const seen = new Set();
  for (const row of rows.rows) {
    const key = row.name.toLowerCase();
    if (seen.has(key)) return roomQuiet("refused", "duplicate_app", body.declared, body.free);
    seen.add(key);
    if (row.locked || key === skip.key) continue;
    if (row.size >= deficit && (best === null || row.size < best.size || (row.size === best.size && key < best.key))) {
      best = {size: row.size, key, name: row.name};
    }
  }
  if (best === null) return roomSaid("said", "machine_larger", null, body.declared, body.free);
  return roomSaid("said", "stop_other", best.name, body.declared, body.free);
}

function charterBook(env) {
  const existing = charterBooks.get(env);
  if (existing) return existing;
  const book = {links: {}};
  charterBooks.set(env, book);
  return book;
}

function roleName(value) {
  if (typeof value !== "string") return ["", "role_name"];
  if (hiddenText(value)) return ["", "credential"];
  if (value === "" || value !== value.trim() || value.includes("\n") || value.length > 32) {
    return ["", "role_name"];
  }
  if (value.charCodeAt(0) > 127 || value[0] !== value[0].toLowerCase() || value[0] === value[0].toUpperCase()) {
    return ["", "role_name"];
  }
  for (const part of value) {
    if (part.charCodeAt(0) > 127) return ["", "role_name"];
    if (!/[a-z0-9_-]/i.test(part)) return ["", "role_name"];
  }
  return [value, ""];
}

function mountReason(value) {
  if (value === undefined || value === null || value === "") return "";
  if (typeof value !== "string") return "mount_closed";
  if (hiddenText(value)) return "credential";
  if (FULL_MOUNTS.has(value.trim())) return "drops_starter_set";
  return "mount_closed";
}

function targetLink(role, value) {
  const link = `full/${role}.md`;
  if (value === undefined || value === null || value === "") return [link, ""];
  if (typeof value !== "string") return ["", "outside_mount"];
  if (hiddenText(value)) return ["", "credential"];
  if (value !== value.trim() || value.includes("\n") || value.includes("\\") || value.includes("..")) {
    return ["", "outside_mount"];
  }
  if (value.startsWith("/")) return ["", "absolute_path"];
  if (value !== link) return ["", "outside_mount"];
  return [link, ""];
}

function charterQuiet(reason) {
  return {
    outcome: "refused",
    reason,
    role: "",
    target: "",
    copied: false,
    linked: false,
    started: false,
    created: false,
    job_cap: 0,
  };
}

function charterFrom(book, role, reason) {
  return {
    outcome: "recorded",
    reason,
    role,
    target: book.links[role] || "",
    copied: false,
    linked: false,
    started: false,
    created: false,
    job_cap: 0,
  };
}

function recordInactive(env, body) {
  if (body.actor !== "board") return charterQuiet("board_only");
  const [name, reason] = roleName(body.role);
  if (reason) return charterQuiet(reason);
  const book = charterBook(env);
  if (Object.prototype.hasOwnProperty.call(book.links, name)) return charterFrom(book, name, "already");
  if (STARTER_IDS.has(name)) return charterQuiet("already_active");
  if (BLOCKED_ROLES.has(name)) return charterQuiet("family_blocked");
  if (!FULL_SET.has(name)) return charterQuiet("unknown_role");
  const mount = mountReason(body.mount);
  if (mount) return charterQuiet(mount);
  const [link, targetReason] = targetLink(name, body.target);
  if (targetReason) return charterQuiet(targetReason);
  book.links[name] = link;
  return charterFrom(book, name, "not_copied");
}

function charterView(env) {
  const book = charterBook(env);
  return FULL_PACK.map((id) => {
    if (BLOCKED_ROLES.has(id)) return {id, state: "blocked", target: ""};
    if (book.links[id]) return {id, state: "recorded", target: book.links[id]};
    return {id, state: "inactive", target: ""};
  });
}

function chartersApi(request, env) {
  const method = request.method || "GET";
  const path = request.path || "/";
  const body = request.body || {};
  if (path === "/api/charters" && method === "GET") {
    return json(200, {
      outcome: "ok",
      reason: "inactive",
      started: false,
      copied: false,
      linked: false,
      created: false,
      job_cap: 0,
      roles: charterView(env),
    });
  }
  if (path === "/api/charters" && method === "POST") {
    const decision = recordInactive(env, body);
    return json(decision.outcome === "recorded" ? 200 : 403, decision);
  }
  return json(404, {
    outcome: "refused",
    reason: "unknown_path",
    started: false,
    copied: false,
    job_cap: 0,
  });
}

const UPDATE_DIGEST = /^[0-9a-f]{64}$/;
const UPDATE_FILENAME = /^[A-Za-z0-9._-]{1,128}$/;
const updateBooks = new WeakMap();

function updateBook(env) {
  const existing = updateBooks.get(env);
  if (existing) return existing;
  const state = {seen: null};
  updateBooks.set(env, state);
  return state;
}

function checksumLine(digest, filename) {
  if (!UPDATE_DIGEST.test(digest) || !UPDATE_FILENAME.test(filename)) return null;
  return `${digest}  ${filename}\n`;
}

function judgeUpdate(body, verifier) {
  const shown = (reason) => ({
    outcome: "refused",
    reason,
    applied: false,
    started: false,
    key_configured: false,
  });
  if (body.actor !== "board") return shown("owner_must_see");
  const signature = body.signature;
  if (typeof signature !== "string" || signature === "") return shown("unsigned");
  if (typeof verifier !== "function") return shown("signature_not_checked");
  const line = checksumLine(
    typeof body.checksum === "string" ? body.checksum : "",
    typeof body.filename === "string" ? body.filename : "",
  );
  if (line === null) return shown("checksum_missing");
  try {
    if (verifier(line, signature) !== true) return shown("signature_rejected");
  } catch (_error) {
    return shown("signature_not_checked");
  }
  return shown("checked_not_applied");
}

function updateReply(reason) {
  if (reason === "no_update") return "No update has been checked.";
  if (reason === "unsigned") return "That update has no signature. Nothing is applied.";
  if (reason === "checksum_missing") return "The checksum line is missing. Nothing is applied.";
  if (reason === "signature_rejected") return "The signature was rejected. Nothing is applied.";
  if (reason === "checked_not_applied") return "The checksum line was checked. Nothing is applied.";
  if (reason === "signature_not_checked") {
    return "No key is configured. The signature was not checked. Nothing is applied.";
  }
  return "No key is configured. Nothing is applied.";
}

function updatesApi(request, env) {
  const method = request.method || "GET";
  const path = request.path || "/";
  const body = request.body || {};
  if (path === "/api/updates" && method === "GET") {
    return json(200, updateBook(env).seen || {
      outcome: "refused",
      reason: "no_update",
      applied: false,
      started: false,
      key_configured: false,
      reply: updateReply("no_update"),
    });
  }
  if (path === "/api/updates" && method === "POST") {
    const decision = judgeUpdate(body, env.updateVerifier);
    if (body.actor !== "board") {
      return json(403, {...decision, reply: "The owner sees an update on this screen."});
    }
    const shown = {...decision, reply: updateReply(decision.reason)};
    updateBook(env).seen = shown;
    return json(200, shown);
  }
  return json(404, {
    outcome: "refused",
    reason: "unknown_path",
    applied: false,
    started: false,
    key_configured: false,
  });
}

function cabinet(request, env) {
  const method = request.method || "GET";
  const path = request.path || "/";
  const body = request.body || {};
  if (path === "/api/cabinet" && method === "GET") {
    return json(200, {
      outcome: "ok",
      reason: "shelf",
      started: false,
      advisors: shelfView(shelfState(env)),
    });
  }
  if (path === "/api/cabinet/secret" && method === "POST") {
    if (!boardActor(body)) {
      return json(403, {outcome: "refused", reason: "actor_cannot_approve", started: false});
    }
    const role = body.role;
    const name = typeof body.name === "string" && SECRET_NAME.test(body.name) ? body.name : "";
    if (!STARTER_IDS.has(role)) {
      return json(403, {outcome: "refused", reason: "role_name", started: false});
    }
    if (name === "") {
      return json(403, {outcome: "refused", reason: "secret_name", started: false});
    }
    if (typeof body.value !== "string" || body.value.trim() === "") {
      return json(403, {outcome: "refused", reason: "secret_value", name, started: false});
    }
    const state = shelfState(env);
    if (!state.secrets[role]) state.secrets[role] = {};
    state.secrets[role][name] = body.value;
    return json(200, {outcome: "recorded", reason: "name_only", name, started: false});
  }
  if (path === "/api/cabinet/tools" && method === "POST") {
    if (!boardActor(body)) {
      return json(403, {outcome: "refused", reason: "actor_cannot_approve", started: false});
    }
    if (!STARTER_IDS.has(body.role)) {
      return json(403, {outcome: "refused", reason: "role_name", started: false});
    }
    const tools = toolList(body.tools);
    const deny = toolList(body.deny);
    const offered = toolList(body.offered);
    if (tools === null || deny === null || offered === null) {
      return json(403, {outcome: "refused", reason: "tool_name", started: false});
    }
    shelfState(env).shown[body.role] = {tools, deny, offered};
    return json(200, {
      outcome: "recorded",
      reason: "shown",
      started: false,
      advisors: shelfView(shelfState(env)),
    });
  }
  if (path === "/api/cabinet/accept" && method === "POST") {
    if (!boardActor(body)) {
      return json(403, {outcome: "refused", reason: "actor_cannot_approve", started: false});
    }
    if (!STARTER_IDS.has(body.role) || !isTool(body.tool)) {
      return json(403, {outcome: "refused", reason: "tool_name", started: false});
    }
    const state = shelfState(env);
    const shown = state.shown[body.role] || {tools: [], deny: [], offered: []};
    if (shown.deny.includes(body.tool)) {
      return json(403, {outcome: "refused", reason: "denied", name: body.tool, started: false});
    }
    if (shown.tools.includes(body.tool)) {
      remember(state.baseline, body.role, body.tool);
      return json(200, {outcome: "accepted", reason: "owner_accepted", name: body.tool, started: false});
    }
    if (shown.offered.includes(body.tool)) {
      remember(state.extra, body.role, body.tool);
      return json(200, {outcome: "accepted", reason: "owner_accepted", name: body.tool, started: false});
    }
    return json(403, {outcome: "refused", reason: "not_offered", name: body.tool, started: false});
  }
  if (path === "/api/cabinet/cap" && method === "POST") {
    if (!boardActor(body)) {
      return json(403, {outcome: "refused", reason: "actor_cannot_approve", cap: 0, started: false});
    }
    if (!STARTER_IDS.has(body.role)) {
      return json(403, {outcome: "refused", reason: "role_name", cap: 0, started: false});
    }
    if (body.cap === 0) {
      return json(200, {outcome: "recorded", reason: "cap_zero", cap: 0, started: false});
    }
    return json(403, {outcome: "refused", reason: "code_profile_off", cap: 0, started: false});
  }
  if (path === "/api/cabinet/engine" && method === "POST") {
    return recordEngine(env, body);
  }
  if (path === "/api/cabinet/durable" && method === "POST") {
    return recordDurable(env, body);
  }
  if (path === "/api/cabinet/collections" && method === "POST") {
    return recordCollections(env, body);
  }
  if (path.startsWith("/api/cabinet")) {
    return json(404, {outcome: "refused", reason: "unknown_path", started: false});
  }
  return null;
}

function page() {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Friday</title>
<style>
  body { font: 16px/1.45 sans-serif; margin: 2rem auto; max-width: 40rem; }
  form, .card { margin: 1rem 0; }
  textarea, input[type=password] { width: 100%; box-sizing: border-box; }
  .waiting { padding: 0.75rem 1rem; background: #f4f1ea; }
  button { margin-right: 0.5rem; }
</style>
</head>
<body>
<h1>Friday</h1>
<p id="status">The screen of this computer. It is only on this machine.</p>
<form id="login">
  <label>Board password <input id="password" type="password" autocomplete="current-password"></label>
  <button type="submit">Open</button>
</form>
<div id="talk" hidden>
  <button id="speak" type="button">Let Friday speak first</button>
  <form id="ask">
    <label>Say something <textarea id="text" rows="3"></textarea></label>
    <button type="submit">Send</button>
  </form>
  <div id="log"></div>
  <section id="events">
    <h2>Events</h2>
    <p>Friday says one fixed sentence. The raw body is not shown. Nothing is sent.</p>
    <ul id="event-list"></ul>
    <p id="event-note"></p>
  </section>
  <section id="tasks">
    <h2>Tasks</h2>
    <p>Goals that wait on this screen. Nothing here starts them.</p>
    <ul id="task-list"></ul>
    <p id="task-note"></p>
  </section>
  <section id="room">
    <h2>Room</h2>
    <p>Declared memory and free RAM are numbers you supply. These numbers are not a hardware measurement. Nothing here is stopped or pulled. Install stays closed.</p>
    <form id="room-form">
      <label>Declared bytes <input id="room-declared" inputmode="numeric" autocomplete="off"></label>
      <label>Free bytes <input id="room-free" inputmode="numeric" autocomplete="off"></label>
      <label>App <input id="room-app" autocomplete="off"></label>
      <label>Other guest <input id="room-guest" autocomplete="off"></label>
      <label>Guest bytes <input id="room-guest-bytes" inputmode="numeric" autocomplete="off"></label>
      <button type="submit">Check room</button>
    </form>
    <p id="room-note">No room check yet. An install button is not offered.</p>
  </section>
  <section id="discover">
    <h2>Discover</h2>
    <p>Names from the catalog packed on this computer. Install stays closed.</p>
    <ul id="discover-list"></ul>
    <p id="discover-note"></p>
  </section>
  <section id="shelf">
    <h2>Advisors</h2>
    <p>Job cap is 0. This screen does not start a job.</p>
    <ul id="advisors">
      ${advisorForms()}
    </ul>
    <form id="secret">
      <label>Advisor
        <select id="secret-role">
          <option>cfo</option>
          <option>chief</option>
          <option>coach</option>
          <option>cto</option>
          <option>home</option>
          <option>media</option>
        </select>
      </label>
      <label>Secret name <input id="secret-name" autocomplete="off"></label>
      <label>Value <input id="secret-value" type="password" autocomplete="new-password"></label>
      <button type="submit">Store the name</button>
    </form>
    <p id="secret-note"></p>
    <form id="compute">
      <p>Engine and budget. Job cap stays 0. This screen does not start a job.</p>
      <label>Advisor
        <select id="compute-role">
          <option>cfo</option>
          <option>chief</option>
          <option>coach</option>
          <option>cto</option>
          <option>home</option>
          <option>media</option>
        </select>
      </label>
      <label>Engine
        <select id="compute-engine">
          <option>claude-code</option>
          <option>gsd</option>
        </select>
      </label>
      <label>Budget minutes <input id="compute-budget" inputmode="numeric" autocomplete="off"></label>
      <button type="submit">Record the engine</button>
    </form>
    <form id="durable">
      <label>Advisor
        <select id="durable-role">
          <option>cfo</option>
          <option>chief</option>
          <option>coach</option>
          <option>cto</option>
          <option>home</option>
          <option>media</option>
        </select>
      </label>
      <label>Durable home on <input id="durable-on" type="checkbox"></label>
      <button type="submit">Record the home</button>
    </form>
    <form id="collection">
      <p>The only collection is cabinet_working. The home is not created.</p>
      <label>Advisor
        <select id="collection-role">
          <option>cfo</option>
          <option>chief</option>
          <option>coach</option>
          <option>cto</option>
          <option>home</option>
          <option>media</option>
        </select>
      </label>
      <button type="submit">Record cabinet_working</button>
    </form>
    <p id="compute-note"></p>
  </section>
  <section id="connections">
    <h2>Connections</h2>
    <p>A grant names a server, a secret reference, a role, and tool names. A tool stays out of the prompt until this screen accepts it. Nothing is called.</p>
    <ul id="grant-list"></ul>
    <form id="grant">
      <label>Server <input id="grant-server" autocomplete="off"></label>
      <label>Role
        <select id="grant-role">
          <option>friday</option>
          <option>cfo</option>
          <option>chief</option>
          <option>coach</option>
          <option>cto</option>
          <option>home</option>
          <option>media</option>
        </select>
      </label>
      <label>Secret reference <input id="grant-ref" autocomplete="off"></label>
      <label>Tool name <input id="grant-tool" autocomplete="off"></label>
      <button type="submit">Record the grant</button>
    </form>
    <p id="grant-note"></p>
  </section>
  <section id="full-pack">
    <h2>Inactive charters</h2>
    <p>The full pack stays inactive until this screen records one name. The file is not copied. Job cap stays 0.</p>
    <ul id="full-pack-list"></ul>
  </section>
  <section id="backup">
    <h2>Backup</h2>
    <p>One manifest for this pause. Nothing is copied. The passphrase stays outside this computer. This is not the life-step button.</p>
    <form id="backup-form">
      <label>Pause <input id="backup-pause" autocomplete="off"></label>
      <label>SQLite
        <select id="backup-method">
          <option>backup_api</option>
          <option>clean_shutdown</option>
        </select>
      </label>
      <label>App <input id="backup-app" autocomplete="off"></label>
      <label>Mark
        <select id="backup-mark">
          <option>managed</option>
          <option>adopted</option>
        </select>
      </label>
      <button type="submit">Record the manifest</button>
    </form>
    <p id="backup-note">No manifest yet. Nothing was copied.</p>
  </section>
  <section id="updates">
    <h2>Updates</h2>
    <p>No key is configured. Nothing is applied.</p>
    <p id="update-note">No update has been checked.</p>
    <form id="update">
      <label>Checksum <input id="update-checksum" autocomplete="off"></label>
      <label>File name <input id="update-filename" autocomplete="off"></label>
      <label>Signature <input id="update-signature" type="password" autocomplete="off"></label>
      <button type="submit">Check</button>
    </form>
  </section>
  <section id="character">
    <h2>Character</h2>
    <p>One proposal for SOUL.md or CHAPTER.md. The file is not written. A week does not apply it. The apply token is not stored.</p>
    <ul id="soul-list"></ul>
    <form id="soul-form">
      <label>File
        <select id="soul-name">
          <option>SOUL.md</option>
          <option>CHAPTER.md</option>
        </select>
      </label>
      <label>Proposal <textarea id="soul-text" rows="3"></textarea></label>
      <button type="submit">Record the proposal</button>
    </form>
    <form id="soul-apply">
      <label>Proposal <input id="soul-id" autocomplete="off"></label>
      <label>Apply token <input id="soul-token" type="password" autocomplete="off"></label>
      <button type="submit">Apply</button>
    </form>
    <p id="soul-note">No proposal yet. The file was not written.</p>
  </section>
</div>
<script>
const password = document.querySelector("#password");
const login = document.querySelector("#login");
const talk = document.querySelector("#talk");
const log = document.querySelector("#log");
function headers() {
  return {"Content-Type": "application/json", "Friday-Board": sessionStorage.getItem("board") || ""};
}
async function openBoard(event) {
  event.preventDefault();
  sessionStorage.setItem("board", password.value);
  password.value = "";
  const response = await fetch("/api/status", {headers: headers()});
  if (response.status === 401) {
    sessionStorage.removeItem("board");
    document.querySelector("#status").textContent = "That password was refused.";
    return;
  }
  login.hidden = true;
  talk.hidden = false;
  const body = await response.json();
  document.querySelector("#status").textContent = body.reply || "Friday is here.";
  loadShelf();
  loadUpdate();
  loadDiscover();
  loadTasks();
  loadPack();
  loadGrants();
  loadEvents();
  loadSoul();
}
function drawShelf(body) {
  const list = document.querySelector("#advisors");
  list.replaceChildren();
  for (const advisor of body.advisors || []) {
    const item = document.createElement("li");
    const title = document.createElement("p");
    title.textContent = advisor.name + " — job cap " + advisor.job_cap;
    item.appendChild(title);
    for (const tool of advisor.tools || []) {
      const row = document.createElement("p");
      row.textContent = tool.name + " is " + tool.state;
      if (tool.state !== "on") {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = "Accept " + tool.name;
        button.addEventListener("click", async () => {
          await fetch("/api/cabinet/accept", {
            method: "POST",
            headers: headers(),
            body: JSON.stringify({actor: "board", role: advisor.id, tool: tool.name}),
          });
          loadShelf();
        });
        row.appendChild(button);
      }
      item.appendChild(row);
    }
    for (const name of advisor.secrets || []) {
      const slot = document.createElement("p");
      slot.textContent = "Secret " + name;
      item.appendChild(slot);
    }
    const engine = document.createElement("p");
    engine.textContent = advisor.engine
      ? advisor.engine + " — " + advisor.budget + " minutes. Job cap " + advisor.job_cap + "."
      : "Engine not set. Job cap " + advisor.job_cap + ".";
    const home = document.createElement("p");
    home.textContent = advisor.durable
      ? advisor.home + " recorded. The workspace is not created."
      : "Durable home is off.";
    const collection = document.createElement("p");
    collection.textContent = advisor.collections && advisor.collections.length
      ? "Collection " + advisor.collections.join(", ") + "."
      : "No collection is recorded.";
    item.append(engine, home, collection);
    const form = document.createElement("form");
    form.className = "advisor-ask";
    form.dataset.advisor = advisor.id;
    const askLabel = document.createElement("label");
    askLabel.textContent = "Ask " + advisor.name + " ";
    const field = document.createElement("textarea");
    field.name = "text";
    field.rows = 2;
    askLabel.appendChild(field);
    const askButton = document.createElement("button");
    askButton.type = "submit";
    askButton.textContent = "Ask " + advisor.name;
    form.append(askLabel, askButton);
    item.appendChild(form);
    list.appendChild(item);
  }
}
async function loadShelf() {
  const response = await fetch("/api/cabinet", {headers: headers()});
  if (response.status !== 200) return;
  drawShelf(await response.json());
}
function drawTasks(body) {
  const list = document.querySelector("#task-list");
  const note = document.querySelector("#task-note");
  list.replaceChildren();
  const rows = body.tasks || [];
  note.textContent = rows.length
    ? rows.length + (rows.length === 1 ? " goal. Nothing is started." : " goals. Nothing is started.")
    : "No goals are waiting.";
  for (const task of rows) {
    const item = document.createElement("li");
    item.textContent = task.goal + " — " + task.state;
    list.appendChild(item);
  }
}
async function loadTasks() {
  const response = await fetch("/api/tasks", {headers: headers()});
  if (response.status !== 200) return;
  drawTasks(await response.json());
}
function drawEvents(body) {
  const list = document.querySelector("#event-list");
  const note = document.querySelector("#event-note");
  list.replaceChildren();
  const rows = body.events || [];
  note.textContent = rows.length
    ? "Friday announced " + rows.length + (rows.length === 1 ? " event." : " events.")
    : "No events yet.";
  for (const row of rows) {
    const item = document.createElement("li");
    item.textContent = row.source + ": " + row.announcement;
    list.appendChild(item);
  }
}
async function loadEvents() {
  const response = await fetch("/api/events", {headers: headers()});
  if (response.status !== 200) return;
  drawEvents(await response.json());
}
function drawPack(body) {
  const list = document.querySelector("#full-pack-list");
  list.replaceChildren();
  for (const role of body.roles || []) {
    const item = document.createElement("li");
    if (role.state === "recorded") {
      item.textContent = role.id + " — " + role.target + " recorded. The file was not copied.";
    } else if (role.state === "blocked") {
      item.textContent = role.id + " stays blocked.";
    } else {
      item.textContent = role.id + " is inactive. ";
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.charter = role.id;
      button.textContent = "Record " + role.id;
      item.appendChild(button);
    }
    list.appendChild(item);
  }
}
function drawGrants(body) {
  const list = document.querySelector("#grant-list");
  const note = document.querySelector("#grant-note");
  list.replaceChildren();
  const rows = body.grants || [];
  note.textContent = rows.length
    ? "A tool stays out of the prompt until it is accepted. Nothing is called."
    : "No grants. Nothing is called.";
  for (const grant of rows) {
    const item = document.createElement("li");
    const title = document.createElement("p");
    title.textContent = grant.role + " — " + grant.server + " — " + grant.secret_ref;
    item.appendChild(title);
    const prompt = document.createElement("p");
    prompt.textContent = grant.prompt && grant.prompt.length
      ? "Prompt: " + grant.prompt.join(", ")
      : "Prompt: (none)";
    item.appendChild(prompt);
    for (const tool of grant.tools || []) {
      const row = document.createElement("p");
      row.textContent = tool.name + " is " + tool.state;
      if (tool.state !== "on") {
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.grantServer = grant.server;
        button.dataset.grantTool = tool.name;
        button.textContent = "Accept " + tool.name;
        row.appendChild(button);
      }
      item.appendChild(row);
    }
    list.appendChild(item);
  }
}
async function loadGrants() {
  const response = await fetch("/api/grants", {headers: headers()});
  if (response.status !== 200) return;
  drawGrants(await response.json());
}
async function recordGrant(event) {
  event.preventDefault();
  const tool = document.querySelector("#grant-tool").value.trim();
  const response = await fetch("/api/grants", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({
      actor: "board",
      server: document.querySelector("#grant-server").value,
      role: document.querySelector("#grant-role").value,
      secret_ref: document.querySelector("#grant-ref").value,
      tools: tool ? [tool] : [],
    }),
  });
  const body = await response.json();
  document.querySelector("#grant-note").textContent = body.reason === "prompt" || body.reason === "kept"
    ? "Recorded. Unaccepted tools stay out of the prompt. Nothing was called."
    : "That grant was refused. Nothing was called.";
  loadGrants();
}
async function acceptGrant(event) {
  const button = event.target.closest("button[data-grant-tool]");
  if (!button) return;
  await fetch("/api/grants/accept", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({
      actor: "board",
      server: button.dataset.grantServer,
      tool: button.dataset.grantTool,
    }),
  });
  loadGrants();
}
async function loadPack() {
  const response = await fetch("/api/charters", {headers: headers()});
  if (response.status !== 200) return;
  drawPack(await response.json());
}
async function recordCharter(event) {
  const button = event.target.closest("button[data-charter]");
  if (!button) return;
  await fetch("/api/charters", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({actor: "board", role: button.dataset.charter}),
  });
  loadPack();
}
let roomFits = false;
let roomBody = null;
function wholeField(value) {
  if (!/^\d+$/.test(value)) return value;
  const number = Number(value);
  return Number.isSafeInteger(number) ? number : value;
}
async function loadDiscover() {
  const response = await fetch("/api/discover", {headers: headers()});
  if (response.status !== 200) return;
  const body = await response.json();
  const list = document.querySelector("#discover-list");
  const note = document.querySelector("#discover-note");
  list.replaceChildren();
  const rows = body.rows || [];
  note.textContent = rows.length
    ? rows.length + " names. Install stays closed."
    : "No catalog names are on this computer. Install stays closed.";
  if (!roomFits) return;
  for (const row of rows) {
    const item = document.createElement("li");
    item.textContent = row.name + " (" + row.train + ") ";
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Install";
    button.addEventListener("click", async () => {
      const refused = await fetch("/api/discover/install", {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({
          actor: "board",
          name: row.name,
          declared: roomBody.declared,
          free: roomBody.free,
          app_id: row.name,
          running: roomBody.running,
        }),
      });
      const result = await refused.json();
      note.textContent = result.reply || result.said || "Catalog install is closed.";
    });
    item.appendChild(button);
    list.appendChild(item);
  }
}
async function checkRoom(event) {
  event.preventDefault();
  const declared = wholeField(document.querySelector("#room-declared").value.trim());
  const free = wholeField(document.querySelector("#room-free").value.trim());
  const app = document.querySelector("#room-app").value;
  const guest = document.querySelector("#room-guest").value.trim();
  const guestBytes = wholeField(document.querySelector("#room-guest-bytes").value.trim());
  const running = guest === "" ? [] : [{id: guest, declared: guestBytes}];
  roomBody = {declared, free, app_id: app, running};
  const response = await fetch("/api/room", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({actor: "board", declared, free, app_id: app, running}),
  });
  const body = await response.json();
  document.querySelector("#room-note").textContent = body.said || body.reason || "";
  roomFits = body.reason === "within_free_ram" && body.offered === false && body.stopped === false;
  loadDiscover();
}
async function loadUpdate() {
  const response = await fetch("/api/updates", {headers: headers()});
  if (response.status !== 200) return;
  const body = await response.json();
  document.querySelector("#update-note").textContent = body.reply || "";
}
async function checkUpdate(event) {
  event.preventDefault();
  const signature = document.querySelector("#update-signature").value;
  const checksum = document.querySelector("#update-checksum").value;
  const filename = document.querySelector("#update-filename").value;
  document.querySelector("#update-signature").value = "";
  const response = await fetch("/api/updates", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({actor: "board", signature, checksum, filename}),
  });
  const body = await response.json();
  document.querySelector("#update-note").textContent = body.reply || "";
}
function wholeBudget(value) {
  if (!/^\d+$/.test(value)) return value;
  const number = Number(value);
  return Number.isSafeInteger(number) ? number : value;
}
async function recordEngine(event) {
  event.preventDefault();
  const response = await fetch("/api/cabinet/engine", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({
      actor: "board",
      role: document.querySelector("#compute-role").value,
      engine: document.querySelector("#compute-engine").value,
      budget: wholeBudget(document.querySelector("#compute-budget").value.trim()),
    }),
  });
  const body = await response.json();
  document.querySelector("#compute-note").textContent = body.reason === "not_started"
    ? "Recorded " + body.name + ". Job cap stays 0. Nothing was started."
    : (body.reason || "");
  loadShelf();
}
async function recordHome(event) {
  event.preventDefault();
  const response = await fetch("/api/cabinet/durable", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({
      actor: "board",
      role: document.querySelector("#durable-role").value,
      on: document.querySelector("#durable-on").checked,
    }),
  });
  const body = await response.json();
  document.querySelector("#compute-note").textContent = body.reason === "not_started"
    ? (body.name ? body.name + " recorded. The workspace is not created." : "Durable home is off. Nothing was started.")
    : (body.reason || "");
  loadShelf();
}
async function recordBackup(event) {
  event.preventDefault();
  const response = await fetch("/api/backup", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({
      actor: "board",
      pause_id: document.querySelector("#backup-pause").value,
      sqlite_method: document.querySelector("#backup-method").value,
      app_id: document.querySelector("#backup-app").value,
      mark: document.querySelector("#backup-mark").value,
    }),
  });
  const body = await response.json();
  const note = document.querySelector("#backup-note");
  note.textContent = body.reason === "stored" || body.reason === "already_stored"
    ? "Recorded. Nothing was copied."
    : (body.reason || "");
}
async function recordCollection(event) {
  event.preventDefault();
  const response = await fetch("/api/cabinet/collections", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({
      actor: "board",
      role: document.querySelector("#collection-role").value,
      names: ["cabinet_working"],
    }),
  });
  const body = await response.json();
  document.querySelector("#compute-note").textContent = body.reason === "cabinet_working"
    ? "Recorded cabinet_working. No other collection was created."
    : (body.reason || "");
  loadShelf();
}
async function storeSecret(event) {
  event.preventDefault();
  const name = document.querySelector("#secret-name").value;
  const value = document.querySelector("#secret-value").value;
  const role = document.querySelector("#secret-role").value;
  document.querySelector("#secret-value").value = "";
  const response = await fetch("/api/cabinet/secret", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({actor: "board", role, name, value}),
  });
  const body = await response.json();
  document.querySelector("#secret-note").textContent = body.name
    ? "Stored " + body.name + "."
    : (body.reason || "");
  loadShelf();
}
async function show(body) {
  const card = document.createElement("div");
  card.className = "card";
  const said = document.createElement("p");
  said.textContent = body.reply || body.reason || "";
  card.appendChild(said);
  if (body.action) {
    const wait = document.createElement("div");
    wait.className = "waiting";
    const label = document.createElement("p");
    label.textContent = "Waiting on this screen. Nothing has been sent or changed.";
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Record the approval";
    let approvalId = "";
    button.addEventListener("click", async () => {
      button.disabled = true;
      if (!approvalId) {
        const approved = await fetch("/api/approve", {
          method: "POST",
          headers: headers(),
          body: JSON.stringify({
            action: body.action,
            target: body.target,
            payload_digest: body.payload_digest
          })
        });
        const result = await approved.json();
        label.textContent = result.reply || result.reason || "";
        const life = body.action === "send" || body.action === "pay" || body.action === "delete" || body.action === "publish";
        if (life && result.outcome === "approved" && /^[0-9a-f-]{36}$/.test(result.approval_id || "")) {
          approvalId = result.approval_id;
          button.textContent = "Exchange once";
          button.disabled = false;
        }
        return;
      }
      const exchanged = await fetch("/api/exchange", {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({
          actor: "board",
          action: body.action,
          approval_id: approvalId,
          target: body.target,
          payload_digest: body.payload_digest
        })
      });
      const result = await exchanged.json();
      label.textContent = result.reply || result.reason || "";
      button.textContent = "Exchange once";
      button.disabled = result.outcome === "exchanged";
    });
    wait.append(label, button);
    card.appendChild(wait);
  }
  log.prepend(card);
}
async function speak() {
  const response = await fetch("/api/ask", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({bootstrap: true, text: ""})
  });
  show(await response.json());
}
async function ask(event) {
  event.preventDefault();
  const text = document.querySelector("#text").value;
  document.querySelector("#text").value = "";
  const response = await fetch("/api/ask", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({text})
  });
  show(await response.json());
}
async function askAdvisor(event) {
  const form = event.target.closest("form.advisor-ask");
  if (!form) return;
  event.preventDefault();
  const field = form.querySelector("textarea");
  const text = field.value;
  field.value = "";
  const response = await fetch("/api/ask", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({role: form.dataset.advisor, text})
  });
  show(await response.json());
}
login.addEventListener("submit", openBoard);
document.querySelector("#speak").addEventListener("click", speak);
document.querySelector("#ask").addEventListener("submit", ask);
document.querySelector("#advisors").addEventListener("submit", askAdvisor);
document.querySelector("#full-pack").addEventListener("click", recordCharter);
document.querySelector("#room-form").addEventListener("submit", checkRoom);
document.querySelector("#secret").addEventListener("submit", storeSecret);
document.querySelector("#compute").addEventListener("submit", recordEngine);
document.querySelector("#durable").addEventListener("submit", recordHome);
document.querySelector("#collection").addEventListener("submit", recordCollection);
document.querySelector("#grant").addEventListener("submit", recordGrant);
document.querySelector("#grant-list").addEventListener("click", acceptGrant);
document.querySelector("#update").addEventListener("submit", checkUpdate);
document.querySelector("#backup-form").addEventListener("submit", recordBackup);
document.querySelector("#soul-form").addEventListener("submit", recordSoulProposal);
document.querySelector("#soul-apply").addEventListener("submit", applySoulProposal);
async function loadSoul() {
  const response = await fetch("/api/soul", {headers: headers()});
  if (response.status !== 200) return;
  const body = await response.json();
  const list = document.querySelector("#soul-list");
  list.replaceChildren();
  for (const item of body.proposals || []) {
    const row = document.createElement("li");
    row.textContent = item.name + " " + item.path + (item.applied ? " applied" : " open");
    list.appendChild(row);
  }
}
async function recordSoulProposal(event) {
  event.preventDefault();
  const field = document.querySelector("#soul-text");
  const text = field.value;
  field.value = "";
  const response = await fetch("/api/soul", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({
      actor: "board",
      name: document.querySelector("#soul-name").value,
      text,
    }),
  });
  const body = await response.json();
  if (body.proposal_id) document.querySelector("#soul-id").value = body.proposal_id;
  await loadSoul();
  document.querySelector("#soul-note").textContent = body.reason + ". The file was not written.";
}
async function applySoulProposal(event) {
  event.preventDefault();
  const field = document.querySelector("#soul-token");
  const token = field.value;
  field.value = "";
  const response = await fetch("/api/soul/apply", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({
      actor: "board",
      proposal_id: document.querySelector("#soul-id").value,
      token,
    }),
  });
  const body = await response.json();
  await loadSoul();
  document.querySelector("#soul-note").textContent = body.reason + ". The file was not written.";
}
</script>
</body>
</html>
`;
}

function missing(env) {
  return REQUIRED.filter((name) => !env[name]);
}

function credentialShape(value) {
  const text = String(value || "");
  return /-----BEGIN |eyJ[A-Za-z0-9_-]{20,}\.|sk-[A-Za-z0-9_-]{16,}|\bAKIA[0-9A-Z]{16}\b|(?:password|passwd|passphrase|token|secret|api[_ -]?key)\s*[:=]\s*\S{4,}|(?:password|passwd|passphrase|token|secret)\s+is\s+\S*\d/i.test(text);
}

function hiddenText(value) {
  let seen = String(value || "");
  for (let i = 0; i < 3; i += 1) {
    if (credentialShape(seen)) return true;
    let decoded = seen;
    try {
      decoded = decodeURIComponent(seen.replaceAll("+", " "));
    } catch (_error) {
      return true;
    }
    if (decoded === seen) return false;
    seen = decoded;
  }
  return credentialShape(seen);
}

const BACKUP_METHODS = new Set(["backup_api", "clean_shutdown"]);
const BACKUP_MARKS = new Set(["managed", "adopted"]);
const BACKUP_APP = /^[a-z][a-z0-9-]{0,63}$/;
const BACKUP_EXCLUDED = new Set(["movies", "jellyfin_config", "optional_apps", "library"]);

function backupQuiet(reason) {
  return {
    outcome: "refused",
    reason,
    copied: false,
    started: false,
  };
}

function backupLeak(body) {
  for (const field of [body.passphrase, body.password, body.secret, body.token, body.value]) {
    if (field === undefined || field === null || field === "" || field === "The password is kept outside the machine") {
      continue;
    }
    return "passphrase_in_manifest";
  }
  return "";
}

async function backupApi(request, env, fetchImpl) {
  const body = request.body || {};
  if (!boardActor(body)) return json(403, backupQuiet("actor_cannot_backup"));
  const leaked = backupLeak(body);
  if (leaked) return json(403, backupQuiet(leaked));
  if (body.operation === "install" || body.action === "install") {
    return json(403, {...backupQuiet("catalog_install_closed"), reply: "Catalog install is closed."});
  }
  const pause = typeof body.pause_id === "string" ? body.pause_id : "";
  const method = typeof body.sqlite_method === "string" ? body.sqlite_method : "";
  const appId = typeof body.app_id === "string" ? body.app_id : "";
  const mark = typeof body.mark === "string" ? body.mark : "";
  if (hiddenText(pause) || hiddenText(method) || hiddenText(appId) || hiddenText(mark)) {
    return json(403, backupQuiet("credential"));
  }
  if (!APPROVAL_ID.test(pause)) return json(403, backupQuiet("pause_id"));
  if (method === "live_file" || method === "path" || method === "copy") {
    return json(403, backupQuiet("live_sqlite"));
  }
  if (!BACKUP_METHODS.has(method)) return json(403, backupQuiet("sqlite_method"));
  if (BACKUP_EXCLUDED.has(appId)) return json(403, backupQuiet("optional_app_excluded"));
  if (!BACKUP_APP.test(appId) || !BACKUP_MARKS.has(mark)) return json(403, backupQuiet("registry_mark"));
  const extra = body.included_extra || body.include_names;
  if (Array.isArray(extra) ? extra.length > 0 : extra) return json(403, backupQuiet("optional_app_excluded"));
  const upstream = await call(
    fetchImpl,
    env.EXECUTOR_URL + "/backup",
    "POST",
    {"Friday-Approval": env.BOARD_APPROVAL_TOKEN},
    {
      actor: "board",
      pause_id: pause,
      sqlite_method: method,
      registry: [{id: appId, mark}],
    }
  );
  const result = upstream.json || {};
  const reason = typeof result.reason === "string" && REASON_CODE.test(result.reason) ? result.reason : "backup";
  const manifest = typeof result.manifest_id === "string" && APPROVAL_ID.test(result.manifest_id)
    ? result.manifest_id
    : "";
  const manifested = result.outcome === "manifested" && (reason === "stored" || reason === "already_stored");
  return json(manifested ? 200 : upstream.status === 503 ? 503 : 403, {
    outcome: manifested ? "manifested" : "refused",
    reason,
    manifest_id: manifest,
    copied: false,
    started: false,
    reply: manifested ? "Recorded. Nothing was copied." : reason,
  });
}

function exchangeQuiet(reason) {
  return {
    outcome: "refused",
    reason,
    started: false,
    sent: false,
    changed: false,
  };
}

function exchangeLeak(body) {
  for (const field of [body.secret, body.value, body.token, body.password]) {
    if (field === undefined || field === null || field === "" || field === "The password is kept outside the machine") {
      continue;
    }
    if (typeof field === "string" && hiddenText(field)) return "credential";
    return "caller_value";
  }
  return "";
}

async function exchangeApi(request, env, fetchImpl) {
  const body = request.body || {};
  const action = typeof body.action === "string" ? body.action : "";
  const approval = typeof body.approval_id === "string" ? body.approval_id : "";
  const target = typeof body.target === "string" ? body.target : "";
  const digest = typeof body.payload_digest === "string" ? body.payload_digest : "";
  if (hiddenText(action) || hiddenText(approval) || hiddenText(target) || hiddenText(digest)) {
    return json(403, exchangeQuiet("credential"));
  }
  if (!boardActor(body)) return json(403, exchangeQuiet("actor_cannot_exchange"));
  const leaked = exchangeLeak(body);
  if (leaked) return json(403, exchangeQuiet(leaked));
  if (action === "install" || action === "uninstall") {
    return json(403, {
      ...exchangeQuiet("catalog_install_closed"),
      reply: "Catalog install is closed.",
    });
  }
  if (!LIFE_ACTIONS.has(action)) return json(403, exchangeQuiet("not_a_life_step"));
  if (!APPROVAL_ID.test(approval)) return json(403, exchangeQuiet("approval_id"));
  if (target === "" || target.length > 200 || target !== target.trim() || /[\n\r]/.test(target)) {
    return json(403, exchangeQuiet("target"));
  }
  if (!DIGEST.test(digest)) return json(403, exchangeQuiet("payload_digest"));
  const upstream = await call(
    fetchImpl,
    env.EXECUTOR_URL + "/exchange",
    "POST",
    {"Friday-Approval": env.BOARD_APPROVAL_TOKEN},
    {
      actor: "board",
      action,
      owner_id: env.OWNER_ID || "owner",
      approval_id: approval,
      body: {action_class: action, target, payload_digest: digest},
    }
  );
  const result = upstream.json || {};
  if (upstream.status !== 200 && upstream.status !== 403) {
    return json(502, exchangeQuiet("executor"));
  }
  const reason = typeof result.reason === "string" && REASON_CODE.test(result.reason) ? result.reason : "exchange";
  const operation = typeof result.operation_id === "string" && APPROVAL_ID.test(result.operation_id)
    ? result.operation_id
    : "";
  const kept = typeof result.approval_id === "string" && APPROVAL_ID.test(result.approval_id)
    ? result.approval_id
    : approval;
  const exchanged = result.outcome === "exchanged" && (reason === "exchanged" || reason === "already_exchanged");
  return json(exchanged ? 200 : upstream.status, {
    outcome: exchanged ? "exchanged" : "refused",
    reason,
    approval_id: kept,
    operation_id: operation,
    started: false,
    sent: false,
    changed: false,
    reply: exchanged ? "Exchanged on the Board. Nothing was sent." : reason,
  });
}

function publicEvents(rows) {
  const found = [];
  if (!Array.isArray(rows)) return found;
  for (const row of rows) {
    if (!row || typeof row !== "object") continue;
    const eventType = row.event_type;
    const source = row.source;
    const sentence = EVENT_SENTENCE[eventType];
    if (!sentence || !EVENT_SOURCES.has(source) || row.announcement !== sentence) continue;
    if (hiddenText(source) || hiddenText(eventType) || hiddenText(sentence)) continue;
    found.push({source, event_type: eventType, announcement: sentence});
    if (found.length === 8) break;
  }
  return found;
}

function publicTasks(rows) {
  const found = [];
  if (!Array.isArray(rows)) return found;
  for (const row of rows) {
    if (!row || typeof row !== "object") continue;
    const goal = typeof row.goal === "string" ? row.goal.replace(/\s+/g, " ").trim().slice(0, 200) : "";
    const id = typeof row.id === "string" ? row.id : "";
    if (!goal || hiddenText(goal) || !TASK_ID.test(id) || hiddenText(id)) continue;
    const steps = [];
    for (const step of Array.isArray(row.steps) ? row.steps : []) {
      if (!step || !STEP_NAME.test(step.name) || !STEP_STATES.has(step.state)) continue;
      steps.push({name: step.name, state: step.state});
      if (steps.length === 8) break;
    }
    found.push({
      id,
      state: TASK_STATES.has(row.state) ? row.state : "waiting",
      role: ROLE_NAME.test(row.role) ? row.role : "friday",
      goal,
      steps,
    });
    if (found.length === 8) break;
  }
  return found;
}

function soulBook(env) {
  const existing = soulBooks.get(env);
  if (existing) return existing;
  const book = {proposals: {}, current: {}, history: []};
  soulBooks.set(env, book);
  return book;
}

function soulQuiet(reason) {
  return {
    outcome: "refused",
    reason,
    name: "",
    proposal_id: "",
    path: "",
    applied: false,
    files_written: false,
    example_read: false,
    token_stored: false,
    scheduled: false,
  };
}

function soulPath(id) {
  return `soul/proposals/${id}.md`;
}

function soulTokenReason(presented, expected) {
  if (typeof presented !== "string" || typeof expected !== "string") return "token_required";
  if (presented.trim() === "" || expected.trim() === "") return "token_required";
  const left = Buffer.from(presented);
  const right = Buffer.from(expected);
  if (left.length !== right.length || !crypto.timingSafeEqual(left, right)) return "token_mismatch";
  if (credentialShape(presented) || credentialShape(expected) || hiddenText(presented) || hiddenText(expected)) {
    return "credential";
  }
  return "";
}

function recordSoul(env, body) {
  if (body.actor !== "board") return soulQuiet("board_only");
  if (!SOUL_FILES.has(body.name)) return soulQuiet("not_a_soul_file");
  if (typeof body.text !== "string" || body.text.trim() === "") return soulQuiet("empty");
  const text = body.text.trim();
  if (hiddenText(text)) return soulQuiet("credential");
  const book = soulBook(env);
  if (Object.values(book.proposals).some((item) => item.name === body.name && !item.applied)) {
    return soulQuiet("proposal_open");
  }
  const id = crypto.randomBytes(16).toString("hex");
  book.proposals[id] = {id, name: body.name, text, applied: false};
  return {
    outcome: "recorded",
    reason: "proposal",
    name: body.name,
    proposal_id: id,
    path: soulPath(id),
    applied: false,
    files_written: false,
    example_read: false,
    token_stored: false,
    scheduled: false,
  };
}

function applySoul(env, body) {
  if (body.actor !== "board") return soulQuiet("board_only");
  if (typeof body.proposal_id !== "string" || body.proposal_id === "") return soulQuiet("unknown_proposal");
  const book = soulBook(env);
  const proposal = book.proposals[body.proposal_id];
  if (!proposal) return soulQuiet("unknown_proposal");
  if (!SOUL_FILES.has(proposal.name)) {
    return {...soulQuiet("not_a_soul_file"), proposal_id: proposal.id, name: proposal.name};
  }
  if (typeof proposal.text !== "string" || proposal.text.trim() === "") {
    return {...soulQuiet("empty"), name: proposal.name, proposal_id: proposal.id};
  }
  const text = proposal.text.trim();
  const reason = soulTokenReason(body.token, typeof env.SOUL_APPLY_TOKEN === "string" ? env.SOUL_APPLY_TOKEN : "");
  if (reason) return {...soulQuiet(reason), name: proposal.name, proposal_id: proposal.id};
  if (hiddenText(text)) return {...soulQuiet("credential"), name: proposal.name, proposal_id: proposal.id};
  if (proposal.applied) {
    return {
      ...soulQuiet("already_applied"),
      name: proposal.name,
      proposal_id: proposal.id,
      path: soulPath(proposal.id),
    };
  }
  book.history.push({proposal_id: proposal.id, name: proposal.name, previous: book.current[proposal.name] || ""});
  book.current[proposal.name] = text;
  proposal.text = text;
  proposal.applied = Boolean(proposal.id);
  return {
    outcome: "applied",
    reason: "applied",
    name: proposal.name,
    proposal_id: proposal.id,
    path: soulPath(proposal.id),
    applied: proposal.applied,
    files_written: false,
    example_read: false,
    token_stored: false,
    scheduled: false,
  };
}

function soulView(env) {
  const book = soulBook(env);
  return {
    outcome: "ok",
    reason: "proposals",
    files_written: false,
    example_read: false,
    token_stored: false,
    scheduled: false,
    current: {...book.current},
    proposals: Object.values(book.proposals).map((item) => ({
      id: item.id,
      name: item.name,
      path: soulPath(item.id),
      applied: item.applied,
      text: item.text,
    })),
  };
}

function soulApi(request, env) {
  const method = request.method || "GET";
  const route = request.path || "/";
  const body = request.body || {};
  if (route === "/api/soul" && method === "GET") return json(200, soulView(env));
  if (route === "/api/soul" && method === "POST") {
    const decision = recordSoul(env, body);
    return json(decision.outcome === "recorded" ? 200 : 403, decision);
  }
  if (route === "/api/soul/apply" && method === "POST") {
    const decision = applySoul(env, body);
    return json(decision.outcome === "applied" ? 200 : 403, decision);
  }
  return json(404, soulQuiet("unknown_path"));
}

async function handle(request, env, fetchImpl) {
  const method = request.method || "GET";
  const path = request.path || "/";
  const headers = request.headers || {};
  const body = request.body || {};
  delete body.confirmed;
  if (path === "/" && method === "GET") {
    return {status: 200, type: "html", body: page()};
  }
  if (missing(env).length) {
    return json(503, {outcome: "refused", reason: "secrets"});
  }
  const presented = String(headers["Friday-Board"] || headers["friday-board"] || "");
  if (presented !== env.BOARD_PASSWORD) {
    return json(401, {outcome: "refused", reason: "unauthenticated"});
  }
  if (path.startsWith("/api/soul")) {
    return soulApi(request, env);
  }
  if (path.startsWith("/api/charters")) {
    return chartersApi(request, env);
  }
  if (path.startsWith("/api/cabinet")) {
    return cabinet(request, env);
  }
  if (path === "/api/updates") {
    return updatesApi(request, env);
  }
  if (path.startsWith("/api/grants")) {
    return grantsApi(request, env);
  }
  if (path === "/api/events" && method === "GET") {
    const upstream = await call(
      fetchImpl,
      env.FRIDAY_URL + "/announcements",
      "GET",
      {"Friday-Notify": env.FRIDAY_NOTIFY_TOKEN},
      null
    );
    const reported = upstream.json || {};
    const reason = REASON_CODE.test(reported.reason) ? reported.reason : "events";
    return json(upstream.status === 200 ? 200 : upstream.status, {
      outcome: reported.outcome === "ok" && upstream.status === 200 ? "ok" : "refused",
      reason,
      started: false,
      sent: false,
      events: upstream.status === 200 ? publicEvents(reported.announcements) : [],
    });
  }
  if (path === "/api/events") {
    return json(405, {
      outcome: "refused",
      reason: "method_refused",
      started: false,
      sent: false,
      events: [],
    });
  }
  if (path === "/api/tasks" && method === "GET") {
    const upstream = await call(
      fetchImpl,
      env.EXECUTOR_URL + "/tasks",
      "GET",
      {
        "Friday-Approval": env.BOARD_APPROVAL_TOKEN,
        "Friday-Owner": env.OWNER_ID || "owner",
      },
      null
    );
    const body = upstream.json || {};
    const reason = REASON_CODE.test(body.reason) ? body.reason : "tasks";
    return json(upstream.status === 200 ? 200 : upstream.status, {
      outcome: body.outcome === "ok" && upstream.status === 200 ? "ok" : "refused",
      reason,
      started: false,
      tasks: upstream.status === 200 ? publicTasks(body.tasks) : [],
    });
  }
  if (path === "/api/discover" && method === "GET") {
    const found = discoverRows(env.CATALOG_ROOT || "");
    return json(200, {
      outcome: "listed",
      reason: found.reason,
      install: "closed",
      started: false,
      rows: found.rows,
    });
  }
  if (path === "/api/room" && method === "POST") {
    if (!boardActor(body)) {
      return json(403, roomQuiet("refused", "actor_cannot_approve"));
    }
    const decision = roomDecision(body);
    return json(decision.outcome === "refused" ? 403 : 200, decision);
  }
  if (path === "/api/discover/install" && method === "POST") {
    if (hasRoom(body)) {
      const decision = roomDecision(body);
      if (decision.reason !== "within_free_ram") {
        return json(decision.outcome === "refused" ? 403 : 200, decision);
      }
    }
    return json(403, {
      outcome: "refused",
      reason: "catalog_install_closed",
      started: false,
      offered: false,
      stopped: false,
      pulled: false,
      reply: "Catalog install is closed.",
    });
  }
  if (path === "/api/status" && method === "GET") {
    const health = await call(fetchImpl, env.FRIDAY_URL + "/health", "GET", {}, null);
    const reply = health.status === 200
      ? "Friday is on this computer. Catalog install stays closed."
      : "Friday is not answering yet.";
    return json(200, {outcome: "ok", reason: "status", reply});
  }
  if (path === "/api/ask" && method === "POST") {
    const asked = advisorAsk(body);
    if (asked.error) {
      return json(403, {outcome: "refused", reason: asked.error, started: false});
    }
    const upstream = await call(
      fetchImpl,
      env.FRIDAY_URL + "/ask",
      "POST",
      {"Friday-Notify": env.FRIDAY_NOTIFY_TOKEN},
      {
        text: asked.text,
        owner_id: env.OWNER_ID || "owner",
        owner_kind: "person",
        bootstrap: asked.bootstrap
      }
    );
    return json(upstream.status, upstream.json);
  }
  if (path === "/api/exchange" && method === "POST") {
    return exchangeApi(request, env, fetchImpl);
  }
  if (path === "/api/backup" && method === "POST") {
    return backupApi(request, env, fetchImpl);
  }
  if (path === "/api/backup") {
    return json(405, backupQuiet("method_refused"));
  }
  if (path === "/api/approve" && method === "POST") {
    const action = String(body.action || "");
    if (action === "install" && hasRoom(body)) {
      const decision = roomDecision(body);
      if (decision.reason !== "within_free_ram") {
        return json(decision.outcome === "refused" ? 403 : 200, decision);
      }
    }
    const payload = action === "install"
      ? {actor: "board", action: "install", operation: "install", owner_id: env.OWNER_ID || "owner"}
      : {
          actor: "board",
          action,
          owner_id: env.OWNER_ID || "owner",
          body: {
            action_class: action,
            target: String(body.target || ""),
            payload_digest: String(body.payload_digest || "")
          }
        };
    const upstream = await call(
      fetchImpl,
      env.EXECUTOR_URL + "/approvals",
      "POST",
      {"Friday-Approval": env.BOARD_APPROVAL_TOKEN},
      payload
    );
    const result = upstream.json || {};
    result.reply = result.reason === "catalog_install_closed"
      ? "Catalog install is closed."
      : result.reason === "recorded"
        ? "Recorded on the Board. Nothing was sent."
        : (result.reply || result.reason || "");
    if (result.outcome === "approved") {
      result.reply = "Recorded on the Board. Nothing was sent.";
    }
    return json(upstream.status, result);
  }
  return json(404, {outcome: "refused", reason: "unknown_path"});
}

async function call(fetchImpl, url, method, headers, payload) {
  const response = await fetchImpl(url, {
    method,
    headers: {"Content-Type": "application/json", ...headers},
    body: payload === null ? undefined : JSON.stringify(payload)
  });
  const text = await response.text();
  let parsed = {};
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch (_error) {
      parsed = {outcome: "refused", reason: "body"};
    }
  }
  return {status: response.status, json: parsed};
}

function json(status, body) {
  return {status, type: "json", body};
}

function listen(env = process.env) {
  const host = env.BIND_HOST || "127.0.0.1";
  const port = Number(env.PORT || 8080);
  if (missing(env).length) {
    console.error("board: secrets");
    process.exit(1);
  }
  const server = http.createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const raw = Buffer.concat(chunks).toString("utf8");
    let payload = {};
    if (raw) {
      try {
        payload = JSON.parse(raw);
      } catch (_error) {
        res.writeHead(400, {"Content-Type": "application/json"});
        res.end(JSON.stringify({outcome: "refused", reason: "body"}));
        return;
      }
    }
    const result = await handle(
      {method: req.method, path: req.url.split("?")[0], headers: req.headers, body: payload},
      env,
      global.fetch
    );
    const type = result.type === "html" ? "text/html; charset=utf-8" : "application/json";
    const encoded = result.type === "html" ? result.body : JSON.stringify(result.body);
    res.writeHead(result.status, {"Content-Type": type, "Cache-Control": "no-store"});
    res.end(encoded);
  });
  server.listen(port, host);
  return server;
}

if (require.main === module) {
  listen();
}

module.exports = {escapeHtml, handle, page};
