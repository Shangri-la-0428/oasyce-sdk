"""Tests for the generic ``oasyce_sdk.agent.*`` modules.

These used to live in ``tests/test_samantha.py`` back when Memory,
Planner, Evaluator, Context, and the Dream bits were under
``oasyce_sdk.samantha``. 0.11.6 moved them into ``oasyce_sdk.agent.*``
so any Agent deployment can use them — and 0.12.0 finished the job
by moving the Samantha reference deployment out to its own repository
(``oasyce-samantha``).

What remains in this file is strictly tests for modules that live
under ``oasyce_sdk/agent/`` and depend on nothing deployment-specific:

- ``agent.memory`` — SQLite-backed fact + verbatim message store
- ``agent.context`` — layered prompt assembly
- ``agent.planner`` — rule-engine Plan construction
- ``agent.evaluator`` — output guard / veto
- Dream helpers (``CoreMemory``, ``HistorySummary``) that live next to Memory
"""

from __future__ import annotations


# ── Memory ────────────────────────────────────────────────────────

class TestMemory:
    def test_save_and_recall(self, tmp_path):
        from oasyce_sdk.agent.memory import Memory

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
        from oasyce_sdk.agent.memory import Memory

        mem = Memory(db_path=tmp_path / "test.db")
        mem.save("fact one", "fact")
        mem.save("fact two", "fact")

        all_facts = mem.all_facts()
        assert len(all_facts) == 2
        assert mem.count() == 2

        mem.close()

    def test_empty_recall(self, tmp_path):
        from oasyce_sdk.agent.memory import Memory

        mem = Memory(db_path=tmp_path / "test.db")
        results = mem.recall("nonexistent topic")
        assert results == []
        mem.close()

    def test_access_count_increments(self, tmp_path):
        from oasyce_sdk.agent.memory import Memory

        mem = Memory(db_path=tmp_path / "test.db")
        mem.save("important fact about cats", "fact")

        mem.recall("cats")
        mem.recall("cats")

        facts = mem.all_facts()
        assert facts[0].access_count == 2
        mem.close()

    def test_cross_thread_access(self, tmp_path):
        """Memory must be safe to use from threads other than its creator.

        Agents share ``Session.memory`` across executor workers plus the
        proactive loop thread. If the sqlite3 connection were bound to
        the creating thread, every cross-thread call would raise
        ``ProgrammingError``. This test guards the invariant: connections
        are thread-local, writes from any thread are durable, and
        cross-thread reads see each other.
        """
        import threading
        from oasyce_sdk.agent.memory import Memory

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
        from oasyce_sdk.agent.memory import Memory

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
        from oasyce_sdk.agent.memory import Memory

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
        from oasyce_sdk.agent.memory import _fts5_query

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


# ── Context builder ───────────────────────────────────────────────

class TestContextBuilder:
    def test_minimal_context(self):
        from oasyce_sdk.agent.context import build_messages

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
        from oasyce_sdk.agent.context import build_messages

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
        from oasyce_sdk.agent.context import build_messages, ConversationMessage

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
        from oasyce_sdk.agent.context import build_messages
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


# ── Planner ──────────────────────────────────────────────────────

class TestPlanner:
    @staticmethod
    def _stimulus(kind="chat", content="hello"):
        from oasyce_sdk.agent.stimulus import Stimulus
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
        from oasyce_sdk.agent.planner import plan
        p = plan(self._stimulus(), None)
        assert p.intent == "respond"
        assert p.include_posts is True
        assert p.include_memories is True
        assert p.tools is None  # all tools

    def test_feed_post_high_guard_observes(self):
        from oasyce_sdk.agent.planner import plan
        from oasyce_sdk.agent.psyche_client import SubjectivityKernel
        perception = self._perception(kernel=SubjectivityKernel(guard=0.6))
        p = plan(self._stimulus(kind="feed_post"), perception)
        assert p.intent == "observe"

    def test_feed_post_low_guard_engages(self):
        from oasyce_sdk.agent.planner import plan
        from oasyce_sdk.agent.psyche_client import SubjectivityKernel
        perception = self._perception(kernel=SubjectivityKernel(guard=0.3))
        p = plan(self._stimulus(kind="feed_post"), perception)
        assert p.intent == "engage"
        assert p.include_posts is False
        assert p.history_limit == 0

    def test_contract_overrides_defaults(self):
        from oasyce_sdk.agent.planner import plan
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
        from oasyce_sdk.agent.planner import plan
        p = plan(self._stimulus(kind="comment"), None)
        assert p.max_sentences == 3
        assert p.include_posts is False

    def test_ambient_priors_failure_residue_adds_caution(self):
        from oasyce_sdk.agent.planner import plan
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
        from oasyce_sdk.agent.planner import plan
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
        from oasyce_sdk.agent.planner import plan
        perception = self._perception(priors={"priors": []})
        p = plan(self._stimulus(), perception)
        assert p.focus == ""  # no caution injected
        assert p.require_confirmation is False


# ── Evaluator ────────────────────────────────────────────────────

class TestEvaluator:
    @staticmethod
    def _plan(**kw):
        from oasyce_sdk.agent.planner import Plan
        return Plan(**kw)

    def test_clean_response_passes(self):
        from oasyce_sdk.agent.evaluator import evaluate
        v = evaluate("你连着三天都在拍食物，是不是最近特别在意吃什么？", self._plan())
        assert v.passed

    def test_emoji_spam_rejected(self):
        from oasyce_sdk.agent.evaluator import evaluate
        v = evaluate("好棒啊！！🔥🔥😍😍🎉🎉", self._plan(emoji_limit=1))
        assert not v.passed
        assert any("emoji" in i.lower() or "Emoji" in i for i in v.issues)

    def test_anti_pattern_rejected(self):
        from oasyce_sdk.agent.evaluator import evaluate
        v = evaluate("哈哈哈太好了冲冲冲！", self._plan())
        assert not v.passed

    def test_generic_opener_rejected(self):
        from oasyce_sdk.agent.evaluator import evaluate
        v = evaluate("哈哈，你好厉害！", self._plan())
        assert not v.passed

    def test_excessive_punctuation_rejected(self):
        from oasyce_sdk.agent.evaluator import evaluate
        v = evaluate("这也太好了吧！！！！", self._plan())
        assert not v.passed

    def test_empty_response_passes(self):
        from oasyce_sdk.agent.evaluator import evaluate
        v = evaluate("", self._plan())
        assert v.passed

    def test_verdict_feedback_format(self):
        from oasyce_sdk.agent.evaluator import evaluate
        v = evaluate("哈哈哈冲冲冲yyds！！！😍😍😍😍", self._plan(emoji_limit=1))
        assert not v.passed
        assert "Your previous response" in v.feedback


# ── Dream helpers (CoreMemory, HistorySummary) ───────────────────

class TestDream:
    def test_history_summary_needs_update(self, tmp_path):
        from oasyce_sdk.agent.memory import HistorySummary

        hs = HistorySummary(tmp_path)
        # No summary, short history → no update
        assert not hs.needs_update(1, 5)
        # No summary, long history → needs update
        assert hs.needs_update(1, 20)
        # After saving, short history → no update
        hs.save(1, "Previous summary of 200 chars" * 5)
        assert not hs.needs_update(1, 5)

    def test_history_summary_persistence(self, tmp_path):
        from oasyce_sdk.agent.memory import HistorySummary

        hs = HistorySummary(tmp_path)
        assert hs.get(42) == ""
        hs.save(42, "User discussed travel plans to Japan.")
        assert "Japan" in hs.get(42)

    def test_core_memory_load_migrates_relationship(self, tmp_path):
        from oasyce_sdk.agent.memory import CoreMemory

        # Write legacy relationship.md
        (tmp_path / "relationship.md").write_text("We are close friends.")
        cm = CoreMemory.load(tmp_path)
        assert "close friends" in cm.relationship
        # Should have created core_memory.json
        assert (tmp_path / "core_memory.json").exists()

    def test_core_memory_update_enforces_limits(self):
        from oasyce_sdk.agent.memory import CoreMemory

        cm = CoreMemory()
        long_text = "x" * 5000
        stored = cm.update("human", long_text)
        assert len(stored) == 2000  # LIMITS["human"]
        stored = cm.update("relationship", long_text)
        assert len(stored) == 1000  # LIMITS["relationship"]

    def test_memory_prune(self, tmp_path):
        from oasyce_sdk.agent.memory import Memory

        mem = Memory(db_path=tmp_path / "test.db")
        mem.save("old fact", "general")
        assert mem.count() == 1
        # Prune with -1 days → julianday diff (≈0) is > -1, so everything qualifies
        pruned = mem.prune(max_age_days=-1, min_access=0)
        assert pruned == 1
        assert mem.count() == 0
        mem.close()


# ── Tools — terminal flag + Registry ─────────────────────────────

class TestToolTerminalFlag:
    """The ``terminal`` flag is the seam that fixes multi-reply on
    mention/comment stimuli — write-side actions complete the turn,
    so the LLM cannot re-emit the same call across tool-loop rounds.
    """

    def test_default_tool_is_not_terminal(self):
        from oasyce_sdk.agent.tools import ToolRegistry, schema

        r = ToolRegistry()
        r.register("noop", schema("noop", "no-op"), lambda a, c: "{}")
        assert r.is_terminal("noop") is False

    def test_register_terminal_flag(self):
        from oasyce_sdk.agent.tools import ToolRegistry, schema

        r = ToolRegistry()
        r.register("post", schema("post", "post"), lambda a, c: "{}", terminal=True)
        assert r.is_terminal("post") is True

    def test_unknown_tool_is_not_terminal(self):
        from oasyce_sdk.agent.tools import ToolRegistry

        r = ToolRegistry()
        # Unknown name → False, never raises
        assert r.is_terminal("does_not_exist") is False

    def test_terminal_does_not_affect_dispatch_or_schema(self):
        """Terminal is metadata only — execute and select work the same."""
        from oasyce_sdk.agent.tools import ToolContext, ToolRegistry, schema

        calls: list[str] = []

        def handler(args, ctx):
            calls.append("called")
            return "{\"ok\": true}"

        r = ToolRegistry()
        r.register("act", schema("act", "act"), handler, terminal=True)
        assert "act" in {t["name"] for t in r.definitions}
        assert r.select(["act"]) == r.definitions
        result = r.execute("act", {}, ToolContext())
        assert result == "{\"ok\": true}"
        assert calls == ["called"]


# ── Agent generator — terminal-tool break ────────────────────────

class TestGenerateTerminalBreak:
    """``Agent._generate``'s tool loop must break after a terminal call.

    The bug this guards against: a single mention with an image caused
    Samantha to post 2-3 duplicate replies because the LLM kept
    re-emitting ``comment_on_post`` across the 3 tool-loop rounds.
    """

    @staticmethod
    def _make_agent(tool_terminal: bool, tool_calls_per_round: int = 1):
        from oasyce_sdk.agent.base import Agent
        from oasyce_sdk.agent.llm import LLMResponse, ToolCall
        from oasyce_sdk.agent.tools import ToolRegistry, schema

        executed: list[str] = []

        def handler(args, ctx):
            executed.append(args.get("payload", ""))
            return "{\"ok\": true}"

        tools = ToolRegistry()
        tools.register(
            "fire", schema("fire", "fire"), handler, terminal=tool_terminal,
        )

        rounds_seen = {"n": 0}

        class StubLLM:
            def generate(self, messages, tools=None):
                rounds_seen["n"] += 1
                # Always emit tool calls — if the loop doesn't break,
                # we'll see N rounds of duplicates.
                tcs = [
                    ToolCall(name="fire", arguments={"payload": f"call-{rounds_seen['n']}-{i}"})
                    for i in range(tool_calls_per_round)
                ]
                return LLMResponse(text="final-text", tool_calls=tcs)

        class StubRegistry:
            def get(self, *, needs_vision: bool = False):
                return StubLLM()

        class StubIdentity:
            client = None
            address = ""

            def perceive(self, context):
                from oasyce_sdk.agent.psyche_client import SubjectivityKernel
                from oasyce_sdk.agent.runtime import Perception
                return Perception(
                    kernel=SubjectivityKernel(),
                    capabilities=[], signals=[],
                )

            def act(self, *a, **k):
                pass

        class NullChannel:
            def deliver(self, stimulus, response):
                pass

        agent = Agent(
            identity=StubIdentity(),  # type: ignore[arg-type]
            channel=NullChannel(),  # type: ignore[arg-type]
            registry=StubRegistry(),  # type: ignore[arg-type]
            tools=tools,
            constitution="test",
        )
        return agent, executed, rounds_seen

    def test_terminal_tool_breaks_loop_after_one_round(self):
        from oasyce_sdk.agent.stimulus import Stimulus

        agent, executed, rounds = self._make_agent(tool_terminal=True)
        try:
            stim = Stimulus(kind="mention", content="hi")
            agent.process(stim)
        finally:
            agent.close()

        # Exactly one LLM round and one tool call — no duplicates.
        assert rounds["n"] == 1
        assert executed == ["call-1-0"]

    def test_non_terminal_tool_loops_until_max_rounds(self):
        from oasyce_sdk.agent.base import Agent
        from oasyce_sdk.agent.stimulus import Stimulus

        agent, executed, rounds = self._make_agent(tool_terminal=False)
        try:
            agent.process(Stimulus(kind="chat", content="hi", session_id=1))
        finally:
            agent.close()

        # Without the terminal flag, the loop runs the full budget.
        assert rounds["n"] == Agent.TOOL_LOOP_MAX_ROUNDS
        assert len(executed) == Agent.TOOL_LOOP_MAX_ROUNDS

    def test_terminal_with_multiple_calls_in_one_batch_runs_all_then_breaks(self):
        """If the LLM emits two terminal calls in one response, both run.

        The break happens *after* the batch — terminal does not mean
        "abort mid-batch", it means "no more rounds".
        """
        from oasyce_sdk.agent.stimulus import Stimulus

        agent, executed, rounds = self._make_agent(
            tool_terminal=True, tool_calls_per_round=2,
        )
        try:
            agent.process(Stimulus(kind="mention", content="hi"))
        finally:
            agent.close()

        assert rounds["n"] == 1
        assert executed == ["call-1-0", "call-1-1"]

    def test_failed_terminal_tool_does_not_end_turn(self):
        from oasyce_sdk.agent.base import Agent
        from oasyce_sdk.agent.llm import LLMResponse, ToolCall
        from oasyce_sdk.agent.stimulus import Stimulus
        from oasyce_sdk.agent.tools import ToolRegistry, schema

        rounds = {"n": 0}

        class StubLLM:
            def generate(self, messages, tools=None):
                rounds["n"] += 1
                if rounds["n"] == 1:
                    return LLMResponse(
                        text="first-pass",
                        tool_calls=[ToolCall(name="fire", arguments={})],
                    )
                return LLMResponse(text="final-text")

        class StubRegistry:
            def get(self, *, needs_vision: bool = False):
                return StubLLM()

        class StubIdentity:
            client = None
            address = ""

            def perceive(self, context):
                from oasyce_sdk.agent.psyche_client import SubjectivityKernel
                from oasyce_sdk.agent.runtime import Perception
                return Perception(kernel=SubjectivityKernel(), capabilities=[], signals=[])

            def act(self, *a, **k):
                pass

        class NullChannel:
            def deliver(self, stimulus, response):
                pass

        tools = ToolRegistry()
        tools.register(
            "fire",
            schema("fire", "fire"),
            lambda args, ctx: (_ for _ in ()).throw(RuntimeError("boom")),
            terminal=True,
        )

        agent = Agent(
            identity=StubIdentity(),  # type: ignore[arg-type]
            channel=NullChannel(),  # type: ignore[arg-type]
            registry=StubRegistry(),  # type: ignore[arg-type]
            tools=tools,
            constitution="test",
        )
        try:
            result = agent.process(Stimulus(kind="mention", content="hi"))
        finally:
            agent.close()

        assert result == "final-text"
        assert rounds["n"] == 2


# ── Agent._plan hook ─────────────────────────────────────────────

class TestAgentPlanHook:
    """``_plan`` is the seam for layering deployment-specific rules on
    top of the SDK rule engine. The default delegates to ``planner.plan``;
    a subclass override can mutate the Plan after super.
    """

    def _make_agent(self, plan_override=None):
        from oasyce_sdk.agent.base import Agent
        from oasyce_sdk.agent.tools import ToolRegistry

        class StubIdentity:
            client = None
            address = ""

            def perceive(self, context):
                from oasyce_sdk.agent.psyche_client import SubjectivityKernel
                from oasyce_sdk.agent.runtime import Perception
                return Perception(
                    kernel=SubjectivityKernel(),
                    capabilities=[], signals=[],
                )

            def act(self, *a, **k):
                pass

        class NullChannel:
            def deliver(self, stimulus, response):
                pass

        class StubRegistry:
            def get(self, *, needs_vision: bool = False):
                from oasyce_sdk.agent.llm import LLMResponse

                class _LLM:
                    def generate(self, messages, tools=None):
                        return LLMResponse(text="ok")
                return _LLM()

        AgentCls = Agent
        if plan_override is not None:
            class CustomAgent(Agent):
                def _plan(self, stimulus, perception):
                    p = super()._plan(stimulus, perception)
                    plan_override(stimulus, p)
                    return p
            AgentCls = CustomAgent

        return AgentCls(
            identity=StubIdentity(),  # type: ignore[arg-type]
            channel=NullChannel(),  # type: ignore[arg-type]
            registry=StubRegistry(),  # type: ignore[arg-type]
            tools=ToolRegistry(),
            constitution="test",
        )

    def test_default_plan_matches_planner_default(self):
        from oasyce_sdk.agent.planner import plan as default_plan
        from oasyce_sdk.agent.stimulus import Stimulus

        agent = self._make_agent()
        try:
            stim = Stimulus(kind="chat", content="hi")
            perception = agent._perceive(stim)
            got = agent._plan(stim, perception)
            expected = default_plan(stim, perception)
            assert got.intent == expected.intent
            assert got.tools == expected.tools
        finally:
            agent.close()

    def test_subclass_can_layer_on_top_of_super(self):
        from oasyce_sdk.agent.stimulus import Stimulus

        captured = {"stim": None}

        def override(stim, plan):
            plan.focus = "custom-focus"
            captured["stim"] = stim

        agent = self._make_agent(plan_override=override)
        try:
            stim = Stimulus(kind="chat", content="hi")
            perception = agent._perceive(stim)
            plan = agent._plan(stim, perception)
            assert plan.focus == "custom-focus"
            assert captured["stim"] is stim
        finally:
            agent.close()

    def test_plan_hook_runs_during_pipeline(self):
        """Pipeline must call ``_plan``, not ``planner.plan`` directly."""
        from oasyce_sdk.agent.stimulus import Stimulus

        called = {"n": 0}

        def override(stim, plan):
            called["n"] += 1

        agent = self._make_agent(plan_override=override)
        try:
            agent.process(Stimulus(kind="chat", content="hi", session_id=1))
        finally:
            agent.close()

        assert called["n"] == 1
