"""
engine — core actor/FSM runtime (domain-agnostic).

Public surface:
    EntityActor   — per-entity mailbox + advance/override handler
    FSMValidator  — validates transitions against a schema
    ActorRegistry — spawns and looks up EntityActor instances
    Router        — single dispatch point for all callers
"""
