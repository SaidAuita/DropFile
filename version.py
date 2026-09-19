"""
DropFile version definition.
"""

import subprocess
from pathlib import Path

__version__ = "1.26.3"
__build__ = "84"


def get_build_number() -> str:
    """Returns static build number or dynamic git commit count if available."""
    try:
        root = Path(__file__).resolve().parent
        if (root / ".git").exists():
            res = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0 and res.stdout.strip().isdigit():
                return res.stdout.strip()
    except Exception:
        pass
    return __build__


def get_full_version() -> str:
    """Returns full version with build, e.g. '1.26.3 (build 84)'."""
    return f"{__version__} (build {get_build_number()})"
