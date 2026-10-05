import { describe, expect, test } from "bun:test";

import { emptyMkaProfile, profileToValues } from "../services/mka/profile.ts";

describe("profileToValues", () => {
  test("incomplete profile -> empty form values", () => {
    expect(profileToValues({ complete: false })).toEqual(emptyMkaProfile);
  });

  test("maps nulls to empty strings and drops region", () => {
    const v = profileToValues({
      complete: true,
      majlis: "Zion",
      region: "Midwest",
      mobile: null,
      amc_id: "123",
      tanzeem: null,
    });
    expect(v).toEqual({ majlis: "Zion", mobile: "", amc_id: "123", tanzeem: "" });
  });
});
