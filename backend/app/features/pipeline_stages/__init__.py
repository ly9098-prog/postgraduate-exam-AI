"""Pipeline stage modules — extracted business logic from pipeline_orchestrator.py.

Each stage module exposes a ``run_<stage>_stage`` function that accepts
stage-specific data and returns a dict result.

Design principles:
1. Stage files own the business logic; orchestrator owns the lifecycle.
2. No stage file imports from pipeline_orchestrator.py.
3. Each function signature is explicit about what data it needs.
4. No global state mutation inside stage functions.
"""
