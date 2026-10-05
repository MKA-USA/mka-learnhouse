import { afterEach, describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { mkaAudienceEnabled, mkaAudienceMock, waitForMkaAudienceEnabled } from "../services/mka/flags.ts";

const VAR = "NEXT_PUBLIC_MKA_AUDIENCE_ENABLED";
const MOCK = "NEXT_PUBLIC_MKA_AUDIENCE_MOCK";
const saved = { env: { [VAR]: process.env[VAR], [MOCK]: process.env[MOCK], NODE_ENV: process.env.NODE_ENV }, window: globalThis.window };
const restore = () => {
  for (const [k, v] of Object.entries(saved.env)) v === undefined ? delete process.env[k] : (process.env[k] = v);
  globalThis.window = saved.window;
  delete globalThis.window.__RUNTIME_CONFIG__;
};
afterEach(restore);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

describe("mkaAudienceEnabled (runtime-configurable)", () => {
  test("client: window.__RUNTIME_CONFIG__ wins over the build-time value, both ways", () => {
    process.env[VAR] = "0";
    window.__RUNTIME_CONFIG__ = { [VAR]: "1" };
    expect(mkaAudienceEnabled()).toBe(true);
    process.env[VAR] = "1";
    window.__RUNTIME_CONFIG__ = { [VAR]: "0" };
    expect(mkaAudienceEnabled()).toBe(false);
    window.__RUNTIME_CONFIG__ = { [VAR]: "" };
    expect(mkaAudienceEnabled()).toBe(false);
  });
  test("client: without the variable in runtime config, the build-time value is the fallback", () => {
    process.env[VAR] = "1";
    window.__RUNTIME_CONFIG__ = { OTHER: "x" };
    expect(mkaAudienceEnabled()).toBe(true);
    delete window.__RUNTIME_CONFIG__;
    expect(mkaAudienceEnabled()).toBe(true);
    process.env[VAR] = "0";
    expect(mkaAudienceEnabled()).toBe(false);
    delete process.env[VAR];
    expect(mkaAudienceEnabled()).toBe(false);
  });
  test("server (no window): reads process.env at runtime", () => {
    globalThis.window = undefined;
    process.env[VAR] = "1";
    expect(mkaAudienceEnabled()).toBe(true);
    process.env[VAR] = "0";
    expect(mkaAudienceEnabled()).toBe(false);
    delete process.env[VAR];
    expect(mkaAudienceEnabled()).toBe(false);
  });
  test("the server branch reads through a variable key, so Next cannot inline it at build time", () => {
    const src = readFileSync(new URL("../services/mka/flags.ts", import.meta.url), "utf8");
    expect(src).toContain("process.env[ENABLED_VAR]");
  });
});

describe("the MOCK flag stays build-time and production-off", () => {
  test("a runtime-config value cannot enable it", () => {
    delete process.env[MOCK];
    window.__RUNTIME_CONFIG__ = { [MOCK]: "1" };
    expect(mkaAudienceMock()).toBe(false);
  });
  test("hard-off in production even when set", () => {
    process.env[MOCK] = "1";
    process.env.NODE_ENV = "production";
    expect(mkaAudienceMock()).toBe(false);
    process.env.NODE_ENV = "development";
    expect(mkaAudienceMock()).toBe(true);
  });
});

describe("waitForMkaAudienceEnabled (runtime-config.js can arrive after hydration)", () => {
  test("calls immediately when already enabled", () => {
    window.__RUNTIME_CONFIG__ = { [VAR]: "1" };
    let n = 0;
    waitForMkaAudienceEnabled(() => n++);
    expect(n).toBe(1);
  });
  test("fires once when the config arrives later", async () => {
    process.env[VAR] = "0";
    let n = 0;
    waitForMkaAudienceEnabled(() => n++, { intervalMs: 5, maxMs: 500 });
    await sleep(30);
    expect(n).toBe(0);
    window.__RUNTIME_CONFIG__ = { [VAR]: "1" };
    await sleep(40);
    expect(n).toBe(1);
    await sleep(40);
    expect(n).toBe(1);
  });
  test("gives up after maxMs and reports it; never fires if the flag stays off", async () => {
    process.env[VAR] = "0";
    let fired = 0;
    let gaveUp = 0;
    waitForMkaAudienceEnabled(() => fired++, { intervalMs: 5, maxMs: 40, onGiveUp: () => gaveUp++ });
    await sleep(120);
    window.__RUNTIME_CONFIG__ = { [VAR]: "1" }; // too late
    await sleep(40);
    expect(fired).toBe(0);
    expect(gaveUp).toBe(1);
  });
  test("cancel stops the poll", async () => {
    process.env[VAR] = "0";
    let n = 0;
    const cancel = waitForMkaAudienceEnabled(() => n++, { intervalMs: 5, maxMs: 500 });
    cancel();
    window.__RUNTIME_CONFIG__ = { [VAR]: "1" };
    await sleep(40);
    expect(n).toBe(0);
  });
});
