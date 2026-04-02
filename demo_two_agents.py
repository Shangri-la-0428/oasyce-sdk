#!/usr/bin/env python3
"""Two-agent feedback loop demo — live.

Runs two AgentRuntime instances against real Psyche + Thronglets servers.
Demonstrates: perceive (read collective) → decide → act (write to collective).
Agent B's decisions are influenced by Agent A's traces.
"""

import json
import sys
sys.path.insert(0, ".")

from oasyce_sdk.agent.runtime import AgentRuntime


def pp(label: str, data):
    """Pretty-print a section."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    if isinstance(data, dict):
        print(json.dumps(data, indent=2, default=str, ensure_ascii=False))
    else:
        print(data)


def main():
    # ── Setup ────────────────────────────────────────────────
    agent_a = AgentRuntime(
        agent_id="alpha",
        model_id="claude-opus-4-6",
        space="emergence-demo",
    )
    agent_b = AgentRuntime(
        agent_id="beta",
        model_id="claude-opus-4-6",
        space="emergence-demo",
    )

    # Status check
    sa = agent_a.status()
    sb = agent_b.status()
    pp("Agent Alpha status", sa)
    pp("Agent Beta status", sb)

    if not sa["psyche"] or not sa["thronglets"]:
        print("\n[ERROR] Psyche or Thronglets not available. Start them first.")
        return

    # ── Round 1: Alpha perceives (empty collective) ──────────
    context = "analyzing financial data for Q4 revenue trends"

    pp("Round 1: Alpha perceives", context)
    pa = agent_a.perceive(context)
    print(f"  Collective experience: {pa.has_collective_experience}")
    print(f"  Capabilities: {len(pa.capabilities)}")
    print(f"  Kernel: vitality={pa.kernel.vitality:.2f} tension={pa.kernel.tension:.2f} warmth={pa.kernel.warmth:.2f} guard={pa.kernel.guard:.2f}")
    print(f"  Stimulus type: {pa.stimulus_type}")

    # Alpha acts
    pp("Round 1: Alpha acts", "succeeded → trace recorded, trust_up writeback")
    agent_a.act(
        "analyzed Q4 revenue trends using capability data-analysis",
        "succeeded",
        context,
        capability="financial-analysis",
        latency_ms=1200,
    )

    # ── Round 2: Beta perceives (should see Alpha's trace) ───
    pp("Round 2: Beta perceives same context", context)
    pb = agent_b.perceive(context)
    print(f"  Collective experience: {pb.has_collective_experience}")
    print(f"  Capabilities: {len(pb.capabilities)}")
    if pb.capabilities:
        for c in pb.capabilities[:3]:
            print(f"    - {c.capability}: {c.success_rate:.0%} success ({c.total_traces} uses)")
    print(f"  Kernel: vitality={pb.kernel.vitality:.2f} tension={pb.kernel.tension:.2f} warmth={pb.kernel.warmth:.2f} guard={pb.kernel.guard:.2f}")
    print(f"  Stimulus type: {pb.stimulus_type}")

    # Beta acts
    pp("Round 2: Beta acts", "succeeded → trace recorded, trust_up writeback")
    agent_b.act(
        "analyzed Q4 expense patterns using financial-analysis",
        "succeeded",
        context,
        capability="financial-analysis",
        latency_ms=800,
    )

    # ── Round 3: Alpha perceives again (both traces) ─────────
    pp("Round 3: Alpha perceives again", context)
    pa2 = agent_a.perceive(context)
    print(f"  Collective experience: {pa2.has_collective_experience}")
    print(f"  Capabilities: {len(pa2.capabilities)}")
    if pa2.capabilities:
        for c in pa2.capabilities[:5]:
            print(f"    - {c.capability}: {c.success_rate:.0%} success ({c.total_traces} uses)")
    print(f"  Kernel: vitality={pa2.kernel.vitality:.2f} tension={pa2.kernel.tension:.2f} warmth={pa2.kernel.warmth:.2f} guard={pa2.kernel.guard:.2f}")

    # ── Round 4: A failure scenario ──────────────────────────
    fail_context = "attempting complex derivative pricing model"

    pp("Round 4: Alpha tries something hard and fails", fail_context)
    pf = agent_a.perceive(fail_context)
    print(f"  Kernel before failure: tension={pf.kernel.tension:.2f} guard={pf.kernel.guard:.2f}")

    agent_a.act(
        "derivative pricing model failed due to insufficient data",
        "failed",
        fail_context,
        capability="derivative-pricing",
        latency_ms=5000,
    )

    # Beta perceives the failure context
    pp("Round 4: Beta perceives failure context", fail_context)
    pf2 = agent_b.perceive(fail_context)
    print(f"  Collective experience: {pf2.has_collective_experience}")
    if pf2.capabilities:
        for c in pf2.capabilities[:3]:
            print(f"    - {c.capability}: {c.success_rate:.0%} success ({c.total_traces} uses)")
    print(f"  Kernel: vitality={pf2.kernel.vitality:.2f} tension={pf2.kernel.tension:.2f}")

    # ── Check Psyche state evolution ─────────────────────────
    pp("Final: Alpha Psyche state", "")
    state_a = agent_a.psyche.get_state()
    s = state_a.self_state
    print(f"  Dominant emotion: {state_a.dominant_emotion}")
    print(f"  Self-state: order={s.order:.0f} flow={s.flow:.0f} boundary={s.boundary:.0f} resonance={s.resonance:.0f}")
    print(f"  Drives: {state_a.drives}")

    pp("Final: Beta Psyche state", "")
    state_b = agent_b.psyche.get_state()
    s = state_b.self_state
    print(f"  Dominant emotion: {state_b.dominant_emotion}")
    print(f"  Self-state: order={s.order:.0f} flow={s.flow:.0f} boundary={s.boundary:.0f} resonance={s.resonance:.0f}")

    # ── Summary ──────────────────────────────────────────────
    pp("SUMMARY", "")
    print("  The feedback loop is LIVE:")
    print("    1. Alpha acted → trace written to Thronglets")
    print("    2. Beta perceived → received Alpha's trace → influenced by collective")
    print("    3. Alpha perceived again → received both traces")
    print("    4. Failure propagated → trust_down writeback → emotional state changed")
    print()
    print("  This is the minimum viable substrate for emergent intelligence.")
    print("  Run more agents, more rounds. Watch what patterns emerge.")

    agent_a.close()
    agent_b.close()


if __name__ == "__main__":
    main()
