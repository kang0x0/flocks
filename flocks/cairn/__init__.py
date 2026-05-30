"""
Cairn integration module for Flocks.

Implements the blackboard architecture with Fact-Intent graph for
state-space search problems.

Core concepts:
- Fact: Confirmed objective findings (immutable, append-only)
- Intent: Declared exploration direction from one or more Facts
- Hint: External strategy suggestions (not part of the graph)
- Project: A problem instance with origin, goal, and evolving graph

This module provides:
- Data models (Fact, Intent, Hint, Project)
- Storage layer (SQLite persistence)
- Protocol API (HTTP endpoints)
- Dispatcher (task scheduling and execution)
"""

__all__ = [
    "models",
    "storage",
    "protocol",
    "dispatcher",
]
