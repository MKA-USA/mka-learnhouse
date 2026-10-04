import { describe, expect, test } from "bun:test";

import { isTurnstileActive, isTurnstileEnforced } from "../lib/mka-turnstile.ts";

describe("mka turnstile rules", () => {
  test("both keys set (non-saas) -> active and enforced", () => {
    expect(isTurnstileActive("site")).toBe(true);
    expect(isTurnstileEnforced("secret", "site")).toBe(true);
  });
  test("only site key -> widget active, server not enforcing (no lockout)", () => {
    expect(isTurnstileActive("site")).toBe(true);
    expect(isTurnstileEnforced(undefined, "site")).toBe(false);
    expect(isTurnstileEnforced("", "site")).toBe(false);
  });
  test("only secret -> neither widget nor enforcement (no lockout)", () => {
    expect(isTurnstileActive(undefined)).toBe(false);
    expect(isTurnstileEnforced("secret", undefined)).toBe(false);
    expect(isTurnstileEnforced("secret", "")).toBe(false);
  });
  test("neither -> off", () => {
    expect(isTurnstileActive("")).toBe(false);
    expect(isTurnstileEnforced(undefined, undefined)).toBe(false);
  });
  test("custom-domain state is not an input to the fork rules (by design)", () => {
    expect(isTurnstileEnforced("secret", "site")).toBe(true);
  });
});
