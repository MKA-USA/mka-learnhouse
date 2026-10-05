# Auto-enrol on first Google sign-in (seam A): technical notes

> Operational steps, env vars, kill switches and rollout live in the single runbook `docs/runbooks/mka-compliance-automation.md`. This file keeps only seam-specific technical detail.

Code: `apps/api/src/services/mka/automation_enroll.py`, called from `attributes.mka_refresh_on_login`. One indexed roster query by `lower(email)`; per org where the user is a member, default cycle; General + the department course of each role row; own session, one transaction per org, 10 s timeout, never raises into login. Does not fire `course_enrolled` or an audit row.

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
