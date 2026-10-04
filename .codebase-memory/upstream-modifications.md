# Upstream File Modifications Log

This file tracks any modifications made to upstream-owned files that could cause merge conflicts when pulling new releases.

## Format

Each entry should include:
- **File**: path to the modified file
- **Date**: when the modification was made
- **Reason**: why the modification was necessary (why no extension point exists)
- **Diff**: the exact changes made (so they can be re-applied after pulling upstream)
- **Upstream PR**: link to upstream PR if this was contributed back

## Current Modifications

### apps/api/src/services/auth/utils.py (Google SSO domain allowlist)

- **Date**: 2026-10-03
- **Reason**: `signWithGoogle` has no hook between establishing the verified email and the user lookup/creation, so the allowlist check must be called inline. All logic lives in the new file `apps/api/src/services/auth/mka_domain_guard.py` (env `MKA_GOOGLE_ALLOWED_DOMAINS`; unset = no restriction).
- **Diff** (2 added lines):

```diff
 from src.db.user_audit_events import UserAuditEventType
+from src.services.auth.mka_domain_guard import enforce_allowed_google_domain
@@ in signWithGoogle
     user_email = google_email.strip().lower()
+    enforce_allowed_google_domain(user_email, google_user.get("hd"))  # MKA fork
```

- **Re-apply after pulling upstream**: if a conflict occurs, add the import at the top of `utils.py`, and add the call directly after `user_email = google_email.strip().lower()` in `signWithGoogle` (before any DB lookup). Confirm with `grep -n enforce_allowed_google_domain apps/api/src/services/auth/utils.py` and run `uv run pytest src/tests/services/auth/test_mka_domain_guard.py` in apps/api.
- **Upstream PR**: none


---

**Reminder**: Before modifying an upstream file, verify that no extension point, plugin, or wrapper approach exists. Document the change here immediately after making it.
