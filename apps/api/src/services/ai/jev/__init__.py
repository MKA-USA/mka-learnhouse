"""Provider-neutral typed AI judgments for Learnhouse (TypeSafe Jev or Cloudflare Clef).

Opt-in per organisation (``jev_config.allowed_org_ids``).  Provides RAG passage
reranking (``client``), query intent routing (``router``), response audit
guardrails (``guardrails``, log-only), batched quiz validation (``quality``)
and content moderation (``moderation``, used by ``services/moderation_ai``).
All Jev calls go through ``client.run_system_one`` so the rest of the codebase
never talks to a provider (TypeSafe SDK or Cloudflare REST) directly.
"""
