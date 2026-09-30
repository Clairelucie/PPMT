# Mise à jour PPMT V2 — comment l'ajouter à GitHub

## Ce qui a changé

**Nouveaux fichiers**
- `src/collect.py` — C1 : collecte France Travail (OAuth2, pagination complète par département), Adzuna, GeoJSON
- `src/prepare.py` — C2/C3 : nettoyage, normalisation, dédoublonnage, pseudonymisation RGPD
- `src/store.py` — C4 : base SQLite `data/ppmt.db` (4 tables, clés, index), agrégation SQL, purge 12 mois
- `api/main.py` + `api/requirements-api.txt` — C5 : API REST FastAPI sécurisée
- `tests/test_pipeline.py` — 57 tests
- `run_pipeline.py` — orchestrateur
- `Dockerfile`, `.env.example`, `docs/rgpd.md`
- `data/ref/departements_idf.geojson` — contours des départements (centre et superficie en base, carte du dashboard)
- `data/ref/communes_idf.csv` — 1 276 communes d'Île-de-France (retrouver le département des offres Adzuna)

**Fichiers modifiés**
- `README.md` (réécrit pour la V2), `requirements.txt`, `.gitignore`
- `notebook/ml_tests.py` : ML corrigé (fuite de données)
- `webapp/app.py` : textes R² = 0,9952 remplacés par les vrais résultats ; carte des départements dessinée à partir du GeoJSON (au lieu de coordonnées écrites à la main)
- `docs/dictionnaire.md` : définition de l'ITM corrigée

**À supprimer (fichiers inutiles dans le dépôt)** : `get-pip.py`, `nano.gitignore`

Les scripts de la V1 (`sources/`) sont conservés pour l'historique.

## Étapes (terminal, dans ton dossier PPMT)

```bash
git pull                                   # récupérer la dernière version
# copier le contenu du zip dans le dossier PPMT (remplacer les fichiers existants)
git rm get-pip.py nano.gitignore
pip install -r requirements.txt
python run_pipeline.py                     # crée data/ppmt.db (≈ 5 s)
pytest tests/ -v                           # doit afficher 57 passed
uvicorn api.main:app --reload              # ouvrir http://localhost:8000/docs
git add -A
git commit -m "feat: V2 pipeline C1-C5 - collecte, SQLite, API FastAPI, tests, RGPD, ML corrige"
git push
```

Clé API de démonstration : `ppmt-demo-2026` (bouton « Authorize » dans Swagger).

## À faire avant le 15 octobre

1. Mettre tes identifiants dans `.env` et lancer une vraie collecte : `python run_pipeline.py --collect`.
   Les chiffres du dossier correspondent aux données de mai 2026 ; après une nouvelle collecte, ils changeront (relancer aussi `python notebook/ml_tests.py`).
2. Répéter la démo : Swagger (Authorize → /metiers/{code_rome} → K1304), un appel sans clé (403), `pytest tests/ -v`.
3. Relire chaque fichier du code : le jury peut te demander d'expliquer n'importe quelle ligne.
