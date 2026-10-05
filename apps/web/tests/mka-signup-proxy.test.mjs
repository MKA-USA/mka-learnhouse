import { describe, expect, test } from "bun:test";

import {
  isMkaConnectError,
  mkaInternalApiUrl,
  mkaSignupFetch,
  mkaSignupForwardHeaders,
} from "../lib/mka-signup-proxy.ts";

const incoming = (obj) => new Headers(obj);

describe("mka signup proxy forward headers", () => {
  test("saas: nothing added (upstream behavior)", () => {
    expect(
      mkaSignupForwardHeaders(true, incoming({ "x-forwarded-for": "203.0.113.9" }), "tok"),
    ).toEqual({});
  });

  test("non-saas: forwards token and client ip headers verbatim", () => {
    expect(
      mkaSignupForwardHeaders(
        false,
        incoming({ "x-forwarded-for": "203.0.113.9, 10.0.0.2", "x-real-ip": "10.0.0.2" }),
        "tok-123",
      ),
    ).toEqual({
      "X-Turnstile-Token": "tok-123",
      "X-Forwarded-For": "203.0.113.9, 10.0.0.2",
      "X-Real-IP": "10.0.0.2",
    });
  });

  test("non-saas: no token -> no token header (API answers missing_token)", () => {
    expect(mkaSignupForwardHeaders(false, incoming({}), null)).toEqual({});
    expect(mkaSignupForwardHeaders(false, incoming({}), "")).toEqual({});
    expect(mkaSignupForwardHeaders(false, incoming({}), undefined)).toEqual({});
  });

  test("non-saas: non-string or unsafe token is replaced so the API rejects it", () => {
    expect(mkaSignupForwardHeaders(false, incoming({}), 42)).toEqual({ "X-Turnstile-Token": "invalid" });
    expect(mkaSignupForwardHeaders(false, incoming({}), "a\nb")).toEqual({ "X-Turnstile-Token": "invalid" });
    expect(mkaSignupForwardHeaders(false, incoming({}), "x".repeat(2049))).toEqual({
      "X-Turnstile-Token": "invalid",
    });
  });

  test("does not invent cf-connecting-ip based forwarding", () => {
    expect(mkaSignupForwardHeaders(false, incoming({ "cf-connecting-ip": "1.2.3.4" }), null)).toEqual({});
  });
});

const connectErr = (code) =>
  Object.assign(new TypeError("fetch failed"), { cause: Object.assign(new Error(code), { code }) });

describe("mka internal api url", () => {
  test("defaults to loopback on LEARNHOUSE_PORT or 9000", () => {
    expect(mkaInternalApiUrl({})).toBe("http://127.0.0.1:9000/api/v1/");
    expect(mkaInternalApiUrl({ LEARNHOUSE_PORT: "9100" })).toBe("http://127.0.0.1:9100/api/v1/");
  });
  test("explicit LEARNHOUSE_INTERNAL_API_URL wins (trailing slash ensured)", () => {
    expect(mkaInternalApiUrl({ LEARNHOUSE_INTERNAL_API_URL: "http://api:9000/api/v1" })).toBe(
      "http://api:9000/api/v1/",
    );
  });
});

describe("mka connect error classification", () => {
  test("connection-establishment failures fall back", () => {
    for (const code of ["ECONNREFUSED", "ENOTFOUND", "EAI_AGAIN", "EHOSTUNREACH", "ENETUNREACH", "UND_ERR_CONNECT_TIMEOUT"]) {
      expect(isMkaConnectError(connectErr(code))).toBe(true);
    }
    const agg = Object.assign(new TypeError("fetch failed"), { cause: { errors: [{ code: "ECONNREFUSED" }] } });
    expect(isMkaConnectError(agg)).toBe(true);
  });
  test("anything that may have reached the API does not", () => {
    expect(isMkaConnectError(connectErr("ECONNRESET"))).toBe(false);
    expect(isMkaConnectError(connectErr("UND_ERR_SOCKET"))).toBe(false);
    expect(isMkaConnectError(Object.assign(new Error("t"), { name: "TimeoutError" }))).toBe(false);
    expect(isMkaConnectError(new TypeError("fetch failed"))).toBe(false);
    expect(isMkaConnectError(null)).toBe(false);
  });
});

describe("mka signup fetch", () => {
  const PUBLIC = "https://learn.example.org/api/v1/";
  const INTERNAL = "http://127.0.0.1:9000/api/v1/";
  const invitePath = "users/7/invite/ABC";
  const init = () => ({
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...mkaSignupForwardHeaders(false, new Headers({ "x-forwarded-for": "8.8.4.4" }), "tok-inv"),
    },
    body: "{}",
  });

  test("saas: calls the original url only", async () => {
    const calls = [];
    const res = await mkaSignupFetch(true, PUBLIC, PUBLIC + invitePath, init(), {
      internalBase: INTERNAL,
      fetchImpl: async (u) => {
        calls.push(u);
        return new Response("{}", { status: 201 });
      },
    });
    expect(res.status).toBe(201);
    expect(calls).toEqual([PUBLIC + invitePath]);
  });

  test("non-saas invite path: loopback url, token + ip headers forwarded", async () => {
    const calls = [];
    await mkaSignupFetch(false, PUBLIC, PUBLIC + invitePath, init(), {
      internalBase: INTERNAL,
      fetchImpl: async (u, i) => {
        calls.push([u, i.headers]);
        return new Response("{}", { status: 200 });
      },
    });
    expect(calls.length).toBe(1);
    expect(calls[0][0]).toBe(INTERNAL + invitePath);
    expect(calls[0][1]["X-Turnstile-Token"]).toBe("tok-inv");
    expect(calls[0][1]["X-Forwarded-For"]).toBe("8.8.4.4");
  });

  test("connect error on loopback falls back ONCE to the public url", async () => {
    const calls = [];
    const res = await mkaSignupFetch(false, PUBLIC, PUBLIC + invitePath, init(), {
      internalBase: INTERNAL,
      fetchImpl: async (u) => {
        calls.push(u);
        if (u.startsWith(INTERNAL)) throw connectErr("ECONNREFUSED");
        return new Response("{}", { status: 200 });
      },
    });
    expect(res.status).toBe(200);
    expect(calls).toEqual([INTERNAL + invitePath, PUBLIC + invitePath]);
  });

  test("a failing fallback is not retried again", async () => {
    const calls = [];
    await expect(
      mkaSignupFetch(false, PUBLIC, PUBLIC + "users/", init(), {
        internalBase: INTERNAL,
        fetchImpl: async (u) => {
          calls.push(u);
          throw connectErr("ECONNREFUSED");
        },
      }),
    ).rejects.toThrow();
    expect(calls.length).toBe(2);
  });

  test("HTTP error responses are never retried", async () => {
    const calls = [];
    const res = await mkaSignupFetch(false, PUBLIC, PUBLIC + "users/", init(), {
      internalBase: INTERNAL,
      fetchImpl: async (u) => {
        calls.push(u);
        return new Response("{}", { status: 503 });
      },
    });
    expect(res.status).toBe(503);
    expect(calls.length).toBe(1);
  });

  test("non-connect errors propagate without a second request", async () => {
    const calls = [];
    await expect(
      mkaSignupFetch(false, PUBLIC, PUBLIC + "users/", init(), {
        internalBase: INTERNAL,
        fetchImpl: async (u) => {
          calls.push(u);
          throw connectErr("ECONNRESET");
        },
      }),
    ).rejects.toThrow();
    expect(calls.length).toBe(1);
  });

  test("url not under the public base is left alone", async () => {
    const calls = [];
    await mkaSignupFetch(false, PUBLIC, "https://other/users/", init(), {
      internalBase: INTERNAL,
      fetchImpl: async (u) => {
        calls.push(u);
        return new Response("{}");
      },
    });
    expect(calls).toEqual(["https://other/users/"]);
  });
});
