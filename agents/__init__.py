"""
agents — LLM adapter layer.

Public surface:
    AgentAdapter   — calls an LLM with structured output for each stage
    StubAdapter    — deterministic fake; always picks the first outbound edge
"""
