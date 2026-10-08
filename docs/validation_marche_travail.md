# Validation de l'indice PPMT par l'API Marché du travail (France Travail / DARES)

Codes ROME interrogés : 1513 ; couverts par indicateur : {'demandeurs': 1475, 'offres': 1503, 'tension': 1301}.

Nomenclatures reçues pour la tension :

| codeNomenclature | libNomenclature | n |
| --- | --- | --- |
| ATTR_SALARIALE | Attractivité salariale | 1281 |
| COND_TRAVAIL | Conditions de travail | 1301 |
| DUR_EMPL | Durabilité de l'emploi | 1301 |
| INT_EMB | Intensité d'embauche | 1301 |
| MAIN_OEUVRE | Manque de main d'oeuvre | 1301 |
| MISMATCH_GEO | Inadéquation géographique | 1301 |
| PERSPECTIVE | Indicateur principal tension | 1301 |
| SPECIF_FORM_EMPL | Lien formation - métier | 1301 |

Nomenclature utilisée pour la comparaison : **PERSPECTIVE** (PERSPECTIVE = indicateur principal ; change avec --nomenclature CODE).

Corrélation de rang de l'indice PPMT avec chaque indicateur officiel :

| indicateur_officiel | rho | p_permutation | n_metiers |
| --- | --- | --- | --- |
| ATTR_SALARIALE | -0.05 | 0.0504 | 1281 |
| COND_TRAVAIL | -0.02 | 0.4754 | 1301 |
| DUR_EMPL | -0.09 | 0.001 | 1301 |
| INT_EMB | 0.15 | 0.0001 | 1301 |
| MAIN_OEUVRE | 0.07 | 0.0148 | 1301 |
| MISMATCH_GEO | -0.26 | 0.0001 | 1301 |
| PERSPECTIVE | 0.09 | 0.0017 | 1301 |
| SPECIF_FORM_EMPL | 0.09 | 0.002 | 1301 |

**Corrélation de rang (Spearman) indice PPMT ↔ tension officielle : ρ = +0.09 (n = 1301 métiers, p de permutation = 0.0017).**

Parmi les 130 métiers les plus en tension selon PPMT, 13 le sont aussi selon l'indicateur officiel (hasard attendu : 13 ; écarts détaillés : ecarts_tension.csv).

Robustesse selon le volume d'offres PPMT (métiers à très peu d'offres = bruit) :

| offres_PPMT_minimum | n_metiers | rho | p_permutation |
| --- | --- | --- | --- |
| 1 | 1301 | 0.09 | 0.0017 |
| 10 | 677 | 0.1 | 0.0094 |
| 30 | 388 | 0.09 | 0.0651 |
| 100 | 147 | -0.04 | 0.6045 |

**Corrélation de rang indice PPMT ↔ rapport offres/demandeurs (France Travail, région) : ρ = +0.25 (n = 1203, p = 0.0001).**

Recoupements (qui ressemble à quoi) :

| paire | rho | p_permutation | n_metiers |
| --- | --- | --- | --- |
| PPMT ↔ nb d'offres France Travail | 0.89 | 0.0001 | 1067 |
| PPMT ↔ nb de demandeurs cat. A | 0.63 | 0.0001 | 1067 |
| tension officielle ↔ offres/demandeurs | 0.39 | 0.0001 | 1067 |
| tension officielle ↔ nb d'offres | 0.09 | 0.0029 | 1067 |
| tension officielle ↔ nb de demandeurs | -0.21 | 0.0001 | 1067 |
| PPMT ↔ tension officielle (mêmes métiers) | 0.15 | 0.0001 | 1067 |


## Limites à citer
- Les deux sources mesurent la tension différemment : PPMT = demande des employeurs (offres), l'indicateur officiel combine plusieurs indicateurs (dont le côté demandeurs d'emploi).
- Périodes différentes : offres collectées le 6 octobre 2026 vs dernière période publiée par l'API.
- Échelle : l'API est interrogée au niveau région Île-de-France ; certains codes ROME de notre base n'existent pas dans l'API (voir couverture ci-dessus).
- Une corrélation n'est pas une causalité ; l'ordre de grandeur compte plus que le chiffre exact.
