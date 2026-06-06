"""Cairn integration module for Flocks.

Implements the blackboard architecture with Fact-Intent graph for
state-space search problems.

Ported from the original Cairn project.
"""

from flocks.cairn import models, storage
from flocks.cairn.dispatcher import (
    config as dispatch_config,
    contracts,
    logging as dispatch_logging,
    models as dispatch_models,
    output_parser,
    prompting,
    scheduler,
    tasks,
    runtime,
    workers,
)

__version__ = "0.1.0"
__all__ = [
    "models",
    "storage",
    "dispatch_config",
    "contracts",
    "dispatch_logging",
    "dispatch_models",
    "output_parser",
    "prompting",
    "scheduler",
    "tasks",
    "runtime",
    "workers",
]