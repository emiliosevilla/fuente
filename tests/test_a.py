"""Must load before other test modules (alphabetically first) to disable .pyc writes."""
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parent.parent

# Snapshot tracked-artifact status at suite start (after bytecode guard is active).
_status = subprocess.run(
    ["git", "status", "--short"],
    cwd=REPO_ROOT,
    capture_output=True,
    text=True,
    check=False,
)
GIT_STATUS_AT_SUITE_START = _status.stdout
