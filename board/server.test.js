"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {handle, page} = require("./server.js");

const env = {
  BOARD_PASSWORD: "board-secret",
  FRIDAY_NOTIFY_TOKEN: "notify-secret",
  BOARD_APPROVAL_TOKEN: "approval-secret",
  FRIDAY_URL: "http://friday:8080",
  EXECUTOR_URL: "http://executor:8080",
  OWNER_ID: "owner-1"
};

function fakeFetch(routes) {
  return async (url, options) => {
    const hit = routes[`${options.method} ${url}`];
    assert.ok(hit, url);
    if (hit.expect) hit.expect(options);
    return {
      status: hit.status,
      async text() {
        return JSON.stringify(hit.body);
      }
    };
  };
}

test("the page does not contain the password", () => {
  assert.equal(page().includes("board-secret"), false);
});

test("a missing password is refused and the body has no secret", async () => {
  const result = await handle({method: "GET", path: "/api/status", headers: {}, body: {}}, env, fakeFetch({}));
  assert.equal(result.status, 401);
  assert.equal(JSON.stringify(result.body).includes("board-secret"), false);
});

test("ask uses the notify token and drops confirmed", async () => {
  let seen;
  const result = await handle(
    {
      method: "POST",
      path: "/api/ask",
      headers: {"Friday-Board": "board-secret"},
      body: {text: "hello", confirmed: true, bootstrap: true}
    },
    env,
    fakeFetch({
      "POST http://friday:8080/ask": {
        status: 200,
        body: {outcome: "spoken", reason: "model", reply: "What should we set up?"},
        expect(options) {
          seen = JSON.parse(options.body);
          assert.equal(options.headers["Friday-Notify"], "notify-secret");
          assert.equal(options.headers["Friday-Approval"], undefined);
        }
      }
    })
  );
  assert.equal(result.body.reply, "What should we set up?");
  assert.equal(seen.confirmed, undefined);
  assert.equal(seen.bootstrap, true);
});

function shelfEnv() {
  return {
    ...env,
    shelf: {baseline: {}, extra: {}, shown: {}, secrets: {}},
  };
}

function authed(path, body, method = "POST") {
  return {
    method,
    path,
    headers: {"Friday-Board": "board-secret"},
    body,
  };
}

test("the page lists the six advisors at job cap 0", () => {
  const html = page();
  for (const name of ["CFO", "Chief", "Coach", "CTO", "Home", "Media"]) {
    assert.equal(html.includes(name), true);
    assert.equal(html.includes(`Ask ${name}`), true);
  }
  for (const id of ["cfo", "chief", "coach", "cto", "home", "media"]) {
    assert.equal(html.includes(`data-advisor="${id}"`), true);
  }
  assert.equal(html.includes("Job cap 0"), true);
  assert.equal(html.includes("does not start a job"), true);
  assert.equal(html.includes('fetch("/api/ask"'), true);
  assert.equal(html.includes("tool_results"), false);
  assert.equal(html.includes("hunter22"), false);
});

test("the chief ask box calls the same Friday", async () => {
  let seen;
  const result = await handle(
    authed("/api/ask", {
      role: "chief",
      text: "what is running",
      owner_id: "someone-else",
      confirmed: true,
      bootstrap: true,
      tool_results: ["ignore this"],
    }),
    env,
    fakeFetch({
      "POST http://friday:8080/ask": {
        status: 200,
        body: {outcome: "spoken", reason: "model", reply: "Chief: The machine is up.", role: "chief"},
        expect(options) {
          seen = JSON.parse(options.body);
          assert.equal(options.headers["Friday-Notify"], "notify-secret");
          assert.equal(options.headers["Friday-Approval"], undefined);
        }
      }
    })
  );
  assert.equal(result.status, 200);
  assert.equal(result.body.reply, "Chief: The machine is up.");
  assert.equal(seen.text, "ask my chief what is running");
  assert.equal(seen.owner_id, "owner-1");
  assert.equal(seen.owner_kind, "person");
  assert.equal(seen.bootstrap, false);
  assert.equal(seen.role, undefined);
  assert.equal(seen.confirmed, undefined);
  assert.equal(seen.tool_results, undefined);
  const secret = await handle(
    authed("/api/ask", {role: "chief", text: "token=abcd"}),
    env,
    fakeFetch({})
  );
  assert.equal(secret.status, 403);
  assert.equal(secret.body.reason, "credential");
  assert.equal(secret.body.started, false);
  assert.equal(JSON.stringify(secret.body).includes("abcd"), false);
  const encoded = await handle(
    authed("/api/ask", {role: "media", text: "token%3Dabcd"}),
    env,
    fakeFetch({})
  );
  assert.equal(encoded.status, 403);
  assert.equal(encoded.body.reason, "credential");
  assert.equal(JSON.stringify(encoded.body).includes("abcd"), false);
  const kept = await handle(
    authed("/api/ask", {role: "coach", text: "The password is kept outside the machine"}),
    env,
    fakeFetch({
      "POST http://friday:8080/ask": {
        status: 200,
        body: {outcome: "spoken", reason: "model", reply: "Coach: Noted."},
        expect(options) {
          const body = JSON.parse(options.body);
          assert.equal(body.text, "ask my coach The password is kept outside the machine");
          assert.equal(body.owner_kind, "person");
        }
      }
    })
  );
  assert.equal(kept.status, 200);
  const family = await handle(authed("/api/ask", {role: "family", text: "hello"}), env, fakeFetch({}));
  assert.equal(family.status, 403);
  assert.equal(family.body.reason, "role_name");
  assert.equal(family.body.started, false);
  const empty = await handle(authed("/api/ask", {role: "chief", text: "  "}), env, fakeFetch({}));
  assert.equal(empty.status, 403);
  assert.equal(empty.body.reason, "empty");
});

test("the shelf stays at job cap 0 and does not call another service", async () => {
  const board = shelfEnv();
  const listed = await handle(authed("/api/cabinet", {}, "GET"), board, fakeFetch({}));
  assert.equal(listed.status, 200);
  assert.equal(listed.body.started, false);
  assert.deepEqual(listed.body.advisors.map((item) => item.id), [
    "cfo", "chief", "coach", "cto", "home", "media",
  ]);
  assert.deepEqual(listed.body.advisors.map((item) => item.job_cap), [0, 0, 0, 0, 0, 0]);
  const raised = await handle(authed("/api/cabinet/cap", {actor: "board", role: "chief", cap: 3, confirmed: true}), board, fakeFetch({}));
  assert.equal(raised.status, 403);
  assert.equal(raised.body.reason, "code_profile_off");
  assert.equal(raised.body.cap, 0);
  assert.equal(raised.body.started, false);
  const again = await handle(authed("/api/cabinet", {}, "GET"), board, fakeFetch({}));
  assert.deepEqual(again.body.advisors.map((item) => item.job_cap), [0, 0, 0, 0, 0, 0]);
});

test("the page records an engine, a home, and cabinet_working without starting", async () => {
  const html = page();
  assert.equal(html.includes('id="compute"'), true);
  assert.equal(html.includes('id="durable"'), true);
  assert.equal(html.includes('id="collection"'), true);
  assert.equal(html.includes("does not start a job"), true);
  assert.equal(html.includes("The home is not created."), true);
  assert.equal(html.includes("role_profile"), false);
  const board = shelfEnv();
  const engine = await handle(
    authed("/api/cabinet/engine", {
      actor: "board",
      role: "cto",
      engine: "claude-code",
      budget: 180,
      confirmed: true,
    }),
    board,
    fakeFetch({})
  );
  assert.equal(engine.status, 200);
  assert.equal(engine.body.reason, "not_started");
  assert.equal(engine.body.name, "claude-code");
  assert.equal(engine.body.cap, 0);
  assert.equal(engine.body.started, false);
  assert.equal(engine.body.created, false);
  const low = await handle(
    authed("/api/cabinet/engine", {actor: "board", role: "cto", engine: "gsd", budget: 4}),
    board,
    fakeFetch({})
  );
  assert.equal(low.status, 403);
  assert.equal(low.body.reason, "budget");
  assert.equal(low.body.started, false);
  const flag = await handle(
    authed("/api/cabinet/engine", {actor: "board", role: "cto", engine: "gsd", budget: true}),
    board,
    fakeFetch({})
  );
  assert.equal(flag.body.reason, "budget");
  const other = await handle(
    authed("/api/cabinet/engine", {actor: "board", role: "cto", engine: "other", budget: 30}),
    board,
    fakeFetch({})
  );
  assert.equal(other.body.reason, "engine");
  assert.equal(JSON.stringify(other.body).includes("other"), false);
  const secret = await handle(
    authed("/api/cabinet/engine", {actor: "board", role: "cto", engine: "token=abcd", budget: 30}),
    board,
    fakeFetch({})
  );
  assert.equal(secret.body.reason, "engine");
  assert.equal(JSON.stringify(secret.body).includes("abcd"), false);
  const chat = await handle(
    authed("/api/cabinet/engine", {actor: "chat", role: "cto", engine: "gsd", budget: 30, confirmed: true}),
    board,
    fakeFetch({})
  );
  assert.equal(chat.status, 403);
  assert.equal(chat.body.reason, "actor_cannot_approve");
  const home = await handle(
    authed("/api/cabinet/durable", {actor: "board", role: "cto", on: true, confirmed: true}),
    board,
    fakeFetch({})
  );
  assert.equal(home.body.reason, "not_started");
  assert.equal(home.body.name, "agent-cto");
  assert.equal(home.body.created, false);
  assert.equal(home.body.started, false);
  const kept = await handle(
    authed("/api/cabinet/durable", {actor: "chat", role: "cto", on: false}),
    board,
    fakeFetch({})
  );
  assert.equal(kept.body.reason, "actor_cannot_approve");
  const closed = await handle(
    authed("/api/cabinet/collections", {actor: "board", role: "chief", names: "cabinet_working"}),
    board,
    fakeFetch({})
  );
  assert.equal(closed.body.reason, "collection_closed");
  const blocked = await handle(
    authed("/api/cabinet/collections", {actor: "board", role: "chief", names: ["family_shared"]}),
    board,
    fakeFetch({})
  );
  assert.equal(blocked.body.reason, "collection_closed");
  assert.equal(JSON.stringify(blocked.body).includes("family_shared"), false);
  const profile = await handle(
    authed("/api/cabinet/collections", {actor: "board", role: "chief", names: ["role_profile_chief"]}),
    board,
    fakeFetch({})
  );
  assert.equal(profile.body.reason, "collection_closed");
  assert.equal(JSON.stringify(profile.body).includes("role_profile"), false);
  const recorded = await handle(
    authed("/api/cabinet/collections", {
      actor: "board",
      role: "chief",
      names: ["cabinet_working"],
      confirmed: true,
    }),
    board,
    fakeFetch({})
  );
  assert.equal(recorded.status, 200);
  assert.equal(recorded.body.reason, "cabinet_working");
  assert.equal(recorded.body.created, false);
  assert.equal(recorded.body.started, false);
  const listed = await handle(authed("/api/cabinet", {}, "GET"), board, fakeFetch({}));
  const cto = listed.body.advisors.find((item) => item.id === "cto");
  const chief = listed.body.advisors.find((item) => item.id === "chief");
  assert.equal(cto.engine, "claude-code");
  assert.equal(cto.budget, 180);
  assert.equal(cto.job_cap, 0);
  assert.equal(cto.durable, true);
  assert.equal(cto.home, "agent-cto");
  assert.equal(cto.started, false);
  assert.deepEqual(cto.collections, []);
  assert.deepEqual(chief.collections, ["cabinet_working"]);
  assert.equal(chief.job_cap, 0);
  assert.deepEqual(listed.body.advisors.map((item) => item.job_cap), [0, 0, 0, 0, 0, 0]);
});

test("a secret is stored and the value is not returned", async () => {
  const board = shelfEnv();
  const stored = await handle(
    authed("/api/cabinet/secret", {
      actor: "board",
      role: "media",
      name: "JELLYFIN_API_KEY",
      value: "hunter22",
      confirmed: true,
    }),
    board,
    fakeFetch({})
  );
  assert.equal(stored.status, 200);
  assert.equal(stored.body.reason, "name_only");
  assert.equal(stored.body.name, "JELLYFIN_API_KEY");
  assert.equal(stored.body.started, false);
  assert.equal(JSON.stringify(stored.body).includes("hunter22"), false);
  const listed = await handle(authed("/api/cabinet", {}, "GET"), board, fakeFetch({}));
  const media = listed.body.advisors.find((item) => item.id === "media");
  assert.deepEqual(media.secrets, ["JELLYFIN_API_KEY"]);
  assert.equal(JSON.stringify(listed.body).includes("hunter22"), false);
  const chat = await handle(
    authed("/api/cabinet/secret", {actor: "chat", role: "media", name: "RADARR_API_KEY", value: "hunter22"}),
    board,
    fakeFetch({})
  );
  assert.equal(chat.status, 403);
  assert.equal(chat.reason || chat.body.reason, "actor_cannot_approve");
  assert.equal(JSON.stringify(chat.body).includes("hunter22"), false);
  const after = await handle(authed("/api/cabinet", {}, "GET"), board, fakeFetch({}));
  assert.deepEqual(after.body.advisors.find((item) => item.id === "media").secrets, ["JELLYFIN_API_KEY"]);
});

test("a new tool stays off until the board accepts that name", async () => {
  const board = shelfEnv();
  const shown = await handle(
    authed("/api/cabinet/tools", {actor: "board", role: "chief", tools: ["status"], offered: ["install_jellyfin"]}),
    board,
    fakeFetch({})
  );
  assert.deepEqual(shown.body.advisors.find((item) => item.id === "chief").tools, [
    {name: "status", state: "off"},
    {name: "install_jellyfin", state: "off"},
  ]);
  const chat = await handle(
    authed("/api/cabinet/accept", {actor: "chat", role: "chief", tool: "status", confirmed: true}),
    board,
    fakeFetch({})
  );
  assert.equal(chat.body.reason, "actor_cannot_approve");
  const accepted = await handle(
    authed("/api/cabinet/accept", {actor: "board", role: "chief", tool: "status"}),
    board,
    fakeFetch({})
  );
  assert.equal(accepted.body.reason, "owner_accepted");
  assert.equal(accepted.body.started, false);
  const upgraded = await handle(
    authed("/api/cabinet/tools", {actor: "board", role: "chief", tools: ["status", "logs"]}),
    board,
    fakeFetch({})
  );
  assert.deepEqual(upgraded.body.advisors.find((item) => item.id === "chief").tools, [
    {name: "status", state: "on"},
    {name: "logs", state: "off"},
  ]);
  const chatTools = await handle(
    authed("/api/cabinet/tools", {actor: "chat", role: "chief", tools: ["other"]}),
    board,
    fakeFetch({})
  );
  assert.equal(chatTools.body.reason, "actor_cannot_approve");
  const kept = await handle(authed("/api/cabinet", {}, "GET"), board, fakeFetch({}));
  assert.deepEqual(kept.body.advisors.find((item) => item.id === "chief").tools, [
    {name: "status", state: "on"},
    {name: "logs", state: "off"},
  ]);
  await handle(
    authed("/api/cabinet/tools", {actor: "board", role: "chief", tools: ["status"], offered: ["install_jellyfin"]}),
    board,
    fakeFetch({})
  );
  const extra = await handle(
    authed("/api/cabinet/accept", {actor: "board", role: "chief", tool: "install_jellyfin"}),
    board,
    fakeFetch({})
  );
  assert.equal(extra.body.reason, "owner_accepted");
  const renamed = await handle(
    authed("/api/cabinet/tools", {actor: "board", role: "chief", tools: ["status"], offered: ["install_media"]}),
    board,
    fakeFetch({})
  );
  const tools = renamed.body.advisors.find((item) => item.id === "chief").tools;
  assert.deepEqual(tools, [
    {name: "status", state: "on"},
    {name: "install_media", state: "off"},
  ]);
  const denied = await handle(
    authed("/api/cabinet/tools", {actor: "board", role: "media", tools: ["play"], deny: ["play"]}),
    board,
    fakeFetch({})
  );
  assert.deepEqual(denied.body.advisors.find((item) => item.id === "media").tools, [
    {name: "play", state: "off"},
  ]);
  const still = await handle(
    authed("/api/cabinet/accept", {actor: "board", role: "media", tool: "play"}),
    board,
    fakeFetch({})
  );
  assert.equal(still.body.reason, "denied");
  assert.equal(JSON.stringify(board.shelf).includes("hunter22"), false);
  const broken = await handle(
    authed("/api/cabinet/tools", {actor: "board", role: "chief", tools: "status"}),
    board,
    fakeFetch({})
  );
  assert.equal(broken.body.reason, "tool_name");
  const stillListed = await handle(authed("/api/cabinet", {}, "GET"), board, fakeFetch({}));
  assert.deepEqual(stillListed.body.advisors.find((item) => item.id === "chief").tools, [
    {name: "status", state: "on"},
    {name: "install_media", state: "off"},
  ]);
  const omitted = await handle(
    authed("/api/cabinet/accept", {role: "chief", tool: "install_media", confirmed: true}),
    board,
    fakeFetch({})
  );
  assert.equal(omitted.body.reason, "actor_cannot_approve");
  assert.deepEqual(
    (await handle(authed("/api/cabinet", {}, "GET"), board, fakeFetch({}))).body.advisors.find((item) => item.id === "chief").tools,
    [
      {name: "status", state: "on"},
      {name: "install_media", state: "off"},
    ]
  );
});

test("an omitted actor stores nothing and the shelf stays off the environment", async () => {
  const board = {...env};
  const stored = await handle(
    authed("/api/cabinet/secret", {role: "media", name: "JELLYFIN_API_KEY", value: "hunter22", confirmed: true}),
    board,
    fakeFetch({})
  );
  assert.equal(stored.status, 403);
  assert.equal(stored.body.reason, "actor_cannot_approve");
  assert.equal(JSON.stringify(stored.body).includes("hunter22"), false);
  assert.equal(board.shelf, undefined);
  const named = await handle(
    authed("/api/cabinet/secret", {actor: "board", role: "media", name: "JELLYFIN_API_KEY", value: "hunter22"}),
    board,
    fakeFetch({})
  );
  assert.equal(named.body.reason, "name_only");
  assert.equal(board.shelf, undefined);
  const listed = await handle(authed("/api/cabinet", {}, "GET"), board, fakeFetch({}));
  assert.deepEqual(listed.body.advisors.find((item) => item.id === "media").secrets, ["JELLYFIN_API_KEY"]);
  assert.equal(JSON.stringify(listed.body).includes("hunter22"), false);
  assert.deepEqual(listed.body.advisors.map((item) => item.job_cap), [0, 0, 0, 0, 0, 0]);
});

test("an unauthenticated shelf call changes nothing", async () => {
  const board = shelfEnv();
  const refused = await handle(
    {method: "POST", path: "/api/cabinet/secret", headers: {}, body: {role: "cto", name: "CODER_TOKEN", value: "hunter22"}},
    board,
    fakeFetch({})
  );
  assert.equal(refused.status, 401);
  assert.equal(JSON.stringify(refused.body).includes("hunter22"), false);
  const listed = await handle(authed("/api/cabinet", {}, "GET"), board, fakeFetch({}));
  assert.deepEqual(listed.body.advisors.find((item) => item.id === "cto").secrets, []);
});

test("the page shows an update as not applied and stores no key", () => {
  const html = page();
  assert.equal(html.includes("No key is configured. Nothing is applied."), true);
  assert.equal(html.includes("No update has been checked."), true);
  assert.equal(html.includes("hunter22"), false);
  assert.equal(html.includes("BEGIN "), false);
});

test("the owner sees a signature that is not checked and not applied", async () => {
  const board = {...env};
  const digest = "ab".repeat(32);
  const before = await handle(authed("/api/updates", {}, "GET"), board, fakeFetch({}));
  assert.equal(before.body.reason, "no_update");
  assert.equal(before.body.reply, "No update has been checked.");
  assert.equal(before.body.applied, false);
  assert.equal(before.body.started, false);
  assert.equal(before.body.key_configured, false);
  const signature = "password is hunter22";
  const seen = await handle(
    authed("/api/updates", {
      actor: "board",
      signature,
      checksum: digest,
      filename: "friday-0.0.2-usb.img.xz",
      confirmed: true,
    }),
    board,
    fakeFetch({})
  );
  assert.equal(seen.status, 200);
  assert.equal(seen.body.reason, "signature_not_checked");
  assert.equal(seen.body.outcome, "refused");
  assert.equal(seen.body.applied, false);
  assert.equal(seen.body.started, false);
  assert.equal(seen.body.key_configured, false);
  assert.equal(JSON.stringify(seen.body).includes("hunter22"), false);
  assert.equal(JSON.stringify(seen.body).includes(signature), false);
  const listed = await handle(authed("/api/updates", {}, "GET"), board, fakeFetch({}));
  assert.equal(listed.body.reason, "signature_not_checked");
  assert.equal(JSON.stringify(listed.body).includes("hunter22"), false);
  const chat = await handle(
    authed("/api/updates", {actor: "chat", signature: "token=abcd", confirmed: true}),
    board,
    fakeFetch({})
  );
  assert.equal(chat.status, 403);
  assert.equal(chat.body.reason, "owner_must_see");
  assert.equal(chat.body.applied, false);
  assert.equal(JSON.stringify(chat.body).includes("abcd"), false);
  const kept = await handle(authed("/api/updates", {}, "GET"), board, fakeFetch({}));
  assert.equal(kept.body.reason, "signature_not_checked");
  const omitted = await handle(
    authed("/api/updates", {signature: "detached", confirmed: true}),
    board,
    fakeFetch({})
  );
  assert.equal(omitted.body.reason, "owner_must_see");
  assert.equal((await handle(authed("/api/updates", {}, "GET"), board, fakeFetch({}))).body.reason, "signature_not_checked");
  const blank = await handle(authed("/api/updates", {actor: "board", signature: ""}), board, fakeFetch({}));
  assert.equal(blank.body.reason, "unsigned");
  assert.equal(blank.body.applied, false);
});

test("a verifier that accepts the checksum line still applies nothing", async () => {
  const digest = "ab".repeat(32);
  const filename = "friday-0.0.2-usb.img.xz";
  const line = `${digest}  ${filename}\n`;
  const seen = [];
  const board = {
    ...env,
    updateVerifier(payload, signature) {
      seen.push([payload, signature]);
      return payload === line && signature === "detached";
    },
  };
  const chat = await handle(
    authed("/api/updates", {actor: "chat", signature: "detached", checksum: digest, filename}),
    board,
    fakeFetch({})
  );
  assert.equal(chat.body.reason, "owner_must_see");
  assert.deepEqual(seen, []);
  const missing = await handle(
    authed("/api/updates", {actor: "board", signature: "detached", checksum: "AB".repeat(32), filename}),
    board,
    fakeFetch({})
  );
  assert.equal(missing.body.reason, "checksum_missing");
  assert.equal(missing.body.applied, false);
  assert.deepEqual(seen, []);
  const rejected = await handle(
    authed("/api/updates", {actor: "board", signature: "other", checksum: digest, filename}),
    board,
    fakeFetch({})
  );
  assert.equal(rejected.body.reason, "signature_rejected");
  assert.equal(rejected.body.applied, false);
  const checked = await handle(
    authed("/api/updates", {actor: "board", signature: "detached", checksum: digest, filename, confirmed: true}),
    board,
    fakeFetch({})
  );
  assert.equal(checked.body.reason, "checked_not_applied");
  assert.equal(checked.body.outcome, "refused");
  assert.equal(checked.body.applied, false);
  assert.equal(checked.body.started, false);
  assert.equal(checked.body.key_configured, false);
  assert.equal(JSON.stringify(checked.body).includes("detached"), false);
  const broken = {
    ...env,
    updateVerifier() {
      throw new Error("no key");
    },
  };
  const failed = await handle(
    authed("/api/updates", {actor: "board", signature: "detached", checksum: digest, filename}),
    broken,
    fakeFetch({})
  );
  assert.equal(failed.body.reason, "signature_not_checked");
  assert.equal(failed.body.applied, false);
  const quiet = await handle(
    {method: "POST", path: "/api/updates", headers: {}, body: {actor: "board", signature: "detached"}},
    board,
    fakeFetch({})
  );
  assert.equal(quiet.status, 401);
  assert.equal((await handle(authed("/api/updates", {}, "GET"), board, fakeFetch({}))).body.reason, "checked_not_applied");
});

test("install stays closed", async () => {
  const result = await handle(
    {
      method: "POST",
      path: "/api/approve",
      headers: {"Friday-Board": "board-secret"},
      body: {action: "install", confirmed: true}
    },
    env,
    fakeFetch({
      "POST http://executor:8080/approvals": {
        status: 403,
        body: {outcome: "refused", reason: "catalog_install_closed", started: false},
        expect(options) {
          assert.equal(options.headers["Friday-Approval"], "approval-secret");
          assert.equal(JSON.parse(options.body).operation, "install");
        }
      }
    })
  );
  assert.equal(result.body.reason, "catalog_install_closed");
  assert.equal(result.body.reply, "Catalog install is closed.");
});

function catalogTree() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "friday-catalog-"));
  const write = (train, name, text) => {
    const dir = path.join(root, "ix-dev", train, name);
    fs.mkdirSync(dir, {recursive: true});
    if (text !== null) fs.writeFileSync(path.join(dir, "app.yaml"), text);
    return dir;
  };
  write("stable", "jellyfin", "token: AKIA_NOT_A_REAL_KEY\n");
  write("community", "custom", "name: custom\n");
  write("enterprise", "hidden", "name: hidden\n");
  write("stable", "bare", null);
  const outside = path.join(root, "outside");
  fs.mkdirSync(outside);
  fs.writeFileSync(path.join(outside, "app.yaml"), "name: outside\n");
  fs.symlinkSync(outside, path.join(root, "ix-dev", "stable", "escape"));
  return root;
}

test("the page says discover does not install", () => {
  const html = page();
  assert.equal(html.includes("Discover"), true);
  assert.equal(html.includes("Install stays closed."), true);
  assert.equal(html.includes("AKIA_NOT_A_REAL_KEY"), false);
});

test("discover lists packed names and does not read the files", async () => {
  const root = catalogTree();
  try {
    const quiet = await handle(
      {method: "GET", path: "/api/discover", headers: {}, body: {}},
      {...env, CATALOG_ROOT: root},
      fakeFetch({})
    );
    assert.equal(quiet.status, 401);
    const listed = await handle(
      authed("/api/discover", {}, "GET"),
      {...env, CATALOG_ROOT: root},
      fakeFetch({})
    );
    assert.equal(listed.status, 200);
    assert.equal(listed.body.outcome, "listed");
    assert.equal(listed.body.reason, "listed");
    assert.equal(listed.body.install, "closed");
    assert.equal(listed.body.started, false);
    assert.deepEqual(listed.body.rows, [
      {name: "jellyfin", train: "stable", install: "refused"},
      {name: "custom", train: "community", install: "refused"},
    ]);
    assert.equal(JSON.stringify(listed.body).includes("AKIA_NOT_A_REAL_KEY"), false);
    assert.equal(JSON.stringify(listed.body).includes("hidden"), false);
    assert.equal(JSON.stringify(listed.body).includes("escape"), false);
  } finally {
    fs.rmSync(root, {recursive: true, force: true});
  }
});

test("a missing catalog lists nothing and install does not call the executor", async () => {
  const missing = await handle(authed("/api/discover", {}, "GET"), env, fakeFetch({}));
  assert.equal(missing.body.reason, "catalog_missing");
  assert.deepEqual(missing.body.rows, []);
  assert.equal(missing.body.install, "closed");
  assert.equal(missing.body.started, false);
  const link = fs.mkdtempSync(path.join(os.tmpdir(), "friday-catalog-link-"));
  const target = path.join(link, "real");
  fs.mkdirSync(target);
  const alias = path.join(link, "alias");
  fs.symlinkSync(target, alias);
  try {
    const refused = await handle(
      authed("/api/discover", {}, "GET"),
      {...env, CATALOG_ROOT: alias},
      fakeFetch({})
    );
    assert.equal(refused.body.reason, "catalog_missing");
    assert.deepEqual(refused.body.rows, []);
  } finally {
    fs.rmSync(link, {recursive: true, force: true});
  }
  const install = await handle(
    authed("/api/discover/install", {name: "jellyfin", confirmed: true}),
    {...env, CATALOG_ROOT: "/no/such/catalog"},
    fakeFetch({})
  );
  assert.equal(install.status, 403);
  assert.equal(install.body.reason, "catalog_install_closed");
  assert.equal(install.body.reply, "Catalog install is closed.");
  assert.equal(install.body.started, false);
  assert.equal(JSON.stringify(install.body).includes("jellyfin"), false);
});

test("the page lists fixed sentences and does not show the body", () => {
  const html = page();
  assert.equal(html.includes("Events"), true);
  assert.equal(html.includes("The raw body is not shown."), true);
  assert.equal(html.includes("Nothing is sent."), true);
  assert.equal(html.includes("hunter22"), false);
});

test("the board reads Friday's sentences and drops the body", async () => {
  const quiet = await handle(
    {method: "GET", path: "/api/events", headers: {}, body: {}},
    env,
    fakeFetch({})
  );
  assert.equal(quiet.status, 401);
  let seen;
  const listed = await handle(
    authed("/api/events", {confirmed: true, body: "password is hunter22"}, "GET"),
    env,
    fakeFetch({
      "GET http://friday:8080/announcements": {
        status: 200,
        body: {
          outcome: "ok",
          reason: "announced",
          started: true,
          sent: true,
          announcements: [
            {
              source: "radarr",
              event_type: "grab",
              announcement: "A download was grabbed.",
              body: "password is hunter22",
              movie: "Inception",
            },
            {
              source: "radarr",
              event_type: "grab",
              announcement: "downloading",
            },
            {
              source: "postgres",
              event_type: "health",
              announcement: "An app health state changed.",
            },
            {
              source: "sonarr",
              event_type: "failure",
              announcement: "A download failed.",
              token: "notify-secret",
            },
          ],
        },
        expect(options) {
          seen = options;
          assert.equal(options.body, undefined);
          assert.equal(options.headers["Friday-Notify"], "notify-secret");
          assert.equal(options.headers["Friday-Approval"], undefined);
        }
      }
    })
  );
  assert.equal(listed.status, 200);
  assert.equal(listed.body.started, false);
  assert.equal(listed.body.sent, false);
  assert.equal(listed.body.events.length, 2);
  assert.equal(listed.body.events[0].announcement, "A download was grabbed.");
  assert.equal(listed.body.events[1].source, "sonarr");
  assert.equal(listed.body.events[0].body, undefined);
  assert.equal(JSON.stringify(listed.body).includes("hunter22"), false);
  assert.equal(JSON.stringify(listed.body).includes("Inception"), false);
  assert.equal(JSON.stringify(listed.body).includes("downloading"), false);
  assert.equal(JSON.stringify(listed.body).includes("notify-secret"), false);
  assert.equal(seen.method, "GET");
  const posted = await handle(
    authed("/api/events", {announcement: "A download was grabbed.", body: "password is hunter22"}),
    env,
    fakeFetch({})
  );
  assert.equal(posted.status, 405);
  assert.equal(posted.body.reason, "method_refused");
  assert.equal(posted.body.sent, false);
  assert.equal(JSON.stringify(posted.body).includes("hunter22"), false);
});

test("the page lists goals and does not start them", () => {
  const html = page();
  assert.equal(html.includes("Tasks"), true);
  assert.equal(html.includes("Nothing here starts them."), true);
  assert.equal(html.includes("hunter22"), false);
});

test("the board lists this owner's goals and drops a credential", async () => {
  const quiet = await handle(
    {method: "GET", path: "/api/tasks", headers: {}, body: {}},
    env,
    fakeFetch({})
  );
  assert.equal(quiet.status, 401);
  let seen;
  const listed = await handle(
    authed("/api/tasks", {confirmed: true}, "GET"),
    env,
    fakeFetch({
      "GET http://executor:8080/tasks": {
        status: 200,
        body: {
          outcome: "ok",
          reason: "tasks",
          started: true,
          tasks: [
            {
              id: "task-1",
              state: "waiting",
              role: "chief",
              goal: "Book Tuesday",
              steps: [{name: "pay", state: "pending"}],
              token: "notify-secret",
            },
            {id: "task-2", state: "waiting", role: "friday", goal: "password is hunter22"},
            {id: "task-3", state: "ready", role: "friday", goal: "password%20is%20hunter22"},
          ],
        },
        expect(options) {
          seen = options;
          assert.equal(options.body, undefined);
          assert.equal(options.headers["Friday-Approval"], "approval-secret");
          assert.equal(options.headers["Friday-Owner"], "owner-1");
          assert.equal(options.headers["Friday-Notify"], undefined);
        }
      }
    })
  );
  assert.equal(listed.status, 200);
  assert.equal(listed.body.started, false);
  assert.equal(listed.body.tasks.length, 1);
  assert.equal(listed.body.tasks[0].goal, "Book Tuesday");
  assert.equal(listed.body.tasks[0].state, "waiting");
  assert.equal(listed.body.tasks[0].token, undefined);
  assert.equal(JSON.stringify(listed.body).includes("hunter22"), false);
  assert.equal(JSON.stringify(listed.body).includes("notify-secret"), false);
  assert.equal(seen.method, "GET");
});

test("the page lists inactive charters and does not copy a file", () => {
  const html = page();
  assert.equal(html.includes("Inactive charters"), true);
  assert.equal(html.includes("The file is not copied."), true);
  assert.equal(html.includes("Job cap stays 0."), true);
  assert.equal(html.includes("/api/charters"), true);
  assert.equal(html.includes("enable_role"), false);
  assert.equal(html.includes("hunter22"), false);
});

test("the board records one inactive charter and copies nothing", async () => {
  const board = {...env};
  const quiet = await handle({method: "GET", path: "/api/charters", headers: {}, body: {}}, board, fakeFetch({}));
  assert.equal(quiet.status, 401);
  const listed = await handle(authed("/api/charters", {}, "GET"), board, fakeFetch({}));
  assert.equal(listed.status, 200);
  assert.equal(listed.body.started, false);
  assert.equal(listed.body.copied, false);
  assert.equal(listed.body.job_cap, 0);
  assert.equal(listed.body.roles.find((item) => item.id === "health").state, "inactive");
  assert.equal(listed.body.roles.find((item) => item.id === "family").state, "blocked");
  assert.equal(listed.body.roles.some((item) => item.id === "chief"), false);
  const recorded = await handle(
    authed("/api/charters", {actor: "board", role: "health", confirmed: true}),
    board,
    fakeFetch({})
  );
  assert.equal(recorded.status, 200);
  assert.equal(recorded.body.reason, "not_copied");
  assert.equal(recorded.body.role, "health");
  assert.equal(recorded.body.target, "full/health.md");
  assert.equal(recorded.body.copied, false);
  assert.equal(recorded.body.linked, false);
  assert.equal(recorded.body.started, false);
  assert.equal(recorded.body.created, false);
  assert.equal(recorded.body.job_cap, 0);
  const chat = await handle(
    authed("/api/charters", {actor: "chat", role: "researcher", confirmed: true}),
    board,
    fakeFetch({})
  );
  assert.equal(chat.status, 403);
  assert.equal(chat.body.reason, "board_only");
  assert.equal(chat.body.role, "");
  const again = await handle(
    authed("/api/charters", {actor: "board", role: "health", target: "full/legal.md", confirmed: true}),
    board,
    fakeFetch({})
  );
  assert.equal(again.body.reason, "already");
  assert.equal(again.body.target, "full/health.md");
  const family = await handle(authed("/api/charters", {actor: "board", role: "family"}), board, fakeFetch({}));
  assert.equal(family.status, 403);
  assert.equal(family.body.reason, "family_blocked");
  const starter = await handle(authed("/api/charters", {actor: "board", role: "chief"}), board, fakeFetch({}));
  assert.equal(starter.body.reason, "already_active");
  const absolute = await handle(
    authed("/api/charters", {actor: "board", role: "legal", target: "/soul/agents/full/legal.md"}),
    board,
    fakeFetch({})
  );
  assert.equal(absolute.body.reason, "absolute_path");
  assert.equal(absolute.body.target, "");
  const mount = await handle(
    authed("/api/charters", {actor: "board", role: "legal", mount: "./charters/full"}),
    board,
    fakeFetch({})
  );
  assert.equal(mount.body.reason, "drops_starter_set");
  const secret = "password is hunter22";
  const hidden = await handle(
    authed("/api/charters", {actor: "board", role: secret, confirmed: true}),
    board,
    fakeFetch({})
  );
  assert.equal(hidden.body.reason, "credential");
  assert.equal(hidden.body.role, "");
  assert.equal(JSON.stringify(hidden.body).includes("hunter22"), false);
  const after = await handle(authed("/api/charters", {}, "GET"), board, fakeFetch({}));
  assert.equal(after.body.roles.find((item) => item.id === "health").state, "recorded");
  assert.equal(after.body.roles.find((item) => item.id === "legal").state, "inactive");
  assert.equal(after.body.roles.find((item) => item.id === "family").state, "blocked");
  assert.equal(JSON.stringify(after.body).includes("hunter22"), false);
  assert.equal(JSON.stringify(after.body).includes(secret), false);
});

test("the page shows room before an install button and does not stop anything", () => {
  const html = page();
  assert.equal(html.includes("These numbers are not a hardware measurement."), true);
  assert.equal(html.includes("Nothing here is stopped or pulled."), true);
  assert.equal(html.includes("An install button is not offered."), true);
  assert.equal(html.includes("measure/ram"), false);
  assert.equal(html.includes("room_for"), false);
});

test("room uses supplied numbers and does not stop or pull", async () => {
  const quiet = await handle(
    {method: "POST", path: "/api/room", headers: {}, body: {actor: "board", declared: 100, free: 100}},
    env,
    fakeFetch({})
  );
  assert.equal(quiet.status, 401);
  const chat = await handle(
    authed("/api/room", {actor: "chat", declared: 250, free: 100, running: [{id: "token=abcd", declared: 300}]}),
    env,
    fakeFetch({})
  );
  assert.equal(chat.status, 403);
  assert.equal(chat.body.reason, "actor_cannot_approve");
  assert.equal(chat.body.stopped, false);
  assert.equal(chat.body.pulled, false);
  assert.equal(chat.body.offered, false);
  assert.equal(JSON.stringify(chat.body).includes("abcd"), false);
  const fits = await handle(
    authed("/api/room", {actor: "board", declared: 100, free: 100, running: "not-a-list", confirmed: true}),
    env,
    fakeFetch({})
  );
  assert.equal(fits.status, 200);
  assert.equal(fits.body.reason, "within_free_ram");
  assert.equal(fits.body.which, null);
  assert.equal(fits.body.stopped, false);
  assert.equal(fits.body.pulled, false);
  assert.equal(fits.body.offered, false);
  assert.equal(fits.body.said.includes("not a hardware measurement"), true);
  assert.equal(fits.body.said.includes("Declared 100"), true);
  const named = await handle(
    authed("/api/room", {
      actor: "board",
      declared: 250,
      free: 100,
      running: [
        {id: "plex", declared: 400},
        {id: "jellyfin", declared: 150},
        {id: "sonarr", declared: 80},
      ],
      confirmed: true,
    }),
    env,
    fakeFetch({})
  );
  assert.equal(named.body.reason, "stop_other");
  assert.equal(named.body.which, "jellyfin");
  assert.equal(named.body.said.startsWith("Stop jellyfin."), true);
  assert.equal(named.body.stopped, false);
  assert.equal(named.body.pulled, false);
  assert.equal(named.body.offered, false);
  const tie = await handle(
    authed("/api/room", {
      actor: "board",
      declared: 200,
      free: 50,
      running: [{app_id: "sonarr", declared: 200}, {app_id: "plex", declared: 200}],
    }),
    env,
    fakeFetch({})
  );
  assert.equal(tie.body.which, "plex");
  const core = await handle(
    authed("/api/room", {
      actor: "board",
      declared: 500,
      free: 100,
      running: [
        {id: "postgres", declared: 900, core: false},
        {id: "Plex", declared: 400, core: true},
        {id: "gateway", declared: 900},
      ],
    }),
    env,
    fakeFetch({})
  );
  assert.equal(core.body.reason, "machine_larger");
  assert.equal(core.body.which, null);
  assert.equal(core.body.said.includes("postgres"), false);
  assert.equal(core.body.said.includes("Plex"), false);
  assert.equal(core.body.stopped, false);
  const own = await handle(
    authed("/api/room", {
      actor: "board",
      declared: 300,
      free: 100,
      app_id: "plex",
      running: [{id: "plex", declared: 400}, {id: "radarr", declared: 50}],
    }),
    env,
    fakeFetch({})
  );
  assert.equal(own.body.reason, "machine_larger");
  const flag = await handle(
    authed("/api/room", {
      actor: "board",
      declared: 200,
      free: 50,
      running: [
        {id: "jellyfin", declared: 300, core: "yes"},
        {id: "sonarr", declared: 200, core: false},
      ],
    }),
    env,
    fakeFetch({})
  );
  assert.equal(flag.body.which, "sonarr");
  assert.equal(flag.body.said.includes("jellyfin"), false);
  const kept = await handle(
    authed("/api/room", {
      actor: "board",
      declared: 200,
      free: 50,
      running: [{id: "The password is kept outside the machine", declared: 300}],
    }),
    env,
    fakeFetch({})
  );
  assert.equal(kept.body.which, "The password is kept outside the machine");
  const secret = await handle(
    authed("/api/room", {
      actor: "board",
      declared: 200,
      free: 50,
      running: [{id: "token=abcd", declared: 300}, {id: "sonarr", declared: 200}],
    }),
    env,
    fakeFetch({})
  );
  assert.equal(secret.status, 403);
  assert.equal(secret.body.reason, "credential");
  assert.equal(secret.body.which, null);
  assert.equal(secret.body.said, "");
  assert.equal(JSON.stringify(secret.body).includes("abcd"), false);
  const encoded = await handle(
    authed("/api/room", {
      actor: "board",
      declared: 200,
      free: 50,
      app_id: "token%3Dabcd",
    }),
    env,
    fakeFetch({})
  );
  assert.equal(encoded.body.reason, "credential");
  assert.equal(JSON.stringify(encoded.body).includes("abcd"), false);
  const duplicate = await handle(
    authed("/api/room", {
      actor: "board",
      declared: 200,
      free: 10,
      running: [{id: "plex", declared: 300}, {id: "Plex", declared: 300}],
    }),
    env,
    fakeFetch({})
  );
  assert.equal(duplicate.body.reason, "duplicate_app");
  assert.equal(duplicate.body.which, null);
  const bad = await handle(
    authed("/api/room", {actor: "board", declared: true, free: 10}),
    env,
    fakeFetch({})
  );
  assert.equal(bad.body.reason, "ram_does_not_fit");
  assert.equal(bad.body.said, "");
});

test("an install that does not fit is not offered and does not call the executor", async () => {
  const tight = await handle(
    authed("/api/discover/install", {
      actor: "board",
      name: "jellyfin",
      declared: 250,
      free: 100,
      app_id: "jellyfin",
      running: [{id: "plex", declared: 400}],
      confirmed: true,
    }),
    env,
    fakeFetch({})
  );
  assert.equal(tight.body.reason, "stop_other");
  assert.equal(tight.body.which, "plex");
  assert.equal(tight.body.offered, false);
  assert.equal(tight.body.stopped, false);
  assert.equal(tight.body.pulled, false);
  assert.equal(JSON.stringify(tight.body).includes("jellyfin"), false);
  const closed = await handle(
    authed("/api/discover/install", {
      actor: "board",
      name: "jellyfin",
      declared: 100,
      free: 100,
      confirmed: true,
    }),
    env,
    fakeFetch({})
  );
  assert.equal(closed.status, 403);
  assert.equal(closed.body.reason, "catalog_install_closed");
  assert.equal(closed.body.reply, "Catalog install is closed.");
  assert.equal(closed.body.offered, false);
  assert.equal(JSON.stringify(closed.body).includes("jellyfin"), false);
  const approval = await handle(
    authed("/api/approve", {action: "install", declared: 400, free: 100, confirmed: true}),
    env,
    fakeFetch({})
  );
  assert.equal(approval.body.reason, "machine_larger");
  assert.equal(approval.body.offered, false);
  assert.equal(approval.body.stopped, false);
  assert.equal(approval.body.pulled, false);
});

test("a grant keeps unaccepted tools out of the prompt and calls nothing", async () => {
  const html = page();
  assert.equal(html.includes('id="connections"'), true);
  assert.equal(html.includes("Nothing is called."), true);
  assert.equal(html.includes("MCP_TOKEN"), false);
  assert.equal(html.includes("MCP_SECRET_REF"), false);
  const board = {
    BOARD_PASSWORD: "board-secret",
    FRIDAY_NOTIFY_TOKEN: "notify-secret",
    BOARD_APPROVAL_TOKEN: "approval-secret",
    FRIDAY_URL: "http://friday:8080",
    EXECUTOR_URL: "http://executor:8080",
    OWNER_ID: "owner-1",
  };
  const server = "https://peer.example/mcp";
  const recorded = await handle(
    authed("/api/grants", {
      actor: "board",
      server,
      role: "cto",
      secret_ref: "HARNESS_REF",
      tools: ["recall", "status"],
      secret: "The password is kept outside the machine",
      confirmed: true,
    }),
    board,
    fakeFetch({})
  );
  assert.equal(recorded.status, 200);
  assert.equal(recorded.body.reason, "prompt");
  assert.equal(recorded.body.server, server);
  assert.equal(recorded.body.role, "cto");
  assert.equal(recorded.body.secret_ref, "HARNESS_REF");
  assert.deepEqual(recorded.body.prompt, []);
  assert.equal(recorded.body.started, false);
  assert.equal(recorded.body.called, false);
  assert.equal(JSON.stringify(recorded.body).includes("kept outside"), false);
  const loop = await handle(
    authed("/api/grants", {actor: "board", server: "https://127.0.0.1/mcp", role: "cto", secret_ref: "HARNESS_REF", tools: ["recall"]}),
    board,
    fakeFetch({})
  );
  assert.equal(loop.body.reason, "loopback");
  assert.equal(loop.body.started, false);
  const secret = await handle(
    authed("/api/grants", {actor: "board", server, role: "cto", secret_ref: "HARNESS_REF", tools: ["recall"], value: "token=abcd"}),
    board,
    fakeFetch({})
  );
  assert.equal(secret.body.reason, "credential");
  assert.equal(JSON.stringify(secret.body).includes("abcd"), false);
  const blank = await handle(
    authed("/api/grants", {
      actor: "board",
      server,
      role: "cto",
      secret_ref: "HARNESS_REF",
      tools: ["recall"],
      secret: "",
      value: "token=abcd",
    }),
    board,
    fakeFetch({})
  );
  assert.equal(blank.body.reason, "credential");
  assert.equal(JSON.stringify(blank.body).includes("abcd"), false);
  const extra = await handle(
    authed("/api/grants", {
      actor: "board",
      server: "https://extra.example/mcp",
      role: "cto",
      secret_ref: "HARNESS_REF",
      tools: ["recall"],
      secret: "",
      value: "hello",
    }),
    board,
    fakeFetch({})
  );
  assert.equal(extra.body.reason, "caller_value");
  const chat = await handle(
    authed("/api/grants", {actor: "chat", server: "https://other.example/mcp", role: "media", secret_ref: "OTHER_REF", tools: ["status"], confirmed: true}),
    board,
    fakeFetch({})
  );
  assert.equal(chat.status, 403);
  assert.equal(chat.body.reason, "actor_cannot_approve");
  const kept = await handle(
    authed("/api/grants", {actor: "board", server, role: "media", secret_ref: "OTHER_REF", tools: ["status"]}),
    board,
    fakeFetch({})
  );
  assert.equal(kept.body.reason, "kept");
  assert.equal(kept.body.role, "cto");
  assert.equal(kept.body.secret_ref, "HARNESS_REF");
  assert.deepEqual(kept.body.prompt, []);
  const accepted = await handle(
    authed("/api/grants/accept", {actor: "board", server, tool: "recall", confirmed: true}),
    board,
    fakeFetch({})
  );
  assert.equal(accepted.status, 200);
  assert.equal(accepted.body.reason, "owner_accepted");
  assert.deepEqual(accepted.body.prompt, ["recall"]);
  assert.equal(accepted.body.called, false);
  const other = await handle(
    authed("/api/grants/accept", {actor: "board", server, tool: "send"}),
    board,
    fakeFetch({})
  );
  assert.equal(other.body.reason, "not_offered");
  assert.deepEqual(other.body.prompt, ["recall"]);
  const listed = await handle(authed("/api/grants", {}, "GET"), board, fakeFetch({}));
  assert.equal(listed.body.grants.length, 1);
  assert.deepEqual(listed.body.grants[0].prompt, ["recall"]);
  assert.equal(listed.body.grants[0].tools.find((item) => item.name === "status").state, "off");
  assert.equal(JSON.stringify(listed.body).includes("abcd"), false);
});

test("the board exchanges one life step and does not send it", async () => {
  const html = page();
  assert.equal(html.includes("Exchange once"), true);
  assert.equal(html.includes("approval-secret"), false);
  const id = "11111111-1111-4111-8111-111111111111";
  const operation = "22222222-2222-4222-8222-222222222222";
  const digest = "ab".repeat(32);
  const target = "sam@example.com";
  let seen = 0;
  const exchanged = await handle(
    authed("/api/exchange", {
      actor: "board",
      action: "send",
      approval_id: id,
      target,
      payload_digest: digest,
      confirmed: true,
      secret: "The password is kept outside the machine",
    }),
    env,
    fakeFetch({
      "POST http://executor:8080/exchange": {
        status: 200,
        body: {
          outcome: "exchanged",
          reason: "exchanged",
          approval_id: id,
          operation_id: operation,
          started: true,
        },
        expect(options) {
          seen += 1;
          assert.equal(options.headers["Friday-Approval"], "approval-secret");
          const payload = JSON.parse(options.body);
          assert.equal(payload.actor, "board");
          assert.equal(payload.action, "send");
          assert.equal(payload.owner_id, "owner-1");
          assert.equal(payload.approval_id, id);
          assert.equal(payload.confirmed, undefined);
          assert.equal(payload.secret, undefined);
          assert.equal(payload.body.action_class, "send");
          assert.equal(payload.body.target, target);
          assert.equal(payload.body.payload_digest, digest);
        },
      },
    })
  );
  assert.equal(seen, 1);
  assert.equal(exchanged.status, 200);
  assert.equal(exchanged.body.outcome, "exchanged");
  assert.equal(exchanged.body.reason, "exchanged");
  assert.equal(exchanged.body.approval_id, id);
  assert.equal(exchanged.body.operation_id, operation);
  assert.equal(exchanged.body.started, false);
  assert.equal(exchanged.body.sent, false);
  assert.equal(exchanged.body.changed, false);
  assert.equal(exchanged.body.reply, "Exchanged on the Board. Nothing was sent.");
  assert.equal(JSON.stringify(exchanged.body).includes(target), false);
  const again = await handle(
    authed("/api/exchange", {
      actor: "board",
      action: "send",
      approval_id: id,
      target,
      payload_digest: digest,
    }),
    env,
    fakeFetch({
      "POST http://executor:8080/exchange": {
        status: 200,
        body: {
          outcome: "exchanged",
          reason: "already_exchanged",
          approval_id: id,
          operation_id: operation,
          started: false,
        },
      },
    })
  );
  assert.equal(again.body.reason, "already_exchanged");
  assert.equal(again.body.operation_id, operation);
  assert.equal(again.body.sent, false);
  assert.equal(again.body.reply, "Exchanged on the Board. Nothing was sent.");
  const chat = await handle(
    authed("/api/exchange", {
      actor: "chat",
      action: "pay",
      approval_id: id,
      target,
      payload_digest: digest,
      confirmed: true,
    }),
    env,
    fakeFetch({})
  );
  assert.equal(chat.status, 403);
  assert.equal(chat.body.reason, "actor_cannot_exchange");
  assert.equal(chat.body.sent, false);
  const quiet = await handle(
    {
      method: "POST",
      path: "/api/exchange",
      headers: {},
      body: {actor: "board", action: "send", approval_id: id, target, payload_digest: digest},
    },
    env,
    fakeFetch({})
  );
  assert.equal(quiet.status, 401);
  const install = await handle(
    authed("/api/exchange", {
      actor: "board",
      action: "install",
      approval_id: id,
      target,
      payload_digest: digest,
      confirmed: true,
    }),
    env,
    fakeFetch({})
  );
  assert.equal(install.status, 403);
  assert.equal(install.body.reason, "catalog_install_closed");
  assert.equal(install.body.reply, "Catalog install is closed.");
  assert.equal(install.body.sent, false);
  const start = await handle(
    authed("/api/exchange", {
      actor: "board",
      action: "start",
      approval_id: id,
      target,
      payload_digest: digest,
    }),
    env,
    fakeFetch({})
  );
  assert.equal(start.body.reason, "not_a_life_step");
  assert.equal(start.body.started, false);
  const shaped = await handle(
    authed("/api/exchange", {
      actor: "board",
      action: "send",
      approval_id: id,
      target: "password is hunter22",
      payload_digest: digest,
    }),
    env,
    fakeFetch({})
  );
  assert.equal(shaped.body.reason, "credential");
  assert.equal(JSON.stringify(shaped.body).includes("hunter22"), false);
  const extra = await handle(
    authed("/api/exchange", {
      actor: "board",
      action: "send",
      approval_id: id,
      target,
      payload_digest: digest,
      value: "token=abcd",
    }),
    env,
    fakeFetch({})
  );
  assert.equal(extra.body.reason, "credential");
  assert.equal(JSON.stringify(extra.body).includes("abcd"), false);
});

test("the board records one backup manifest and does not copy", async () => {
  const html = page();
  const section = html.split('id="backup"')[1].split('id="updates"')[0];
  assert.equal(section.includes("Record the manifest"), true);
  assert.equal(section.includes("Nothing is copied"), true);
  assert.equal(section.includes('type="password"'), false);
  assert.equal(section.includes("passphrase"), true);
  assert.equal(html.includes("approval-secret"), false);
  const pause = "11111111-1111-4111-8111-111111111111";
  const manifest = "22222222-2222-4222-8222-222222222222";
  const digest = "ab".repeat(32);
  let seen;
  const recorded = await handle(
    authed("/api/backup", {
      actor: "board",
      pause_id: pause,
      sqlite_method: "backup_api",
      app_id: "notes",
      mark: "managed",
    }),
    env,
    fakeFetch({
      "POST http://executor:8080/backup": {
        status: 200,
        body: {
          outcome: "manifested",
          reason: "stored",
          manifest_id: manifest,
          copied: false,
          started: false,
        },
        expect(options) {
          seen = JSON.parse(options.body);
          assert.equal(options.headers["Friday-Approval"], "approval-secret");
          assert.equal(options.headers["Friday-Notify"], undefined);
        },
      },
    })
  );
  assert.equal(recorded.status, 200);
  assert.equal(recorded.body.outcome, "manifested");
  assert.equal(recorded.body.reason, "stored");
  assert.equal(recorded.body.manifest_id, manifest);
  assert.equal(recorded.body.copied, false);
  assert.equal(recorded.body.started, false);
  assert.equal(recorded.body.reply, "Recorded. Nothing was copied.");
  assert.equal(seen.actor, "board");
  assert.equal(seen.pause_id, pause);
  assert.equal(seen.sqlite_method, "backup_api");
  assert.deepEqual(seen.registry, [{id: "notes", mark: "managed"}]);
  assert.equal(seen.passphrase, undefined);
  assert.equal(seen.app_id, undefined);
  const again = await handle(
    authed("/api/backup", {
      actor: "board",
      pause_id: pause,
      sqlite_method: "backup_api",
      app_id: "notes",
      mark: "managed",
    }),
    env,
    fakeFetch({
      "POST http://executor:8080/backup": {
        status: 200,
        body: {
          outcome: "manifested",
          reason: "already_stored",
          manifest_id: manifest,
          copied: false,
          started: false,
        },
      },
    })
  );
  assert.equal(again.body.reason, "already_stored");
  assert.equal(again.body.manifest_id, manifest);
  assert.equal(again.body.copied, false);
  const chat = await handle(
    authed("/api/backup", {
      actor: "friday",
      pause_id: pause,
      sqlite_method: "backup_api",
      app_id: "notes",
      mark: "managed",
    }),
    env,
    fakeFetch({})
  );
  assert.equal(chat.status, 403);
  assert.equal(chat.body.reason, "actor_cannot_backup");
  assert.equal(chat.body.copied, false);
  const leaked = await handle(
    authed("/api/backup", {
      actor: "board",
      pause_id: pause,
      sqlite_method: "backup_api",
      app_id: "notes",
      mark: "managed",
      passphrase: "password is hunter22",
    }),
    env,
    fakeFetch({})
  );
  assert.equal(leaked.body.reason, "passphrase_in_manifest");
  assert.equal(JSON.stringify(leaked.body).includes("hunter22"), false);
  const live = await handle(
    authed("/api/backup", {
      actor: "board",
      pause_id: pause,
      sqlite_method: "live_file",
      app_id: "notes",
      mark: "managed",
    }),
    env,
    fakeFetch({})
  );
  assert.equal(live.body.reason, "live_sqlite");
  const movies = await handle(
    authed("/api/backup", {
      actor: "board",
      pause_id: pause,
      sqlite_method: "backup_api",
      app_id: "movies",
      mark: "managed",
    }),
    env,
    fakeFetch({})
  );
  assert.equal(movies.body.reason, "optional_app_excluded");
  const install = await handle(
    authed("/api/backup", {
      actor: "board",
      action: "install",
      pause_id: pause,
      sqlite_method: "backup_api",
      app_id: "notes",
      mark: "managed",
    }),
    env,
    fakeFetch({})
  );
  assert.equal(install.body.reason, "catalog_install_closed");
  const machine = await handle(
    authed("/api/exchange", {
      actor: "board",
      action: "backup",
      approval_id: pause,
      target: "notes",
      payload_digest: digest,
    }),
    env,
    fakeFetch({})
  );
  assert.equal(machine.body.reason, "not_a_life_step");
  assert.equal(machine.body.started, false);
  assert.equal(machine.body.sent, false);
});

function soulEnv(token = "apply-token-ok") {
  return {...env, SOUL_APPLY_TOKEN: token};
}

test("the character page offers a proposal and does not embed the token", () => {
  const html = page();
  assert.equal(html.includes('id="character"'), true);
  assert.equal(html.includes("The file is not written."), true);
  assert.equal(html.includes('fetch("/api/soul"'), true);
  assert.equal(html.includes("board-secret"), false);
  assert.equal(html.includes("apply-token-ok"), false);
  assert.equal(html.includes("SOUL_APPLY_TOKEN"), false);
  assert.equal(html.includes("record_proposal"), false);
  assert.equal(html.includes("memoryd.soul"), false);
});

test("the board records one character proposal and keeps the file unwritten", async () => {
  const local = soulEnv();
  const anonymous = await handle({method: "GET", path: "/api/soul", headers: {}, body: {}}, local, fakeFetch({}));
  assert.equal(anonymous.status, 401);
  assert.equal(JSON.stringify(anonymous.body).includes("apply-token-ok"), false);
  for (const actor of ["chat", "friday"]) {
    const refused = await handle(
      authed("/api/soul", {actor, name: "SOUL.md", text: "A public line.", confirmed: true}),
      local,
      fakeFetch({})
    );
    assert.equal(refused.status, 403);
    assert.equal(refused.body.reason, "board_only");
    assert.equal(refused.body.files_written, false);
  }
  for (const name of ["../SOUL.md", "notes.md", "soul/SOUL.md"]) {
    const refused = await handle(
      authed("/api/soul", {actor: "board", name, text: "A public line."}),
      local,
      fakeFetch({})
    );
    assert.equal(refused.body.reason, "not_a_soul_file");
  }
  const blank = await handle(
    authed("/api/soul", {actor: "board", name: "SOUL.md", text: "   "}),
    local,
    fakeFetch({})
  );
  assert.equal(blank.body.reason, "empty");
  const allowed = "The password is kept outside the machine";
  for (const text of ["password is hunter22", "password%20is%20hunter22", "password+is+hunter22"]) {
    const leaked = await handle(
      authed("/api/soul", {actor: "board", name: "SOUL.md", text}),
      local,
      fakeFetch({})
    );
    assert.equal(leaked.body.reason, "credential");
    assert.equal(JSON.stringify(leaked.body).includes("hunter22"), false);
  }
  const recorded = await handle(
    authed("/api/soul", {actor: "board", name: "SOUL.md", text: allowed, confirmed: true, weekly: true}),
    local,
    fakeFetch({})
  );
  assert.equal(recorded.status, 200);
  assert.equal(recorded.body.reason, "proposal");
  assert.equal(recorded.body.files_written, false);
  assert.equal(recorded.body.example_read, false);
  assert.equal(recorded.body.token_stored, false);
  assert.equal(recorded.body.scheduled, false);
  assert.match(recorded.body.path, /^soul\/proposals\/[0-9a-f]{32}\.md$/);
  assert.equal(recorded.body.path.includes(".."), false);
  assert.equal(path.isAbsolute(recorded.body.path), false);
  const again = await handle(
    authed("/api/soul", {actor: "board", name: "SOUL.md", text: "A second open line."}),
    local,
    fakeFetch({})
  );
  assert.equal(again.status, 403);
  assert.equal(again.body.reason, "proposal_open");
  const chapter = await handle(
    authed("/api/soul", {actor: "board", name: "CHAPTER.md", text: "A chapter line."}),
    local,
    fakeFetch({})
  );
  assert.equal(chapter.status, 200);
  assert.equal(chapter.body.reason, "proposal");
  const listed = await handle(authed("/api/soul", {}, "GET"), local, fakeFetch({}));
  assert.equal(listed.status, 200);
  assert.equal(listed.body.proposals.length, 2);
  assert.equal(listed.body.proposals.some((item) => item.text === allowed), true);
  assert.equal(JSON.stringify(listed.body).includes("apply-token-ok"), false);
  assert.equal(JSON.stringify(listed.body).includes("hunter22"), false);
  assert.equal(fs.existsSync(path.join(__dirname, "..", "soul", "proposals")), false);
  assert.equal(fs.existsSync(path.join(__dirname, "..", "soul", "SOUL.md")), false);
  assert.equal(fs.existsSync(path.join(__dirname, "..", "soul", "CHAPTER.md")), false);
});

test("the board applies one character proposal only when the token matches", async () => {
  const local = soulEnv();
  const allowed = "The password is kept outside the machine";
  const recorded = await handle(
    authed("/api/soul", {actor: "board", name: "SOUL.md", text: allowed}),
    local,
    fakeFetch({})
  );
  const id = recorded.body.proposal_id;
  const missing = await handle(
    authed("/api/soul/apply", {actor: "board", proposal_id: "a".repeat(32), token: "apply-token-ok"}),
    local,
    fakeFetch({})
  );
  assert.equal(missing.body.reason, "unknown_proposal");
  const chat = await handle(
    authed("/api/soul/apply", {actor: "chat", proposal_id: id, token: "apply-token-ok"}),
    local,
    fakeFetch({})
  );
  assert.equal(chat.body.reason, "board_only");
  const blank = await handle(
    authed("/api/soul/apply", {actor: "board", proposal_id: id, token: "   "}),
    local,
    fakeFetch({})
  );
  assert.equal(blank.body.reason, "token_required");
  const mismatched = await handle(
    authed("/api/soul/apply", {actor: "board", proposal_id: id, token: "mismatch-token-qq"}),
    local,
    fakeFetch({})
  );
  assert.equal(mismatched.status, 403);
  assert.equal(mismatched.body.reason, "token_mismatch");
  assert.equal(JSON.stringify(mismatched.body).includes("mismatch-token-qq"), false);
  assert.equal(JSON.stringify(mismatched.body).includes("apply-token-ok"), false);
  const applied = await handle(
    authed("/api/soul/apply", {actor: "board", proposal_id: id, token: "apply-token-ok", weekly: true, confirmed: true}),
    local,
    fakeFetch({})
  );
  assert.equal(applied.status, 200);
  assert.equal(applied.body.reason, "applied");
  assert.equal(applied.body.scheduled, false);
  assert.equal(applied.body.files_written, false);
  assert.equal(applied.body.example_read, false);
  assert.equal(applied.body.token_stored, false);
  assert.equal(applied.body.path, `soul/proposals/${id}.md`);
  const listed = await handle(authed("/api/soul", {}, "GET"), local, fakeFetch({}));
  assert.equal(listed.body.current["SOUL.md"], allowed);
  assert.equal(JSON.stringify(listed.body).includes("apply-token-ok"), false);
  const repeat = await handle(
    authed("/api/soul/apply", {actor: "board", proposal_id: id, token: "apply-token-ok"}),
    local,
    fakeFetch({})
  );
  assert.equal(repeat.status, 403);
  assert.equal(repeat.body.reason, "already_applied");
  assert.equal(repeat.body.path, `soul/proposals/${id}.md`);
  const next = await handle(
    authed("/api/soul", {actor: "board", name: "SOUL.md", text: "A later public line."}),
    local,
    fakeFetch({})
  );
  assert.equal(next.status, 200);
  assert.equal(next.body.reason, "proposal");
  const still = await handle(authed("/api/soul", {}, "GET"), local, fakeFetch({}));
  assert.equal(still.body.current["SOUL.md"], allowed);
  const shaped = soulEnv("token=zzqq99");
  const held = await handle(
    authed("/api/soul", {actor: "board", name: "SOUL.md", text: allowed}),
    shaped,
    fakeFetch({})
  );
  const refused = await handle(
    authed("/api/soul/apply", {actor: "board", proposal_id: held.body.proposal_id, token: "token=zzqq99"}),
    shaped,
    fakeFetch({})
  );
  assert.equal(refused.status, 403);
  assert.equal(refused.body.reason, "credential");
  assert.equal(refused.body.applied, false);
  assert.equal(JSON.stringify(refused.body).includes("zzqq99"), false);
  const after = await handle(authed("/api/soul", {}, "GET"), shaped, fakeFetch({}));
  assert.equal(after.body.current["SOUL.md"], undefined);
  assert.equal(after.body.proposals[0].applied, false);
});

test("ask does not record a character proposal", async () => {
  const local = soulEnv();
  const result = await handle(
    authed("/api/ask", {text: "hello", confirmed: true}),
    local,
    fakeFetch({
      "POST http://friday:8080/ask": {
        status: 200,
        body: {outcome: "spoken", reason: "model", reply: "ok"},
      },
    })
  );
  assert.equal(result.status, 200);
  assert.equal(result.body.proposal_id, undefined);
  const listed = await handle(authed("/api/soul", {}, "GET"), local, fakeFetch({}));
  assert.equal(listed.body.proposals.length, 0);
  assert.deepEqual(listed.body.current, {});
});
