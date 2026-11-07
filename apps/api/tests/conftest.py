"""Global pytest fixtures and path configuration."""

import sys
from pathlib import Path

# Add repo root to sys.path so datasets and benchmarks can be imported
repo_root = Path(__file__).resolve().parents[3]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
