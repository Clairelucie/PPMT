"""
Orchestrateur PPMT : C1 collecte → C2/C3 préparation → C4 stockage (+ agrégation SQL).

  python run_pipeline.py            # prépare + stocke à partir des données disponibles
  python run_pipeline.py --collect  # lance d'abord la collecte API (clés dans .env)

Planification quotidienne (cron, 7h) :
  0 7 * * * cd ~/PPMT && python3 run_pipeline.py --collect >> logs/cron.log 2>&1
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import collect  # noqa: E402
import prepare  # noqa: E402
import store  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--collect", action="store_true", help="collecter via les API avant de préparer")
    args = p.parse_args()
    t0 = time.time()
    etapes = ([("C1 collecte", lambda: collect.main([]))] if args.collect else []) + [
        ("C2/C3 préparation", prepare.main),
        ("C4 stockage + agrégation SQL", store.main),
    ]
    for nom, fn in etapes:
        print(f"\n▶ {nom}")
        code = fn()
        if code and nom.startswith("C1"):
            print("  ⚠ collecte partielle — on poursuit avec les données déjà disponibles")
        elif code:
            print(f"  ✗ échec de l'étape {nom}")
            return code
    print(f"\n✓ Pipeline terminé en {time.time() - t0:.1f} s — base : data/ppmt.db")
    print("  API : uvicorn api.main:app --reload  →  http://localhost:8000/docs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
