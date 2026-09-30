"use strict";

const http = require("http");

const REQUIRED = ["BOARD_PASSWORD", "FRIDAY_NOTIFY_TOKEN", "BOARD_APPROVAL_TOKEN"];

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
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
    button.addEventListener("click", async () => {
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
      button.disabled = true;
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
login.addEventListener("submit", openBoard);
document.querySelector("#speak").addEventListener("click", speak);
document.querySelector("#ask").addEventListener("submit", ask);
</script>
</body>
</html>
`;
}

function missing(env) {
  return REQUIRED.filter((name) => !env[name]);
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
  if (path === "/api/status" && method === "GET") {
    const health = await call(fetchImpl, env.FRIDAY_URL + "/health", "GET", {}, null);
    const reply = health.status === 200
      ? "Friday is on this computer. Catalog install stays closed."
      : "Friday is not answering yet.";
    return json(200, {outcome: "ok", reason: "status", reply});
  }
  if (path === "/api/ask" && method === "POST") {
    const upstream = await call(
      fetchImpl,
      env.FRIDAY_URL + "/ask",
      "POST",
      {"Friday-Notify": env.FRIDAY_NOTIFY_TOKEN},
      {
        text: String(body.text || ""),
        owner_id: env.OWNER_ID || "owner",
        owner_kind: "person",
        bootstrap: body.bootstrap === true
      }
    );
    return json(upstream.status, upstream.json);
  }
  if (path === "/api/approve" && method === "POST") {
    const action = String(body.action || "");
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
