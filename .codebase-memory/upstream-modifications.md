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


### Majlis / Region profile fields (`mka_user_profile` side table)

- **Date**: 2026-10-04
- **Reason**: Capture Majlis (required), derived Region, and optional Mobile / AMC ID / Tanzeem at signup, and gate users who lack a profile. All logic is fork-only (file list in section D); upstream files get 1-3 line `MKA fork` hooks. Region is always derived server-side. Spec: `docs/superpowers/specs/2026-10-04-mka-profile-fields-design.md`.
- **Diff base**: `74807657` (origin/dev); regenerate with `git diff 74807657..HEAD -- <file>`.

#### A. Source hooks (upstream-owned files, edited)

1. `apps/api/src/db/users.py`
   - **Why / no extension point**: `UserCreate` gains one optional `mka_profile: Optional[dict]` field so signup payloads can carry the profile. No extension point: a pydantic model field has to live on the class. Profile data is stored in the fork-only side table, never in `extra_metadata`.

```diff
diff --git a/apps/api/src/db/users.py b/apps/api/src/db/users.py
index a818aed1..0847d2cd 100644
--- a/apps/api/src/db/users.py
+++ b/apps/api/src/db/users.py
@@ -34,6 +34,8 @@ class UserCreate(UserBase):
     # request could write an arbitrary blob. Values here are validated against
     # the org's declared fields before anything is stored.
     custom_fields: Optional[dict] = None
+    # MKA fork: Majlis/Region profile (validated in services/users/mka_profile.py)
+    mka_profile: Optional[dict] = None
 
 
 class UserUpdate(UserBase):
```

2. `apps/api/src/services/users/users.py`
   - **Why / no extension point**: 1 import, plus in each of `create_user()` and `create_user_without_org()`: `validate_signup_profile` directly AFTER the `rbac_check(...)` line (moved there in the fix wave so a forbidden signup answers 403, never a 409 AMC-ID oracle; still BEFORE the user row exists) and `save_signup_profile` right after the user commit/refresh. `create_user_with_invite` calls `create_user`, so it needs no hook. No extension point: the create functions have no hook registry. The import sits next to the Google-only import from the 2026-10-03 entry.

```diff
diff --git a/apps/api/src/services/users/users.py b/apps/api/src/services/users/users.py
index 24b06f32..268462a6 100644
--- a/apps/api/src/services/users/users.py
+++ b/apps/api/src/services/users/users.py
@@ -16,6 +16,7 @@ from src.security.features_utils.usage import (
 from src.core.deployment_mode import get_deployment_mode
 from src.services.users.usergroups import add_users_to_usergroup
 from src.services.auth.mka_google_only import block_email_change, block_non_google_auth  # MKA fork
+from src.services.users.mka_profile import save_signup_profile, validate_signup_profile  # MKA fork
 from src.services.users.emails import (
     send_account_creation_email,
 )
@@ -203,6 +204,7 @@ async def create_user(
 
     # RBAC check
     await rbac_check(request, current_user, "create", "user_x", db_session)
+    mka_profile = await validate_signup_profile(db_session, user_object.mka_profile, is_oauth)  # MKA fork
 
     # Complete the user object
     user.user_uuid = f"user_{uuid4()}"
@@ -277,6 +279,7 @@ async def create_user(
     db_session.add(user)
     await db_session.commit()
     await db_session.refresh(user)
+    await save_signup_profile(db_session, user, mka_profile)  # MKA fork
 
     # Link user and organization
     user_organization = UserOrganization(
@@ -453,6 +456,7 @@ async def create_user_without_org(
 
     # RBAC check
     await rbac_check(request, current_user, "create", "user_x", db_session)
+    mka_profile = await validate_signup_profile(db_session, user_object.mka_profile, is_oauth)  # MKA fork
 
     # Complete the user object
     user.user_uuid = f"user_{uuid4()}"
@@ -505,6 +509,7 @@ async def create_user_without_org(
     db_session.add(user)
     await db_session.commit()
     await db_session.refresh(user)
+    await save_signup_profile(db_session, user, mka_profile)  # MKA fork
 
     user_read = UserRead.model_validate(user)
```

2b. `apps/api/src/services/admin/admin.py` (GDPR; added in the fix wave)
   - **Why / no extension point**: 1 import + 2 one-line hooks. `export_user_data` adds an `"mka_profile"` key (the `profile_status` output) so the GDPR export includes the profile; `anonymize_user` calls `delete_profile(...)` BEFORE its commit so the profile row (mobile, AMC ID, Majlis) is deleted atomically with the scrub and the AMC ID is freed. Hard user delete needs nothing (DB FK cascade). No extension point: both functions build their result/transaction inline.

```diff
diff --git a/apps/api/src/services/admin/admin.py b/apps/api/src/services/admin/admin.py
index 610df4a7..9dc843fa 100644
--- a/apps/api/src/services/admin/admin.py
+++ b/apps/api/src/services/admin/admin.py
@@ -34,6 +34,7 @@ from src.db.usergroups import UserGroup, UserGroupRead
 from src.db.user_organizations import UserOrganization
 from src.db.users import APITokenUser, User, UserRead
 from src.services.trail.trail import _build_trail_read
+from src.services.users.mka_profile import delete_profile, profile_status  # MKA fork
 from src.services.courses.certifications import (
     check_course_completion_and_create_certificate,
     is_course_fully_completed,
@@ -2432,6 +2433,7 @@ async def export_user_data(
         "user_groups": [
             UserGroupRead.model_validate(g).model_dump() for g, _ in group_rows
         ],
+        "mka_profile": await profile_status(db_session, user_id),  # MKA fork
         "exported_at": datetime.now().isoformat(),
     }
 
@@ -2486,6 +2488,7 @@ async def anonymize_user(
     user.signup_method = "anonymized"
     user.update_date = str(datetime.now())
     db_session.add(user)
+    await delete_profile(db_session, user_id)  # MKA fork
     await db_session.commit()
 
     try:
```

3. `apps/api/src/router.py`
   - **Why / no extension point**: 1 import + 1 `include_router` (prefix `/mka/profile`, `get_non_api_token_user` dependency) for the fork router. No router plugin registry.

```diff
diff --git a/apps/api/src/router.py b/apps/api/src/router.py
index 6a0a747b..8c6f2452 100644
--- a/apps/api/src/router.py
+++ b/apps/api/src/router.py
@@ -11,6 +11,7 @@ from src.routers import plans
 from src.routers import usergroups
 from src.routers import dev, trail, users, auth, orgs, roles, search
 from src.routers import mfa as mfa_router_module
+from src.routers import mka_profile as mka_profile_router_module  # MKA fork
 from src.routers import monitoring
 from src.routers import nudges as nudges_router_module
 from src.routers import stream
@@ -71,6 +72,12 @@ v1_router.include_router(
     tags=["users"],
     dependencies=[Depends(get_non_api_token_user)]
 )
+v1_router.include_router(  # MKA fork
+    mka_profile_router_module.router,
+    prefix="/mka/profile",
+    tags=["mka-profile"],
+    dependencies=[Depends(get_non_api_token_user)],
+)
 v1_router.include_router(
     usergroups.router,
     prefix="/usergroups",
```

4. `apps/web/app/api/signup/route.ts`
   - **Why / no extension point**: Add `mka_profile` to `SignupBody`, destructure it, forward ONLY four string/null keys (majlis, mobile, amc_id, tanzeem; never spread client input). No extension point in the Next route.

```diff
diff --git a/apps/web/app/api/signup/route.ts b/apps/web/app/api/signup/route.ts
index 62d64fa1..87328e85 100644
--- a/apps/web/app/api/signup/route.ts
+++ b/apps/web/app/api/signup/route.ts
@@ -29,6 +29,8 @@ interface SignupBody {
   bio?: string
   /** Answers to the org's admin-defined signup fields, keyed by field key. */
   custom_fields?: Record<string, unknown>
+  // MKA fork
+  mka_profile?: { majlis?: string; mobile?: string | null; amc_id?: string | null; tanzeem?: string | null }
   turnstileToken?: string | null
   inviteCode?: string
 }
@@ -53,6 +55,7 @@ export async function POST(request: NextRequest) {
     last_name,
     bio,
     custom_fields,
+    mka_profile, // MKA fork
   } = body
 
   if (!email || !password || !username) {
@@ -107,6 +110,17 @@ export async function POST(request: NextRequest) {
     last_name,
     bio,
     ...(custom_fields ? { custom_fields } : {}),
+    // MKA fork: forward only the four known profile keys (never spread client input)
+    ...(mka_profile && typeof mka_profile === 'object'
+      ? {
+          mka_profile: {
+            majlis: typeof mka_profile.majlis === 'string' ? mka_profile.majlis : undefined,
+            mobile: mka_profile.mobile === null ? null : typeof mka_profile.mobile === 'string' ? mka_profile.mobile : undefined,
+            amc_id: mka_profile.amc_id === null ? null : typeof mka_profile.amc_id === 'string' ? mka_profile.amc_id : undefined,
+            tanzeem: mka_profile.tanzeem === null ? null : typeof mka_profile.tanzeem === 'string' ? mka_profile.tanzeem : undefined,
+          },
+        }
+      : {}),
   }
 
   let url: string
```

5. `apps/web/app/auth/signup/OpenSignup.tsx`
   - **Why / no extension point**: Imports, Formik initial value + validation, send the API-shaped body, map server errors with fork helper `applyMkaServerErrors`, render `<MkaProfileFields/>`. No slot mechanism in the signup form.

```diff
diff --git a/apps/web/app/auth/signup/OpenSignup.tsx b/apps/web/app/auth/signup/OpenSignup.tsx
index feb25160..7eaf2759 100644
--- a/apps/web/app/auth/signup/OpenSignup.tsx
+++ b/apps/web/app/auth/signup/OpenSignup.tsx
@@ -18,6 +18,8 @@ import { PasswordStrengthIndicator, validatePasswordStrength } from '@components
 import TurnstileWidget, { useTurnstileRequired, type TurnstileWidgetHandle } from '@components/Auth/TurnstileWidget'
 import { useLHAnalytics, AnalyticsEvent } from '@services/analytics'
 import { getAllowedAuthMethods } from '@services/auth/authMethods'
+import MkaProfileFields from '@components/mka/MkaProfileFields' // MKA fork
+import { emptyMkaProfile, validateMkaProfile, mkaValuesToBody, applyMkaServerErrors } from '@services/mka/profile' // MKA fork
 import CustomSignupFields, {
   initialCustomFieldValues,
   validateCustomFields,
@@ -56,6 +58,10 @@ const validate = (values: any, t: any, customFields: SignupFieldItem[]) => {
     errors.custom_fields = customFieldErrors
   }
 
+  // MKA fork
+  const mkaErrors = validateMkaProfile(values.mka_profile)
+  if (Object.keys(mkaErrors).length > 0) errors.mka_profile = mkaErrors
+
   return errors
 }
 
@@ -105,6 +111,7 @@ function OpenSignUpComponent({ org: propOrg }: OpenSignUpComponentProps = {}) {
       first_name: '',
       last_name: '',
       custom_fields: initialCustomFieldValues(customFields),
+      mka_profile: { ...emptyMkaProfile }, // MKA fork
       turnstileToken: null as string | null,
     },
     validate: (values) => validate(values, t, customFields),
@@ -115,7 +122,9 @@ function OpenSignUpComponent({ org: propOrg }: OpenSignUpComponentProps = {}) {
       setIsSubmitting(true)
       track(AnalyticsEvent.SignupSubmitted, { invite_code_present: false, has_bio: !!values.bio })
       try {
-        let res = await signup(values)
+        // MKA fork: send the API-shaped profile (empty optionals -> null)
+        const body = { ...values, mka_profile: mkaValuesToBody(values.mka_profile) }
+        let res = await signup(body)
         let message = await res.json().catch(() => ({}))
         if (res.status == 200) {
           track(AnalyticsEvent.SignupSucceeded, { email_verified: message.email_verified })
@@ -128,6 +137,7 @@ function OpenSignUpComponent({ org: propOrg }: OpenSignUpComponentProps = {}) {
           // gave us nothing readable.
           track(AnalyticsEvent.SignupFailed, { status_code: res.status })
           setError(getErrorMessage(message?.detail, t('common.something_went_wrong')))
+          applyMkaServerErrors(res.status, message?.detail, formik.setFieldError) // MKA fork
           // Turnstile tokens are single-use — fetch a fresh one for the retry.
           turnstileRef.current?.reset()
         }
@@ -371,6 +381,16 @@ function OpenSignUpComponent({ org: propOrg }: OpenSignUpComponentProps = {}) {
           </FormField>
 
           <CustomSignupFields fields={customFields} formik={formik} />
+          {/* MKA fork */}
+          <MkaProfileFields
+            idPrefix="signup"
+            values={formik.values.mka_profile}
+            errors={formik.touched.mka_profile || formik.submitCount > 0 ? formik.errors.mka_profile : undefined}
+            onChange={(field, value) => {
+              formik.setFieldValue(`mka_profile.${field}`, value)
+              formik.setFieldTouched('mka_profile', true, false)
+            }}
+          />
 
           <TurnstileWidget
             ref={turnstileRef}
```

6. `apps/web/app/auth/signup/InviteOnlySignUp.tsx`
   - **Why / no extension point**: Same touches as OpenSignup.tsx (invite flow has its own form).

```diff
diff --git a/apps/web/app/auth/signup/InviteOnlySignUp.tsx b/apps/web/app/auth/signup/InviteOnlySignUp.tsx
index 0dfac71b..d95a4159 100644
--- a/apps/web/app/auth/signup/InviteOnlySignUp.tsx
+++ b/apps/web/app/auth/signup/InviteOnlySignUp.tsx
@@ -17,6 +17,8 @@ import { useTranslation } from 'react-i18next'
 import { PasswordStrengthIndicator, validatePasswordStrength } from '@components/Auth/PasswordStrengthIndicator'
 import TurnstileWidget, { useTurnstileRequired, type TurnstileWidgetHandle } from '@components/Auth/TurnstileWidget'
 import { useLHAnalytics, AnalyticsEvent } from '@services/analytics'
+import MkaProfileFields from '@components/mka/MkaProfileFields' // MKA fork
+import { emptyMkaProfile, validateMkaProfile, mkaValuesToBody, applyMkaServerErrors } from '@services/mka/profile' // MKA fork
 import CustomSignupFields, {
   initialCustomFieldValues,
   validateCustomFields,
@@ -55,6 +57,10 @@ const validate = (values: any, t: any, customFields: SignupFieldItem[]) => {
     errors.custom_fields = customFieldErrors
   }
 
+  // MKA fork
+  const mkaErrors = validateMkaProfile(values.mka_profile)
+  if (Object.keys(mkaErrors).length > 0) errors.mka_profile = mkaErrors
+
   return errors
 }
 
@@ -95,6 +101,7 @@ function InviteOnlySignUpComponent(props: InviteOnlySignUpProps) {
       first_name: '',
       last_name: '',
       custom_fields: initialCustomFieldValues(customFields),
+      mka_profile: { ...emptyMkaProfile }, // MKA fork
       turnstileToken: null as string | null,
     },
     validate: (values) => validate(values, t, customFields),
@@ -105,7 +112,9 @@ function InviteOnlySignUpComponent(props: InviteOnlySignUpProps) {
       setIsSubmitting(true)
       track(AnalyticsEvent.SignupSubmitted, { invite_code_present: true, has_bio: !!values.bio })
       try {
-        let res = await signUpWithInviteCode(values, props.inviteCode)
+        // MKA fork: send the API-shaped profile (empty optionals -> null)
+        const body = { ...values, mka_profile: mkaValuesToBody(values.mka_profile) }
+        let res = await signUpWithInviteCode(body, props.inviteCode)
         let message = await res.json().catch(() => ({}))
         if (res.status == 200) {
           track(AnalyticsEvent.SignupSucceeded, { email_verified: message.email_verified })
@@ -115,6 +124,7 @@ function InviteOnlySignUpComponent(props: InviteOnlySignUpProps) {
           // masking everything past a few statuses behind a generic message.
           track(AnalyticsEvent.SignupFailed, { status_code: res.status })
           setError(getErrorMessage(message?.detail, t('common.something_went_wrong')))
+          applyMkaServerErrors(res.status, message?.detail, formik.setFieldError) // MKA fork
           // Turnstile tokens are single-use — fetch a fresh one for the retry.
           turnstileRef.current?.reset()
         }
@@ -337,6 +347,16 @@ function InviteOnlySignUpComponent(props: InviteOnlySignUpProps) {
           </FormField>
 
           <CustomSignupFields fields={customFields} formik={formik} />
+          {/* MKA fork */}
+          <MkaProfileFields
+            idPrefix="signup"
+            values={formik.values.mka_profile}
+            errors={formik.touched.mka_profile || formik.submitCount > 0 ? formik.errors.mka_profile : undefined}
+            onChange={(field, value) => {
+              formik.setFieldValue(`mka_profile.${field}`, value)
+              formik.setFieldTouched('mka_profile', true, false)
+            }}
+          />
 
           <TurnstileWidget
             ref={turnstileRef}
```

7. `apps/web/app/orgs/[orgslug]/layout.tsx`
   - **Why / no extension point**: Import + mount `<MkaProfileGate />` immediately before `<CompleteSignupFields />`. The org layout is the only mount point (the `(hub)` layout is SaaS-only and deliberately NOT hooked).

```diff
diff --git a/apps/web/app/orgs/[orgslug]/layout.tsx b/apps/web/app/orgs/[orgslug]/layout.tsx
index e1c21c51..5a341679 100644
--- a/apps/web/app/orgs/[orgslug]/layout.tsx
+++ b/apps/web/app/orgs/[orgslug]/layout.tsx
@@ -7,6 +7,7 @@ import Toast from '@components/Objects/StyledElements/Toast/Toast'
 import '@styles/globals.css'
 import Footer from '@components/Footer/Footer'
 import CompleteSignupFields from '@components/Auth/CompleteSignupFields'
+import MkaProfileGate from '@components/mka/MkaProfileGate' // MKA fork
 import { getOrganizationContextInfo } from '@services/organizations/orgs'
 import { getOrgFaviconMediaDirectory } from '@services/media/media'
 
@@ -45,6 +46,7 @@ export default async function RootLayout(props: {
         <OrgLanguageSync />
         <NextTopLoader color="#2e2e2e" initialPosition={0.3} height={4} easing={'ease'} speed={500} showSpinner={false} />
         <Toast />
+        <MkaProfileGate /> {/* MKA fork */}
         <CompleteSignupFields />
         {props.children}
         <Footer />
```

8. `apps/e2e/core/client.ts`
   - **Why / no extension point**: `createStudent` posts `mka_profile: { majlis: 'Zion' }` because the backend now requires a Majlis for non-OAuth signup; without it e2e student creation returns 422.

```diff
diff --git a/apps/e2e/core/client.ts b/apps/e2e/core/client.ts
index 20a72e4e..9bd71b07 100644
--- a/apps/e2e/core/client.ts
+++ b/apps/e2e/core/client.ts
@@ -90,6 +90,7 @@ export async function createStudent(
     password: student.password,
     first_name: student.first_name ?? '',
     last_name: student.last_name ?? '',
+    mka_profile: { majlis: 'Zion' }, // MKA fork: backend requires a Majlis for non-OAuth signup
   })
   return user.id
 }
```

##### `apps/web/components/Dashboard/Pages/Users/OrgUsers/OrgUsers.tsx` (admin profile edit, 4 `MKA fork` markers)

Why no extension point: the members table has no row-action slot or plugin API, so a button in the actions cell and a dialog mount are the minimum. Logic lives in the fork-only `components/mka/MkaProfileEditDialog.tsx`. The button shows only for `canManageOrg` (organizations.action_update: org admin / superadmin), the strictest signal `useAdminStatus` offers; the backend still enforces ADMIN-only and the dialog shows its 403 message. Verbatim `git diff 74807657..HEAD`:

```diff
diff --git a/apps/web/components/Dashboard/Pages/Users/OrgUsers/OrgUsers.tsx b/apps/web/components/Dashboard/Pages/Users/OrgUsers/OrgUsers.tsx
index e683a01a..594b7bb6 100644
--- a/apps/web/components/Dashboard/Pages/Users/OrgUsers/OrgUsers.tsx
+++ b/apps/web/components/Dashboard/Pages/Users/OrgUsers/OrgUsers.tsx
@@ -25,6 +25,7 @@ import { useQuery, useQueryClient } from '@tanstack/react-query'
 import { queryKeys } from '@/lib/query/keys'
 import { readSignupFields } from '@services/settings/org'
 import { useTranslation } from 'react-i18next'
+import MkaProfileEditDialog from '@components/mka/MkaProfileEditDialog' // MKA fork
 import {
   Select,
   SelectContent,
@@ -81,6 +82,7 @@ function OrgUsers() {
   // Per-student analytics (integrated into this Users list)
   const [analyticsUserId, setAnalyticsUserId] = useState<number | null>(null)
   const [comparing, setComparing] = useState(false)
+  const [mkaEdit, setMkaEdit] = useState<{ id: number; name: string } | null>(null) // MKA fork
 
   const buildQuery = () => {
     const params = new URLSearchParams()
@@ -757,6 +759,18 @@ function OrgUsers() {
                                 <ExternalLink className="w-3.5 h-3.5" />
                               </Link>
                             </ToolTip>
+                          {/* MKA fork: admin-only (canManageOrg = org admin / superadmin) */}
+                          {canManageOrg && (
+                            <button
+                              onClick={() => setMkaEdit({ id: user.user.id, name: `${user.user.first_name} ${user.user.last_name}`.trim() || user.user.username })}
+                              className="inline-flex items-center gap-1.5 h-8 px-3 bg-white text-gray-600 hover:bg-indigo-50 hover:text-indigo-600 rounded-md text-xs font-medium nice-shadow transition-all"
+                              aria-label="Edit profile"
+                              title="Edit profile"
+                            >
+                              <User className="w-3.5 h-3.5" />
+                              <span>Edit profile</span>
+                            </button>
+                          )}
                           {canManageOrg && (
                             <ConfirmationModal
                               confirmationButtonText={t('dashboard.users.active_users.modals.remove_user.button')}
@@ -826,6 +840,10 @@ function OrgUsers() {
 
       {/* Per-student analytics (integrated into the Users tab) */}
       <UserDossierModal userId={analyticsUserId} onOpenChange={(o) => !o && setAnalyticsUserId(null)} />
+      {/* MKA fork: admin edit of a member's Majlis/mobile/AMC ID/Tanzeem */}
+      {mkaEdit && org?.id && (
+        <MkaProfileEditDialog open onOpenChange={(o) => !o && setMkaEdit(null)} userId={mkaEdit.id} orgId={org.id} displayName={mkaEdit.name} />
+      )}
       <Dialog open={comparing} onOpenChange={setComparing}>
         <DialogContent className="max-w-5xl max-h-[90vh] overflow-y-auto bg-[#f8f8f8] p-6 sm:p-8">
           <h2 className="font-bold text-xl tracking-tight mb-4">{t('dashboard.users.analytics.compare_students')}</h2>
```

Re-apply checklist: the `useState` hook, the button and the dialog mount all reference `canManageOrg`, `org` and the row variable `user` (`user.user.id/first_name/last_name/username`); if upstream renames them, adapt the three spots. Also count: `OrgUsers.tsx` 4 `MKA fork` markers.

#### B. Upstream tests edited (upstream-test-edit)

- `apps/api/src/tests/services/test_signup_custom_fields_flow.py` (+9 lines) and `apps/api/src/tests/services/test_users_service.py` (+5 lines): every pre-existing non-OAuth `UserCreate(...)` now passes `mka_profile={"majlis": "Zion"}`, because the signup hook rejects non-OAuth creation without a Majlis. The pattern is one added kwarg line each time. After a merge, any new upstream test that creates a non-OAuth `UserCreate` needs the same kwarg. Regenerate with `git diff 74807657..HEAD -- <file>`.

#### C. Added file inside an upstream directory (no upstream conflict today)

- `apps/web/components/ui/command.tsx`: shadcn registry `command` component, hand-created from `shadcn view command` output (not via `shadcn add`). Wraps `cmdk` (already a dependency) and reuses `ui/dialog`. Used by `components/mka/MajlisCombobox.tsx`. If upstream ever adds its own `command.tsx`, resolve the add/add conflict by taking upstream's version and re-check `MajlisCombobox.tsx`; `bunx shadcn@latest diff command` shows drift.

#### D. Fork-only new files (no merge risk)

- API: `apps/api/src/services/users/mka_profile.py`, `apps/api/src/db/mka_user_profile.py`, `apps/api/src/routers/mka_profile.py`, `apps/api/migrations/versions/mka_20261004_user_profile.py`
- API tests: `src/tests/services/test_mka_profile_{domain,store,signup,gdpr,amc_rule}.py`, `src/tests/routers/test_mka_profile_router.py`
- Web: `apps/web/components/mka/{MajlisCombobox,MkaProfileFields,MkaProfileGate,MkaProfileEditDialog}.tsx`, `apps/web/services/mka/profile.ts`, `apps/web/tests/mka-profile-{validation,admin}.test.mjs`
- Docs: `docs/superpowers/specs/2026-10-04-mka-profile-fields-design.md`, `docs/superpowers/plans/2026-10-04-mka-profile-fields.md`

#### E. Re-apply after upstream merge (checklist)

1. `grep -rn "MKA fork" apps` and confirm every hook above survives. Added `MKA fork` lines per file in this feature: `users.py` 1; `users.py` 5; `admin.py` 3; `router.py` 2; `route.ts` 3; `OpenSignup.tsx` 7; `InviteOnlySignUp.tsx` 7; `layout.tsx` 2; `client.ts` 1; `OrgUsers.tsx` 4. (`services/users/users.py` also carries the 2026-10-03 Google-only hooks, counted separately.) Recount against the diffs above.
2. `alembic heads` (apps/api, venv) must print exactly one head; today `mka_20261004_user_profile`. If upstream adds a migration and two heads appear, add a fork merge migration (prefix `mka_`) merging both. Never edit upstream migrations.
3. Re-check `apps/web/components/ui/dialog.tsx`: `MkaProfileGate.tsx` repeats dialog.tsx's inline `style` properties on purpose (passing `style` replaces them wholesale).
4. Run the focused tests: `src/tests/services/test_mka_profile_*.py`, `src/tests/routers/test_mka_profile_router.py`, `test_signup_custom_fields_flow.py`, `test_users_service.py`; web: `bun test tests` and eslint on the files above.
5. e2e: the `apps/e2e/core/client.ts` hook must be present or e2e student creation 422s.

#### F. Known unlogged documentation caveat

- `docs/content/guides/build-learning-platform/do-it-yourself.mdx:442` shows `POST /users/{org.id}` without `mka_profile`. On this fork that call now needs `mka_profile: {"majlis": "..."}` for non-OAuth users. The upstream doc was not edited (would add merge noise).

- **Upstream PR**: none


### Turnstile signup protection without SaaS mode (`apps/web/lib/mka-turnstile.ts`)

- **Date**: 2026-10-04
- **Reason**: Upstream only runs Cloudflare Turnstile when the deployment is SaaS (which would put the MKA org on free-plan limits, require email verification and hide Google SSO). The fork activates it OUTSIDE SaaS when the keys are configured. In SaaS mode behavior is exactly upstream. Logic is fork-only in `apps/web/lib/mka-turnstile.ts` (pure rules `isMkaTurnstileApplicable`, `mkaTurnstileActiveFor`, `mkaTurnstileEnforcedFor`, wrapper `isMkaTurnstileEnforced(mode)`); tests in `apps/web/tests/mka-turnstile.test.mjs`. Spec: section 12 of `docs/superpowers/specs/2026-10-04-mka-profile-fields-design.md`.
- **Hooks (3 upstream files)**: `TurnstileWidget.tsx` (`isTurnstileConfigured()` short-circuits true when non-SaaS and the site key is set), `app/api/signup/route.ts` (a `!saas && enforced` verify block before `if (saas)`; the SaaS block is untouched, so verification can never run twice), `app/api/turnstile/verify/route.ts` (SaaS keeps the upstream condition; non-SaaS skips unless both keys are set).
- **Custom domain**: ignored only outside SaaS (it can be true for a single-org deployment's own host and would disable protection); SaaS keeps upstream's exclusion.
- **Stale upstream comments**: comments in `TurnstileWidget.tsx` and the verify route still say "SaaS-only"; stale for this fork, left unedited to avoid merge noise.
- **Diff** (`git diff 74807657..HEAD`; the `signup/route.ts` diff is limited to the Turnstile hunks, the `mka_profile` hooks are logged in section A):

```diff
diff --git a/apps/web/app/api/signup/route.ts b/apps/web/app/api/signup/route.ts
@@ -2,6 +2,7 @@ import { NextRequest, NextResponse } from 'next/server'
 import { getServerAPIUrl } from '@services/config/config'
 import { isSaaSMode, isCustomDomainRequest } from '@lib/saas'
 import { verifyTurnstile, clientIpFromHeaders } from '@lib/turnstile'
+import { isMkaTurnstileEnforced } from '@lib/mka-turnstile' // MKA fork
 import { validateSignupEmail } from '@services/emails/disposableEmail'
 import { addContactWithLoops, sendLoopsEvent, LOOPS_SIGNED_USERS_GROUP } from '@services/emails/loops'
 
@@ -63,6 +67,18 @@ export async function POST(request: NextRequest) {
   // this route is a thin proxy to the backend user-create endpoint.
   const saas = await isSaaSMode()
 
+  // MKA fork: outside SaaS, Turnstile runs when both keys are set (SaaS = upstream block below).
+  if (!saas && isMkaTurnstileEnforced('oss')) { // MKA fork
+    const mkaTurnstile = await verifyTurnstile(turnstileToken, clientIpFromHeaders(request.headers)) // MKA fork
+    if (!mkaTurnstile.ok) { // MKA fork
+      const detail = // MKA fork
+        mkaTurnstile.reason === 'missing_token' // MKA fork
+          ? 'Please complete the verification challenge.' // MKA fork
+          : 'Verification failed. Please try again.' // MKA fork
+      return NextResponse.json({ detail }, { status: 403 }) // MKA fork
+    } // MKA fork
+  } // MKA fork
+
   if (saas) {
     // 1. Turnstile — allowed through automatically when no secret is set. Skipped
     // on org custom domains: the hostname-locked widget can't render there, so the
diff --git a/apps/web/app/api/turnstile/verify/route.ts b/apps/web/app/api/turnstile/verify/route.ts
--- a/apps/web/app/api/turnstile/verify/route.ts
+++ b/apps/web/app/api/turnstile/verify/route.ts
@@ -1,6 +1,7 @@
 import { NextRequest, NextResponse } from 'next/server'
 import { isSaaSMode, isCustomDomainRequest } from '@lib/saas'
 import { verifyTurnstile, clientIpFromHeaders } from '@lib/turnstile'
+import { isMkaTurnstileEnforced } from '@lib/mka-turnstile' // MKA fork
 
 // Standalone Turnstile verification endpoint, used by the auth forms that call
 // the backend DIRECTLY (login / forgot-password / reset-password) — they verify
@@ -12,7 +13,8 @@ export async function POST(request: NextRequest) {
   // Off outside SaaS — never challenge OSS/self-hosted users. Also off on org
   // custom domains, where the hostname-locked Turnstile widget can't render, so
   // the client sends no token and would otherwise be blocked here.
-  if (!(await isSaaSMode()) || (await isCustomDomainRequest())) {
+  // MKA fork: SaaS keeps the upstream condition; outside SaaS skip unless both keys are set.
+  if ((await isSaaSMode()) ? await isCustomDomainRequest() : !isMkaTurnstileEnforced('oss')) { // MKA fork
     return NextResponse.json({ ok: true })
   }
 
diff --git a/apps/web/components/Auth/TurnstileWidget.tsx b/apps/web/components/Auth/TurnstileWidget.tsx
--- a/apps/web/components/Auth/TurnstileWidget.tsx
+++ b/apps/web/components/Auth/TurnstileWidget.tsx
@@ -1,5 +1,6 @@
 'use client'
 import { getConfig, getDeploymentMode } from '@services/config/config'
+import { mkaTurnstileActiveFor } from '@lib/mka-turnstile' // MKA fork
 import { Turnstile, type TurnstileInstance } from '@marsidev/react-turnstile'
 import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
 
@@ -34,6 +35,7 @@ function isOnCustomDomain(): boolean {
  * `useTurnstileRequired`) to avoid hydration mismatches.
  */
 export function isTurnstileConfigured(): boolean {
+  if (mkaTurnstileActiveFor({ mode: getDeploymentMode(), siteKey: getTurnstileSiteKey() })) return true // MKA fork: non-SaaS only
   return getTurnstileSiteKey().length > 0 && getDeploymentMode() === 'saas' && !isOnCustomDomain()
 }
 
```

- **Re-apply**: `grep -rn "MKA fork" apps/web/app/api/signup apps/web/app/api/turnstile apps/web/components/Auth/TurnstileWidget.tsx`.

---

**Reminder**: Before modifying an upstream file, verify that no extension point, plugin, or wrapper approach exists. Document the change here immediately after making it.


### MKA identity attributes (`mka_user_attributes`, Feature A, milestones M1+M2)

- **Date**: 2026-10-04
- **Reason**: Server-derived identity attributes (level / department / role / Majlis / Region) from the Google-verified email, with admin + roster overrides and an audit trail. All logic is fork-only (`services/mka/`, `routers/mka_attributes.py`, `db/mka_user_attributes.py`, migration `mka_20261004_user_attributes`, tests under `src/tests/**/mka*`). Upstream files get ONLY the three hooks below. Spec: `docs/superpowers/specs/2026-10-04-mka-conditional-visibility-design.md` (A1/A2/GDPR).
- **Re-apply after pulling upstream**: `grep -rn "MKA fork" apps/api/src` and run `uv run pytest src/tests/services/mka src/tests/routers/test_mka_attributes_router.py src/tests/routers/test_mka_attributes_security.py`.

1. `apps/api/src/router.py` (hook A1: mount the router; same pattern as the `mka_profile` block). The router admits a session OR an org API token and gates every handler itself (admin routes reuse upstream's `_require_api_token` + `_resolve_org_slug`, as `/admin/{org_slug}/...` does).
```diff
+from src.routers import mka_attributes as mka_attributes_router_module  # MKA fork
@@ after the mka_profile include_router block
+v1_router.include_router(  # MKA fork: session (/me) + org API token (admin routes), gated per handler
+    mka_attributes_router_module.router,
+    prefix="/mka/attributes",
+    tags=["mka-attributes"],
+    dependencies=[Depends(require_authenticated_user_or_api_token)],
+)
```
2. `apps/api/src/services/auth/session.py` (hook A2: derive on login; fail-open, Google-only, SAVEPOINT; the function itself swallows every error)
```diff
+from src.services.mka.attributes import mka_refresh_on_login  # MKA fork
@@ issue_session_or_challenge, right after the block_non_google_auth lines
+    await mka_refresh_on_login(db_session, user, amr)  # MKA fork: fail-open, Google-only
```
3. `apps/api/src/services/admin/admin.py` (GDPR export: one-token change to the EXISTING `# MKA fork` line; `profile_status` returns attributes only when `include_attributes=True`, so learner-facing routes never see them)
```diff
-        "mka_profile": await profile_status(db_session, user_id),  # MKA fork
+        "mka_profile": await profile_status(db_session, user_id, include_attributes=True),  # MKA fork
```
(`delete_profile`, called by upstream `anonymize_user`, now also deletes attribute/audit/roster rows: the change is inside the fork file `services/users/mka_profile.py`, no upstream edit.)

- **Fork-owned file changed (no upstream edit)**: `apps/api/src/services/auth/mka_google_only.py` (fork, added in 4ca921bd) now records the verified `hd` of every Google login in a request-scoped ContextVar (`take_verified_hd`), set inside the existing `require_workspace_hd` call that upstream `signWithGoogle` already makes. The attribute login hook uses it as proof of Workspace ownership (per address). Behaviour of `require_workspace_hd` (accept/reject) is unchanged.
- **Not touched**: `cli.py` (backfill is `python -m src.services.mka.backfill`), `MKA_GOOGLE_ONLY_DOMAINS` / any SSO setting.
- Re-apply test command also includes `src/tests/routers/test_mka_attributes_review_fixes.py`.
