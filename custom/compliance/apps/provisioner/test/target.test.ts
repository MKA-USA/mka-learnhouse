import { afterEach, describe, expect, test } from "bun:test";
import { SafetyError, TARGETS } from "@mka/compliance-core";
import { parseArgs } from "../src/args";
import { cmdAssignAuthors, cmdPushCycle, cmdPushRoster, cmdSyncIdentity } from "../src/commands-push";
import { cmdPublish, cmdReconcile } from "../src/commands-lh";
import { confirmHint, currentTarget, initTarget, outSubdir, writeOk } from "../src/target";

const PROD = TARGETS.prod.host;
const init = (argv: string[], env: Record<string, string | undefined> = {}) => initTarget(parseArgs(argv), env);

describe("provisioner target selection", () => {
  afterEach(() => { init([]); }); // never leak a resolved prod target into other tests
  test("dev is the default: staging host, out/ untouched, --confirm-staging is the write gate", () => {
    const t = init(["apply", "--all"]);
    expect(t.name).toBe("dev"); expect(currentTarget().host).toBe("ilm-dev.mkausa.org"); expect(outSubdir()).toBe("");
    expect(writeOk(parseArgs(["apply"]))).toBe(false); expect(writeOk(parseArgs(["apply", "--confirm-staging"]))).toBe(true);
    expect(confirmHint()).toBe("--confirm-staging");
  });
  test("prod is refused without --confirm-prod <exact hostname>; --confirm-staging does not help", () => {
    expect(() => init(["apply", "--target", "prod"])).toThrow(SafetyError);
    expect(() => init(["apply", "--target", "prod", "--confirm-staging"])).toThrow(SafetyError);
    expect(() => init(["apply", "--target", "prod", "--confirm-prod"])).toThrow(SafetyError);
    expect(() => init(["apply", "--target", "prod", "--confirm-prod", "ilm-dev.mkausa.org"])).toThrow(SafetyError);
    expect(() => init(["apply", "--target", "prod", "--confirm-prod", `${PROD}x`])).toThrow(SafetyError);
  });
  test("prod writes need an explicit --write on top of --confirm-prod", () => {
    init(["apply", "--target", "prod", "--confirm-prod", PROD], { LH_API_TOKEN: "x", LH_TOKEN_TARGET: "prod" });
    expect(writeOk(parseArgs(["apply", "--confirm-prod", PROD]))).toBe(false);
    expect(writeOk(parseArgs(["apply", "--confirm-prod", PROD, "--confirm-staging"]))).toBe(false);
    expect(writeOk(parseArgs(["apply", "--confirm-prod", PROD, "--write"]))).toBe(true);
    expect(confirmHint()).toContain("--write");
  });
  test("every prod write command is refused without --write, before any DB or network access", async () => {
    init(["x", "--target", "prod", "--confirm-prod", PROD]);
    const base = ["--confirm-prod", PROD];
    const cases: [string, Promise<unknown>][] = [
      ["push-cycle", cmdPushCycle(parseArgs(["push-cycle", "--apply", ...base]))],
      ["push-roster", cmdPushRoster(parseArgs(["push-roster", "--all", "--apply", ...base]))],
      ["assign-authors", cmdAssignAuthors(parseArgs(["assign-authors", "--map", "x.csv", "--apply", ...base]))],
      ["sync-identity", cmdSyncIdentity(parseArgs(["sync-identity", "--apply", ...base]))],
      ["reconcile", cmdReconcile(parseArgs(["reconcile", "--all", "--apply", ...base]))],
      ["publish", cmdPublish(parseArgs(["publish", "--all", "--execute", ...base]))],
    ];
    for (const [name, run] of cases) await expect(run, name).rejects.toThrow(/--write/);
  });
  test("apply on prod without --write prints that it stops at the plan (nothing is written)", async () => {
    const p = Bun.spawn(["bun", "run", "src/cli.ts", "apply", "--all", "--target", "prod", "--confirm-prod", PROD], { cwd: new URL("..", import.meta.url).pathname, env: { PATH: process.env.PATH ?? "", HOME: process.env.HOME ?? "" }, stdout: "pipe", stderr: "pipe" });
    const [out, code] = [await new Response(p.stdout).text(), await p.exited];
    expect(out).toContain("showing the plan and stopping (nothing is written)"); expect(code).toBe(1); // the plan itself needs the DB, which this env does not have
  });
  test("an untagged token is refused for dev and prod", () => {
    expect(() => init(["plan"], { LH_API_TOKEN: "x" })).toThrow(SafetyError);
    expect(() => init(["plan", "--target", "prod", "--confirm-prod", PROD], { LH_API_TOKEN: "x" })).toThrow(SafetyError);
    expect(() => init(["plan"], { LH_API_TOKEN: "x", LH_TOKEN_TARGET: "dev" })).not.toThrow();
  });
  test("prod with the exact confirm: prod host, separate out/prod", () => {
    const t = init(["apply", "--target", "prod", "--confirm-prod", PROD, "--all"], { LH_API_TOKEN: "x", LH_TOKEN_TARGET: "prod" });
    expect(t).toMatchObject({ name: "prod", host: PROD }); expect(outSubdir()).toBe("prod");
    expect(writeOk(parseArgs(["apply"]))).toBe(false); // selecting prod is not permission to write
  });
  test("a dev token is refused for prod, and a prod token for dev", () => {
    expect(() => init(["plan", "--target", "prod", "--confirm-prod", PROD], { LH_API_TOKEN: "x", LH_TOKEN_TARGET: "dev" })).toThrow(SafetyError);
    expect(() => init(["plan", "--target", "prod", "--confirm-prod", PROD], { LH_API_TOKEN: "x" })).toThrow(SafetyError);
    expect(() => init(["plan"], { LH_API_TOKEN: "x", LH_TOKEN_TARGET: "prod" })).toThrow(SafetyError);
  });
  test("the CLI exits before any DB or network call when prod is requested without the confirm", async () => {
    const p = Bun.spawn(["bun", "run", "src/cli.ts", "plan", "--target", "prod", "--all"], { cwd: new URL("..", import.meta.url).pathname, env: { PATH: process.env.PATH ?? "", HOME: process.env.HOME ?? "" }, stdout: "pipe", stderr: "pipe" });
    const [err, code] = [await new Response(p.stderr).text(), await p.exited];
    expect(code).toBe(1); expect(err).toContain("--confirm-prod ilm.mkausa.org");
  });
});
