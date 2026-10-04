import { describe, expect, test } from "bun:test";

import {
  applyMkaServerErrors,
  emptyMkaProfile,
  mkaValuesToBody,
  validateMkaProfile,
} from "../services/mka/profile.ts";

const valid = { ...emptyMkaProfile, majlis: "Silicon Valley" };

describe("validateMkaProfile", () => {
  test("requires majlis only", () => {
    expect(validateMkaProfile(emptyMkaProfile)).toEqual({ majlis: "Majlis is required" });
    expect(validateMkaProfile(valid)).toEqual({});
  });

  test("accepts common US mobile formats", () => {
    for (const m of ["(555) 234-0142", "555-234-0142", "+1 555 234 0142", "5552340142"]) {
      expect(validateMkaProfile({ ...valid, mobile: m }).mobile).toBeUndefined();
    }
  });

  test("rejects bad mobile numbers", () => {
    for (const m of ["123", "555-123-0142", "call me", "1234567890"]) {
      expect(validateMkaProfile({ ...valid, mobile: m }).mobile).toBeDefined();
    }
  });

  test("amc_id must be 1-15 digits", () => {
    expect(validateMkaProfile({ ...valid, amc_id: "12345" }).amc_id).toBeUndefined();
    expect(validateMkaProfile({ ...valid, amc_id: "12a" }).amc_id).toBeDefined();
    expect(validateMkaProfile({ ...valid, amc_id: "1".repeat(16) }).amc_id).toBeDefined();
  });
});

describe("mkaValuesToBody", () => {
  test("empty optionals become null and region is never sent", () => {
    const body = mkaValuesToBody({ ...valid, mobile: "  ", amc_id: "", tanzeem: "" });
    expect(body).toEqual({ majlis: "Silicon Valley", mobile: null, amc_id: null, tanzeem: null });
    expect("region" in body).toBe(false);
  });

  test("trims values", () => {
    expect(mkaValuesToBody({ majlis: " X ", mobile: " 5552340142 ", amc_id: " 7 ", tanzeem: "ansar" }))
      .toEqual({ majlis: "X", mobile: "5552340142", amc_id: "7", tanzeem: "ansar" });
  });
});

describe("applyMkaServerErrors", () => {
  const run = (status, detail) => {
    const set = {};
    const ok = applyMkaServerErrors(status, detail, (p, m) => (set[p] = m));
    return { ok, set };
  };

  test("409 string detail maps to amc_id", () => {
    expect(run(409, "That AMC ID is already registered")).toEqual({
      ok: true,
      set: { "mka_profile.amc_id": "That AMC ID is already registered" },
    });
  });

  test("422 {field,message} list", () => {
    expect(run(422, [{ field: "mobile", message: "bad number" }])).toEqual({
      ok: true,
      set: { "mka_profile.mobile": "bad number" },
    });
  });

  test("422 {loc,msg} strips Value error prefix", () => {
    expect(run(422, [{ loc: ["body", "mka_profile", "majlis"], msg: "Value error, Unknown Majlis" }])).toEqual({
      ok: true,
      set: { "mka_profile.majlis": "Unknown Majlis" },
    });
  });

  test("unknown field key ignored", () => {
    expect(run(422, [{ field: "region", message: "x" }, { loc: ["body", "email"], msg: "y" }])).toEqual({
      ok: false,
      set: {},
    });
  });

  test("non-matching status/detail returns false", () => {
    expect(run(422, "some string").ok).toBe(false);
    expect(run(409, [{ foo: 1 }]).ok).toBe(false);
    expect(run(500, undefined).ok).toBe(false);
  });

  test("400 returns false", () => {
    expect(run(400, "Missing required fields")).toEqual({ ok: false, set: {} });
  });
});
