"""Where the Europress engine is. Original layout: next to this folder. Our repo: ../europress/<engine>.
Override with EUROPRESS_ENGINE."""
import os
from pathlib import Path

NAME = "Europress_SMART_Material_Value_Engine_v1.0.1"
_here = Path(__file__).resolve().parent


def engine_root() -> Path:
    if os.getenv("EUROPRESS_ENGINE"):
        return Path(os.environ["EUROPRESS_ENGINE"])
    for cand in (_here.parent / NAME, _here.parent / "europress" / NAME):
        if cand.exists():
            return cand
    return _here.parent / NAME
