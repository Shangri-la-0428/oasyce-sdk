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

    def test_chat_defaults(self):
        from oasyce_sdk.samantha.planner import plan
        p = plan(self._stimulus(), None, None)
        assert p.intent == "respond"
        assert p.include_posts is True
        assert p.include_memories is True
        assert p.tools is None  # all tools

    def test_feed_post_high_guard_observes(self):
        from oasyce_sdk.samantha.planner import plan
        from oasyce_sdk.agent.psyche_client import SubjectivityKernel
        kernel = SubjectivityKernel(guard=0.6)
        p = plan(self._stimulus(kind="feed_post"), kernel, None)
        assert p.intent == "observe"

    def test_feed_post_low_guard_engages(self):
        from oasyce_sdk.samantha.planner import plan
        from oasyce_sdk.agent.psyche_client import SubjectivityKernel
        kernel = SubjectivityKernel(guard=0.3)
        p = plan(self._stimulus(kind="feed_post"), kernel, None)
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
            tone_particles=["嗯", "..."],
        )
        p = plan(self._stimulus(), None, contract)
        assert p.register == "thoughtful"
        assert p.max_sentences == 3
        assert p.emoji_limit == 0
        assert p.tone_particles == ["嗯", "..."]

    def test_comment_is_short(self):
        from oasyce_sdk.samantha.planner import plan
        p = plan(self._stimulus(kind="comment"), None, None)
        assert p.max_sentences == 3
        assert p.include_posts is False


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
