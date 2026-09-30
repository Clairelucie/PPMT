# PPMT — Plateforme Prédictive des Métiers en Tension (Île-de-France)

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688)](https://fastapi.tiangolo.com)
[![Tests](https://img.shields.io/badge/pytest-57%20tests-green)]()
[![RNCP](https://img.shields.io/badge/RNCP-37827BC01-orange)]()

**Équipe** : Claire DIOUF & Bernard GBOHOUGNON · **Formation** : Développeur en IA — Artefact
**Bloc** : RNCP37827BC01 — Réaliser la collecte, le stockage et la mise à disposition des données d'un projet en IA

---

## 1. Le service

PPMT repère les métiers qui recrutent le plus en Île-de-France en croisant les offres **France Travail** (API officielle OAuth2) et **Adzuna** (agrégateur). Les données sont collectées, nettoyées, stockées en base SQLite, puis mises à disposition par une **API REST sécurisée** et un **dashboard Streamlit**.

**Problématique** : comment identifier automatiquement les métiers en tension de recrutement en Île-de-France pour mieux orienter candidats, recruteurs et organismes de formation ?

## 2. Architecture

```
C1 Collecte            C2/C3 Préparation        C4 Stockage                 C5 Mise à disposition
─────────────────      ───────────────────      ─────────────────────       ──────────────────────
API France Travail  →  src/prepare.py        →  src/store.py            →   api/main.py (FastAPI)
API Adzuna             dédoublonnage            SQLite data/ppmt.db          7 endpoints · X-API-Key
Contours + communes    salaires (médianes) ·      4 tables · FK · index        Swagger /docs
src/collect.py         départements · RGPD      agrégation SQL (ITM)     →   webapp/app.py (Streamlit)
                       run_pipeline.py orchestre C1 → C4 · tests/ (pytest)
```

## 3. Installation et lancement

```bash
git clone https://github.com/maninconseil-commits/PPMT.git && cd PPMT
pip install -r requirements.txt
cp .env.example .env            # renseigner les clés France Travail et Adzuna

python run_pipeline.py --collect   # C1 → C4 (sans --collect : repart des CSV versionnés)
pytest tests/ -v                   # 57 tests
uvicorn api.main:app --reload      # API → http://localhost:8000/docs
streamlit run webapp/app.py        # dashboard → http://localhost:8501
```

Planification quotidienne : `0 7 * * * cd ~/PPMT && python3 run_pipeline.py --collect >> logs/cron.log 2>&1`

## 4. Structure

```
PPMT/
├── src/
│   ├── collect.py        C1 — API France Travail (OAuth2, pagination par département), API Adzuna, GeoJSON
│   ├── prepare.py        C2/C3 — nettoyage, normalisation, dédoublonnage, pseudonymisation
│   └── store.py          C4 — schéma SQLite, chargement, agrégation SQL, purge RGPD
├── api/main.py           C5 — API REST FastAPI
├── tests/test_pipeline.py  57 tests (collecte simulée, règles, base, API)
├── run_pipeline.py       orchestrateur
├── notebook/ml_tests.py  expérimentation ML (hors BC01)
├── webapp/app.py         dashboard Streamlit
├── sources/              scripts de la V1 (historique)
├── data/ref/             departements_idf.geojson (contours) · communes_idf.csv (1 276 communes) — versionnés
├── docs/                 dictionnaire.md · rgpd.md · soutenance/
└── Dockerfile            image de l'API
```

## 4 bis. Préparation — méthodes retenues

| Problème | Méthode |
|---|---|
| Salaires non affichés (64 %) | Médiane des salaires affichés : métier × département → métier → domaine ROME → département → région ; `salaire_impute`, `salaire_source` |
| Codes ROME Adzuna | Intitulé identique à des offres France Travail, sinon catégorie Adzuna ; fourre-tout M1607 écarté |
| Lieux sans département | Référentiel des 1 276 communes d'Île-de-France |
| Doublons | URL puis titre + entreprise + lieu, entre les deux sources |

## 5. Base de données (`data/ppmt.db`)

| Table | Lignes | Clé | Rôle |
|---|---|---|---|
| `departements` | 8 | `code_dept` | référentiel des 8 départements : centre géographique et superficie calculés depuis le GeoJSON |
| `metiers_rome` | 1 100 | `code_rome` | référentiel ROME (libellé officiel France Travail) |
| `offres` | 28 219 | `id`, `hash_offre` UNIQUE | une ligne par offre, FK vers les deux référentiels |
| `indicateurs_tension` | 1 100 | `code_rome` | agrégats par métier calculés en SQL |

**Indice de tension (ITM)** = nombre d'offres du métier ÷ nombre moyen d'offres par métier × 100 (100 = métier moyen).
Statuts : SATURÉ < 50 · ÉQUILIBRÉ 50–100 · EN TENSION 100–150 · TRÈS EN TENSION > 150.
L'ITM mesure la pression de la demande des employeurs (côté offres) ; PPMT ne dispose pas du nombre de candidats.

## 6. API

| Méthode | Endpoint | Description |
|---|---|---|
| GET | `/health` | disponibilité (public) |
| GET | `/offres` | liste paginée — filtres `departement`, `code_rome`, `source`, `contrat`, `q` |
| GET | `/offres/{id}` | détail d'une offre |
| GET | `/metiers` | indicateurs de tension, tri décroissant, filtre `statut` |
| GET | `/metiers/{code_rome}` | fiche métier : répartition par département et par contrat |
| GET | `/stats/departements` | volume, densité (offres / 100 km²), part de CDI, salaire moyen, coordonnées |
| GET | `/stats/tension` | nombre de métiers et d'offres par statut |

```bash
curl -H "X-API-Key: $PPMT_API_KEY" "http://localhost:8000/metiers?statut=TRES%20EN%20TENSION&limit=5"
```

## 7. Machine Learning (expérimentation, hors BC01)

- **V1** (régression de l'ITM à partir des volumes d'offres, R² = 0,995) **écartée** : l'ITM est calculé à partir de ces volumes → fuite de données.
- **V2** : classification « en tension » à partir du **profil** des offres (contrats, salaires, expérience, famille ROME), sans variable de volume, sur 446 métiers ayant au moins 10 offres. Validation croisée à 5 plis, trois modèles comparés : régression logistique (AUC 0,58), Random Forest (AUC 0,82), **XGBoost retenu (AUC 0,84 · F1 0,77)**. Un classement au hasard donne 0,5.
- Prochaine étape : croiser avec le nombre de demandeurs d'emploi par code ROME et accumuler des collectes quotidiennes pour une vraie prévision à 3 mois.

## 8. RGPD

Aucune donnée de candidat. E-mails et téléphones masqués avant stockage, conservation 12 mois glissants, API en lecture seule. Registre : [`docs/rgpd.md`](docs/rgpd.md).

## 9. Organisation

| Membre | Contributions |
|---|---|
| Claire DIOUF | V1 : collecte France Travail (OAuth2), dashboard, ML · V2 : refonte collect / prepare / store en modules testables, API FastAPI, tests, correction du ML |
| Bernard GBOHOUGNON | V1 : collecte et nettoyage Adzuna, mapping catégories → ROME, administration Git · V2 : journalisation (logs) et idempotence du pipeline |

*Formation Développeur en IA — RNCP37827BC01 — Artefact — 2026*
