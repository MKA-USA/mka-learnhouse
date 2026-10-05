export const env = {
  fixtureMode: () => process.env.DASHBOARD_FIXTURE_MODE === "1" && process.env.NODE_ENV !== "production",
  asOf: () => process.env.DASHBOARD_AS_OF || "2026-11-18",
  allowedDomain: () => (process.env.ALLOWED_EMAIL_DOMAIN || "mkausa.org").toLowerCase(),
  adminEmails: () => (process.env.DASHBOARD_ADMIN_EMAILS || "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean),
};
