# Auto-enrol on first Google sign-in (seam A)

Code: `apps/api/src/services/mka/automation_enroll.py`, called from `attributes.mka_refresh_on_login` (fork-owned).
Spec: `docs/superpowers/specs/2026-10-05-mka-compliance-automation-design.md` section 2 A.

## Switches
Both must be `true`: `MKA_AUTOMATION_ENABLED` (master) and `MKA_AUTOENROLL_ENABLED`. Either off = complete no-op
(no query, no event). Rollback = unset either flag; no migration involved.

## What it does
On a Google sign-in, after the attribute refresh succeeds, if the account's address is **proven**
(`is_address_proven`: fresh row, `verified_hd` = domain of `email_seen`, `email_seen` = current email):
1. ONE indexed query: `mka_compliance_expected` by `lower(email)`. No match = exit (the common case).
2. Per org on the roster where the user is a member: default cycle (`get_cycle`, same logic as the dashboard);
   only roster rows of that cycle count.
3. Courses: the cycle's General course + the department course for EACH role row (deduped). Executive / national
   rows with no department course get General only.
4. Draft (unpublished) courses are skipped and recorded as `skipped_unpublished` (once per user+course). The next
   login after the course is published, or `reconcile`, enrols them.
5. Enrolment = learner `Trail` (advisory lock `mka-enrol:<user>:<org>` plus in-process lock) and
   `INSERT ... ON CONFLICT DO NOTHING` `TrailRun`, in its own session and one transaction per org.
   It does not fire the `course_enrolled` webhook or an audit row.

Never enrols: unproven accounts (non-Google signup, email changed since the proof, no `verified_hd`, stale row),
non-members of the roster's org, or into another org's courses.

## Events (`mka_automation_event`, event = `autoenroll`)
`processed` (note `enrolled:<n>`), `skipped_unpublished` (course_uuid), `ignored` (note `not_member` | `no_cycle` |
`not_on_active_roster`), `error` (note `enrol_failed`; the org's enrolment rolled back, retried next login).
Delivery id `autoenroll:<uuid>`. No addresses, no payloads. Unproven / no-match logins write nothing.

## Dry run
```python
async with session_factory() as s:
    plan = await plan_autoenroll(s, user)   # user: anything with .id and .email; read-only
    plan.reason, [(o.org_id, o.enroll, o.skipped_unpublished, o.reason) for o in plan.orgs]
```

## Troubleshooting
* "Not enrolled": `plan.reason` = `no_match` (email not on a roster) or `unproven`; check the user's
  `mka_user_attributes` row and the org's membership; check the course `published` flag.
* Look at `select status, note, course_uuid from mka_automation_event where event='autoenroll' and user_id=<id>`.
* Failures are logged (`MKA auto-enrol failed`) and never block login; 10 s hard timeout.
