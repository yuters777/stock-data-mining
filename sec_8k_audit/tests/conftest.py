"""Adds src/ to sys.path so tests can import sec_8k_audit without install."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
