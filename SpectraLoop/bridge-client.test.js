const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  BridgeClient,
  BridgeClientError,
  TOKEN_KEY,
  consumeBridgeToken,
} = require("./bridge-client.js");

test("bridge token is accepted from the URL fragment, stored for the tab, and scrubbed", () => {
  const values = new Map();
  const storage = {
    setItem: (key, value) => values.set(key, value),
    getItem: (key) => values.get(key) || null,
  };
  let replacement = null;
  const token = "A_secure_test_token_123456789";

  const result = consumeBridgeToken({
    location: { hash: `#bridge_token=${token}`, pathname: "/setup.html", search: "?mode=local" },
    sessionStorage: storage,
    history: { replaceState: (_state, _title, value) => { replacement = value; } },
  });

  assert.equal(result, token);
  assert.equal(values.get(TOKEN_KEY), token);
  assert.equal(replacement, "/setup.html?mode=local");
});

test("client sends bearer token only to fixed loopback bridge", async () => {
  const requests = [];
  const token = "A_secure_test_token_123456789";
  const client = new BridgeClient({
    token,
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return { ok: true, status: 200, json: async () => ({ api_version: "v1" }) };
    },
  });

  await client.status();

  assert.equal(requests[0].url, "http://127.0.0.1:8765/v1/status");
  assert.equal(requests[0].options.headers.Authorization, `Bearer ${token}`);
  assert.equal(requests[0].options.credentials, "omit");
  assert.equal("targetAddressSpace" in requests[0].options, false);
  assert.throws(
    () => new BridgeClient({ token, baseUrl: "https://attacker.invalid" }),
    (error) => error instanceof BridgeClientError && error.code === "invalid_bridge_url",
  );
});

test("setup page loads the authenticated bridge client before its UI controller", () => {
  const html = fs.readFileSync(path.join(__dirname, "setup.html"), "utf8");
  const bridgePosition = html.indexOf('<script src="bridge-client.js?v=bridge-session-4"></script>');
  const appPosition = html.indexOf('<script src="app.js?v=bridge-session-4"></script>');

  assert.ok(bridgePosition >= 0);
  assert.ok(appPosition > bridgePosition);
  assert.match(html, /id="select-storage-button"/);
  assert.match(html, /id="discover-instrument-button"/);
  assert.match(html, /data-confirmation="cell_output_off"/);
});

test("bridge API errors remain structured for the setup interface", async () => {
  const client = new BridgeClient({
    token: "A_secure_test_token_123456789",
    fetchImpl: async () => ({
      ok: false,
      status: 409,
      json: async () => ({ error: { code: "vendor_interface_unavailable", message: "No verified adapter." } }),
    }),
  });

  await assert.rejects(
    client.discoverInstrument({}),
    (error) => error.code === "vendor_interface_unavailable" && error.status === 409,
  );
});

test("local pages can use an HttpOnly same-origin bridge session", async () => {
  const requests = [];
  const client = new BridgeClient({
    cookieAuth: true,
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return { ok: true, status: 200, json: async () => ({ api_version: "v1" }) };
    },
  });

  await client.status();

  assert.equal(requests[0].options.credentials, "same-origin");
  assert.equal("Authorization" in requests[0].options.headers, false);
});
