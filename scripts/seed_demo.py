from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))
from provenance.service import Prototype  # noqa: E402


if __name__ == "__main__":
    system = Prototype(ROOT)
    print(system.seed_demo())
    print("PQC:", system.status()["pqc_engine"], "watermark:", system.status()["watermark_engine"])
