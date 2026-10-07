# PPMT — Plateforme Prédictive des Métiers en Tension (Île-de-France)

Projet RNCP37827BC01 — Claire Lucie DIOUF — soutenance du 16 octobre 2026.

PPMT collecte les offres d'emploi d'Île-de-France (France Travail + Adzuna), les nettoie, les stocke dans une base SQLite normalisée, calcule un indice de tension par code ROME, puis les expose par une **API REST sécurisée** (FastAPI) et un **dashboard** (Streamlit). Un modèle de Machine Learning (XGBoost) repère les métiers en tension.


## Problématique et Issue Tree

**Comment collecter, fiabiliser et mettre à disposition automatiquement les offres d'emploi de plusieurs sources pour identifier les métiers qui recrutent le plus en Île-de-France ?**

```
├─► 1. COLLECTER (C1) ─────────────┬─► [CLAIRE] Combien d'offres France Travail ?
│   (D'où viennent les données ?)  │    (API OAuth2, cascade : 63 173 sur 63 504, 99,5 %)
│                                  └─► [BERNARD] Quelles offres Adzuna ?
│                                       (API Adzuna : échantillon de 12 500 sur 220 238)
│
├─► 2. FIABILISER (C2 / C3) ───────┬─► [CLAIRE & BERNARD] Comment supprimer les doublons ?
│   (Peut-on s'y fier ?)           │    (URL puis empreinte : 12 404 supprimés, 0 en base)
│                                  ├─► [CLAIRE] Que faire des salaires absents (56 %) ?
│                                  │    (médiane du groupe le plus précis, valeur signalée)
│                                  ├─► [BERNARD] Comment rattacher Adzuna aux codes ROME ?
│                                  │    (intitulé 636, catégorie 1 388, sans code 2 110)
│                                  └─► [CLAIRE] Comment protéger les données personnelles ?
│                                       (e-mails et téléphones masqués, purge à 12 mois)
│
├─► 3. STOCKER (C4) ───────────────┬─► [CLAIRE] Quel modèle de données ?
│   (Où ranger la donnée ?)        │    (SQLite : 4 tables, 62 435 offres, 1 514 métiers)
│                                  └─► [BERNARD] Comment relancer sans doublon ?
│                                       (idempotence : un fichier brut par source et par jour)
│
└─► 4. METTRE À DISPOSITION (C5) ──┬─► [CLAIRE] Comment l'exposer ? (API FastAPI, 7 routes, clé API)
    (Pour qui ?)                   ├─► [CLAIRE] Comment le montrer ? (dashboard Streamlit, 6 onglets)
                                   ├─► [CLAIRE] Comment le garantir ? (57 tests pytest)
                                   └─► [CLAIRE] Quels métiers sont en tension ? (ML : XGBoost, AUC 0,886)
```

La version détaillée est dans [`docs/issue_tree.md`](docs/issue_tree.md).

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

## Arborescence du projet

```
PPMT/                          # Plateforme Prédictive des Métiers en Tension (Île-de-France)
│
├── data/                      # ⚠️ Données locales : data/raw/ est ignoré par Git (jamais d'upload de données brutes)
│   ├── raw/                   # Réponses brutes des API : france_travail_AAAAMMJJ.json, adzuna_AAAAMMJJ.json (1 par source et par jour)
│   ├── ref/                   # Fichiers de référence : communes_idf.csv (1 276 communes), departements_idf.geojson (8 contours)
│   ├── processed/             # offres_unifiees.csv : offres nettoyées et unifiées (63 242 lignes)
│   ├── offres_ft_idf.csv      # France Travail aplati, produit par collect.py (entrée de prepare.py)
│   ├── offres_idf.csv         # Adzuna aplati, produit par collect.py (entrée de prepare.py)
│   ├── offres_ft_idf_clean.csv  # Version nettoyée de secours, versionnée dans Git (lue si les bruts sont absents)
│   ├── offres_idf_clean.csv   # Idem pour Adzuna
│   ├── ppmt.db                # Base SQLite : 62 435 offres, 1 514 métiers ROME (fournie par data_ppmt_octobre.zip)
│   ├── ml_resultats.json      # Résultats du Machine Learning (AUC, F1, variables importantes)
│   └── predictions_tension.csv# Prédictions « en tension » par métier
│
├── logs/                      # collect_AAAAMMJJ_HHMMSS.log : un journal horodaté par collecte
│
├── notebook/                  # Espace d'expérimentation
│   └── ml_tests.py            # ML V2 : classification « en tension » (XGBoost, AUC 0,886)
│
├── src/                       # Le cœur logique : scripts Python permanents du pipeline (ex-« sources/ »)
│   ├── collect.py             # C1 : France Travail (OAuth2, cascade), Adzuna, contours et communes IDF
│   ├── prepare.py             # C2/C3 : nettoyage, dédoublonnage, salaires, codes ROME, RGPD
│   └── store.py               # C4 : schéma SQLite, chargement, agrégation SQL, purge 12 mois
│
├── api/
│   ├── main.py                # C5 : API REST FastAPI (7 routes, clé X-API-Key, Swagger)
│   └── requirements-api.txt   # Dépendances de l'API seule (image Docker allégée)
│
├── webapp/                    # Interface utilisateur (ce que le jury manipule)
│   ├── app.py                 # Dashboard Streamlit : 6 onglets, lit data/ppmt.db
│   └── models/                # Modèles ML sauvegardés, utilisés par le dashboard
│
├── tests/
│   └── test_pipeline.py       # 57 tests pytest (collecte simulée, règles, base, API)
│
├── docs/
│   ├── dictionnaire.md        # Dictionnaire de données
│   ├── rgpd.md                # Registre des traitements RGPD
│   ├── arborescence.md        # Ce plan commenté
│   ├── issue_tree.md          # Issue Tree du projet
│   └── PPMT_Arborescence_Issue_Tree_V2.xlsx   # Classeur de cadrage (arborescence, explications, Issue Tree)
│
├── run_pipeline.py            # Orchestrateur C1 → C4 (python run_pipeline.py --collect)
├── Dockerfile                 # Image de l'API
├── .env.example               # Noms des variables d'environnement (jamais de valeurs)
├── .gitignore                 # Ignore .env, data/raw/, environnements Python
├── requirements.txt           # Outils Python à installer (pip install -r requirements.txt)
└── README.md                  # Page d'accueil GitHub : notice, Issue Tree, dictionnaire de données
```

Le rôle de chaque dossier est expliqué dans [`docs/arborescence.md`](docs/arborescence.md). Les données circulent ainsi : `src/collect.py` télécharge dans `data/raw/` → `src/prepare.py` nettoie et écrit `data/processed/` → `src/store.py` range dans `data/ppmt.db` → l'API (`api/main.py`) et le dashboard (`webapp/app.py`) lisent cette base.

## Dictionnaire de données

### Sources

| Source | Type de données | Contenu / champs principaux | Volume (collecte du 6 octobre 2026) | Qualité et risques |
|---|---|---|---|---|
| France Travail — Offres d'emploi v2 | API REST, JSON (semi-structuré) | Identifiant, intitulé, entreprise, lieu, code ROME natif, type de contrat, temps de travail, expérience, salaire (libellé), date de création, description, URL | 63 173 offres sur 63 504 annoncées (99,5 %), 492 appels, environ 6 min 40 s | Plafond de 3 150 offres par requête (cascade nécessaire) ; 331 offres d'écart (0,5 %) ; salaires non affichés ; environ 4 845 doublons supprimés en préparation (déduit par calcul) |
| Adzuna | API REST, JSON (semi-structuré) | Intitulé, entreprise, lieu, catégorie, contrat, salaire min/max, date, description, URL | 12 500 offres lues sur 220 238 annoncées (échantillon) ; 4 134 en base après dédoublonnage et purge | Échantillon ; code ROME déduit (51 % des offres sans code) ; contrat « Non renseigné » pour 55 % ; 68 % des salaires absents |
| Contours des départements (IGN) | Fichier GeoJSON | Polygones des 8 départements d'Île-de-France | 8 contours | Sert à calculer le centre et la superficie de chaque département (table departements) |
| Communes d'Île-de-France (IGN / Insee) | Fichier GeoJSON converti en CSV | Code et nom des communes, rattachement au département | 1 276 communes | Sert à retrouver le département des offres Adzuna ; 32 offres restent sans département |

### Tables de la base SQLite (`data/ppmt.db`)

| Table | Rôle | Lignes | Colonnes |
|---|---|---|---|
| departements | Référentiel des départements | 8 | `code_dept`, `nom`, `latitude`, `longitude`, `superficie_km2` |
| metiers_rome | Référentiel des métiers ROME | 1 514 | `code_rome`, `libelle` |
| offres | Table de faits : une ligne par offre | 62 435 | `id`, `source`, `id_source`, `hash_offre`, `titre`, `entreprise`, `lieu`, `code_dept`, `code_rome`, `categorie`, `contrat`, `temps_travail`, `experience`, `salaire_min`, `salaire_max`, `salaire_moyen`, `salaire_impute`, `salaire_source`, `rome_source`, `date_publication`, `description`, `url`, `date_import` |
| indicateurs_tension | Table d'agrégats recalculée à chaque exécution | 1 514 | `code_rome`, `nb_offres_ft`, `nb_offres_adzuna`, `nb_offres_total`, `nb_entreprises`, `nb_departements`, `part_cdi`, `salaire_median`, `part_salaire_affiche`, `indice_tension`, `statut`, `date_calcul` |

Le détail colonne par colonne (types, règles, valeurs) est dans [`docs/dictionnaire.md`](docs/dictionnaire.md).

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

## Détails du pipeline

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
- Machine Learning : l'importance d'une variable n'indique pas le sens de son effet, et la longueur des descriptions reflète surtout la source (300 caractères conservés pour France Travail, 500 pour Adzuna) : le résultat est un signal exploratoire.

## Équipe

- **Claire Lucie DIOUF** — V1 : collecte France Travail (OAuth2), dashboard Streamlit, Machine Learning. V2 : cascade France Travail, stockage, API, tests, RGPD, correction du ML, gestion du dépôt Git (branches, commits) et déploiement du dashboard.
- **Bernard GBOHOUGNON** — V1 : collecte et nettoyage Adzuna, administration du dépôt Git (droits, branches, protection de `main`). V2 : collecte et nettoyage Adzuna, idempotence du pipeline (journaux, relance sans doublon).

Les données sont des offres d'emploi publiques. Les données personnelles éventuelles (e-mails, téléphones) sont pseudonymisées ou supprimées avant stockage ; voir `docs/rgpd.md`.


## Documents du dossier `docs/`

| Fichier | Contenu |
|---|---|
| `dictionnaire.md` | Dictionnaire de données (tables, colonnes, règles) |
| `rgpd.md` | Registre des traitements RGPD |
| `arborescence.md` | Plan commenté du dépôt |
| `issue_tree.md` | Issue Tree du projet |
| `PPMT_Arborescence_Issue_Tree_V2.xlsx` | Classeur de cadrage : arborescence, explications, évolutions depuis mai, Issue Tree, sources de données |
