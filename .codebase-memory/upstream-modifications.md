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

### Google-only email domains (`MKA_GOOGLE_ONLY_DOMAINS`)

- **Date**: 2026-10-03
- **Reason**: Google SSO stays open to all, but addresses in the configured domains (mkausa.org) must authenticate only via Google (so Workspace suspension removes access) and must carry the Workspace `hd` claim. No extension points exist in these upstream functions, so each gets a 1-2 line call. All logic is in the new fork-only file `apps/api/src/services/auth/mka_google_only.py`; tests in `apps/api/src/tests/services/auth/test_mka_google_only.py`. Unset env = no-op.
- **Hook sites and diffs**:

1. `apps/api/src/services/auth/utils.py` (Google path, `hd` requirement)
```diff
+from src.services.auth.mka_google_only import require_workspace_hd  # MKA fork
@@ in signWithGoogle, directly after `user_email = google_email.strip().lower()`
+    require_workspace_hd(user_email, google_user.get("hd"))  # MKA fork
```
2. `apps/api/src/services/auth/session.py` (central chokepoint: password login, magic-link verify, email-verification auto-signin, admin magic link all pass through it)
```diff
-from src.security.session_context import AMR_CLAIM, SORG_CLAIM, session_claims
+from src.security.session_context import AMR_CLAIM, AUTH_METHOD_GOOGLE, SORG_CLAIM, session_claims
+from src.services.auth.mka_google_only import block_non_google_auth  # MKA fork
@@ first lines of issue_session_or_challenge body (after docstring)
+    if amr != AUTH_METHOD_GOOGLE:  # MKA fork
+        block_non_google_auth(user.email)
```
3. `apps/api/src/routers/auth.py` (early login block, before password verification; magic-link request)
```diff
+from src.services.auth.mka_google_only import block_non_google_auth, is_google_only_email  # MKA fork
@@ login(), before "# Step 2: Authenticate"
+    block_non_google_auth(username)  # MKA fork
@@ magic_link_request(), right after `generic = {...}`
+    if is_google_only_email(str(body.email)):  # MKA fork
+        return generic
```
4. `apps/api/src/services/users/users.py` (email/password signup incl. invite signup, which calls create_user; email change)
```diff
+from src.services.auth.mka_google_only import block_email_change, block_non_google_auth  # MKA fork
@@ create_user() and create_user_without_org(), first statement of body
+    if not is_oauth:  # MKA fork
+        block_non_google_auth(user_object.email)
@@ update_user(), just before "# Update user; strip protected fields..."
+    block_email_change(user.email, user_object.email)  # MKA fork
```
5. `apps/api/src/services/users/password_reset.py` (4 functions)
```diff
+from src.services.auth.mka_google_only import block_non_google_auth, is_google_only_email  # MKA fork
@@ send_reset_password_code() and send_reset_password_code_platform(), first statement
+    if is_google_only_email(email):  # MKA fork: issue nothing, same response
+        return "If an account with that email exists, a reset code has been sent"
@@ change_password_with_reset_code() and change_password_with_reset_code_platform(), first statement
+    block_non_google_auth(email)  # MKA fork
```

- **Not hooked (by design)**: `services/admin/admin.py` admin-API user creation with a password and `services/setup/setup.py` first-run setup (operator actions; the password cannot be used to log in for these domains anyway, since login is blocked at hooks 2 and 3); `update_user_password` (logged-in change; resulting password is unusable for login).
- **Re-apply after pulling upstream**: re-add each hook at the location named above. Verify with `grep -rn "MKA fork" apps/api/src` (expect 17 lines, including the new module docstring) and run `uv run pytest src/tests/services/auth/test_mka_google_only.py` in apps/api.
- **Upstream PR**: none


---

**Reminder**: Before modifying an upstream file, verify that no extension point, plugin, or wrapper approach exists. Document the change here immediately after making it.
