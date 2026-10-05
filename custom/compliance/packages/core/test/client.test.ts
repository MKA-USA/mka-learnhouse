import { describe, expect, test } from "bun:test";
import { LhClient, LhHttpError, LhNetworkError, LhApi, redactPath } from "../src/lh";

const TOKEN = "lh_secret_token_value";
const json = (b: unknown, status = 200, h: Record<string, string> = {}) =>
  new Response(JSON.stringify(b), { status, headers: { "content-type": "application/json", ...h } });

function make(responses: (() => Response | Promise<Response>)[], extra: Record<string, unknown> = {}) {
  const calls: { url: string; init: RequestInit }[] = [];
  const sleeps: number[] = [];
  const logs: string[] = [];
  let i = 0;
  const client = new LhClient({
    baseUrl: "https://x.test/api/v1/", token: TOKEN, orgSlug: "org", delayMs: 1000, backoffBaseMs: 10,
    fetch: (async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      const r = responses[Math.min(i++, responses.length - 1)]!;
      if (r instanceof Error) throw r;
      return r();
    }) as unknown as typeof fetch,
    sleep: async (ms) => { sleeps.push(ms); },
    log: (l) => logs.push(l),
    ...extra,
  });
  return { client, calls, sleeps, logs };
}

describe("LhClient", () => {
  test("sends bearer token and builds URL with query", async () => {
    const { client, calls } = make([() => json([{ a: 1 }])]);
    const r = await client.get("/courses/x", { page: 2, skip: undefined });
    expect(r).toEqual([{ a: 1 }]);
    expect(calls[0]!.url).toBe("https://x.test/api/v1/courses/x?page=2");
    expect((calls[0]!.init.headers as Record<string, string>).Authorization).toBe(`Bearer ${TOKEN}`);
  });

  test("applies politeness delay between requests", async () => {
    const { client, sleeps } = make([() => json({})]);
    await client.get("/a"); await client.get("/b");
    expect(sleeps.some((s) => s > 0 && s <= 1000)).toBe(true);
  });

  test("retries 429 then succeeds, honoring Retry-After", async () => {
    const { client, calls, sleeps } = make([() => json({ detail: "slow" }, 429, { "retry-after": "2" }), () => json({ ok: 1 })]);
    expect(await client.get<{ ok: number }>("/a")).toEqual({ ok: 1 });
    expect(calls.length).toBe(2);
    expect(sleeps).toContain(2000);
  });

  test("does not retry POST on 502", async () => {
    const { client, calls } = make([() => json({}, 502)]);
    await expect(client.post("/a", {})).rejects.toBeInstanceOf(LhHttpError);
    expect(calls.length).toBe(1);
  });

  test("typed errors: status helpers, detail kept off message", async () => {
    const { client } = make([() => json({ detail: "User bob@x.org not found" }, 404)]);
    const e = (await client.get("/admin/org/users/by-email/bob@x.org").catch((x) => x)) as LhHttpError;
    expect(e).toBeInstanceOf(LhHttpError);
    expect(e.isNotFound).toBe(true);
    expect(e.message).not.toContain("bob@x.org");
    expect(e.path).toContain(":email");
  });

  test("network errors retry then throw LhNetworkError", async () => {
    const { client, calls } = make([new Error("boom") as unknown as () => Response], { maxRetries: 2 });
    const e = await client.get("/a").catch((x) => x);
    expect(e).toBeInstanceOf(LhNetworkError);
    expect(calls.length).toBe(3);
  });

  test("token never appears in logs, errors, or serialization", async () => {
    const { client, logs } = make([() => json({ detail: "nope" }, 403)]);
    const e = (await client.get("/a").catch((x) => x)) as Error;
    expect(JSON.stringify(client)).not.toContain(TOKEN);
    expect(String(e.message)).not.toContain(TOKEN);
    expect(logs.join("\n")).not.toContain(TOKEN);
    expect(logs[0]).toBe("GET /a 403");
  });

  test("requires base url and token", () => {
    expect(() => LhClient.fromEnv({})).toThrow();
  });

  test("api wrapper builds admin paths", async () => {
    const { client, calls } = make([() => json({ enrolled: [1], already_enrolled: [], skipped: [] })]);
    await new LhApi(client).bulkEnroll("course_1", [1]);
    expect(calls[0]!.url).toBe("https://x.test/api/v1/admin/org/enrollments/bulk");
    expect(JSON.parse(String(calls[0]!.init.body))).toEqual({ course_uuid: "course_1", user_ids: [1] });
  });

  test("redactPath", () => { expect(redactPath("/admin/o/users/by-email/a@b.c")).toBe("/admin/o/users/by-email/:email"); });
});
