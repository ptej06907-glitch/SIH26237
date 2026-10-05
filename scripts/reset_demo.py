from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = (ROOT / "data").resolve()
if DATA.parent != ROOT.resolve() or DATA.name != "data":
    raise RuntimeError("Unsafe demo data path")

if __name__ == "__main__":
    if DATA.exists():
        shutil.rmtree(DATA)
    sys.path.insert(0, str(ROOT / "services" / "api"))
    from provenance.service import Prototype
    system = Prototype(ROOT)
    print(system.seed_demo())
    print("Demo reset complete. Three fictional recipients, one encrypted sample PDF and genesis blocks are ready.")
