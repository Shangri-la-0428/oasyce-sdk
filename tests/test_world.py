"""Feature 9 contract tests — World Protocol (SDK layer).

Validates:
  - Outcome dataclass defaults
  - World is a runtime-checkable Protocol
  - DefaultWorld delivers on REACTIVE, no-ops on other modes
  - Pipeline uses world.act when world is provided
  - Pipeline falls back to deliver when world is None
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from oasyce_sdk.agent.cognitive import CognitiveMode
from oasyce_sdk.agent.planner import Plan
from oasyce_sdk.agent.stimulus import Stimulus
from oasyce_sdk.agent.world import DefaultWorld, Outcome, World


# ── Outcome ────────────────────────────────────────────────────

class TestOutcome:
    def test_defaults(self):
        o = Outcome(success=True)
        assert o.success is True
        assert o.detail == ""

    def test_with_detail(self):
        o = Outcome(success=False, detail="timeout")
        assert o.success is False
        assert o.detail == "timeout"


# ── World Protocol ─────────────────────────────────────────────

class TestWorldProtocol:
    def test_default_world_satisfies_protocol(self):
        channel = MagicMock()
        w = DefaultWorld(channel)
        assert isinstance(w, World)

    def test_concrete_class_with_act_satisfies_protocol(self):
        class MyWorld:
            def act(self, mode, stimulus, response, plan):
                return Outcome(success=True)
        assert isinstance(MyWorld(), World)


# ── DefaultWorld ───────────────────────────────────────────────

class TestDefaultWorld:
    def test_reactive_with_response_delivers(self):
        channel = MagicMock()
        w = DefaultWorld(channel)
        stimulus = Stimulus(kind="chat", content="hi", sender_id=1)
        plan = Plan(mode=CognitiveMode.REACTIVE)

        outcome = w.act(CognitiveMode.REACTIVE, stimulus, "hello!", plan)

        assert outcome.success is True
        assert outcome.detail == "delivered"
        channel.deliver.assert_called_once_with(stimulus, "hello!")

    def test_reactive_without_response_no_deliver(self):
        channel = MagicMock()
        w = DefaultWorld(channel)
        stimulus = Stimulus(kind="chat", content="hi", sender_id=1)
        plan = Plan(mode=CognitiveMode.REACTIVE)

        outcome = w.act(CognitiveMode.REACTIVE, stimulus, None, plan)

        assert outcome.success is True
        channel.deliver.assert_not_called()

    def test_proactive_no_deliver(self):
        channel = MagicMock()
        w = DefaultWorld(channel)
        stimulus = Stimulus(kind="reflection", content="thought", sender_id=1)
        plan = Plan(mode=CognitiveMode.PROACTIVE)

        outcome = w.act(CognitiveMode.PROACTIVE, stimulus, "a thought", plan)

        assert outcome.success is True
        channel.deliver.assert_not_called()

    def test_observing_no_deliver(self):
        channel = MagicMock()
        w = DefaultWorld(channel)
        stimulus = Stimulus(kind="feed_post", content="post", sender_id=1)
        plan = Plan(mode=CognitiveMode.OBSERVING)

        outcome = w.act(CognitiveMode.OBSERVING, stimulus, None, plan)

        assert outcome.success is True
        channel.deliver.assert_not_called()

    def test_reflecting_no_deliver(self):
        channel = MagicMock()
        w = DefaultWorld(channel)
        stimulus = Stimulus(kind="maintenance", content="", sender_id=0)
        plan = Plan(mode=CognitiveMode.REFLECTING)

        outcome = w.act(CognitiveMode.REFLECTING, stimulus, None, plan)

        assert outcome.success is True
        channel.deliver.assert_not_called()


# ── Pipeline integration ───────────────────────────────────────

class TestPipelineWorldIntegration:
    def test_world_act_called_when_provided(self):
        from oasyce_sdk.agent.pipeline import run_pipeline

        stimulus = Stimulus(kind="chat", content="hello", sender_id=1)
        perception = MagicMock()
        perception.generation_controls = None
        perception.ambient_priors = None
        perception.kernel = None
        perception.response_contract = None
        perception.system_context = ""
        perception.dynamic_context = ""

        plan = Plan(mode=CognitiveMode.REACTIVE, intent="respond")
        world = MagicMock()
        world.act.return_value = Outcome(success=True)

        llm = MagicMock()
        resp = MagicMock()
        resp.text = "hi there"
        resp.tool_calls = []
        llm.generate.return_value = resp

        deliver = MagicMock()
        registry = MagicMock()
        registry.select.return_value = []

        run_pipeline(
            stimulus,
            perceive=lambda s: perception,
            enrich=lambda s, p: MagicMock(
                memories=[], message_matches=[], core_memory=None,
                history=[], image_urls=[], recent_posts=[],
                hist_summary="", observations=[], essential_story="",
            ),
            build_prompt=lambda s: s.content,
            get_llm=lambda s, needs_vision=False: llm,
            build_tool_ctx=lambda s: MagicMock(),
            generate=lambda llm, s, msgs, tools, ctx: "hi there",
            deliver=deliver,
            log_turn=lambda s, r: None,
            reflect=lambda s, r, p: None,
            constitution="test",
            tool_registry=registry,
            plan_fn=lambda s, p: plan,
            world=world,
        )

        world.act.assert_called_once()
        args = world.act.call_args[0]
        assert args[0] == CognitiveMode.REACTIVE
        assert args[2] == "hi there"
        deliver.assert_not_called()

    def test_deliver_used_when_world_is_none(self):
        from oasyce_sdk.agent.pipeline import run_pipeline

        stimulus = Stimulus(kind="chat", content="hello", sender_id=1)
        perception = MagicMock()
        perception.generation_controls = None
        perception.ambient_priors = None
        perception.kernel = None
        perception.response_contract = None
        perception.system_context = ""
        perception.dynamic_context = ""

        plan = Plan(mode=CognitiveMode.REACTIVE, intent="respond")

        llm = MagicMock()
        resp = MagicMock()
        resp.text = "hi there"
        resp.tool_calls = []
        llm.generate.return_value = resp

        deliver = MagicMock()
        registry = MagicMock()
        registry.select.return_value = []

        run_pipeline(
            stimulus,
            perceive=lambda s: perception,
            enrich=lambda s, p: MagicMock(
                memories=[], message_matches=[], core_memory=None,
                history=[], image_urls=[], recent_posts=[],
                hist_summary="", observations=[], essential_story="",
            ),
            build_prompt=lambda s: s.content,
            get_llm=lambda s, needs_vision=False: llm,
            build_tool_ctx=lambda s: MagicMock(),
            generate=lambda llm, s, msgs, tools, ctx: "hi there",
            deliver=deliver,
            log_turn=lambda s, r: None,
            reflect=lambda s, r, p: None,
            constitution="test",
            tool_registry=registry,
            plan_fn=lambda s, p: plan,
            world=None,
        )

        deliver.assert_called_once()

    def test_deliver_used_when_plan_mode_is_none(self):
        from oasyce_sdk.agent.pipeline import run_pipeline

        stimulus = Stimulus(kind="chat", content="hello", sender_id=1)
        perception = MagicMock()
        perception.generation_controls = None
        perception.ambient_priors = None
        perception.kernel = None
        perception.response_contract = None
        perception.system_context = ""
        perception.dynamic_context = ""

        plan = Plan(mode=None, intent="respond")
        world = MagicMock()

        llm = MagicMock()
        resp = MagicMock()
        resp.text = "hi"
        resp.tool_calls = []
        llm.generate.return_value = resp

        deliver = MagicMock()
        registry = MagicMock()
        registry.select.return_value = []

        run_pipeline(
            stimulus,
            perceive=lambda s: perception,
            enrich=lambda s, p: MagicMock(
                memories=[], message_matches=[], core_memory=None,
                history=[], image_urls=[], recent_posts=[],
                hist_summary="", observations=[], essential_story="",
            ),
            build_prompt=lambda s: s.content,
            get_llm=lambda s, needs_vision=False: llm,
            build_tool_ctx=lambda s: MagicMock(),
            generate=lambda llm, s, msgs, tools, ctx: "hi",
            deliver=deliver,
            log_turn=lambda s, r: None,
            reflect=lambda s, r, p: None,
            constitution="test",
            tool_registry=registry,
            plan_fn=lambda s, p: plan,
            world=world,
        )

        deliver.assert_called_once()
        world.act.assert_not_called()


# ── Export check ───────────────────────────────────────────────

class TestFeature9Exports:
    def test_world_importable(self):
        from oasyce_sdk.agent import World, DefaultWorld, Outcome
        assert World is not None
        assert DefaultWorld is not None
        assert Outcome is not None
