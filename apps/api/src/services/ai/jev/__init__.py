"""TypeSafe Jev integration — fast, typed judgments for Learnhouse.

Provides RAG passage reranking and (future) guardrails, moderation, and
quality scoring.  All Jev calls go through ``client.py`` so the rest of the
codebase never imports the TypeSafe SDK directly.
"""
