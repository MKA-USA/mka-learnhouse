# Upstream File Modifications Log

This file tracks any modifications made to upstream-owned files that could cause merge conflicts when pulling new releases.

## Format

Each entry includes: file, date, reason (why no extension point exists), and the exact diff so it can be re-applied after pulling upstream.

## Current Modifications

All Jev (TypeSafe) integration. New, non-upstream files (no conflict risk): `apps/api/src/services/ai/jev/**`, `apps/api/src/services/ai/jev_integration.py`, `apps/api/src/tests/**/test_jev_*.py`. `apps/api/src/services/ai/base.py` is intentionally unmodified (Jev title generation was removed).

### `apps/api/config/config.py`

- **Date**: 2026-10-03
- **Reason**: Config is a single monolithic function with no plugin/registry mechanism; Jev settings must be parsed alongside Judge0/Tinybird and exposed on `LearnHouseConfig`. Adds `JevConfig`, two tolerant parse helpers and one additive block.
- **Diff**:

```diff
diff --git a/apps/api/config/config.py b/apps/api/config/config.py
index aa82a5b1..18fbf3b6 100644
--- a/apps/api/config/config.py
+++ b/apps/api/config/config.py
@@ -29,6 +29,17 @@ class Judge0Config(BaseModel):
     client_secret: str | None
 
 
+class JevConfig(BaseModel):
+    enabled: bool = False
+    api_key: str = ""
+    timeout: float = 3.0
+    # Explicit opt-in: an empty list disables Jev for every organization.
+    allowed_org_ids: list[int] = []
+    quiz_validation_enabled: bool = False
+    guardrails_enabled: bool = True
+    intent_routing_enabled: bool = False
+
+
 class GeneralConfig(BaseModel):
     development_mode: bool
     sentry_config: SentryConfig
@@ -154,6 +165,7 @@ class LearnHouseConfig(BaseModel):
     payments_config: InternalPaymentsConfig
     tinybird_config: TinybirdConfig | None
     judge0_config: Judge0Config | None
+    jev_config: JevConfig | None
 
 
 def _env_bool(env_value, yaml_value):
@@ -178,6 +190,51 @@ def _env_bool(env_value, yaml_value):
     return str(value).strip().lower() in ("true", "1", "yes", "on")
 
 
+def _parse_jev_float(env_value, yaml_value, default: float) -> float:
+    """Parse a float setting; log a warning and use the default on bad input."""
+    raw = yaml_value if env_value is None or env_value == "" else env_value
+    if raw is None or raw == "":
+        return default
+    try:
+        value = float(raw)
+        if value <= 0:
+            raise ValueError("must be positive")
+        return value
+    except (TypeError, ValueError):
+        import logging as _jev_log
+        _jev_log.getLogger(__name__).warning(
+            "Invalid Jev timeout setting; using default %s", default
+        )
+        return default
+
+
+def _parse_jev_org_ids(env_value, yaml_value) -> list[int]:
+    """Parse a list of org IDs from a comma-separated env string or a YAML list.
+
+    Invalid entries are skipped with a warning; config load never fails.
+    """
+    raw = yaml_value if env_value is None or env_value == "" else env_value
+    if raw is None or raw == "":
+        return []
+    if isinstance(raw, (list, tuple)):
+        items = list(raw)
+    else:
+        items = str(raw).split(",")
+    ids: list[int] = []
+    for item in items:
+        text = str(item).strip()
+        if not text:
+            continue
+        try:
+            ids.append(int(text))
+        except ValueError:
+            import logging as _jev_log
+            _jev_log.getLogger(__name__).warning(
+                "Ignoring invalid Jev allowed org id entry"
+            )
+    return ids
+
+
 _yaml_cache: dict = {}
 
 
@@ -554,6 +611,40 @@ def get_learnhouse_config() -> LearnHouseConfig:
             client_secret=judge0_client_secret,
         )
 
+    # Jev (TypeSafe) config — requires enabled flag AND an API key. Per-org
+    # opt-in is enforced at call time via allowed_org_ids (empty = nobody).
+    jev_yaml = yaml_config.get("jev_config", {}) or {}
+    jev_api_key = os.environ.get("LEARNHOUSE_JEV_API_KEY") or jev_yaml.get("api_key") or ""
+    jev_enabled = bool(
+        _env_bool(os.environ.get("LEARNHOUSE_JEV_ENABLED"), jev_yaml.get("enabled", False))
+    )
+
+    jev_config = None
+    if jev_enabled and jev_api_key:
+        jev_config = JevConfig(
+            enabled=True,
+            api_key=str(jev_api_key),
+            timeout=_parse_jev_float(
+                os.environ.get("LEARNHOUSE_JEV_TIMEOUT"), jev_yaml.get("timeout"), 3.0
+            ),
+            allowed_org_ids=_parse_jev_org_ids(
+                os.environ.get("LEARNHOUSE_JEV_ALLOWED_ORG_IDS"),
+                jev_yaml.get("allowed_org_ids"),
+            ),
+            quiz_validation_enabled=bool(_env_bool(
+                os.environ.get("LEARNHOUSE_JEV_QUIZ_VALIDATION"),
+                jev_yaml.get("quiz_validation_enabled", False),
+            )),
+            guardrails_enabled=bool(_env_bool(
+                os.environ.get("LEARNHOUSE_JEV_GUARDRAILS"),
+                jev_yaml.get("guardrails_enabled", True),
+            )),
+            intent_routing_enabled=bool(_env_bool(
+                os.environ.get("LEARNHOUSE_JEV_INTENT_ROUTING"),
+                jev_yaml.get("intent_routing_enabled", False),
+            )),
+        )
+
     # Payments config
     env_stripe_secret_key = os.environ.get("LEARNHOUSE_STRIPE_SECRET_KEY")
     env_stripe_publishable_key = os.environ.get("LEARNHOUSE_STRIPE_PUBLISHABLE_KEY")
@@ -753,6 +844,7 @@ def get_learnhouse_config() -> LearnHouseConfig:
         ),
         tinybird_config=tinybird_config,
         judge0_config=judge0_config,
+        jev_config=jev_config,
     )
 
     return config
```

### `apps/api/pyproject.toml`

- **Date**: 2026-10-03
- **Reason**: Dependency pin for the optional TypeSafe SDK; there is no separate requirements extension point for a fork.
- **Diff**:

```diff
diff --git a/apps/api/pyproject.toml b/apps/api/pyproject.toml
index d94e081a..aee7defd 100644
--- a/apps/api/pyproject.toml
+++ b/apps/api/pyproject.toml
@@ -49,6 +49,7 @@ dependencies = [
     "pgvector==0.5.0",
     "pypdf==6.19.0",
     "regex==2026.9.10",
+    "typesafe-sdk==0.7.2",
 ]
 
 [tool.ruff]
```

### `apps/api/src/services/ai/rag/query_service.py`

- **Date**: 2026-10-03
- **Reason**: Reranking must happen between the vector query and context assembly inside `query_course_rag`; there is no hook between those steps. Logic lives in `jev/client.py`; the hunk is a candidate-count helper plus one call.
- **Diff**:

```diff
diff --git a/apps/api/src/services/ai/rag/query_service.py b/apps/api/src/services/ai/rag/query_service.py
index 927c3c44..a7e64d8c 100644
--- a/apps/api/src/services/ai/rag/query_service.py
+++ b/apps/api/src/services/ai/rag/query_service.py
@@ -1,8 +1,8 @@
 """
 RAG query service.
 
-Handles vector similarity search and streaming LLM responses
-grounded in course content.
+Handles vector similarity search, optional Jev reranking, and streaming
+LLM responses grounded in course content.
 """
 
 import logging
@@ -20,6 +20,24 @@ logger = logging.getLogger(__name__)
 TOP_K = 5
 
 
+# Candidates fetched from vector search when Jev reranking is active.
+JEV_RERANK_CANDIDATES = 10
+
+
+def _resolve_rag_limits(top_k: int, org_id: Optional[int] = None) -> tuple[int, int]:
+    """Return (retrieve_k, final_k).
+
+    When Jev reranking is active for this org we fetch more candidates from
+    vector search than the caller asked for, rerank them, then trim to the
+    original top_k. Otherwise the two values are identical (no behaviour change).
+    """
+    from src.services.ai.jev.client import jev_enabled
+
+    if jev_enabled(org_id):
+        return max(top_k, JEV_RERANK_CANDIDATES), top_k
+    return top_k, top_k
+
+
 async def query_course_rag(
     question: str,
     org_id: int,
@@ -28,7 +46,8 @@ async def query_course_rag(
     top_k: int = TOP_K,
 ) -> dict:
     """
-    Retrieve relevant course content via vector similarity search.
+    Retrieve relevant course content via vector similarity search,
+    optionally reranked by Jev for semantic precision.
 
     Args:
         question: The user's question
@@ -40,6 +59,8 @@ async def query_course_rag(
     Returns:
         {context: str, sources: list[dict]}
     """
+    retrieve_k, final_k = _resolve_rag_limits(top_k, org_id)
+
     # Embed the question
     query_embedding = await embed_single_text(question)
 
@@ -62,7 +83,7 @@ async def query_course_rag(
             "query_embedding": embedding_str,
             "org_id": org_id,
             "course_id": course_id,
-            "top_k": top_k,
+            "top_k": retrieve_k,
         }
     else:
         sql = text("""
@@ -79,7 +100,7 @@ async def query_course_rag(
         params = {
             "query_embedding": embedding_str,
             "org_id": org_id,
-            "top_k": top_k,
+            "top_k": retrieve_k,
         }
 
     results = (await db_session.execute(sql, params)).fetchall()
@@ -87,6 +108,10 @@ async def query_course_rag(
     if not results:
         return {"context": "", "sources": []}
 
+    # Optional Jev reranking: score all retrieved chunks, keep the best final_k
+    if retrieve_k > final_k:
+        results = await _jev_rerank(question, results, final_k)
+
     # Build numbered context and deduplicated source list
     context_parts = []
     sources = []
@@ -121,6 +146,18 @@ async def query_course_rag(
     return {"context": context, "sources": sources}
 
 
+async def _jev_rerank(question: str, results: list, final_k: int) -> list:
+    """Rerank vector-search results via Jev. Falls back to vector order
+    (trimmed to final_k) if Jev is unavailable or fails."""
+    from src.services.ai.jev.client import jev_rerank_chunks
+
+    reranked = await jev_rerank_chunks(question, results, final_k)
+    if reranked is None:
+        logger.debug("Jev reranking unavailable; using vector ordering")
+        return results[:final_k]
+    return reranked[:final_k]
+
+
 async def query_course_rag_stream(
     question: str,
     org_id: int,
```

### `apps/api/src/services/ai/quiz.py`

- **Date**: 2026-10-03
- **Reason**: Single additive call after generation to the log-only validator in `services/ai/jev_integration.py`; no post-generation hook exists.
- **Diff**:

```diff
diff --git a/apps/api/src/services/ai/quiz.py b/apps/api/src/services/ai/quiz.py
index 9a10cb95..5fd8282b 100644
--- a/apps/api/src/services/ai/quiz.py
+++ b/apps/api/src/services/ai/quiz.py
@@ -116,6 +116,20 @@ async def generate_quiz(
         output_type=GeneratedQuiz,
     )
 
+    # Optional Jev quiz validation (log-only, opt-in, never fails generation)
+    from src.services.ai.jev_integration import validate_generated_quiz
+    await validate_generated_quiz(
+        [
+            {
+                "question": q.question,
+                "answers": [{"answer": a.answer, "correct": a.correct} for a in q.answers],
+            }
+            for q in generated.questions
+        ],
+        org_id=org_id,
+        course_content=context,
+    )
+
     block_quiz = _to_block_quiz(generated)
 
     # Record the exchange so a follow-up refine turn can amend the actual quiz
```

### `apps/api/src/routers/ai/rag.py`

- **Date**: 2026-10-03
- **Reason**: Needs a fire-and-forget audit call after the final SSE event and an intent-routing check before retrieval; no middleware hook exists inside the SSE generator or endpoint. Logic lives in `services/ai/jev_integration.py`.
- **Diff**:

```diff
diff --git a/apps/api/src/routers/ai/rag.py b/apps/api/src/routers/ai/rag.py
index 34ed6518..8f1d849d 100644
--- a/apps/api/src/routers/ai/rag.py
+++ b/apps/api/src/routers/ai/rag.py
@@ -105,6 +105,16 @@ async def rag_chat_event_generator(
         # Send done event
         yield f"data: {json.dumps({'type': 'done', 'aichat_uuid': aichat_uuid})}\n\n"
 
+        # Jev output audit: fire-and-forget, never blocks the stream
+        from src.services.ai.jev_integration import schedule_guardrail_audit
+        schedule_guardrail_audit(
+            full_response,
+            user_question=user_message,
+            org_id=org_id,
+            source_context=context_text[:2000] if context_text else "",
+            chat_id=aichat_uuid,
+        )
+
         # Generate follow-up suggestions
         follow_ups = await generate_follow_up_suggestions(
             full_response,
@@ -168,6 +178,7 @@ async def api_rag_chat(
     - If course_uuid is omitted, searches across all courses for the user's org.
     """
     course_id = None
+    course_name = ""
     org_id = None
 
     if chat_request.course_uuid:
@@ -177,6 +188,7 @@ async def api_rag_chat(
         if not course:
             raise HTTPException(status_code=404, detail="Course not found")
         course_id = course.id
+        course_name = getattr(course, "name", "") or ""
         org_id = course.org_id
     else:
         if chat_request.org_slug:
@@ -250,6 +262,18 @@ async def api_rag_chat(
     # Get or create chat session
     chat_session = get_chat_session_history(chat_request.aichat_uuid)
 
+    # Optional Jev intent routing (opt-in; only when the client sent no explicit mode)
+    effective_mode = chat_request.mode or "course_only"
+    from src.services.ai.jev_integration import should_route_to_general
+    if await should_route_to_general(
+        chat_request.message,
+        org_id=org_id,
+        mode=chat_request.mode,
+        course_name=course_name,
+        history=chat_session["message_history"],
+    ):
+        effective_mode = "general"
+
     # Perform RAG query with streaming
     stream, sources = await query_course_rag_stream(
         question=chat_request.message,
@@ -257,7 +281,7 @@ async def api_rag_chat(
         db_session=db_session,
         message_history=chat_session["message_history"],
         course_id=course_id,
-        mode=chat_request.mode or "course_only",
+        mode=effective_mode,
     )
 
     return StreamingResponse(
```

Follow-up (Executor E): `RAGChatRequest.mode` became `Optional[Literal["course_only","general"]] = None` (None = no explicit client choice; intent routing applies only then, and `effective_mode` falls back to `"course_only"`). The SSE generator now receives `mode=effective_mode` (instead of `chat_request.mode`) so chat history records the mode actually used. Re-apply:

```diff
-    mode: Literal["course_only", "general"] = "course_only"
+    # None = client expressed no preference (treated as "course_only"; the only
+    # case where opt-in Jev intent routing may switch to "general").
+    mode: Optional[Literal["course_only", "general"]] = None
@@ rag_chat_event_generator(...) call in api_rag_chat
-            mode=chat_request.mode,
+            mode=effective_mode,
```

### `apps/api/src/routers/ai/ai.py`

- **Date**: 2026-10-03
- **Reason**: Same as rag.py: one fire-and-forget audit call after the done event in `activity_chat_event_generator`.
- **Diff**:

```diff
diff --git a/apps/api/src/routers/ai/ai.py b/apps/api/src/routers/ai/ai.py
index d31fe3ff..42508ccd 100644
--- a/apps/api/src/routers/ai/ai.py
+++ b/apps/api/src/routers/ai/ai.py
@@ -120,6 +120,15 @@ async def activity_chat_event_generator(
         # Send done event immediately (without waiting for follow-ups)
         yield f"data: {json.dumps({'type': 'done', 'aichat_uuid': aichat_uuid, 'activity_uuid': activity_uuid})}\n\n"
 
+        # Jev output audit: fire-and-forget, never blocks the stream
+        from src.services.ai.jev_integration import schedule_guardrail_audit
+        schedule_guardrail_audit(
+            full_response,
+            user_question=user_message,
+            org_id=org_id,
+            chat_id=aichat_uuid,
+        )
+
         # Generate follow-up suggestions and send as separate event
         follow_ups = await generate_follow_up_suggestions(
             full_response,
```

## Moderation wiring (frontend, Executor D)
- **Date**: 2026-10-04
- **Reason**: Staff-only AI moderation UI. All logic lives in new files (`apps/web/services/moderation/flags.ts`, `apps/web/components/Dashboard/Moderation/*`, `apps/web/components/Dashboard/Pages/Org/OrgEditAI/OrgEditAIModeration.tsx`, `apps/web/app/orgs/[orgslug]/dash/moderation/page.tsx`). Upstream files below only get import + one-line mounts; no extension point exists for these components. `apps/web/locales/en.json` gains a new top-level `moderation` key (additive; other locales fall back to English via i18next).
- **Re-apply**: after pulling upstream, re-add each hunk below (imports + one JSX line each).
- **Diff**:

```diff
diff --git a/apps/web/app/orgs/[orgslug]/dash/assignments/[assignmentuuid]/subpages/AssignmentSubmissionsSubPage.tsx b/apps/web/app/orgs/[orgslug]/dash/assignments/[assignmentuuid]/subpages/AssignmentSubmissionsSubPage.tsx
index a56f55b4..857d1f63 100644
--- a/apps/web/app/orgs/[orgslug]/dash/assignments/[assignmentuuid]/subpages/AssignmentSubmissionsSubPage.tsx
+++ b/apps/web/app/orgs/[orgslug]/dash/assignments/[assignmentuuid]/subpages/AssignmentSubmissionsSubPage.tsx
@@ -26,0 +27,2 @@ import EvaluateAssignment from './Modals/EvaluateAssignment';
+import { ModerationFlagIndicator } from '@components/Dashboard/Moderation/ModerationFlagIndicator';
+import useAdminStatus from '@components/Hooks/useAdminStatus';
@@ -484,0 +487,3 @@ function SubmissionRow({
+    // Dashboard-only page (AdminAuthorization). The API decides per-course whether
+    // this grader may see flags; 403/404 render nothing.
+    const { isAdmin: isDashboardUser } = useAdminStatus();
@@ -600,0 +606,9 @@ function SubmissionRow({
+            {/* Staff-only moderation signal (this grading page is dashboard-only) */}
+            <div className="me-4 empty:hidden">
+                <ModerationFlagIndicator
+                    contentType="assignment_submission"
+                    contentUuid={submission.assignmentusersubmission_uuid}
+                    isStaff={isDashboardUser === true}
+                />
+            </div>
+
diff --git a/apps/web/components/Dashboard/Menus/DashLeftMenu.tsx b/apps/web/components/Dashboard/Menus/DashLeftMenu.tsx
index 4e11e71f..02dde8ca 100644
--- a/apps/web/components/Dashboard/Menus/DashLeftMenu.tsx
+++ b/apps/web/components/Dashboard/Menus/DashLeftMenu.tsx
@@ -26,0 +27 @@ import {
+  ShieldCheck,
@@ -83,0 +85 @@ import useAdminStatus from '@components/Hooks/useAdminStatus'
+import useCanModerate from '@components/Hooks/useCanModerate'
@@ -197,0 +200 @@ function DashLeftMenu() {
+  const { canModerate } = useCanModerate()
@@ -523,0 +527,9 @@ function DashLeftMenu() {
+            {canModerate && (
+              <MenuLink
+                href="/dash/moderation"
+                icon={<ShieldCheck size={20} weight="fill" />}
+                label={t('moderation.nav')}
+                isCollapsed={isCollapsed}
+                active={isActivePath('/dash/moderation')}
+              />
+            )}
diff --git a/apps/web/components/Dashboard/Pages/Org/OrgEditAI/OrgEditAI.tsx b/apps/web/components/Dashboard/Pages/Org/OrgEditAI/OrgEditAI.tsx
--- a/apps/web/components/Dashboard/Pages/Org/OrgEditAI/OrgEditAI.tsx
+++ b/apps/web/components/Dashboard/Pages/Org/OrgEditAI/OrgEditAI.tsx
@@ -15,0 +16 @@ import Image from 'next/image'
+import OrgEditAIModeration from './OrgEditAIModeration'
@@ -176,0 +178,2 @@ const OrgEditAI: React.FC = () => {
+
+        <OrgEditAIModeration />
diff --git a/apps/web/components/Dashboard/Pages/Users/UserAnalytics/UserDossier.tsx b/apps/web/components/Dashboard/Pages/Users/UserAnalytics/UserDossier.tsx
--- a/apps/web/components/Dashboard/Pages/Users/UserAnalytics/UserDossier.tsx
+++ b/apps/web/components/Dashboard/Pages/Users/UserAnalytics/UserDossier.tsx
@@ -19,0 +20 @@ import BehaviorSection from './sections/BehaviorSection'
+import ModerationFlagsSection from '@components/Dashboard/Moderation/ModerationFlagsSection'
@@ -92,0 +94,3 @@ export default function UserDossier({ dossier }: { dossier: any }) {
+      {/* Staff-only AI moderation flags (review aids, not verdicts) */}
+      <ModerationFlagsSection userUuid={user.user_uuid} />
+
diff --git a/apps/web/components/Objects/Communities/CommentCard.tsx b/apps/web/components/Objects/Communities/CommentCard.tsx
--- a/apps/web/components/Objects/Communities/CommentCard.tsx
+++ b/apps/web/components/Objects/Communities/CommentCard.tsx
@@ -23,0 +24 @@ import { CommentUpvoteButton } from './CommentUpvoteButton'
+import { ModerationFlagIndicator } from '@components/Dashboard/Moderation/ModerationFlagIndicator'
@@ -204,0 +206 @@ export function CommentCard({ comment, canManage = false, onDeleted, onUpdated }
+                  <ModerationFlagIndicator contentType="discussion_comment" contentUuid={comment.comment_uuid} isStaff={canManage} />
diff --git a/apps/web/components/Objects/Communities/DiscussionCard.tsx b/apps/web/components/Objects/Communities/DiscussionCard.tsx
--- a/apps/web/components/Objects/Communities/DiscussionCard.tsx
+++ b/apps/web/components/Objects/Communities/DiscussionCard.tsx
@@ -22,0 +23 @@ import { getUriWithOrg } from '@services/config/config'
+import { ModerationFlagIndicator } from '@components/Dashboard/Moderation/ModerationFlagIndicator'
@@ -274,0 +276 @@ export function DiscussionCard({
+              <ModerationFlagIndicator contentType="discussion" contentUuid={discussion.discussion_uuid} isStaff={canManage} />
```

## Moderation wiring (backend, Executor C)
- **Date**: 2026-10-04
- **Reason**: Advisory AI moderation (record flags for staff review). All logic is in NEW isolated files: `apps/api/src/services/moderation_ai/**`, `apps/api/src/db/moderation_flags.py`, `apps/api/src/routers/moderation_flags.py` (also serves `PUT/GET /orgs/{org_id}/config/ai-moderation`, so `routers/orgs/orgs.py` and `services/orgs/orgs.py` are untouched), `apps/api/migrations/versions/f1a2b3c4d5e7_add_moderation_flag.py`, tests `src/tests/services/test_moderation_ai.py` and `src/tests/routers/test_moderation_flags_router.py`. Upstream files below only get an import + one call each (no extension point exists for "after this row is saved"), the org toggle model, router registration, and a shutdown drain. The org toggle is stored in the org config JSON blob (no migration): v2 `admin_toggles.moderation_ai`, v1 `features.moderation_ai`. The new `moderation_flag` table is created by Alembic `f1a2b3c4d5e7` (down_revision `b1c2d3e4f5a6`); re-point `down_revision` at the new head after pulling upstream migrations.
- **Re-apply**: after pulling upstream, re-add each hunk below.
- **Diff**:

```diff
diff --git a/apps/api/src/core/events/events.py b/apps/api/src/core/events/events.py
@@ -117,0 +118,3 @@ def shutdown_app(app: FastAPI) -> Callable:
+        # Let in-flight AI moderation passes finish (fail-open, own sessions).
+        from src.services.moderation_ai.scheduler import drain_moderation_tasks
+        await drain_moderation_tasks()
diff --git a/apps/api/src/db/organization_config.py b/apps/api/src/db/organization_config.py
@@ -168,0 +169,11 @@ class SecurityAdminToggle(BaseModel):
+class ModerationAIAdminToggle(BaseModel):
+    enabled: bool = False
+    surfaces: Optional[list[str]] = None
+
@@ -169,0 +181 @@ class AdminToggles(BaseModel):
+    moderation_ai: ModerationAIAdminToggle = ModerationAIAdminToggle()
diff --git a/apps/api/src/router.py b/apps/api/src/router.py
@@ -10,0 +11 @@ from src.routers import plans
+from src.routers import moderation_flags as moderation_flags_router_module
@@ -105,0 +107,12 @@ v1_router.include_router(
+v1_router.include_router(
+    moderation_flags_router_module.org_settings_router,
+    prefix="/orgs",
+    tags=["moderation"],
+    dependencies=[Depends(require_authenticated_user)]
+)
+v1_router.include_router(
+    moderation_flags_router_module.router,
+    prefix="/moderation-flags",
+    tags=["moderation"],
+    dependencies=[Depends(require_authenticated_user)]
+)
diff --git a/apps/api/src/services/communities/comments.py b/apps/api/src/services/communities/comments.py
@@ -19,0 +20 @@ from src.services.webhooks.dispatch import dispatch_webhooks
+from src.services.moderation_ai import schedule_moderation, forum_text
@@ -84,0 +86 @@ async def create_comment(   (after commit/refresh)
+    schedule_moderation(kind="forum_post", content_type="discussion_comment", content_uuid=comment.comment_uuid, org_id=community.org_id, author_user_id=comment.author_id, text_loader=forum_text(comment.content))
@@ -231,0 +234 @@ async def update_comment(   (after commit/refresh)
+    schedule_moderation(kind="forum_post", content_type="discussion_comment", content_uuid=comment.comment_uuid, org_id=discussion.org_id if discussion else None, author_user_id=comment.author_id, text_loader=forum_text(comment.content))
diff --git a/apps/api/src/services/communities/discussions.py b/apps/api/src/services/communities/discussions.py
@@ -31,0 +32 @@ from src.services.communities.moderation import (
+from src.services.moderation_ai import schedule_moderation, forum_text
@@ -153,0 +155 @@ async def create_discussion(   (after commit/refresh)
+    schedule_moderation(kind="forum_post", content_type="discussion", content_uuid=discussion.discussion_uuid, org_id=community.org_id, author_user_id=discussion.author_id, text_loader=forum_text(discussion.title, discussion.content))
@@ -440,0 +443 @@ async def update_discussion(   (after commit/refresh)
+    schedule_moderation(kind="forum_post", content_type="discussion", content_uuid=discussion.discussion_uuid, org_id=discussion.org_id, author_user_id=discussion.author_id, text_loader=forum_text(discussion.title, discussion.content))
diff --git a/apps/api/src/services/courses/activities/assignments.py b/apps/api/src/services/courses/activities/assignments.py
@@ -84,0 +85 @@ from src.services.webhooks.dispatch import dispatch_webhooks
+from src.services.moderation_ai import schedule_moderation, assignment_submission_text
@@ -2976,0 +2978 @@ async def create_assignment_submission(   (inside `if won_insert:`, after dispatch_webhooks; NOT in handle_assignment_task_submission/autosave)
+        schedule_moderation(kind="assignment_submission", content_type="assignment_submission", content_uuid=assignment_user_submission.assignmentusersubmission_uuid, org_id=course.org_id, author_user_id=submitter.id, text_loader=assignment_submission_text(submitter.id, assignment.id))
diff --git a/apps/api/src/services/users/users.py b/apps/api/src/services/users/users.py
@@ -50,0 +51 @@ from src.services.webhooks.dispatch import dispatch_webhooks
+from src.services.moderation_ai import schedule_moderation, profile_text
@@ -600,0 +602 @@ async def update_user(   (after commit/refresh, before UserRead conversion)
+    schedule_moderation(kind="general", content_type="user_profile", content_uuid=user.user_uuid, org_id=None, author_user_id=user.id, text_loader=profile_text(user.bio, user.first_name, user.last_name))
```

Executor E follow-up to the shutdown hunk above (same hunk in `events.py`, placed right after the moderation drain; drains Jev background audits, then closes the shared SDK client):

```diff
+        # Jev: drain fire-and-forget audits, then close the shared SDK client.
+        from src.services.ai import jev_integration
+        from src.services.ai.jev.client import aclose_jev_client
+        if jev_integration._background_tasks:
+            await asyncio.gather(*list(jev_integration._background_tasks), return_exceptions=True)
+        await aclose_jev_client()
```

`apps/api/src/db/organization_config.py` (complete hunk, including the 4 docstring lines the diff above elides):

```diff
+class ModerationAIAdminToggle(BaseModel):
+    """Per-org opt-in for advisory AI content moderation (off by default).
+
+    ``surfaces`` empty/None means every surface; otherwise a subset of
+    discussion | discussion_comment | assignment_submission | user_profile.
+    """
+
+    enabled: bool = False
+    surfaces: Optional[list[str]] = None
+
@@ class AdminToggles(BaseModel):
+    moderation_ai: ModerationAIAdminToggle = ModerationAIAdminToggle()
```

Other files touched by the Jev/moderation work (additive; re-apply or re-merge after upstream pulls):
- `apps/web/locales/en.json`: new top-level `moderation` key (additive; other locales fall back to English).
- `docs/content/self-hosting/configuration/environment-variables.mdx`: new "Jev (TypeSafe) AI add-ons" section plus the "AI content moderation (advisory)" subsection. `LEARNHOUSE_JEV_INTENT_ROUTING` is documented as opt-in, default `false` (Executor E).
- `apps/api/uv.lock`: regenerated lock for the new `typesafe-sdk` dependency from `pyproject.toml`; after pulling upstream, re-run `uv lock` instead of merging by hand.

Docs: a "AI content moderation (advisory)" subsection was appended to `docs/content/self-hosting/configuration/environment-variables.mdx` (inside the Jev section Executor B wrote).

## Moderation wiring (frontend fixes, Executor F)

- **Reason**: Follow-up fixes. Logic stays in new files (`flags.ts`, `useModerationFlags.ts`, `ModerationFlagCard.tsx`, `OrgEditAIModeration.tsx`); upstream hunks are minimal.
- `apps/web/app/orgs/[orgslug]/dash/assignments/[assignmentuuid]/subpages/AssignmentSubmissionsSubPage.tsx` (SubmissionRow): added `import useAdminStatus`, one hook line `const { isAdmin: isDashboardUser } = useAdminStatus();`, and changed `isStaff` (hardcoded) to `isStaff={isDashboardUser === true}`.
- `DashLeftMenu.tsx` (diff in the Executor D block above, exact and current) and `DashMobileMenu.tsx` (exact diff below) gate the Moderation links on `canModerate` from the new `useCanModerate` hook:

```diff
diff --git a/apps/web/components/Dashboard/Menus/DashMobileMenu.tsx b/apps/web/components/Dashboard/Menus/DashMobileMenu.tsx
index 5415a755..a77143af 100644
--- a/apps/web/components/Dashboard/Menus/DashMobileMenu.tsx
+++ b/apps/web/components/Dashboard/Menus/DashMobileMenu.tsx
@@ -28,0 +29 @@ import {
+  ShieldCheck,
@@ -36,0 +38 @@ import { useLHSession } from '@components/Contexts/LHSessionContext'
+import useCanModerate from '@components/Hooks/useCanModerate'
@@ -53,0 +56 @@ function DashMobileMenu() {
+  const { canModerate } = useCanModerate()
@@ -228,0 +232 @@ function DashMobileMenu() {
+                {canModerate && <PanelItem href="/dash/moderation" icon={<ShieldCheck size={15} weight="fill" />} label={t('moderation.nav')} active={isActive('/dash/moderation')} onClick={close} />}
```
- `apps/web/locales/en.json`: additive keys under `moderation.settings` (`loading`, `load_error`, `no_provider`, `surfaces_title`, `surface.*`).

## Moderation follow-up fixes (Executor G)

- `apps/web/components/Hooks/useCanModerate.ts` (NEW, fork-safe): `canManageOrg || role in this org with communities.action_update`, mirroring the API's `is_moderation_staff`. `useAdminStatus` is deliberately untouched: its `rights` object only merges a fixed key set and never contains `communities`. The two menu hunks above and `ModerationQueue.tsx` (new file; 403 `ErrorUI` guard) use it. Caveat: `/dash/*` is still gated by `dashboard.action_access` in `AdminAuthorization`, so a moderator without dashboard access still cannot reach the page.
- Backend (new files only): `moderation_ai/service.py` `flags_by_user` returns `[]` before any user/flag query for non-staff callers without courses update rights; `moderation_ai/scheduler.py` adds a per-content cap (5 provider calls per rolling 60s, Redis sorted set with in-memory fallback). No upstream files touched.

## Jev provider generalization (Executor H, config.py)

- **Reason**: make the AI-judgment layer provider-neutral (TypeSafe Jev or Cloudflare Workers AI Clef). Logic lives in `apps/api/src/services/ai/jev/**` (fork-owned); the only upstream-file hunk is in `apps/api/config/config.py` (additive to the existing Jev block; re-apply after pulling upstream).
- Env vars: `LEARNHOUSE_JEV_PROVIDER`, `_MODEL`, `_CLOUDFLARE_ACCOUNT_ID`, `_MODEL_RERANK|GUARDRAILS|MODERATION|INTENT|QUIZ`. Docs: Jev section of `docs/content/self-hosting/configuration/environment-variables.mdx`.

Exact `git diff <merge-base with dev> -- apps/api/config/config.py` (202 lines incl. headers, +163 lines; additive only, re-apply after pulling upstream):

```diff
diff --git a/apps/api/config/config.py b/apps/api/config/config.py
index aa82a5b1..51c5b396 100644
--- a/apps/api/config/config.py
+++ b/apps/api/config/config.py
@@ -29,6 +29,26 @@ class Judge0Config(BaseModel):
     client_secret: str | None
 
 
+class JevConfig(BaseModel):
+    enabled: bool = False
+    api_key: str = ""
+    timeout: float = 3.0
+    # Explicit opt-in: an empty list disables Jev for every organization.
+    allowed_org_ids: list[int] = []
+    quiz_validation_enabled: bool = False
+    guardrails_enabled: bool = True
+    intent_routing_enabled: bool = False
+    # Provider-neutral System One backend: 'typesafe' (Jev via typesafe-sdk) or
+    # 'cloudflare' (Workers AI Clef). ``api_key`` is the TypeSafe key OR a
+    # Cloudflare API token scoped to Workers AI.
+    provider: str = "typesafe"
+    # None => SDK default (typesafe) / 'clef-flash' (cloudflare).
+    model: str | None = None
+    cloudflare_account_id: str = ""
+    # Optional per-capability model overrides (rerank|guardrails|moderation|intent|quiz).
+    models: dict[str, str] = {}
+
+
 class GeneralConfig(BaseModel):
     development_mode: bool
     sentry_config: SentryConfig
@@ -154,6 +174,7 @@ class LearnHouseConfig(BaseModel):
     payments_config: InternalPaymentsConfig
     tinybird_config: TinybirdConfig | None
     judge0_config: Judge0Config | None
+    jev_config: JevConfig | None
 
 
 def _env_bool(env_value, yaml_value):
@@ -178,6 +199,94 @@ def _env_bool(env_value, yaml_value):
     return str(value).strip().lower() in ("true", "1", "yes", "on")
 
 
+def _parse_jev_float(env_value, yaml_value, default: float) -> float:
+    """Parse a float setting; log a warning and use the default on bad input."""
+    raw = yaml_value if env_value is None or env_value == "" else env_value
+    if raw is None or raw == "":
+        return default
+    try:
+        value = float(raw)
+        if value <= 0:
+            raise ValueError("must be positive")
+        return value
+    except (TypeError, ValueError):
+        import logging as _jev_log
+        _jev_log.getLogger(__name__).warning(
+            "Invalid Jev timeout setting; using default %s", default
+        )
+        return default
+
+
+def _parse_jev_org_ids(env_value, yaml_value) -> list[int]:
+    """Parse a list of org IDs from a comma-separated env string or a YAML list.
+
+    Invalid entries are skipped with a warning; config load never fails.
+    """
+    raw = yaml_value if env_value is None or env_value == "" else env_value
+    if raw is None or raw == "":
+        return []
+    if isinstance(raw, (list, tuple)):
+        items = list(raw)
+    else:
+        items = str(raw).split(",")
+    ids: list[int] = []
+    for item in items:
+        text = str(item).strip()
+        if not text:
+            continue
+        try:
+            ids.append(int(text))
+        except ValueError:
+            import logging as _jev_log
+            _jev_log.getLogger(__name__).warning(
+                "Ignoring invalid Jev allowed org id entry"
+            )
+    return ids
+
+
+JEV_PROVIDERS = ("typesafe", "cloudflare")
+JEV_CAPABILITIES = ("rerank", "guardrails", "moderation", "intent", "quiz")
+
+
+def _parse_jev_provider(env_value, yaml_value) -> str:
+    """Return 'typesafe' or 'cloudflare'; warn and default on anything else."""
+    raw = yaml_value if env_value is None or env_value == "" else env_value
+    if raw is None or str(raw).strip() == "":
+        return "typesafe"
+    value = str(raw).strip().lower()
+    if value in JEV_PROVIDERS:
+        return value
+    import logging as _jev_log
+    _jev_log.getLogger(__name__).warning(
+        "Invalid Jev provider setting; using default 'typesafe'"
+    )
+    return "typesafe"
+
+
+def _clean_jev_str(env_value, yaml_value) -> str | None:
+    raw = yaml_value if env_value is None or env_value == "" else env_value
+    if raw is None:
+        return None
+    text = str(raw).strip()
+    return text or None
+
+
+def _parse_jev_models(yaml_value) -> dict[str, str]:
+    """Per-capability model overrides from env (``LEARNHOUSE_JEV_MODEL_<CAP>``)
+    layered over the YAML ``models`` mapping. Unknown capabilities are ignored."""
+    models: dict[str, str] = {}
+    if isinstance(yaml_value, dict):
+        for cap in JEV_CAPABILITIES:
+            val = _clean_jev_str(None, yaml_value.get(cap))
+            if val:
+                models[cap] = val
+    for cap in JEV_CAPABILITIES:
+        val = _clean_jev_str(os.environ.get(f"LEARNHOUSE_JEV_MODEL_{cap.upper()}"), None)
+        if val:
+            models[cap] = val
+    return models
+
+
 _yaml_cache: dict = {}
 
 
@@ -554,6 +663,59 @@ def get_learnhouse_config() -> LearnHouseConfig:
             client_secret=judge0_client_secret,
         )
 
+    # Jev (TypeSafe) config — requires enabled flag AND an API key. Per-org
+    # opt-in is enforced at call time via allowed_org_ids (empty = nobody).
+    jev_yaml = yaml_config.get("jev_config", {}) or {}
+    jev_api_key = os.environ.get("LEARNHOUSE_JEV_API_KEY") or jev_yaml.get("api_key") or ""
+    jev_enabled = bool(
+        _env_bool(os.environ.get("LEARNHOUSE_JEV_ENABLED"), jev_yaml.get("enabled", False))
+    )
+
+    jev_provider = _parse_jev_provider(
+        os.environ.get("LEARNHOUSE_JEV_PROVIDER"), jev_yaml.get("provider")
+    )
+    jev_cf_account = _clean_jev_str(
+        os.environ.get("LEARNHOUSE_JEV_CLOUDFLARE_ACCOUNT_ID"),
+        jev_yaml.get("cloudflare_account_id"),
+    ) or ""
+    jev_ready = bool(jev_enabled and jev_api_key)
+    if jev_ready and jev_provider == "cloudflare" and not jev_cf_account:
+        import logging as _jev_log
+        _jev_log.getLogger(__name__).warning(
+            "Jev provider 'cloudflare' needs LEARNHOUSE_JEV_CLOUDFLARE_ACCOUNT_ID; Jev disabled"
+        )
+        jev_ready = False
+
+    jev_config = None
+    if jev_ready:
+        jev_config = JevConfig(
+            provider=jev_provider,
+            model=_clean_jev_str(os.environ.get("LEARNHOUSE_JEV_MODEL"), jev_yaml.get("model")),
+            cloudflare_account_id=jev_cf_account,
+            models=_parse_jev_models(jev_yaml.get("models")),
+            enabled=True,
+            api_key=str(jev_api_key),
+            timeout=_parse_jev_float(
+                os.environ.get("LEARNHOUSE_JEV_TIMEOUT"), jev_yaml.get("timeout"), 3.0
+            ),
+            allowed_org_ids=_parse_jev_org_ids(
+                os.environ.get("LEARNHOUSE_JEV_ALLOWED_ORG_IDS"),
+                jev_yaml.get("allowed_org_ids"),
+            ),
+            quiz_validation_enabled=bool(_env_bool(
+                os.environ.get("LEARNHOUSE_JEV_QUIZ_VALIDATION"),
+                jev_yaml.get("quiz_validation_enabled", False),
+            )),
+            guardrails_enabled=bool(_env_bool(
+                os.environ.get("LEARNHOUSE_JEV_GUARDRAILS"),
+                jev_yaml.get("guardrails_enabled", True),
+            )),
+            intent_routing_enabled=bool(_env_bool(
+                os.environ.get("LEARNHOUSE_JEV_INTENT_ROUTING"),
+                jev_yaml.get("intent_routing_enabled", False),
+            )),
+        )
+
     # Payments config
     env_stripe_secret_key = os.environ.get("LEARNHOUSE_STRIPE_SECRET_KEY")
     env_stripe_publishable_key = os.environ.get("LEARNHOUSE_STRIPE_PUBLISHABLE_KEY")
@@ -753,6 +915,7 @@ def get_learnhouse_config() -> LearnHouseConfig:
         ),
         tinybird_config=tinybird_config,
         judge0_config=judge0_config,
+        jev_config=jev_config,
     )
 
     return config
```

Other upstream-file hunks (all additive; exact diffs via `git diff <merge-base> -- <file>`):

- `apps/web/locales/en.json`: 1 hunk `@@ -6689,5 +6689,84 @@`, +79 lines: closes the previous top-level object with `},` and appends a new top-level `"moderation": { ... }` key (nav/title/status/severity/content_type/scores/dossier/settings strings) before the final `}`.
- `docs/content/self-hosting/configuration/environment-variables.mdx`: 1 hunk `@@ -100,0 +101,46 @@`, +46 lines: new "Jev AI add-ons" section (providers, generic Cloudflare production setup with compose passthrough lines, data-flow/privacy) and the "AI content moderation (advisory)" subsection.
- `apps/api/uv.lock`: 3 hunks, +18 lines: `@@ -740,0 +741 @@` (one `dependencies` entry), `@@ -786,0 +788 @@` (one `requires-dist` entry), `@@ -1597,0 +1600,16 @@` (the `typesafe-sdk` 0.7.2 package block). Regenerate with `uv lock` after pulling upstream.
- `apps/api/pyproject.toml`: 1 hunk `@@ -51,0 +52 @@`, +1 line (the `typesafe-sdk` dependency).

## MKA deployment notes (fork-only)

- The compose file used by the deployment tool lists API-service environment variables explicitly, so every new variable must be passed through or it never reaches the container. For the Jev provider generalization these are: `LEARNHOUSE_JEV_PROVIDER`, `LEARNHOUSE_JEV_MODEL`, `LEARNHOUSE_JEV_CLOUDFLARE_ACCOUNT_ID`, `LEARNHOUSE_JEV_MODEL_RERANK`, `LEARNHOUSE_JEV_MODEL_GUARDRAILS`, `LEARNHOUSE_JEV_MODEL_MODERATION`, `LEARNHOUSE_JEV_MODEL_INTENT`, `LEARNHOUSE_JEV_MODEL_QUIZ`, each as `- 'NAME=${NAME:-}'`. The API token variable (and `LEARNHOUSE_JEV_ENABLED`) follow the same rule.
- The Cloudflare token must be scoped to Workers AI (Read and Edit) only, and supplied via the deployment tool's secret store, never committed.
- Changing a variable needs a redeploy of the API service; the docs in the upstream-bound MDX are intentionally generic.

---

**Reminder**: Before modifying an upstream file, verify that no extension point, plugin, or wrapper approach exists. Document the change here immediately after making it.
