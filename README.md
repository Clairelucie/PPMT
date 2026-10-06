# PPMT — Plateforme Prédictive des Métiers en Tension (Île-de-France)

Projet RNCP37827BC01 — Claire Lucie DIOUF — soutenance du 16 octobre 2026.

PPMT collecte les offres d'emploi d'Île-de-France (France Travail + Adzuna), les nettoie, les stocke dans une base SQLite normalisée, calcule un indice de tension par code ROME, puis les expose par une **API REST sécurisée** (FastAPI) et un **dashboard** (Streamlit). Un modèle de Machine Learning (XGBoost) repère les métiers en tension.

## Chiffres de la version V2 (collecte du 6 octobre 2026)

| Indicateur | Valeur |
|---|---|
| Offres en base | 62 435 (France Travail 58 301 · Adzuna 4 134) |
| Codes ROME | 1 514 |
| Métiers « très en tension » | 235 (≈ 75 % des offres rattachées à un code ROME) |
| Collecte France Travail | 63 173 offres sur 63 504 annoncées (99,5 %), 492 appels, environ 6 min 40 s |
| Tests automatisés | 57 tests pytest réussis |
| Modèle ML (XGBoost, 717 métiers) | ROC-AUC 0,886 · F1 0,785 · exactitude équilibrée 0,804 |

## Démonstration

- **Choix 1 (principal) : en local**, sur la base figée du 6 octobre 2026 (voir « Lancement rapide »).
- **Choix 2 (secours) : en ligne** — https://ppmt-claire.streamlit.app (même base figée, branche `demo-cloud` du dépôt).

La base est figée volontairement pour la soutenance : les chiffres des documents correspondent à une collecte précise, et une nouvelle collecte donnerait d'autres valeurs.

## Lancement rapide

```bash
git clone https://github.com/Clairelucie/PPMT.git && cd PPMT
pip install -r requirements.txt
cp .env.example .env                 # renseigner les identifiants France Travail et Adzuna
```

### Option A — partir de la base d'octobre (recommandé pour la démonstration)

Récupérer l'archive `data_ppmt_octobre.zip` (base `ppmt.db`, résultats ML, modèles), la décompresser dans un dossier temporaire, puis copier les fichiers :

```bash
python3 -m zipfile -e data_ppmt_octobre.zip /tmp/oct
cp /tmp/oct/ppmt.db /tmp/oct/ml_resultats.json /tmp/oct/predictions_tension.csv data/
cp /tmp/oct/models/* webapp/models/
python3 -c "import sqlite3; print(sqlite3.connect('data/ppmt.db').execute('select count(*) from offres').fetchone())"   # (62435,)
```

### Option B — refaire la chaîne complète

```bash
python run_pipeline.py --collect     # C1 → C4 : collecte, préparation, stockage (environ 7 min de collecte)
python notebook/ml_tests.py          # résultats ML + modèle de tension
```

> La collecte dépend des clés API et du réseau, et elle produit d'autres chiffres que ceux du dossier de soutenance.

### Lancer les services

```bash
pytest tests/ -v                          # 57 tests
export PPMT_API_KEY=ppmt-demo-2026        # clé de démonstration
uvicorn api.main:app --reload             # API       → http://localhost:8000/docs
streamlit run webapp/app.py               # dashboard → http://localhost:8501
```

## API

Les 7 routes sont en lecture seule (GET) et protégées par l'en-tête `X-API-Key`, sauf `/health`.

| Route | Rôle |
|---|---|
| `GET /health` | état du service et nombre d'offres (public) |
| `GET /offres` | liste paginée et filtrable des offres |
| `GET /offres/{offre_id}` | détail d'une offre |
| `GET /metiers` | indicateurs de tension par métier (tri décroissant) |
| `GET /metiers/{code_rome}` | fiche métier : tension, départements, contrats |
| `GET /stats/tension` | répartition des métiers par statut de tension |
| `GET /stats/departements` | offres et indicateurs par département |

La documentation interactive est sur `/docs` (Swagger). Exemple :

```bash
curl -H "X-API-Key: ppmt-demo-2026" http://localhost:8000/metiers/K1304
```

Sécurité : clé API (403 sans clé), paramètres validés par Pydantic (422), SQL paramétré, `limit` ≤ 500, base ouverte en lecture seule, image Docker minimale avec clé injectée en secret.

## Architecture

```
PPMT/
├── src/
│   ├── collect.py     C1 — API France Travail (cascade), API Adzuna, contours et communes IDF
│   ├── prepare.py     C2/C3 — nettoyage, normalisation, dédoublonnage, RGPD
│   └── store.py       C4 — schéma SQLite, chargement, agrégation SQL, purge
├── api/main.py        C5 — API REST FastAPI
├── tests/             57 tests pytest
├── run_pipeline.py    orchestrateur C1 → C4
├── webapp/app.py      dashboard Streamlit (lit data/ppmt.db)
├── notebook/ml_tests.py   expérimentation ML (V2)
├── docs/              dictionnaire de données, registre RGPD
└── Dockerfile         image de l'API
```

### Collecte France Travail en cascade

L'API France Travail ne renvoie pas plus de 3 150 offres par requête. La collecte découpe donc par département, puis par fenêtres de dates de création (365 jours divisés par deux jusqu'à 1 heure), puis par type de contrat, jusqu'à ce que chaque requête passe sous le plafond. Résultat : 99,5 % des offres, contre 38 % avec la version de mai.

### Adzuna

L'API annonce 220 238 offres ; le script lit au maximum 250 pages de 50 offres (12 500) : c'est un **échantillon**. Les codes ROME sont rattachés par l'intitulé, puis par la catégorie Adzuna, puis restent vides s'il n'y a pas de correspondance.

## Machine Learning

La première version (V1) annonçait un R² de 0,995, dû à une **fuite de données** : la cible était calculée à partir des variables d'entrée. La V2 reformule le problème en classification « métier en tension » (717 métiers d'au moins 10 offres), avec validation croisée :

| Modèle | ROC-AUC | F1 |
|---|---|---|
| Hasard | 0,51 | — |
| Régression logistique | 0,61 | 0,56 |
| Random Forest | 0,87 | 0,76 |
| **XGBoost (retenu)** | **0,89** | **0,79** |

## Limites connues

- Adzuna n'est lu qu'en échantillon (12 500 offres sur 220 238).
- L'indice mesure uniquement la demande des employeurs, pas le nombre de demandeurs d'emploi.
- La collecte n'est pas planifiée automatiquement (lancement à la demande ; cron puis Airflow prévus).
- La cascade de collecte et la table de correspondance ROME d'Adzuna n'ont pas de test unitaire dédié.
- Une seule collecte complète : pas d'historique, donc pas de prévision.

## Équipe

- **Claire Lucie DIOUF** — V1 : collecte France Travail (OAuth2), dashboard Streamlit, Machine Learning. V2 : cascade France Travail, stockage, API, tests, RGPD, correction du ML, gestion du dépôt Git (branches, commits) et déploiement du dashboard.
- **Bernard GBOHOUGNON** — V1 : collecte et nettoyage Adzuna, administration du dépôt Git (droits, branches, protection de `main`). V2 : collecte et nettoyage Adzuna, idempotence du pipeline (journaux, relance sans doublon).

Les données sont des offres d'emploi publiques. Les données personnelles éventuelles (e-mails, téléphones) sont pseudonymisées ou supprimées avant stockage ; voir `docs/rgpd.md`.
