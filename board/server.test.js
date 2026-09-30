"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
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
