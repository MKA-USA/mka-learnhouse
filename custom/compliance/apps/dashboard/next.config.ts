import path from "node:path";
import type { NextConfig } from "next";

// The app imports pure TS from ../../packages/analytics (and a department list from ../../packages/core),
// so the tracing/turbopack root is custom/compliance.
const root = path.resolve(__dirname, "../..");
const config: NextConfig = {
  outputFileTracingRoot: root,
  turbopack: { root },
  poweredByHeader: false,
  // stops Next writing AGENTS.md/CLAUDE.md into the app dir
  agentRules: false,
  async headers() {
    return [{ source: "/:path*", headers: [
      { key: "X-Frame-Options", value: "DENY" },
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "same-origin" },
      { key: "Cache-Control", value: "private, no-store" },
    ] }];
  },
};
export default config;
