(function exposeBridgeClient(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.SpectraLoopBridge = api;
})(typeof globalThis === "object" ? globalThis : this, function buildBridgeClient() {
  "use strict";

  const DEFAULT_BRIDGE_URL = "http://127.0.0.1:8765";
  const TOKEN_KEY = "spectraloop-bridge-token";

  class BridgeClientError extends Error {
    constructor(message, code = "bridge_unreachable", status = 0) {
      super(message);
      this.name = "BridgeClientError";
      this.code = code;
      this.status = status;
    }
  }

  function validToken(value) {
    return typeof value === "string" && /^[A-Za-z0-9_-]{20,256}$/.test(value);
  }

  function validBridgeUrl(value) {
    try {
      const parsed = new URL(value);
      return parsed.protocol === "http:"
        && parsed.hostname === "127.0.0.1"
        && !parsed.username
        && !parsed.password
        && parsed.pathname === "/"
        && !parsed.search
        && !parsed.hash;
    } catch (error) {
      return false;
    }
  }

  function consumeBridgeToken({ location, sessionStorage, history } = {}) {
    const currentLocation = location || (typeof window !== "undefined" ? window.location : null);
    const storage = sessionStorage || (typeof window !== "undefined" ? window.sessionStorage : null);
    const browserHistory = history || (typeof window !== "undefined" ? window.history : null);
    if (!currentLocation || !storage) return null;

    const fragment = new URLSearchParams((currentLocation.hash || "").replace(/^#/, ""));
    const fragmentToken = fragment.get("bridge_token");
    if (validToken(fragmentToken)) {
      storage.setItem(TOKEN_KEY, fragmentToken);
      if (browserHistory && typeof browserHistory.replaceState === "function") {
        browserHistory.replaceState(
          null,
          "",
          `${currentLocation.pathname || "/"}${currentLocation.search || ""}`,
        );
      }
      return fragmentToken;
    }
    const stored = storage.getItem(TOKEN_KEY);
    return validToken(stored) ? stored : null;
  }

  class BridgeClient {
    constructor({ token, baseUrl = DEFAULT_BRIDGE_URL, fetchImpl, cookieAuth = false } = {}) {
      if (!validToken(token) && cookieAuth !== true) throw new BridgeClientError("Start the local bridge to create a secure session.", "token_missing");
      if (!validBridgeUrl(baseUrl)) throw new BridgeClientError("The bridge URL must remain loopback-only.", "invalid_bridge_url");
      this.token = validToken(token) ? token : null;
      this.cookieAuth = cookieAuth === true;
      this.baseUrl = baseUrl.replace(/\/$/, "");
      this.fetchImpl = fetchImpl || (typeof fetch === "function" ? fetch.bind(globalThis) : null);
      if (!this.fetchImpl) throw new BridgeClientError("This browser does not support local bridge requests.", "fetch_unavailable");
    }

    async request(path, { method = "GET", body } = {}) {
      let response;
      try {
        response = await this.fetchImpl(`${this.baseUrl}${path}`, {
          method,
          mode: "cors",
          cache: "no-store",
          credentials: this.cookieAuth ? "same-origin" : "omit",
          headers: {
            ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
            ...(body === undefined ? {} : { "Content-Type": "application/json" }),
          },
          ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        });
      } catch (error) {
        throw new BridgeClientError(
          "The local bridge is not reachable. Start it on this instrument computer and try again.",
          "bridge_unreachable",
        );
      }
      let payload;
      try {
        payload = await response.json();
      } catch (error) {
        throw new BridgeClientError("The local bridge returned an invalid response.", "invalid_response", response.status);
      }
      if (!response.ok) {
        const bridgeError = payload && payload.error;
        throw new BridgeClientError(
          bridgeError && bridgeError.message ? bridgeError.message : `Bridge request failed (${response.status}).`,
          bridgeError && bridgeError.code ? bridgeError.code : "bridge_request_failed",
          response.status,
        );
      }
      return payload;
    }

    status() {
      return this.request("/v1/status");
    }

    selectStorageFolder() {
      return this.request("/v1/storage/select", { method: "POST", body: {} });
    }

    discoverInstrument(confirmations) {
      return this.request("/v1/instrument/discover", {
        method: "POST",
        body: { confirmations },
      });
    }
  }

  return {
    BridgeClient,
    BridgeClientError,
    DEFAULT_BRIDGE_URL,
    TOKEN_KEY,
    consumeBridgeToken,
    validBridgeUrl,
    validToken,
  };
});
