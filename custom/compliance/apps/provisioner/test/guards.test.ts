import { describe, expect, test } from "bun:test";
import { SafetyError } from "@mka/compliance-core";
import { parseArgs } from "../src/args";
import { cmdApply } from "../src/commands-lh";

describe("apply guards (all throw before any DB or network access)", () => {
  const env = { ...process.env };
  const restore = () => { process.env = { ...env }; };
  test("requires --confirm-staging", async () => { await expect(cmdApply(parseArgs(["apply", "--pilot"]))).rejects.toBeInstanceOf(SafetyError); });
  test("requires an explicit selection", async () => { await expect(cmdApply(parseArgs(["apply", "--confirm-staging"]))).rejects.toThrow("--pilot"); });
  test("refuses a non-staging LH_API_BASE", async () => {
    process.env.LH_API_BASE = "https://ilm.mkausa.org/api/v1"; process.env.LH_API_TOKEN = "t";
    try { await expect(cmdApply(parseArgs(["apply", "--confirm-staging", "--pilot"]))).rejects.toBeInstanceOf(SafetyError); } finally { restore(); }
  });
});
