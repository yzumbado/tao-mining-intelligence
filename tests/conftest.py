"""Centralized test path configuration.

All sys.path setup lives HERE — individual test files must NOT use sys.path.insert().

Paths added:
- lambda/     → enables `from src.X.Y import Z` (matches Docker container layout)
- cdk/        → enables `from stacks.pipeline_stack import ...`

NOTE: lambda/src/ is NOT added. Tests MUST use `from src.X` to match the
Docker runtime (COPY src/ ${LAMBDA_TASK_ROOT}/src/, CMD src.X.handler.handle).
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent

_paths_to_add = [
    str(_project_root / "lambda"),
    str(_project_root / "cdk"),
]

for p in _paths_to_add:
    if p not in sys.path:
        sys.path.insert(0, p)
