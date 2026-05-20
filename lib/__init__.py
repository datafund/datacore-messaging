"""Datacore messaging library."""
import sys
from pathlib import Path

# Ensure lib/ is importable from hooks/ (hooks run standalone)
_LIB_DIR = Path(__file__).resolve().parent
_REPO_DIR = _LIB_DIR.parent
if str(_REPO_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_DIR))
