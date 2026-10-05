import { describe, expect, test } from "bun:test";

import { mkaSignupForwardHeaders } from "../lib/mka-signup-proxy.ts";

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
