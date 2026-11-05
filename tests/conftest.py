import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "airflow", ROOT / "backend"):
    sys.path.insert(0, str(p))

os.environ.setdefault("MOCK_AS_OF", "2026-11-04")
