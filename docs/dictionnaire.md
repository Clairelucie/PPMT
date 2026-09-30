# Dictionnaire des Donnees - PPMT

Projet Data Analyst - Soutenance 29/05/2026
Equipe : Bernard | Claire

---

## 1. offres_idf_clean.csv — Offres Adzuna nettoyees (4 626 offres)

| Colonne | Type | Description | Valeurs possibles | Qualite |
|---------|------|-------------|-------------------|---------|
| titre | str | Intitule du poste | Texte libre | Nettoye - 354 offres parasites supprimees |
| entreprise | str | Nom de l'entreprise | Texte libre | Non renseigne si vide |
| lieu | str | Ville ou region | Texte libre | Ile-de-France uniquement |
| salaire_min | float | Salaire minimum annuel brut (EUR) | 0 - 200 000 | 71% manquants - enrichi via mediane FT |
| salaire_max | float | Salaire maximum annuel brut (EUR) | 0 - 200 000 | 71% manquants |
| salaire_moyen | float | Moyenne salaire_min et salaire_max | 0 - 200 000 | Calcule |
| date_publication | date | Date de publication de l'offre | YYYY-MM-DD | Normalise ISO 8601 |
| contrat | str | Type de contrat normalise | CDI / CDD / Interim / Autre | Normalise depuis Full-time/Permanent/Contract |
| categorie | str | Secteur metier | Emplois Informatique / Sante & medical / ... | 20 categories dont Autres/General |
| code_rome | str | Code metier ROME 4.0 | Ex: M1805, J1502 | 19 codes uniques assignes |
| url | str | Lien vers l'offre originale | URL | Peut etre expire |
| annee | int | Annee extraite de date_publication | 2025 / 2026 | Calcule |
| mois | int | Mois extrait de date_publication | 1 - 12 | Calcule |
| age_jours | int | Nombre de jours depuis publication | 0 - 365 | Calcule |
| is_recente | bool | Offre de moins de 30 jours | True / False | Calcule |

---

## 2. offres_ft_idf_clean.csv — Offres France Travail nettoyees (24 051 offres)

| Colonne | Type | Description | Valeurs possibles | Qualite |
|---------|------|-------------|-------------------|---------|
| titre | str | Intitule du poste | Texte libre | Source officielle FT |
| code_rome | str | Code metier ROME 4.0 | Ex: M1805, J1502 | Fourni directement par FT |
| appellation_rome | str | Libelle officiel du metier ROME | Texte | Source officielle |
| entreprise | str | Nom de l'entreprise | Texte / Non renseigne | 64.7% manquants - remplace par Non renseigne |
| lieu | str | Ville ou commune | Texte libre | IDF uniquement |
| departement | str | Code departement | 75 / 77 / 78 / 91 / 92 / 93 / 94 / 95 | 8 departements IDF |
| contrat | str | Type de contrat normalise | CDI / CDD / Interim / Autre | Normalise depuis CDI/MIS/SAI/... |
| salaire | str | Libelle salaire brut FT | Texte libre | 65% manquants - conserves tels quels |
| salaire_moyen_ft | float | Salaire annuel moyen calcule | 0 - 130 000 | Calcule depuis libelle |
| description | str | Texte de l'offre (300 premiers caracteres) | Texte | Tronque |
| date_publication | date | Date de creation de l'offre | YYYY-MM-DD | Normalise ISO 8601 |
| categorie | str | Appellation ROME utilisee comme categorie | Texte | Cree depuis appellation_rome |

---

## 3. itm_consolide.csv — Dataset ML consolide (1 102 metiers)

| Colonne | Type | Description | Valeurs possibles | Qualite |
|---------|------|-------------|-------------------|---------|
| code_rome | str | Code metier ROME 4.0 | Ex: M1805, J1502 | Cle primaire - 1 102 codes uniques |
| libelle | str | Libelle du metier | Texte | Source ROME 4.0 |
| nb_offres_ft | float | Nombre d'offres France Travail | 1 - 479 | Source officielle |
| nb_offres_adzuna | float | Nombre d'offres Adzuna | 0 - 659 | 0 si pas d'offres Adzuna |
| nb_offres_total | float | Total offres toutes sources | 1 - 2243 | nb_offres_ft + nb_offres_adzuna |
| salaire_moyen_ft | float | Salaire moyen FT pour ce metier | 12 000 - 130 000 | Calcule depuis offres FT |
| salaire_moyen_adzuna | float | Salaire moyen Adzuna pour ce metier | 0 - 58 679 | 0 si pas d'offres Adzuna |
| salaire_moyen | float | Salaire moyen toutes sources | 12 000 - 130 000 | Moyenne ponderee |
| indice_tension | float | Indice de tension (ITM) = nb_offres_total / moyenne des métiers × 100 (100 = métier moyen) | 4 - 2 800 | Calculé (pression de la demande employeurs, côté offres) |
| statut | str | Classification du metier | SATURE / EQUILIBRE / EN TENSION / TRES EN TENSION | Seuils 50/100/150 |
| source_calcul | str | Source du calcul ITM | France Travail | |
| date_calcul | date | Date du calcul | YYYY-MM-DD | |

---

## 4. predictions_itm.csv — Predictions Random Forest (1 102 metiers)

| Colonne | Type | Description | Valeurs possibles | Qualite |
|---------|------|-------------|-------------------|---------|
| code_rome | str | Code metier ROME 4.0 | Ex: M1805, J1502 | Cle primaire |
| libelle | str | Libelle du metier | Texte | |
| indice_tension | float | Indice de tension reel (ITM) | 4.1 - 2885.7 | Valeur observee |
| itm_predit | float | Indice de tension predit par le modele ML | 4.1 - 2885.7 | Random Forest R2=0.9952 |
| ecart | float | Difference entre reel et predit | 0 - 50 | Faible = bonne prediction |
| statut_predit | str | Statut predit par le modele | SATURE / EQUILIBRE / EN TENSION / TRES EN TENSION | Seuils 50/100/150 |

---

## 5. Regles de classification des statuts

| Statut | Seuil indice tension | Interpretation | Nb metiers |
|--------|---------------------|----------------|------------|
| SATURE | < 50 | Trop de candidats - marche difficile pour trouver un emploi | 723 |
| EQUILIBRE | 50 - 100 | Offre et demande equilibrees | 145 |
| EN TENSION | 100 - 150 | Plus d'offres que de candidats - recrutement difficile | 55 |
| TRES EN TENSION | > 150 | Penurie critique de candidats | 179 |

---

## 6. Top metiers en tension (TRES EN TENSION)

| Code ROME | Libelle | Indice tension |
|-----------|---------|----------------|
| J1502 | Soins infirmiers | 2 885 |
| M1805 | Informatique / Developpement | 2 791 |
| C1504 | Immobilier | 2 243 |
| K1304 | Aide menagere / Nettoyage | 2 005 |
| K1311 | Aide sociale | 1 575 |

