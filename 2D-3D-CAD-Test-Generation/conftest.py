"""Pytest configuration: ensure the project root is importable.

Lets tests do ``from pipeline... import`` / ``from utils... import`` regardless
of the directory pytest is invoked from.
"""
import os
import sys
from pathlib import Path

# The suite mocks the Anthropic-shaped client; production defaults to OpenAI.
# Set before any pipeline import (load_dotenv never overrides an existing var).
os.environ.setdefault("EXTRACTION_PROVIDER", "anthropic")
# Never let the suite read or write the real spend ledger.
import tempfile  # noqa: E402

os.environ["API_BUDGET_LEDGER"] = str(Path(tempfile.mkdtemp(prefix="budget_")) / "ledger.jsonl")

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
