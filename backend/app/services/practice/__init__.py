"""Practice domain services.

Keep orchestration that has a distinct consistency/lifecycle boundary out of the
legacy ``practice_service`` module.  Public API compatibility remains in
``practice_service`` while new code can evolve in smaller domain modules.
"""
