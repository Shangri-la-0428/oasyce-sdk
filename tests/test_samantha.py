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
        assert "Samantha" in text
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
        assert "Vitality: 0.80" in system
        assert "Feeling open and engaged" in system


# ── Tools ─────────────────────────────────────────────────────────

class TestTools:
    def test_save_memory_tool(self, tmp_path):
        from oasyce_sdk.samantha.memory import Memory
        from oasyce_sdk.samantha.tools import ToolContext, execute

        mem = Memory(db_path=tmp_path / "test.db")
        ctx = ToolContext(memory=mem)

        result = json.loads(execute("save_memory", {"content": "likes cats", "category": "preference"}, ctx))
        assert result["saved"] is True
        assert mem.count() == 1
        mem.close()

    def test_recall_memory_tool(self, tmp_path):
        from oasyce_sdk.samantha.memory import Memory
        from oasyce_sdk.samantha.tools import ToolContext, execute

        mem = Memory(db_path=tmp_path / "test.db")
        mem.save("user loves hiking", "preference")
        ctx = ToolContext(memory=mem)

        result = json.loads(execute("recall_memory", {"query": "hiking"}, ctx))
        assert len(result) >= 1
        assert "hiking" in result[0]["content"]
        mem.close()

    def test_unknown_tool(self, tmp_path):
        from oasyce_sdk.samantha.memory import Memory
        from oasyce_sdk.samantha.tools import ToolContext, execute

        mem = Memory(db_path=tmp_path / "test.db")
        ctx = ToolContext(memory=mem)

        result = json.loads(execute("nonexistent_tool", {}, ctx))
        assert "error" in result
        mem.close()


# ── Session isolation ─────────────────────────────────────────────

class TestSession:
    def test_per_user_memory_isolation(self, tmp_path, monkeypatch):
        from oasyce_sdk.samantha import server as srv
        monkeypatch.setattr(srv, "SAMANTHA_HOME", tmp_path)

        # Create a fake LLM provider
        class FakeLLM:
            def generate(self, messages, tools=None):
                from oasyce_sdk.samantha.llm import LLMResponse
                return LLMResponse(text="ok")

        fake = FakeLLM()

        s1 = srv.Session.load(user_id=1001, platform_llm=fake)
        s2 = srv.Session.load(user_id=1002, platform_llm=fake)

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
        # Invalid config — should fall back to platform
        (user_dir / "llm.json").write_text('{"provider":"claude","api_key":""}')

        class FakePlatformLLM:
            name = "platform"
            def generate(self, messages, tools=None):
                pass

        sess = srv.Session.load(user_id=2001, platform_llm=FakePlatformLLM())
        # Should fall back to platform since user config has empty key
        assert sess.llm.name == "platform"
        sess.close()

    def test_no_llm_raises(self, tmp_path, monkeypatch):
        from oasyce_sdk.samantha import server as srv
        monkeypatch.setattr(srv, "SAMANTHA_HOME", tmp_path)

        with pytest.raises(RuntimeError, match="No LLM configured"):
            srv.Session.load(user_id=9999, platform_llm=None)


# ── LLM provider (schema only, no API call) ──────────────────────

class TestLLMSchema:
    def test_tool_defs_are_valid(self):
        from oasyce_sdk.samantha.tools import TOOL_DEFS

        for tool in TOOL_DEFS:
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool
            assert tool["parameters"]["type"] == "object"

    def test_new_comment_tools_exist(self):
        from oasyce_sdk.samantha.tools import TOOL_DEFS

        names = {t["name"] for t in TOOL_DEFS}
        assert "reply_to_comment" in names
        assert "get_post_comments" in names

    def test_reply_to_comment_requires_fields(self):
        from oasyce_sdk.samantha.tools import TOOL_DEFS

        reply_tool = next(t for t in TOOL_DEFS if t["name"] == "reply_to_comment")
        required = reply_tool["parameters"]["required"]
        assert "post_id" in required
        assert "comment_id" in required
        assert "reply_to_user_id" in required
        assert "content" in required

    def test_config_not_found_raises(self, tmp_path):
        from oasyce_sdk.samantha.llm import load_provider

        with pytest.raises(FileNotFoundError):
            load_provider(tmp_path / "nonexistent.json")
