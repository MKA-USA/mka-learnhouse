import { describe, expect, test } from "bun:test";

import {
  isMkaTurnstileApplicable,
  mkaTurnstileActiveFor,
  mkaTurnstileEnforcedFor,
} from "../lib/mka-turnstile.ts";

const row = (mode, siteKey, secretKey) => ({
  active: mkaTurnstileActiveFor({ mode, siteKey }),
  enforced: mkaTurnstileEnforcedFor({ mode, siteKey, secretKey }),
});

describe("mka turnstile matrix", () => {
  test("non-saas: both keys -> widget and server", () => {
    expect(row("oss", "site", "secret")).toEqual({ active: true, enforced: true });
  });
  test("non-saas: only site key -> widget yes, server no (no lockout)", () => {
    expect(row("oss", "site", undefined)).toEqual({ active: true, enforced: false });
    expect(row("oss", "site", "")).toEqual({ active: true, enforced: false });
  });
  test("non-saas: only secret -> neither (no lockout)", () => {
    expect(row("oss", undefined, "secret")).toEqual({ active: false, enforced: false });
    expect(row("oss", "", "secret")).toEqual({ active: false, enforced: false });
  });
  test("non-saas: neither -> off", () => {
    expect(row("oss", "", undefined)).toEqual({ active: false, enforced: false });
  });
  test("saas with keys -> fork inactive, upstream handles it", () => {
    expect(isMkaTurnstileApplicable("saas")).toBe(false);
    expect(row("saas", "site", "secret")).toEqual({ active: false, enforced: false });
    expect(isMkaTurnstileApplicable("oss")).toBe(true);
  });
});
