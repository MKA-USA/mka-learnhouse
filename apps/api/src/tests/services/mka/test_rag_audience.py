"""MKA fork: audience sections never enter the shared RAG index (rag_audience + the hook in rag/sources/__init__.py)."""

import copy
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from src.db.courses.blocks import Block, BlockTypeEnum
from src.services.ai.rag import sources
from src.services.ai.rag.sources import dynamic, extract
from src.services.ai.rag.types import ContentRef, SourceType
from src.services.mka import rag_audience
from src.tests.services.rag_helpers import ActivitySubTypeEnum, ActivityTypeEnum, add_activity

SECRET = "RESTRICTED-SECRET-TEXT"
API_ROOT = Path(__file__).resolve().parents[4]


def para(text):
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def aud(*children, **attrs):
    return {"type": "mkaAudience", "attrs": {"id": "a1", "rule": {"v": 1}, **attrs}, "content": list(children)}


def doc(*nodes):
    return {"type": "doc", "content": list(nodes)}


class TestWalkerHandler:
    def test_audience_text_absent_nested_and_deep(self):
        deep = para(SECRET)
        for _ in range(30):
            deep = {"type": "blockquote", "content": [deep]}
        content = doc(
            para("public one"),
            aud(para(SECRET), {"type": "bulletList", "content": [{"type": "listItem", "content": [para(SECRET)]}]}),
            {"type": "blockquote", "content": [aud(para(SECRET), aud(para(SECRET)))]},
            {"type": "bulletList", "content": [{"type": "listItem", "content": [aud(para(SECRET))]}]},
            aud(deep),
            aud({"type": "blockQuiz", "attrs": {"questions": [{"question": SECRET, "answers": []}]}}),
            para("public two"),
        )
        text = dynamic.extract_text_from_prosemirror(content)
        assert SECRET not in text
        assert text == "public one\npublic two"

    def test_malformed_audience_nodes_leak_nothing_and_do_not_raise(self):
        for bad in (
            {"type": "mkaAudience"},
            {"type": "mkaAudience", "content": SECRET},
            {"type": "mkaAudience", "content": [None, 5, SECRET, {"type": "text", "text": SECRET}]},
            {"type": "mkaAudience", "attrs": None, "text": SECRET},
            {"type": "mkaAudience", "attrs": {"rule": SECRET}, "content": [{"type": "text", "text": SECRET}]},
        ):
            assert SECRET not in dynamic.extract_text_from_prosemirror(doc(para("ok"), bad))

    def test_root_audience_node_yields_nothing(self):
        assert dynamic.extract_text_from_prosemirror(aud(para(SECRET))) == ""

    def test_non_audience_output_is_unchanged(self):
        content = doc(
            {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Title"}]},
            para("Body"),
            {"type": "bulletList", "content": [{"type": "listItem", "content": [para("item")]}]},
        )
        before = copy.deepcopy(content)
        assert dynamic.extract_text_from_prosemirror(content) == "## Title\nBody\n- item"
        assert content == before


class TestHelpers:
    def test_strip_audience_is_copy_and_removes_all(self):
        content = doc(para("a"), {"type": "blockquote", "content": [aud(para(SECRET)), para("b")]}, aud(para(SECRET)))
        before = copy.deepcopy(content)
        out = rag_audience.strip_audience(content)
        assert content == before
        assert SECRET not in repr(out) and "mkaAudience" not in repr(out)
        assert "a" in repr(out) and "'b'" in repr(out)

    def test_strip_audience_handles_depth_beyond_recursion_limit(self):
        node = aud(para(SECRET))
        for _ in range(5000):
            node = {"type": "blockquote", "content": [node]}
        assert rag_audience.contains_audience(doc(node))
        assert not rag_audience.contains_audience(rag_audience.strip_audience(doc(node)))  # iterative: must not raise

    def test_restricted_strings_only_inside_audience(self):
        content = doc({"type": "blockPDF", "attrs": {"blockObject": {"block_uuid": "block_pub"}}},
                      aud({"type": "blockPDF", "attrs": {"blockObject": {"block_uuid": "block_secret"}}}))
        found = rag_audience.restricted_strings(content)
        assert "block_secret" in found and "block_pub" not in found


class TestRegistration:
    def test_handler_and_extractors_installed(self):
        assert dynamic._NODE_HANDLERS["mkaAudience"] is rag_audience._noop_audience
        assert sources._EXTRACTORS, "no extractors registered: upstream registry renamed?"
        assert all(getattr(fn, "_mka_audience_wrapped", False) for fn in sources._EXTRACTORS.values())

    def test_install_is_idempotent(self):
        before = dict(sources._EXTRACTORS)
        rag_audience.install()
        assert sources._EXTRACTORS == before

    def test_fresh_import_of_indexing_path_registers_hook(self):
        """A brand new interpreter that only imports what the indexer/pipeline imports gets the hook (queue/worker/CLI processes)."""
        code = (
            "from src.services.ai.rag import pipeline\n"
            "from src.services.ai.rag.sources import dynamic, _EXTRACTORS\n"
            "assert 'mkaAudience' in dynamic._NODE_HANDLERS\n"
            "assert _EXTRACTORS and all(getattr(f, '_mka_audience_wrapped', False) for f in _EXTRACTORS.values())\n"
            "d = {'type': 'doc', 'content': [{'type': 'mkaAudience', 'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': 'X'}]}]}]}\n"
            "assert dynamic.extract_text_from_prosemirror(d) == ''\n"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=API_ROOT, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr

    def test_upstream_contract_guard(self):
        """Fails loudly if upstream renames the walker, its handler table or the extractor registry, instead of the hook silently dying."""
        assert isinstance(dynamic._NODE_HANDLERS, dict) and callable(dynamic._walk_prosemirror_node)
        assert callable(dynamic.extract_text_from_prosemirror)
        assert isinstance(sources._EXTRACTORS, dict)
        # behavioural: the walker really consults the table (a rename of the lookup would make this leak)
        marker = {"type": "zzTestNode"}
        dynamic._NODE_HANDLERS["zzTestNode"] = lambda node, parts: parts.append("HANDLED")
        try:
            assert dynamic.extract_text_from_prosemirror(doc(marker)) == "HANDLED"
        finally:
            del dynamic._NODE_HANDLERS["zzTestNode"]
        # and the ProseMirror extractor still receives the activity (signature the guard wraps)
        assert callable(sources.extract)


def _block(block_id, activity, block_type, **content):
    return Block(
        id=block_id, block_type=block_type, content={"activity_uuid": activity.activity_uuid, **content},
        org_id=activity.org_id, course_id=activity.course_id, activity_id=activity.id, block_uuid=f"block_{block_id}",
        creation_date=str(datetime.now()), update_date=str(datetime.now()),
    )


class TestExtractEndToEnd:
    async def test_dynamic_page_and_blocks(self, db, org, course, chapter):
        content = doc(
            para("Public intro"),
            {"type": "blockImage", "attrs": {"blockObject": {"block_uuid": "block_1"}}},
            aud(para(SECRET), {"type": "blockImage", "attrs": {"blockObject": {"block_uuid": "block_2"}}}),
        )
        activity = await add_activity(
            db, org, course, chapter, 30, activity_type=ActivityTypeEnum.TYPE_DYNAMIC,
            sub_type=ActivitySubTypeEnum.SUBTYPE_DYNAMIC_PAGE, content=content, name="Mixed",
        )
        db.add(_block(1, activity, BlockTypeEnum.BLOCK_IMAGE, file_name="public.png"))
        db.add(_block(2, activity, BlockTypeEnum.BLOCK_IMAGE, file_name=f"{SECRET}.png", alt=SECRET))
        await db.commit()
        before = copy.deepcopy(activity.content)

        extraction = await extract(ContentRef.activity(30), db)
        everything = "\n".join(s.text for s in extraction.segments)
        assert SECRET not in everything
        assert "Public intro" in everything and "public.png" in everything
        assert {s.block_uuid for s in extraction.segments if s.block_uuid} == {"block_1"}
        assert activity.content == before  # the ORM row is never altered

    async def test_activity_without_audience_is_untouched(self, db, org, course, chapter):
        await add_activity(
            db, org, course, chapter, 31, activity_type=ActivityTypeEnum.TYPE_DYNAMIC,
            sub_type=ActivitySubTypeEnum.SUBTYPE_DYNAMIC_PAGE, content=doc(para("Plain")), name="Plain",
        )
        extraction = await extract(ContentRef.activity(31), db)
        assert [s.text for s in extraction.segments if s.source_type == SourceType.PAGE] == ["Plain"]

    async def test_custom_activity_generic_walker_is_stripped(self, db, org, course, chapter):
        await add_activity(
            db, org, course, chapter, 32, activity_type=ActivityTypeEnum.TYPE_CUSTOM,
            sub_type=ActivitySubTypeEnum.SUBTYPE_CUSTOM, content=doc(para("Open text"), aud(para(SECRET))), name="Cust",
        )
        extraction = await extract(ContentRef.activity(32), db)
        text = "\n".join(s.text for s in extraction.segments)
        assert "Open text" in text and SECRET not in text

    async def test_guard_failure_indexes_nothing_from_activity(self, db, org, course, chapter, monkeypatch):
        await add_activity(
            db, org, course, chapter, 33, activity_type=ActivityTypeEnum.TYPE_DYNAMIC,
            sub_type=ActivitySubTypeEnum.SUBTYPE_DYNAMIC_PAGE, content=doc(para("t"), aud(para(SECRET))), name="Boom",
        )

        def boom(_):
            raise RuntimeError("x")

        monkeypatch.setattr(rag_audience, "strip_audience", boom)
        extraction = await extract(ContentRef.activity(33), db)
        assert SECRET not in "\n".join(s.text for s in extraction.segments)
        assert [s for s in extraction.segments if s.source_type == SourceType.PAGE] == []


class TestReindexScript:
    async def test_purges_only_affected_activities_and_reindexes(self, db, org, course, chapter):
        from unittest.mock import AsyncMock, patch

        from sqlmodel import select

        from src.db.course_embeddings import CourseEmbedding
        from src.services.mka import rag_audience_reindex as job
        from src.tests.services.rag_helpers import same_session

        for aid, content in ((40, doc(para("x"), aud(para(SECRET)))), (41, doc(para("plain")))):
            await add_activity(db, org, course, chapter, aid, activity_type=ActivityTypeEnum.TYPE_DYNAMIC,
                               sub_type=ActivitySubTypeEnum.SUBTYPE_DYNAMIC_PAGE, content=content)
            db.add(CourseEmbedding(
                org_id=org.id, course_id=course.id, activity_id=aid, activity_uuid=f"activity_{aid}", source_type="page",
                chunk_text=SECRET if aid == 40 else "plain", chunk_index=0, content_hash="h", activity_name="a",
                chapter_name="c", course_name="co", embedding=[0.0] * CourseEmbedding.__table__.c.embedding.type.dim,
                creation_date="2026", update_date="2026",
            ))
        await db.commit()
        assert await job.affected_activity_ids(db) == [40]

        with patch("src.core.events.database._async_session_factory", new=lambda: same_session(db)), \
             patch("src.services.ai.rag.pipeline.run", new=AsyncMock(return_value=1)) as run:
            assert await job.run(dry_run=True) == {"activities": 1, "purged": False, "reindexed": 0}
            assert len((await db.execute(select(CourseEmbedding))).scalars().all()) == 2
            assert await job.run() == {"activities": 1, "purged": True, "reindexed": 1}
        remaining = (await db.execute(select(CourseEmbedding))).scalars().all()
        assert [r.activity_id for r in remaining] == [41]
        run.assert_awaited_once()
