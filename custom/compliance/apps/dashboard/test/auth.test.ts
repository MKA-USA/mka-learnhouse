import "./setup";
import { describe, expect, test } from "bun:test";
import { isAllowedAccount } from "@/auth";
import { parseAttributesResponse } from "@/lib/attributes";

describe("Google domain gate", () => {
  test("only verified @mkausa.org", () => {
    expect(isAllowedAccount({ email: "A.B@mkausa.org", email_verified: true })).toBe(true);
    expect(isAllowedAccount({ email: "a@mkausa.org", email_verified: false })).toBe(false);
    expect(isAllowedAccount({ email: "a@mkausa.org" })).toBe(false);
    expect(isAllowedAccount({ email: "a@gmail.com", email_verified: true })).toBe(false);
    expect(isAllowedAccount({ email: "a@evil-mkausa.org", email_verified: true })).toBe(false);
    expect(isAllowedAccount({ email: "a@mkausa.org.evil.com", email_verified: true })).toBe(false);
    expect(isAllowedAccount({ email: "mkausa.org", email_verified: true })).toBe(false);
    expect(isAllowedAccount(undefined)).toBe(false);
  });
});

describe("attributes response parser (fail closed)", () => {
  const row = { email: "T@x.invalid", status: "matched", is_officeholder: true, level: "national", department: "tabligh", role: "mohtamim", majlis: null, region: null };
  test("accepts array, {items}, and nested effective/attributes", () => {
    expect(parseAttributesResponse([row], "t@x.invalid")?.role).toBe("mohtamim");
    expect(parseAttributesResponse({ items: [row] }, "t@x.invalid")?.department).toBe("tabligh");
    expect(parseAttributesResponse({ items: [{ email: "t@x.invalid", effective: row }] }, "t@x.invalid")?.role).toBe("mohtamim");
  });
  test("null for no match, bad status, or garbage", () => {
    expect(parseAttributesResponse([row], "other@x.invalid")).toBeNull();
    expect(parseAttributesResponse([{ ...row, status: "weird" }], "t@x.invalid")).toBeNull();
    expect(parseAttributesResponse("nope", "t@x.invalid")).toBeNull();
    expect(parseAttributesResponse(null, "t@x.invalid")).toBeNull();
  });
});
