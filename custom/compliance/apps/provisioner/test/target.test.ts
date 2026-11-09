import { describe, expect, test } from "bun:test";
import { SafetyError, TARGETS } from "@mka/compliance-core";
import { parseArgs } from "../src/args";
import { confirmHint, currentTarget, initTarget, outSubdir, writeOk } from "../src/target";

const PROD = TARGETS.prod.host;
const init = (argv: string[], env: Record<string, string | undefined> = {}) => initTarget(parseArgs(argv), env);

describe("provisioner target selection", () => {
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
  test("prod with the exact confirm: prod host, separate out/prod, prod write gate", () => {
    const t = init(["apply", "--target", "prod", "--confirm-prod", PROD, "--all"], { LH_API_TOKEN: "x", LH_TOKEN_TARGET: "prod" });
    expect(t).toMatchObject({ name: "prod", host: PROD }); expect(outSubdir()).toBe("prod");
    expect(writeOk(parseArgs(["apply"]))).toBe(true); expect(confirmHint()).toBe(`--confirm-prod ${PROD}`);
    init([]); // back to dev for the other tests
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
