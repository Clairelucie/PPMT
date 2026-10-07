# Arborescence du projet PPMT

Structure du dépôt à la version V2 (soutenance du 16 octobre 2026). Le même plan est dans le `README.md` et dans le classeur `PPMT_Arborescence_Issue_Tree_V2.xlsx`.

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

## Rôle de chaque dossier


### 1. Le dossier data/ : le hangar à matières premières


C'est l'endroit où transitent les données : le stock physique de l'usine.


raw/ (données brutes) : les réponses des API telles que France Travail et Adzuna les renvoient (france_travail_20261006.json, adzuna_20261006.json). Un fichier par source et par jour : si le fichier du jour existe déjà, il n'est pas retéléchargé (idempotence). C'est aussi l'historique des collectes. Attention : ces fichiers contiennent les réponses non masquées de l'API.


ref/ (référentiels) : les deux fichiers de référence téléchargés une fois : communes_idf.csv (1 276 communes d'Île-de-France, pour retrouver le département des offres Adzuna) et departements_idf.geojson (contours des 8 départements, pour le centre et la superficie).


processed/ (données nettoyées) : offres_unifiees.csv, produit par prepare.py : 63 242 offres des deux sources, après suppression de 12 404 doublons.


offres_ft_idf.csv et offres_idf.csv : les offres aplaties (une ligne par offre) que collect.py écrit à partir des réponses brutes ; c'est l'entrée de prepare.py. offres_ft_idf_clean.csv et offres_idf_clean.csv sont des versions nettoyées de secours, versionnées dans Git : prepare.py les lit si les fichiers bruts sont absents.


ppmt.db, ml_resultats.json, predictions_tension.csv : la base SQLite (62 435 offres) et les résultats du Machine Learning. Pour la soutenance, la base est figée au 6 octobre 2026 : elle est fournie par l'archive data_ppmt_octobre.zip.


⚠️ Pourquoi le .gitignore ? Les fichiers bruts pèsent lourd, contiennent des données non masquées, et ne doivent jamais être publiés. Le .gitignore ordonne à Git : « suis mon code, mais ne touche pas à data/raw/ ». Le fichier .env (identifiants) est ignoré pour la même raison.


### 2. Le dossier logs/ : le journal de bord


Chaque collecte écrit un journal horodaté (collect_AAAAMMJJ_HHMMSS.log) : zones découpées, avertissements, bilan de couverture (63 173 offres sur 63 504 annoncées le 6 octobre). C'est la preuve de ce que la collecte a réellement fait.


### 3. Le dossier notebook/ : le laboratoire d'expérimentation


ml_tests.py : l'expérimentation Machine Learning de la V2. La V1 annonçait un R² de 0,995, dû à une fuite de données ; la V2 classe les 717 métiers d'au moins 10 offres en « en tension » ou non (XGBoost : AUC 0,886, F1 0,785). Hors du bloc BC01, c'est une ouverture.


### 4. Le dossier src/ : les machines automatisées de l'usine


C'est le dossier le plus important pour l'évaluation du bloc (le pipeline). Ce sont des scripts Python permanents, chacun testable et exécutable seul. Il remplace le dossier « sources/ » du plan de mai : même rôle, nom plus courant.


collect.py (la pompe à API) : se connecte à France Travail en OAuth2 (client_credentials), renouvelle le jeton toutes les 20 minutes, et télécharge les offres. L'API plafonne à 3 150 offres par requête : la collecte découpe en cascade (département, fenêtres de dates, type de contrat). Il lit aussi Adzuna (échantillon de 12 500 offres sur 220 238), les contours des départements et les 1 276 communes d'Île-de-France. 3 tentatives avec attente croissante, pause de 100 ms entre deux appels.


prepare.py (le centre de tri) : prend les fichiers de data/raw/, supprime les doublons (URL, puis titre + entreprise + lieu), complète les salaires manquants par une médiane (56 % non affichés), rattache les offres Adzuna aux codes ROME, harmonise les contrats en 7 catégories, masque les e-mails et téléphones (RGPD).


store.py (le rangement) : crée le schéma SQLite (4 tables, clés étrangères, contraintes CHECK/UNIQUE, 6 index), charge les offres, calcule les indicateurs de tension en SQL, purge les offres de plus de 12 mois. C'est l'équivalent du schema_db.sql du plan de mai.


### 5. Le dossier api/ : la porte d'entrée pour les développeurs


main.py : l'API FastAPI. requirements-api.txt liste ses seules dépendances, pour une image Docker légère. 7 routes en lecture seule, protégées par une clé X-API-Key (403 sans clé), paramètres validés par Pydantic (422), SQL paramétré, base ouverte en lecture seule. La documentation interactive (Swagger) est sur /docs.


### 6. Le dossier webapp/ : la vitrine du magasin


app.py : le dashboard Streamlit (6 onglets, filtres par département, contrat et secteur). Il ne collecte rien : il lit uniquement data/ppmt.db. models/ contient les modèles ML sauvegardés. Une version en ligne sert de secours : https://ppmt-claire.streamlit.app (branche demo-cloud).


### 7. Le dossier tests/ : le contrôle qualité


test_pipeline.py : 57 tests pytest. 4 pour la collecte (API simulées), 31 pour les règles de préparation, 13 pour la base, 9 pour l'API. Limite connue : la cascade France Travail n'a pas encore de test unitaire dédié.


### 8. Les fichiers à la racine (les indispensables de gestion)


README.md : la notice du projet : problème, Issue Tree, arborescence, dictionnaire de données, lancement, API, limites.


requirements.txt : la liste des outils Python. Une seule commande (pip install -r requirements.txt) installe les mêmes versions chez tout le monde.


.env.example : la liste des variables d'environnement attendues (identifiants France Travail et Adzuna), sans aucune valeur. On le copie en .env, qui n'est jamais envoyé sur Git.


run_pipeline.py : l'orchestrateur. Il enchaîne la collecte, la préparation et le stockage ; sans l'option --collect, il repart des fichiers bruts déjà présents dans data/raw/.


Dockerfile : l'image de l'API (FastAPI, Uvicorn et Pydantic seulement), déployable sur Google Cloud Run ou Render.


### En résumé, comment les données circulent dans cette structure :


1. collect.py télécharge les données dans data/raw/ (et écrit son journal dans logs/).


2. prepare.py nettoie le tout et écrit data/processed/offres_unifiees.csv.


3. store.py range les offres dans la base SQLite data/ppmt.db et calcule les indicateurs de tension.


4. api/main.py et webapp/app.py lisent cette base : l'API pour les développeurs, le dashboard pour les utilisateurs.


5. tests/ vérifie chaque étape ; notebook/ml_tests.py ajoute le modèle de classification des métiers en tension.


## Évolutions par rapport au plan de mai

| Plan de mai (TensioMatch) | Structure V2 (PPMT) | Pourquoi |
|---|---|---|
| sources/extract_api.py | src/collect.py | Un seul module de collecte, avec la cascade France Travail |
| sources/extract_scrape.py (Indeed, Glassdoor) | src/collect.py (API Adzuna) | Le scraping est remplacé par l'API Adzuna : 12 500 offres lues sur 220 238 |
| sources/transform_sql.py | src/prepare.py + src/store.py | Séparation du nettoyage (C2/C3) et du stockage (C4) |
| schema_db.sql (3 tables) | src/store.py (4 tables) | Le schéma est créé par le code : 2 référentiels, 1 table de faits, 1 table d'agrégats |
| webapp/app.py + models/ | webapp/app.py + models/ | Inchangé : dashboard Streamlit et modèles sauvegardés |
| (absent) | api/main.py | Nouveauté V2 : API REST sécurisée (compétence C5) |
| (absent) | tests/test_pipeline.py | Nouveauté V2 : 57 tests pytest |
| (absent) | logs/ | Journal de chaque collecte |
| (absent) | docs/ et Dockerfile | Dictionnaire, registre RGPD, image de l'API |
| notebook/ (un notebook par personne) | notebook/ml_tests.py | Expérimentation ML de la V2 |
