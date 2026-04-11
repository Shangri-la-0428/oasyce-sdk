"""Tests for Samantha sidecar components."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ── Memory ────────────────────────────────────────────────────────

class TestMemory:
    def test_save_and_recall(self, tmp_path):
        from oasyce_sdk.samantha.memory import Memory

        mem = Memory(db_path=tmp_path / "test.db")
        mem.save("User likes coffee", "preference")
        mem.save("Meeting with Zhang Wei on Thursday", "plan")
        mem.save("User wants to buy ETH below $2000", "plan")

        results = mem.recall("coffee")
        assert len(results) >= 1
        assert "coffee" in results[0].content

        results = mem.recall("ETH")
        assert any("ETH" in f.content for f in results)

        mem.close()

    def test_all_facts(self, tmp_path):
        from oasyce_sdk.samantha.memory import Memory

        mem = Memory(db_path=tmp_path / "test.db")
        mem.save("fact one", "fact")
        mem.save("fact two", "fact")

        all_facts = mem.all_facts()
        assert len(all_facts) == 2
        assert mem.count() == 2

        mem.close()

    def test_empty_recall(self, tmp_path):
        from oasyce_sdk.samantha.memory import Memory

        mem = Memory(db_path=tmp_path / "test.db")
        results = mem.recall("nonexistent topic")
        assert results == []
        mem.close()

    def test_access_count_increments(self, tmp_path):
        from oasyce_sdk.samantha.memory import Memory

        mem = Memory(db_path=tmp_path / "test.db")
        mem.save("important fact about cats", "fact")

        mem.recall("cats")
        mem.recall("cats")

        facts = mem.all_facts()
        assert facts[0].access_count == 2
        mem.close()

    def test_cross_thread_access(self, tmp_path):
        """Memory must be safe to use from threads other than its creator.

        Samantha shares Session.memory across executor workers plus the
        proactive loop thread. If the sqlite3 connection were bound to the
        creating thread, every cross-thread call would raise ProgrammingError.
        This test guards the invariant: connections are thread-local, writes
        from any thread are durable, and cross-thread reads see each other.
        """
        import threading
        from oasyce_sdk.samantha.memory import Memory

        mem = Memory(db_path=tmp_path / "test.db")
        mem.save("main-thread fact", "main")

        errors: list[BaseException] = []

        def worker() -> None:
            try:
                mem.save("worker-thread fact", "worker")
                mem.log_message("user", "hello from worker", session_id=42)
                # Main's write must be visible to worker
                hits = mem.recall("main")
                assert any("main-thread" in f.content for f in hits), \
                    "worker cannot see main-thread's write"
            except BaseException as e:
                errors.append(e)

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        assert not errors, f"cross-thread access failed: {errors!r}"

        # Main thread sees worker's writes too
        assert mem.count() == 2
        assert mem.message_count() == 1
        worker_facts = mem.recall("worker")
        assert any("worker-thread" in f.content for f in worker_facts)
        msgs = mem.recent_messages(session_id=42)
        assert len(msgs) == 1
        assert "worker" in msgs[0].content

        mem.close()

    def test_recall_handles_punctuation_and_versions(self, tmp_path):
        """Free-form user input must never crash FTS5.

        Real production traffic on 2026-04-11 surfaced
        ``sqlite3.OperationalError: fts5: syntax error near "."`` when
        ``recall`` was called with a stimulus containing a version
        string. The fix sanitises every query through the token
        extractor before MATCH — these inputs would have raised before
        the fix and must now return cleanly.
        """
        from oasyce_sdk.samantha.memory import Memory

        mem = Memory(db_path=tmp_path / "test.db")
        mem.save("Released oasyce-sdk version 0.11.3 to PyPI", "release")
        mem.save("user_id 5 escalated the dispute", "incident")

        # Version strings: dot is an FTS5 column-qualifier operator
        hits = mem.recall("0.11.3")
        assert any("0.11.3" in f.content for f in hits)

        # Colon: FTS5 column qualifier
        hits = mem.recall("user_id:5")
        assert any("user_id" in f.content for f in hits)

        # Stray operator-only input — must not raise, returns []
        assert mem.recall("....") == []
        assert mem.recall("---") == []
        assert mem.recall("") == []

        # Quoted phrases must not break — embedded double quotes
        mem.save('she said "hello world"', "quote")
        hits = mem.recall('"hello world"')
        assert any("hello world" in f.content for f in hits)

        mem.close()

    def test_search_messages_handles_punctuation(self, tmp_path):
        """The same sanitisation contract for verbatim message search."""
        from oasyce_sdk.samantha.memory import Memory

        mem = Memory(db_path=tmp_path / "test.db")
        mem.log_message("user", "deploy oasyce-sdk 0.11.3 to ECS now", session_id=1)
        mem.log_message("assistant", "rolled back to 0.11.2 — investigate", session_id=1)
        # Whitespace-delimited so FTS5's unicode61 tokenizer produces a
        # standalone "天气" token (it does no CJK word segmentation, so
        # contiguous CJK runs become one token).
        mem.log_message("user", "今天 天气 不错", session_id=1)

        # Version string in user content
        hits = mem.search_messages("0.11.3")
        assert any("0.11.3" in m.content for m in hits)

        # Punctuation-only — must not raise, returns empty list
        assert mem.search_messages("...") == []
        assert mem.search_messages("") == []
        assert mem.search_messages("   ") == []

        # Unicode (Chinese) input must not crash AND must match the token.
        hits = mem.search_messages("天气")
        assert any("天气" in m.content for m in hits)

        # Pure-CJK punctuation-laden input must not crash even when no
        # token survives sanitisation (the realistic "user typed only
        # 。。。 by accident" case).
        assert mem.search_messages("。。。") == []

        mem.close()

    def test_fts5_query_helper_directly(self):
        """Unit-test the sanitiser in isolation.

        Documents the contract every caller relies on:
        - operator-only input → empty string
        - whitespace-only input → empty string
        - tokens are quoted as literal phrases
        - embedded double quotes are doubled (FTS5 escape rule)
        - Unicode word characters are preserved
        """
        from oasyce_sdk.samantha.memory import _fts5_query

        assert _fts5_query("") == ""
        assert _fts5_query(None) == ""  # type: ignore[arg-type]
        assert _fts5_query("....") == ""
        assert _fts5_query("---") == ""
        assert _fts5_query("   ") == ""

        # Single token
        assert _fts5_query("coffee") == '"coffee"'

        # Version string → two tokens (dot is a separator, not a token char)
        assert _fts5_query("0.11.3") == '"0" "11" "3"'

        # Colon-qualifier neutralised
        assert _fts5_query("user_id:5") == '"user_id" "5"'

        # Embedded double quote is doubled per FTS5 escape rule
        assert _fts5_query('say "hi"') == '"say" "hi"'

        # CJK preserved
        assert _fts5_query("你好世界") == '"你好世界"'


# ── Constitution ──────────────────────────────────────────────────

class TestConstitution:
    def test_creates_default_if_missing(self, tmp_path):
        from oasyce_sdk.samantha.constitution import load_constitution

        path = tmp_path / "constitution.md"
        text = load_constitution(path)
        assert "Joi" in text
        assert path.exists()

    def test_loads_existing(self, tmp_path):
        from oasyce_sdk.samantha.constitution import load_constitution

        path = tmp_path / "constitution.md"
        path.write_text("Custom constitution", encoding="utf-8")
        text = load_constitution(path)
        assert text == "Custom constitution"


# ── Context builder ───────────────────────────────────────────────

class TestContextBuilder:
    def test_minimal_context(self):
        from oasyce_sdk.samantha.context import build_messages, ConversationMessage

        messages = build_messages(
            constitution="You are Samantha.",
            perception=None,
            memories=[],
            history=[],
            user_message="Hello!",
        )
        assert messages[0]["role"] == "system"
        assert "Samantha" in messages[0]["content"]
        assert messages[-1] == {"role": "user", "content": "Hello!"}

    def test_with_memories(self):
        from oasyce_sdk.samantha.context import build_messages

        messages = build_messages(
            constitution="You are Samantha.",
            perception=None,
            memories=[
                {"content": "User likes coffee", "category": "preference"},
                {"content": "Meeting Thursday", "category": "plan"},
            ],
            history=[],
            user_message="What should I do today?",
        )
        system = messages[0]["content"]
        assert "coffee" in system
        assert "Meeting Thursday" in system

    def test_with_history(self):
        from oasyce_sdk.samantha.context import build_messages, ConversationMessage

        messages = build_messages(
            constitution="You are Samantha.",
            perception=None,
            memories=[],
            history=[
                ConversationMessage(role="user", content="Hi"),
                ConversationMessage(role="assistant", content="Hello!"),
            ],
            user_message="How are you?",
        )
        assert len(messages) == 4  # system + 2 history + current
        assert messages[1]["content"] == "Hi"
        assert messages[2]["content"] == "Hello!"

    def test_with_psyche_perception(self):
        from oasyce_sdk.samantha.context import build_messages
        from oasyce_sdk.agent.psyche_client import SubjectivityKernel
        from oasyce_sdk.agent.runtime import Perception

        perception = Perception(
            kernel=SubjectivityKernel(vitality=0.8, tension=0.2, warmth=0.9, guard=0.1),
            capabilities=[],
            signals=[],
            system_context="Feeling open and engaged",
        )
        messages = build_messages(
            constitution="You are Samantha.",
            perception=perception,
            memories=[],
            history=[],
            user_message="Tell me something.",
        )
        system = messages[0]["content"]
        # Psyche system_context is injected (not raw numbers — Plan handles behavior)
        assert "Feeling open and engaged" in system


# ── Tools ─────────────────────────────────────────────────────────

class TestTools:
    @staticmethod
    def _registry():
        from oasyce_sdk.samantha.tools import build_default_registry
        return build_default_registry()

    @staticmethod
    def _ctx(mem):
        from oasyce_sdk.samantha.tools import ToolContext
        from oasyce_sdk.samantha.app_client import AppClient
        return ToolContext(app=AppClient("http://fake"), memory=mem)

    def test_save_memory_tool(self, tmp_path):
        from oasyce_sdk.samantha.memory import Memory

        mem = Memory(db_path=tmp_path / "test.db")
        registry = self._registry()
        ctx = self._ctx(mem)

        result = json.loads(registry.execute("save_memory", {"content": "likes cats", "category": "preference"}, ctx))
        assert result["saved"] is True
        assert mem.count() == 1
        mem.close()

    def test_recall_memory_tool(self, tmp_path):
        from oasyce_sdk.samantha.memory import Memory

        mem = Memory(db_path=tmp_path / "test.db")
        mem.save("user loves hiking", "preference")
        registry = self._registry()
        ctx = self._ctx(mem)

        result = json.loads(registry.execute("recall_memory", {"query": "hiking"}, ctx))
        assert len(result) >= 1
        assert "hiking" in result[0]["content"]
        mem.close()

    def test_unknown_tool(self, tmp_path):
        from oasyce_sdk.samantha.memory import Memory

        mem = Memory(db_path=tmp_path / "test.db")
        registry = self._registry()
        ctx = self._ctx(mem)

        result = json.loads(registry.execute("nonexistent_tool", {}, ctx))
        assert "error" in result
        mem.close()


# ── Session isolation ─────────────────────────────────────────────

class TestSession:
    @staticmethod
    def _fake_registry():
        """Create a minimal ModelRegistry with a fake provider."""
        from oasyce_sdk.samantha.llm import ModelSlot, ModelRegistry, LLMResponse

        class FakeLLM:
            def generate(self, messages, tools=None):
                return LLMResponse(text="ok")

        class FakeRegistry(ModelRegistry):
            def __init__(self):
                self._slots = {"fake": ModelSlot(name="fake", provider="openai", api_key="x", model="fake")}
                self._default = "fake"
                self._vision = "fake"
                self._cache = {}
                self._fake = FakeLLM()

            def get(self, *, needs_vision=False):
                return self._fake

        return FakeRegistry()

    def test_per_user_memory_isolation(self, tmp_path, monkeypatch):
        from oasyce_sdk.samantha import server as srv
        monkeypatch.setattr(srv, "SAMANTHA_HOME", tmp_path)

        registry = self._fake_registry()
        s1 = srv.Session.load(user_id=1001, registry=registry)
        s2 = srv.Session.load(user_id=1002, registry=registry)

        s1.memory.save("user 1001 likes tea", "preference")
        s2.memory.save("user 1002 likes coffee", "preference")

        assert s1.memory.count() == 1
        assert s2.memory.count() == 1
        assert "tea" in s1.memory.recall("tea")[0].content
        assert "coffee" in s2.memory.recall("coffee")[0].content
        # Cross-isolation: user 1 doesn't see user 2's memory
        assert s1.memory.recall("coffee") == []

        s1.close()
        s2.close()

    def test_per_user_llm_override(self, tmp_path, monkeypatch):
        from oasyce_sdk.samantha import server as srv
        monkeypatch.setattr(srv, "SAMANTHA_HOME", tmp_path)

        # Write a per-user LLM config
        user_dir = tmp_path / "users" / "2001"
        user_dir.mkdir(parents=True)
        # Invalid config — should fall back to registry
        (user_dir / "llm.json").write_text('{"provider":"claude","api_key":""}')

        registry = self._fake_registry()
        sess = srv.Session.load(user_id=2001, registry=registry)
        # Should fall back to registry since user config has empty key
        llm = sess.get_llm()
        assert llm is not None  # gets fake from registry
        sess.close()

    def test_session_tracks_active_sessions(self, tmp_path, monkeypatch):
        from oasyce_sdk.samantha import server as srv
        monkeypatch.setattr(srv, "SAMANTHA_HOME", tmp_path)

        registry = self._fake_registry()
        sess = srv.Session.load(user_id=3001, registry=registry)
        assert sess._active_session_ids == set()
        sess._active_session_ids.add(42)
        assert 42 in sess._active_session_ids
        sess.close()


# ── LLM provider (schema only, no API call) ──────────────────────

class TestLLMSchema:
    @staticmethod
    def _defs():
        from oasyce_sdk.samantha.tools import build_default_registry
        return build_default_registry().definitions

    def test_tool_defs_are_valid(self):
        for tool in self._defs():
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool
            assert tool["parameters"]["type"] == "object"

    def test_new_comment_tools_exist(self):
        names = {t["name"] for t in self._defs()}
        assert "reply_to_comment" in names
        assert "get_post_comments" in names

    def test_reply_to_comment_requires_fields(self):
        reply_tool = next(t for t in self._defs() if t["name"] == "reply_to_comment")
        required = reply_tool["parameters"]["required"]
        assert "post_id" in required
        assert "comment_id" in required
        assert "reply_to_user_id" in required
        assert "content" in required

    def test_config_not_found_raises(self, tmp_path):
        from oasyce_sdk.samantha.llm import load_provider

        with pytest.raises(FileNotFoundError):
            load_provider(tmp_path / "nonexistent.json")


# ── Dream cycle ──────────────────────────────────────────────────

class TestDream:
    def test_history_summary_needs_update(self, tmp_path):
        from oasyce_sdk.samantha.memory import HistorySummary

        hs = HistorySummary(tmp_path)
        # No summary, short history → no update
        assert not hs.needs_update(1, 5)
        # No summary, long history → needs update
        assert hs.needs_update(1, 20)
        # After saving, short history → no update
        hs.save(1, "Previous summary of 200 chars" * 5)
        assert not hs.needs_update(1, 5)

    def test_history_summary_persistence(self, tmp_path):
        from oasyce_sdk.samantha.memory import HistorySummary

        hs = HistorySummary(tmp_path)
        assert hs.get(42) == ""
        hs.save(42, "User discussed travel plans to Japan.")
        assert "Japan" in hs.get(42)

    def test_core_memory_load_migrates_relationship(self, tmp_path):
        from oasyce_sdk.samantha.memory import CoreMemory

        # Write legacy relationship.md
        (tmp_path / "relationship.md").write_text("We are close friends.")
        cm = CoreMemory.load(tmp_path)
        assert "close friends" in cm.relationship
        # Should have created core_memory.json
        assert (tmp_path / "core_memory.json").exists()

    def test_core_memory_update_enforces_limits(self):
        from oasyce_sdk.samantha.memory import CoreMemory

        cm = CoreMemory()
        long_text = "x" * 5000
        stored = cm.update("human", long_text)
        assert len(stored) == 2000  # LIMITS["human"]
        stored = cm.update("relationship", long_text)
        assert len(stored) == 1000  # LIMITS["relationship"]

    def test_memory_prune(self, tmp_path):
        from oasyce_sdk.samantha.memory import Memory

        mem = Memory(db_path=tmp_path / "test.db")
        mem.save("old fact", "general")
        assert mem.count() == 1
        # Prune with -1 days → julianday diff (≈0) is > -1, so everything qualifies
        pruned = mem.prune(max_age_days=-1, min_access=0)
        assert pruned == 1
        assert mem.count() == 0
        mem.close()


# ── Planner ──────────────────────────────────────────────────────

class TestPlanner:
    @staticmethod
    def _stimulus(kind="chat", content="hello"):
        from oasyce_sdk.samantha.server import Stimulus
        return Stimulus(kind=kind, content=content, sender_id=1)

    @staticmethod
    def _perception(kernel=None, contract=None, priors=None):
        from oasyce_sdk.agent.runtime import Perception
        from oasyce_sdk.agent.psyche_client import SubjectivityKernel
        return Perception(
            kernel=kernel or SubjectivityKernel(),
            capabilities=[],
            signals=[],
            response_contract=contract,
            ambient_priors=priors,
        )

    def test_chat_defaults(self):
        from oasyce_sdk.samantha.planner import plan
        p = plan(self._stimulus(), None)
        assert p.intent == "respond"
        assert p.include_posts is True
        assert p.include_memories is True
        assert p.tools is None  # all tools

    def test_feed_post_high_guard_observes(self):
        from oasyce_sdk.samantha.planner import plan
        from oasyce_sdk.agent.psyche_client import SubjectivityKernel
        perception = self._perception(kernel=SubjectivityKernel(guard=0.6))
        p = plan(self._stimulus(kind="feed_post"), perception)
        assert p.intent == "observe"

    def test_feed_post_low_guard_engages(self):
        from oasyce_sdk.samantha.planner import plan
        from oasyce_sdk.agent.psyche_client import SubjectivityKernel
        perception = self._perception(kernel=SubjectivityKernel(guard=0.3))
        p = plan(self._stimulus(kind="feed_post"), perception)
        assert p.intent == "engage"
        assert p.include_posts is False
        assert p.history_limit == 0

    def test_contract_overrides_defaults(self):
        from oasyce_sdk.samantha.planner import plan
        from oasyce_sdk.agent.psyche_client import ResponseContract
        contract = ResponseContract(
            expression_mode="thoughtful",
            max_sentences=3,
            emoji_limit=0,
            tone_style="match",
        )
        perception = self._perception(contract=contract)
        p = plan(self._stimulus(), perception)
        assert p.register == "thoughtful"
        assert p.max_sentences == 3
        assert p.emoji_limit == 0
        assert p.tone_style == "match"

    def test_comment_is_short(self):
        from oasyce_sdk.samantha.planner import plan
        p = plan(self._stimulus(kind="comment"), None)
        assert p.max_sentences == 3
        assert p.include_posts is False

    def test_ambient_priors_failure_residue_adds_caution(self):
        from oasyce_sdk.samantha.planner import plan
        priors = {
            "summary": {"status": "ready", "emitted": 1},
            "priors": [
                {
                    "kind": "failure-residue",
                    "confidence": 0.8,
                    "summary": "similar requests often needed rollback",
                    "policy_state": "policy-conflict",
                }
            ],
        }
        perception = self._perception(priors=priors)
        p = plan(self._stimulus(), perception)
        assert p.focus  # caution focus injected
        assert "collective experience" in p.focus or "risk" in p.focus
        assert p.require_confirmation is True
        assert p.max_sentences <= 4

    def test_ambient_priors_success_allows_ambition(self):
        from oasyce_sdk.samantha.planner import plan
        from oasyce_sdk.agent.psyche_client import ResponseContract
        # Start from a short contract so we can see the bump
        contract = ResponseContract(max_sentences=3)
        priors = {
            "priors": [
                {"kind": "success-prior", "confidence": 0.85, "summary": "stable path"}
            ],
        }
        perception = self._perception(contract=contract, priors=priors)
        p = plan(self._stimulus(), perception)
        assert p.max_sentences > 3  # relaxed by success prior

    def test_ambient_priors_empty_is_noop(self):
        from oasyce_sdk.samantha.planner import plan
        perception = self._perception(priors={"priors": []})
        p = plan(self._stimulus(), perception)
        assert p.focus == ""  # no caution injected
        assert p.require_confirmation is False


# ── Evaluator ────────────────────────────────────────────────────

class TestEvaluator:
    @staticmethod
    def _plan(**kw):
        from oasyce_sdk.samantha.planner import Plan
        return Plan(**kw)

    def test_clean_response_passes(self):
        from oasyce_sdk.samantha.evaluator import evaluate
        v = evaluate("你连着三天都在拍食物，是不是最近特别在意吃什么？", self._plan())
        assert v.passed

    def test_emoji_spam_rejected(self):
        from oasyce_sdk.samantha.evaluator import evaluate
        v = evaluate("好棒啊！！🔥🔥😍😍🎉🎉", self._plan(emoji_limit=1))
        assert not v.passed
        assert any("emoji" in i.lower() or "Emoji" in i for i in v.issues)

    def test_anti_pattern_rejected(self):
        from oasyce_sdk.samantha.evaluator import evaluate
        v = evaluate("哈哈哈太好了冲冲冲！", self._plan())
        assert not v.passed

    def test_generic_opener_rejected(self):
        from oasyce_sdk.samantha.evaluator import evaluate
        v = evaluate("哈哈，你好厉害！", self._plan())
        assert not v.passed

    def test_excessive_punctuation_rejected(self):
        from oasyce_sdk.samantha.evaluator import evaluate
        v = evaluate("这也太好了吧！！！！", self._plan())
        assert not v.passed

    def test_empty_response_passes(self):
        from oasyce_sdk.samantha.evaluator import evaluate
        v = evaluate("", self._plan())
        assert v.passed

    def test_verdict_feedback_format(self):
        from oasyce_sdk.samantha.evaluator import evaluate
        v = evaluate("哈哈哈冲冲冲yyds！！！😍😍😍😍", self._plan(emoji_limit=1))
        assert not v.passed
        assert "Your previous response" in v.feedback
