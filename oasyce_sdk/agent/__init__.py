"""Oasyce Agent package — two layers.

**Layer 1: ``AgentRuntime`` (the feedback loop, from v0.x)**

    from oasyce_sdk.agent.runtime import AgentRuntime

    agent = AgentRuntime()
    perception = agent.perceive("I need to analyze financial data")
    # ... make decision ...
    agent.act("analyzed Q4 data", "succeeded", "financial analysis")

Low-level: wraps Psyche + Thronglets + wallet into a two-method Loop.
Still used by the ``oasyce-agent`` CLI and direct consumers.

**Layer 2: ``Agent`` base class (0.11.6+)**

    from oasyce_sdk.agent import Agent, Channel, Stimulus

    class MyAgent(Agent):
        def _build_prompt(self, stimulus):
            return f"Reply to: {stimulus.content}"

    agent = MyAgent(
        identity=sigil_manager,
        channel=MyChannel(),
        registry=load_registry(),
        tools=build_tools(),
        constitution="You are a helpful agent.",
    )
    agent.submit(Stimulus(kind="chat", content="hello"))

High-level: full PGE cognitive loop, tool calling, Channel seam.
Samantha is the reference deployment.
"""

from .base import Agent
from .channel import Channel
from .cognitive import Annotation, Appraisal, CognitiveMode, KnowledgeTriple, Observation
from .llm import LLMChunk
from .pipeline import EnrichContext, run_pipeline
from .planner import Plan, plan
from .stimulus import Stimulus
from .self import Self, default_appraise
from .store import KnowledgeStore, ObservationStore
from .stream import Stream
from .tools import Tool, ToolContext, ToolRegistry, schema
from .world import DefaultWorld, Outcome, World

__all__ = [
    "Agent",
    "Annotation",
    "Appraisal",
    "Channel",
    "CognitiveMode",
    "EnrichContext",
    "KnowledgeStore",
    "KnowledgeTriple",
    "LLMChunk",
    "Observation",
    "ObservationStore",
    "Plan",
    "Stimulus",
    "Self",
    "Stream",
    "Tool",
    "default_appraise",
    "ToolContext",
    "ToolRegistry",
    "plan",
    "run_pipeline",
    "schema",
    "DefaultWorld",
    "Outcome",
    "World",
]
