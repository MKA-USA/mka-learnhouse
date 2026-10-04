import { describe, expect, test } from "bun:test";

import {
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
