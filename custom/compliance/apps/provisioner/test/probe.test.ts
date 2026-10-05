import { describe, expect, test } from "bun:test";
import { LhApi, LhClient } from "@mka/compliance-core/lh";
import { classify, renderMatrix, runProbe } from "../src/probe-lib";
import { LhHttpError } from "@mka/compliance-core/lh";

describe("probe", () => {
  test("classify", () => {
    expect(classify(new LhHttpError("GET", "/a", 403, "Admin API requires a Pro plan or higher.")).verdict).toBe("plan-required");
    expect(classify(new LhHttpError("GET", "/a", 403, "no")).verdict).toBe("forbidden");
    expect(classify(new LhHttpError("GET", "/a", 404)).verdict).toBe("not-found");
  });
  test("401 stops and only GETs are issued", async () => {
    const methods: string[] = [];
    const client = new LhClient({
      baseUrl: "https://x.test/api/v1", token: "t", orgSlug: "a", delayMs: 0, sleep: async () => {},
      fetch: (async (_u: string, i: RequestInit) => { methods.push(String(i.method)); return new Response("{}", { status: 401 }); }) as unknown as typeof fetch,
    });
    const r = await runProbe(new LhApi(client), ["a", "b"]);
    expect(r.stoppedReason).toContain("401");
    expect(methods.every((m) => m === "GET")).toBe(true);
    expect(renderMatrix(r.rows)).toContain("| 401 |");
  });
});
