"""Centralized test path configuration.

All sys.path setup lives HERE — individual test files must NOT use sys.path.insert().

Paths added:
- lambda/     → enables `from src.X.Y import Z` (matches Docker container layout)
- lambda/src/ → enables `from X.Y import Z` (legacy property test imports)
- cdk/        → enables `from stacks.pipeline_stack import ...`
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent

# Add paths once at test session start
_paths_to_add = [
    str(_project_root / "lambda"),
    str(_project_root / "lambda" / "src"),
    str(_project_root / "cdk"),
]

for p in _paths_to_add:
    if p not in sys.path:
        sys.path.insert(0, p)
