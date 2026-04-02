"""Oasyce Agent — autonomous data asset registration daemon + agent runtime.

    pip install oasyce-sdk
    oasyce-agent start

Agent Runtime (the feedback loop)::

    from oasyce_sdk.agent.runtime import AgentRuntime

    agent = AgentRuntime()
    perception = agent.perceive("I need to analyze financial data")
    # ... make decision ...
    agent.act("analyzed Q4 data", "succeeded", "financial analysis")
"""
