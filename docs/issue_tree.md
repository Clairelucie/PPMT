# Issue Tree du projet PPMT

## Version simplifiée

```
PROBLÈME CENTRAL
Comment collecter, fiabiliser et mettre à disposition automatiquement
les offres d'emploi de plusieurs sources pour identifier les métiers
qui recrutent le plus en Île-de-France ?
│
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

## Version détaillée

```
PROBLÈME PRINCIPAL
Comment collecter, fiabiliser et mettre à disposition automatiquement les offres d'emploi
de plusieurs sources pour identifier les métiers qui recrutent le plus en Île-de-France ?
│
├─► 1. COLLECTER (chaîne C1)
│   │
│   ├─► 1.1 Collecter les offres
│   │   ├─► [Claire · API France Travail] Cascade département → dates → contrat : 63 173 offres sur 63 504 (99,5 %)
│   │   ├─► [Claire] Authentification OAuth2 : jeton renouvelé toutes les 20 min et sur erreur 401
│   │   ├─► [Bernard · API Adzuna] Échantillon de 12 500 offres lues sur 220 238
│   │   └─► [Fichiers de référence] Contours des 8 départements · 1 276 communes d'Île-de-France
│   │
│   └─► 1.2 Fiabiliser la collecte
│       ├─► [Claire] 3 tentatives, attente croissante, pause de 100 ms : 0 erreur HTTP 429
│       ├─► [Bernard] Idempotence : 1 fichier brut par source et par jour
│       └─► [Journal] logs/collect_*.log : bilan de couverture et avertissements
│
├─► 2. FIABILISER (chaînes C2 / C3)
│   │
│   ├─► 2.1 Nettoyer et harmoniser
│   │   ├─► [Claire & Bernard] Doublons : URL puis empreinte : 12 404 supprimés, 0 en base
│   │   ├─► [Claire] Salaires absents (56 %) : médiane du groupe le plus précis, valeur signalée
│   │   ├─► [Bernard] Codes ROME d'Adzuna : intitulé 636 · catégorie 1 388 · sans code 2 110
│   │   └─► [Claire] Contrats en 7 catégories · départements retrouvés via les 1 276 communes
│   │
│   └─► 2.2 Protéger les données
│       ├─► [Claire] RGPD : e-mails et téléphones masqués ([email], [tel])
│       └─► [Claire] Purge des offres de plus de 12 mois (807 supprimées)
│
├─► 3. STOCKER (chaîne C4)
│   ├─► [Claire] Schéma SQLite : 4 tables, clés étrangères, CHECK, UNIQUE, 6 index
│   ├─► [Base SQL] Table offres : 62 435 lignes (France Travail 58 301 · Adzuna 4 134)
│   └─► [Base SQL] Indicateurs de tension : 1 514 métiers, calculés en SQL
│
└─► 4. METTRE À DISPOSITION (chaîne C5)
    ├─► [Claire] API FastAPI : 7 routes, clé X-API-Key (403), validation Pydantic (422), Docker
    ├─► [Claire] Dashboard Streamlit : 6 onglets, version en ligne de secours
    ├─► [Claire] 57 tests pytest : API simulées, règles, base, API
    └─► [Claire · ML] Métiers « en tension » : XGBoost, AUC 0,886 (V1 : fuite de données corrigée)
```

Légende : [Claire] et [Bernard] indiquent la personne qui a réalisé la partie en V2. Les chiffres sont ceux de la collecte du 6 octobre 2026.
