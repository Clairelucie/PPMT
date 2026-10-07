# Dictionnaire des données — PPMT (V2, collecte du 6 octobre 2026)

Projet RNCP37827BC01 — soutenance du 16 octobre 2026. Équipe : Claire Lucie DIOUF, Bernard GBOHOUGNON.

Ce dictionnaire décrit la **base SQLite `data/ppmt.db`** produite par `run_pipeline.py` (C1 → C4), puis les fichiers de sortie du Machine Learning. Il remplace la version de mai 2026 (V1), qui décrivait des fichiers CSV séparés (4 626 offres Adzuna, 24 051 offres France Travail, 1 102 métiers).

Volumes : **62 435 offres** (France Travail 58 301 · Adzuna 4 134), **1 514 codes ROME**, **8 départements**, 1 514 lignes d'indicateurs de tension.

---

## 1. Table `offres` — 62 435 lignes

Une ligne par offre d'emploi, sources France Travail et Adzuna projetées sur un schéma commun.

| Colonne | Type | Description | Valeurs / contraintes | Qualité |
|---|---|---|---|---|
| id | entier | Clé primaire auto-incrémentée | — | — |
| source | texte | Source de l'offre | `france_travail` ou `adzuna` (CHECK) | France Travail 58 301 · Adzuna 4 134 |
| id_source | texte | Identifiant de l'offre chez la source | Texte | — |
| hash_offre | texte | Empreinte de l'offre (identifiant de déduplication) | UNIQUE, non nul | 0 doublon en base |
| titre | texte | Intitulé du poste | Non nul | Offres parasites écartées à la préparation |
| entreprise | texte | Nom de l'entreprise | `Non renseigné` si vide | 14 495 non renseignées (France Travail 24,7 %, Adzuna 2,9 %) ; exclues du comptage des entreprises |
| lieu | texte | Commune ou ville | Texte | Île-de-France uniquement |
| code_dept | texte | Code du département | 75, 77, 78, 91, 92, 93, 94, 95 — clé étrangère vers `departements` | 32 offres sans département |
| code_rome | texte | Code métier ROME | Clé étrangère vers `metiers_rome` | 60 325 offres rattachées ; 2 110 sans code (toutes Adzuna) |
| categorie | texte | Catégorie d'origine | France Travail : appellation ROME ; Adzuna : catégorie du site | Adzuna : 27 catégories distinctes en base |
| contrat | texte | Type de contrat normalisé | CDI, CDD, Intérim, Libéral, Alternance, Autre, Non renseigné (CHECK) | CDI 38 188 · CDD 10 317 · Intérim 9 298 · Libéral 1 968 · Non renseigné 2 278 · Autre 386 |
| temps_travail | texte | Temps plein ou partiel | Temps plein, Temps partiel | Renseigné pour 1 122 offres seulement |
| experience | texte | Expérience demandée | Débutant accepté, 1 An(s), 2 An(s)… | — |
| salaire_min | réel | Salaire minimum annuel brut (€) | Entre 10 000 et 300 000 (CHECK) | Heures × 1 820, mois × 12 ; bornes inversées permutées |
| salaire_max | réel | Salaire maximum annuel brut (€) | Entre 10 000 et 300 000 (CHECK) | Idem |
| salaire_moyen | réel | Moyenne de salaire_min et salaire_max, ou salaire complété | — | 100 % des offres ont un salaire |
| salaire_impute | entier | 1 si le salaire a été complété, 0 s'il est affiché | 0 ou 1 (CHECK) | 34 997 offres complétées |
| salaire_source | texte | Origine du salaire | `affiché`, `médiane métier × département`, `médiane métier`, `médiane domaine`, `médiane département`, `médiane régionale` | Affiché : 27 438 · métier × département : 24 635 · métier : 6 638 · domaine : 2 035 · département : 1 679 · région : 10 |
| rome_source | texte | Origine du code ROME | `france_travail`, `intitule`, `categorie` (CHECK), vide si aucun code | France Travail 58 301 · Adzuna par intitulé 636 · par catégorie 1 388 · sans code 2 110 |
| date_publication | texte | Date de création de l'offre | ISO 8601 | Fenêtre de 12 mois (9 octobre 2025 → 6 octobre 2026) |
| description | texte | Début de la description | 500 caractères au plus | RGPD : e-mails et téléphones retirés |
| url | texte | Lien vers l'offre d'origine | URL | Peut être expiré |
| date_import | texte | Date de chargement en base | ISO 8601 | — |

Index : département, code ROME, source, contrat, date de publication.

## 2. Table `metiers_rome` — 1 514 lignes

| Colonne | Type | Description | Valeurs / contraintes |
|---|---|---|---|
| code_rome | texte | Code métier ROME, clé primaire | Une lettre A à N suivie de 4 chiffres (CHECK), ex. K1304 |
| libelle | texte | Libellé officiel du métier | Non nul, ex. « Aide ménager / Aide ménagère à domicile » |

## 3. Table `departements` — 8 lignes

| Colonne | Type | Description | Valeurs / contraintes |
|---|---|---|---|
| code_dept | texte | Code du département, clé primaire | 2 caractères (75, 77, 78, 91, 92, 93, 94, 95) |
| nom | texte | Nom du département | Non nul |
| latitude | réel | Latitude du centre | Entre 48,0 et 49,5 |
| longitude | réel | Longitude du centre | Entre 1,4 et 3,6 |
| superficie_km2 | réel | Superficie | Issue du fichier GeoJSON IGN / Insee |

## 4. Table `indicateurs_tension` — 1 514 lignes

Calculée par agrégation SQL (GROUP BY et fonction fenêtre) à partir de `offres`. Une ligne par code ROME.

| Colonne | Type | Description | Valeurs / contraintes |
|---|---|---|---|
| code_rome | texte | Code ROME, clé primaire et clé étrangère | — |
| nb_offres_ft | entier | Offres France Travail du métier | Ex. K1304 : 1 426 |
| nb_offres_adzuna | entier | Offres Adzuna du métier | Ex. K1304 : 105 |
| nb_offres_total | entier | Total des deux sources | De 1 à 1 531 |
| nb_entreprises | entier | Entreprises distinctes (hors « Non renseigné ») | K1304 : 321 |
| nb_departements | entier | Départements où le métier est présent | — |
| part_cdi | réel | Part de CDI, en % | K1304 : 81,1 |
| salaire_median | réel | Médiane des salaires **affichés** (€) | K1304 : 22 477 |
| part_salaire_affiche | réel | Part d'offres avec salaire affiché, en % | K1304 : 48,1 |
| indice_tension | réel | **ITM** = nb_offres_total ÷ moyenne des métiers × 100 (100 = métier moyen) | De 2,5 à 3 842,4 |
| statut | texte | Classe de tension | Voir § 5 |
| date_calcul | texte | Date du calcul | ISO 8601 |

L'indice mesure la **pression de la demande des employeurs** (côté offres). Il n'intègre pas le nombre de demandeurs d'emploi.

## 5. Règles de classification des statuts

| Statut | Seuil de l'indice | Interprétation | Métiers |
|---|---|---|---|
| SATURE | moins de 50 | Peu d'offres rapportées au métier moyen | 1 006 |
| EQUILIBRE | 50 à 100 | Niveau proche du métier moyen | 179 |
| EN TENSION | 100 à 150 | Plus d'offres que la moyenne | 94 |
| TRES EN TENSION | plus de 150 | Pression très forte de la demande employeurs | 235 |

Les 235 métiers « très en tension » concentrent 45 044 des 60 325 offres rattachées à un code ROME, soit environ 75 %.

## 6. Les cinq métiers les plus en tension

| Code ROME | Libellé | Offres | Indice |
|---|---|---|---|
| K1304 | Aide ménager / Aide ménagère à domicile | 1 531 | 3 842,4 |
| J1506 | Infirmier / Infirmière de soins généraux | 1 152 | 2 891,2 |
| C1504 | Conseiller / Conseillère immobilier | 983 | 2 467,1 |
| M1203 | Comptable | 875 | 2 196,0 |
| K1311 | Auxiliaire de vie | 825 | 2 070,5 |

## 7. Fichiers de sortie du Machine Learning

### `data/predictions_tension.csv` — 717 lignes (métiers de 10 offres ou plus)

| Colonne | Type | Description |
|---|---|---|
| code_rome | texte | Code ROME |
| statut | texte | Statut observé (voir § 5) |
| indice_tension | réel | Indice de tension observé |
| proba_tension | réel | Probabilité prédite par XGBoost que le métier soit « en tension » (entre 0 et 1), arrondie à 3 décimales ; calculée en validation croisée à 5 plis : le métier est prédit par un modèle qui ne l'a pas vu à l'entraînement |

### `data/ml_resultats.json`

Résultats de la validation croisée à 5 plis sur 717 métiers (46 % en tension) :

| Modèle | ROC-AUC | F1 | Exactitude équilibrée |
|---|---|---|---|
| Référence (hasard) | 0,507 | — | — |
| Régression logistique | 0,611 | 0,558 | 0,561 |
| Random Forest | 0,874 | 0,761 | 0,783 |
| **XGBoost (retenu)** | **0,886** | **0,785** | **0,804** |

Variables les plus importantes : longueur_description (0,167), part_interim (0,086), part_cdd (0,073), part_debutant (0,058), famille_rome_C (0,054), part_cdi (0,052).

La cible est « indice de tension > 100 ». Les variables d'entrée décrivent le profil des offres de chaque métier (parts de CDI, CDD et intérim, salaire, part de salaires non affichés, expérience demandée, part d'offres pour débutants, longueur des descriptions, famille ROME), sans variable de volume. Sans `longueur_description`, l'AUC de XGBoost passe de 0,886 à 0,795 (Random Forest : 0,874 à 0,794).

Le fichier contient aussi la trace de la **version V1** : régression linéaire R² = 1,0000 et Random Forest R² = 0,9999, car la cible était calculée à partir des variables d'entrée (fuite de données). Cette version est écartée.

### `webapp/models/modele_tension.pkl`

Modèle XGBoost entraîné sur les 717 métiers. Les fichiers `modele_itm.pkl`, `scaler_itm.pkl` et `features_itm.pkl` appartiennent à la V1 (conservés pour l'historique).

## 8. Fichiers de la V1 (historique)

`itm_consolide.csv` et `predictions_itm.csv` (V1) ont été retirés du dépôt : ils ne sont plus utilisés. `offres_idf_clean.csv` et `offres_ft_idf_clean.csv` datent de la collecte de mai 2026 (24 051 offres France Travail, 4 626 offres Adzuna) : ce sont des versions de secours, lues par `prepare.py` uniquement si les fichiers bruts sont absents. Le dashboard et l'API lisent uniquement `data/ppmt.db`.
