"""Autofill subsystem: rules → answer cache → LLM fallback.

Public surface:
  resolve_field(candidate, profile, cache, llm)  -> FieldDecision

Everything else is internal.
"""
from .engine import resolve_field
from .models import FieldCandidate, FieldDecision, UserProfile, DecisionSource

__all__ = [
    "resolve_field",
    "FieldCandidate",
    "FieldDecision",
    "UserProfile",
    "DecisionSource",
]
