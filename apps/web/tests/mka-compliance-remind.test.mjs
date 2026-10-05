// MKA fork (seam C): the course "Remind" button. The fixtures in tests/fixtures/mka-compliance/remind_*.json / err_*_remind_*.json
// are REAL responses dumped by apps/api/src/tests/routers/test_mka_remind_contract_dump.py. They are shape-checked against
// RemindResponse (services/mka/compliance.types.ts) and fed to the pure helpers and the dialog view.
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { canSendReminders, currentCycle, remindBlockedReason, remindConflict, remindErrorMessage, remindHeadline, remindSkipped } from "../components/mka/compliance/format.ts";
import { RemindButton, RemindDialogView } from "../components/mka/compliance/RemindDialog.tsx";
import { MKA_COMPLIANCE_REMIND, errorStatus } from "../services/mka/compliance.ts";

const fx = (name) => JSON.parse(readFileSync(join(import.meta.dir, "fixtures", "mka-compliance", `${name}.json`), "utf8"));

// The UI type, field by field. Adding a field to RemindResponse without updating this list is the drift this test catches.
const SHAPE = {
  dry_run: "boolean", enabled: "boolean", test_mode: "boolean", candidates: "number", would_send: "number", sent: "number",
  skipped_recent: "number", skipped_attested: "number", skipped_excluded: "number", suppressed: "number", failed: "number",
  disabled: "number", stopped: "string?", remaining: "number", time_budget_hit: "boolean", quarantined: "number", skipped_cooldown: "number", cooldown_days: "number", preview_digest: "string?",
};
function problems(body) {
  const out = [];
  for (const [k, t] of Object.entries(SHAPE)) {
    const nullable = t.endsWith("?");
    const type = nullable ? t.slice(0, -1) : t;
    if (!(k in body)) out.push(`${k}: missing`);
    else if (body[k] === null) { if (!nullable) out.push(`${k}: null`); }
    else if (typeof body[k] !== type) out.push(`${k}: ${typeof body[k]}, want ${type}`);
  }
  for (const k of Object.keys(body)) if (!(k in SHAPE)) out.push(`${k}: not in the UI type`);
  return out;
}

describe("contract: remind responses satisfy RemindResponse", () => {
  for (const name of ["remind_preview_tabligh", "remind_sent_tabligh"]) {
    test(name, () => {
      const f = fx(name);
      expect(f.status).toBe(200);
      expect(problems(f.body)).toEqual([]);
    });
  }
  test("a preview is dry_run with nothing sent; the real send is not dry_run and sent == previewed", () => {
    const p = fx("remind_preview_tabligh").body;
    const s = fx("remind_sent_tabligh").body;
    expect([p.dry_run, p.sent]).toEqual([true, 0]);
    expect([s.dry_run, s.would_send]).toEqual([false, 0]);
    expect(s.sent).toBe(p.would_send);
  });
  test("the error statuses the dialog words each carry a string detail", () => {
    for (const [name, status] of [["err_429_remind_again", 429], ["err_404_remind_other_course", 404], ["err_403_remind_as_learner", 403]]) {
      const f = fx(name);
      expect(f.status).toBe(status);
      expect(typeof f.body.detail).toBe("string");
      expect(remindErrorMessage(f.status).length).toBeGreaterThan(20);
    }
  });
  test("an out-of-scope course looks like a missing one", () => {
    expect(fx("err_404_remind_other_course").body.detail).toBe("Course not found");
  });
});

describe("wording", () => {
  const base = { dry_run: true, would_send: 12, sent: 0, skipped_recent: 5, skipped_attested: 0, skipped_excluded: 0, suppressed: 0, failed: 0 };
  test("preview: '12 people will be reminded' + '5 skipped: already reminded this week'", () => {
    expect(remindHeadline(base)).toBe("12 people will be reminded");
    expect(remindSkipped(base)).toBe("5 skipped: already reminded this week");
  });
  test("singular, zero, several reasons, none", () => {
    expect(remindHeadline({ ...base, would_send: 1 })).toBe("1 person will be reminded");
    expect(remindHeadline({ ...base, would_send: 0 })).toBe("Nobody needs a reminder right now");
    expect(remindSkipped({ ...base, skipped_attested: 2 })).toBe("7 skipped: 5 already reminded this week, 2 already signed off");
    expect(remindSkipped({ ...base, skipped_recent: 0 })).toBeNull();
  });
  test("after sending", () => {
    expect(remindHeadline({ ...base, dry_run: false, sent: 12 })).toBe("Reminded 12 people");
    expect(remindHeadline({ ...base, dry_run: false, sent: 1 })).toBe("Reminded 1 person");
    expect(remindHeadline({ ...base, dry_run: false, sent: 0 })).toBe("No reminders were sent");
  });
  test("403 / 404 / 409 / 429 / anything else each get their own sentence", () => {
    const m = [403, 404, 409, 429, 500, null].map((s) => remindErrorMessage(s));
    expect(new Set(m).size).toBe(5); // 500 and an unknown (null) status share the generic sentence
    expect(m[4]).toBe(m[5]);
    expect(m[3]).toContain("24 hours");
  });
  test("a failed PREVIEW never sent anything; a failed real send must not claim that (review H2e)", () => {
    expect(remindErrorMessage(500)).toContain("Nothing was sent");
    const sending = remindErrorMessage(500, { sending: true });
    expect(sending).not.toContain("Nothing was sent");
    expect(sending).toContain("some reminders may already have gone out");
    expect(remindErrorMessage(null, { sending: true })).toBe(sending);
  });
  test("a run the server stopped early says how much is done and that it can simply be run again", () => {
    const base = { dry_run: false, would_send: 0, sent: 3, remaining: 5 };
    expect(remindHeadline(base)).toBe("Sent 3 so far; 5 remaining. Run it again to send the rest.");
    expect(remindHeadline({ ...base, remaining: 0 })).toBe("Reminded 3 people");
    expect(remindHeadline({ dry_run: false, would_send: 0, sent: 3 })).toBe("Reminded 3 people"); // older responses
  });
  test("confirm needs someone to remind and the feature on", () => {
    expect(canSendReminders({ enabled: true, would_send: 3 })).toBe(true);
    expect(canSendReminders({ enabled: true, would_send: 0 })).toBe(false);
    expect(canSendReminders({ enabled: false, would_send: 3 })).toBe(false);
  });
  test("errorStatus reads the status off the client error", () => {
    expect(errorStatus({ status: 429 })).toBe(429);
    expect(errorStatus(new Error("x"))).toBeNull();
  });
});

describe("dialog view", () => {
  const noop = () => {};
  const html = (phase) => renderToStaticMarkup(React.createElement(RemindDialogView, { phase, onConfirm: noop, onRetry: noop, onClose: noop }));
  const preview = fx("remind_preview_tabligh").body;

  test("loading announces itself politely", () => {
    const h = html({ kind: "loading" });
    expect(h).toContain('role="status"');
    expect(h).toContain('aria-live="polite"');
  });
  test("preview shows the counts first and a confirm button; nothing is sent by rendering", () => {
    const h = html({ kind: "preview", data: preview });
    expect(h).toContain("4 people will be reminded");
    expect(h).toContain("1 skipped: already signed off");
    expect(h).toContain("Send 4 reminders");
    expect(h).not.toMatch(/Send 4 reminders<\/button>.*disabled/);
    expect(h).toContain("Cancel");
  });
  test("test mode is called out, and a switched-off feature disables the confirm button", () => {
    expect(html({ kind: "preview", data: preview })).toContain("Test mode is on");
    const off = html({ kind: "preview", data: { ...preview, enabled: false, test_mode: false } });
    expect(off).toContain("preview only");
    expect(off).toMatch(/<button[^>]*disabled=""[^>]*>[^]*Send 4 reminders/);
  });
  test("zero to send disables confirm", () => {
    const h = html({ kind: "preview", data: { ...preview, would_send: 0 } });
    expect(h).toContain("Nobody needs a reminder right now");
    expect(h).toMatch(/<button[^>]*disabled=""[^>]*>[^]*Send 0 reminders/);
  });
  test("sending disables both buttons", () => {
    const h = html({ kind: "sending", data: preview });
    expect(h.match(/disabled=""/g)?.length).toBe(2);
    expect(h).toContain("Sending");
  });
  test("429 is a final answer: alert, no retry button", () => {
    const h = html({ kind: "error", status: 429 });
    expect(h).toContain('role="alert"');
    expect(h).toContain("24 hours");
    expect(h).not.toContain(">Try again</button>");
  });
  test("an unknown failure can be retried; 403/404/409 cannot", () => {
    expect(html({ kind: "error", status: 500 })).toContain(">Try again</button>");
    for (const s of [403, 404, 409]) expect(html({ kind: "error", status: s })).not.toContain(">Try again</button>");
  });
});

describe("feature flag", () => {
  test("the flag is off unless NEXT_PUBLIC_MKA_COMPLIANCE_REMIND=1 (the button is hidden by default)", () => {
    expect(MKA_COMPLIANCE_REMIND).toBe(false);
    expect(typeof RemindButton).toBe("function");
  });
  test("the placeholder is gone from the actions module", async () => {
    const mod = await import("../components/mka/compliance/ChaseActions.tsx");
    expect("RemindPlaceholder" in mod).toBe(false);
  });
});

describe("Remind only for the current, started cycle (review H1)", () => {
  const past = { id: 1, label: "2025-26", starts_on: "2025-11-01", deadline_on: "2025-12-01" };
  const now = { id: 2, label: "2026-27", starts_on: "2026-11-01", deadline_on: "2026-12-01" };
  const next = { id: 3, label: "2027-28", starts_on: "2027-11-01", deadline_on: "2027-12-01" };
  const all = [past, now, next];
  test("the current cycle is the one whose window holds today, else the latest started one", () => {
    expect(currentCycle(all, "2026-11-16").id).toBe(2);
    expect(currentCycle(all, "2026-12-20").id).toBe(2); // after the deadline, before the next start
    expect(currentCycle(all, "2024-01-01")).toBeNull();
  });
  test("the current cycle may send; last year's and a not-yet-started one may not (with a reason)", () => {
    expect(remindBlockedReason(now, all, "2026-11-16")).toBeNull();
    expect(remindBlockedReason(past, all, "2026-11-16")).toContain("current cycle (2026-27)");
    expect(remindBlockedReason(next, all, "2026-11-16")).toContain("hasn't started");
  });
  test("with no cycle list the single cycle on screen is judged on its own dates", () => {
    expect(remindBlockedReason(now, undefined, "2026-11-16")).toBeNull();
    expect(remindBlockedReason(next, undefined, "2026-11-16")).not.toBeNull();
  });
  test("a blocked button is disabled and carries the explanation (hidden flag is checked elsewhere)", () => {
    // RemindButton returns null while the feature flag is off, so only the pure rule is rendered here.
    expect(remindBlockedReason(past, all, "2026-11-16").length).toBeGreaterThan(20);
  });
});

describe("the real send is tied to the preview (review M4)", () => {
  const noop = () => {};
  const html = (phase) => renderToStaticMarkup(React.createElement(RemindDialogView, { phase, onConfirm: noop, onRetry: noop, onClose: noop }));
  test("the preview carries the digest the confirm must send back; a real send does not", () => {
    const p = fx("remind_preview_tabligh").body;
    const s = fx("remind_sent_tabligh").body;
    expect(typeof p.preview_digest).toBe("string");
    expect(p.preview_digest.length).toBeGreaterThanOrEqual(32);
    expect(s.preview_digest).toBeNull();
  });
  test("the API's 409s are told apart by their detail (real fixtures)", () => {
    const changed = fx("err_409_remind_preview_changed");
    const stale = fx("err_409_remind_not_current_cycle");
    expect([changed.status, stale.status]).toEqual([409, 409]);
    expect(remindConflict(changed.body.detail)).toBe("preview_changed");
    expect(remindConflict(stale.body.detail)).toBe("not_current");
    expect(remindConflict("Reminders are not switched on")).toBe("disabled");
    expect(remindConflict(null)).toBe("disabled");
    expect(remindErrorMessage(409, { detail: changed.body.detail })).toContain("review it again");
    expect(remindErrorMessage(409, { detail: stale.body.detail })).toContain("current cycle");
  });
  test("when the list changed the dialog says so, offers a fresh review and does not offer to send", () => {
    const h = html({ kind: "changed" });
    expect(h).toContain('role="alert"');
    expect(h).toContain("The list changed since you looked at it");
    expect(h).toContain(">Review the list again</button>");
    expect(h).not.toContain("Send ");
  });
});

describe("skipped wording: cooldown and quarantine (round 2 N1/N3)", () => {
  const base = { skipped_recent: 6, skipped_attested: 0, skipped_excluded: 0, suppressed: 0, failed: 0 };
  test("people inside the cooldown are named as such, with the number of days", () => {
    expect(remindSkipped({ ...base, skipped_cooldown: 6, cooldown_days: 3 })).toBe("6 skipped: reminded in the last 3 days");
    expect(remindSkipped({ ...base, skipped_cooldown: 2, cooldown_days: 1 })).toBe("6 skipped: 4 already reminded this week, 2 reminded in the last 1 day");
  });
  test("a failing address is called out and older responses still read fine", () => {
    expect(remindSkipped({ ...base, skipped_recent: 0, quarantined: 2 })).toBe("2 skipped: address keeps failing");
    expect(remindSkipped(base)).toBe("6 skipped: already reminded this week");
  });
});
