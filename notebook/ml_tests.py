"""
PPMT — Expérimentation Machine Learning (hors périmètre BC01, présentée en ouverture).

Question : le PROFIL des offres d'un métier (contrats, salaires, expérience, famille ROME…)
permet-il de repérer les métiers en tension, SANS utiliser le volume d'offres ?

Historique de la démarche :
  V1 (mai 2026) : régression de l'indice de tension à partir de nb_offres_ft, nb_offres_adzuna,
      nb_offres_total… → R² = 0,995. Diagnostic : FUITE DE DONNÉES. L'indice est calculé
      comme nb_offres_total / moyenne × 100 : le modèle « retrouve » une formule, il ne prédit rien.
      L'étape 1 ci-dessous reproduit ce diagnostic.
  V2 (cette version) : classification binaire « en tension » (ITM > 100) à partir de variables
      qui ne dépendent PAS du volume, validation croisée stratifiée 5 plis, comparaison à une
      référence naïve. Métiers retenus : ≥ 10 offres (proportions calculées sur trop peu
      d'offres = bruit et fuite indirecte de la taille d'échantillon).

Entrée : data/ppmt.db (produite par run_pipeline.py)
Sorties : webapp/models/modele_tension.pkl · data/ml_resultats.json · data/predictions_tension.csv
"""
import json
import sqlite3
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import balanced_accuracy_score, f1_score, r2_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
SEUIL_OFFRES = 10
conn = sqlite3.connect(ROOT / "data" / "ppmt.db")

# ───────────────────────────────── ÉTAPE 1 — diagnostic de la fuite de données (V1)
ind = pd.read_sql("SELECT * FROM indicateurs_tension", conn)
X_v1 = ind[["nb_offres_ft", "nb_offres_adzuna", "nb_offres_total"]]
Xtr, Xte, ytr, yte = train_test_split(X_v1, ind["indice_tension"], test_size=0.2, random_state=42)
r2_lin = r2_score(yte, LinearRegression().fit(Xtr, ytr).predict(Xte))
r2_rf = r2_score(yte, RandomForestRegressor(100, random_state=42).fit(Xtr, ytr).predict(Xte))
print("=== ÉTAPE 1 — V1 : features de volume ===")
print(f"Régression linéaire R² = {r2_lin:.4f} | Random Forest R² = {r2_rf:.4f}")
print("→ indice_tension = nb_offres_total / moyenne × 100 : cible déterministe des features. V1 écartée.")

# ───────────────────────────────── ÉTAPE 2 — features de profil, construites en SQL
df = pd.read_sql("""
    SELECT o.code_rome,
           substr(o.code_rome, 1, 1)                    AS famille_rome,
           AVG(o.contrat = 'CDI')                       AS part_cdi,
           AVG(o.contrat = 'CDD')                       AS part_cdd,
           AVG(o.contrat = 'Intérim')                   AS part_interim,
           AVG(o.temps_travail = 'Temps partiel')       AS part_temps_partiel,
           AVG(CASE WHEN o.salaire_impute = 0 THEN o.salaire_moyen END) AS salaire_affiche_moyen,
           AVG(o.salaire_impute)                        AS part_salaire_absent,
           AVG(o.experience LIKE '%Débutant%')          AS part_debutant,
           AVG(length(o.description))                   AS longueur_description,
           i.statut, i.indice_tension, i.nb_offres_total
    FROM offres o JOIN indicateurs_tension i USING (code_rome)
    GROUP BY o.code_rome HAVING COUNT(*) >= :seuil""", conn, params={"seuil": SEUIL_OFFRES})
df["en_tension"] = (df["indice_tension"] > 100).astype(int)
X = pd.get_dummies(df.drop(columns=["code_rome", "statut", "indice_tension", "nb_offres_total",
                                    "en_tension"]), columns=["famille_rome"], dtype=float)
X = X.fillna(X.median())
y = df["en_tension"]
print(f"\n=== ÉTAPE 2 — V2 : {len(df)} métiers (≥ {SEUIL_OFFRES} offres), {y.mean():.0%} en tension ===")

# ───────────────────────────────── ÉTAPE 3 — comparaison en validation croisée
cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
# Référence : un classement au hasard (proportions des classes) → AUC ≈ 0,5. Tout modèle utile doit faire mieux.
proba_hasard = cross_val_predict(DummyClassifier(strategy="stratified", random_state=42), X, y, cv=cv,
                                 method="predict_proba")[:, 1]
auc_hasard = round(roc_auc_score(y, proba_hasard), 3)
print(f"{'Référence (hasard)':24s} AUC {auc_hasard:.3f}")
modeles = {
    "Régression logistique": make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced")),
    "Random Forest": RandomForestClassifier(n_estimators=300, min_samples_leaf=5, class_weight="balanced", random_state=42),
    "XGBoost": XGBClassifier(n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.9,
                             colsample_bytree=0.9, eval_metric="logloss", random_state=42),
}
resultats = {}
for nom, m in modeles.items():
    proba = cross_val_predict(m, X, y, cv=cv, method="predict_proba")[:, 1]
    resultats[nom] = {"roc_auc": round(roc_auc_score(y, proba), 3),
                      "f1": round(f1_score(y, proba > 0.5), 3),
                      "balanced_accuracy": round(balanced_accuracy_score(y, proba > 0.5), 3)}
    print(f"{nom:24s} AUC {resultats[nom]['roc_auc']:.3f} | F1 {resultats[nom]['f1']:.3f} | "
          f"Bal. acc. {resultats[nom]['balanced_accuracy']:.3f}")

# ───────────────────────────────── ÉTAPE 4 — modèle final + importance des variables
meilleur = max(resultats, key=lambda n: resultats[n]["roc_auc"])      # modèle retenu : meilleure AUC
print(f"\nModèle retenu : {meilleur}")
final = modeles[meilleur].fit(X, y)
importances = pd.Series(final.feature_importances_, index=X.columns).sort_values(ascending=False)
print("Top 8 variables :\n" + importances.head(8).round(3).to_string())
proba_cv = cross_val_predict(modeles[meilleur], X, y, cv=cv, method="predict_proba")[:, 1]
out = df[["code_rome", "statut", "indice_tension"]].assign(proba_tension=np.round(proba_cv, 3))
out.to_csv(ROOT / "data" / "predictions_tension.csv", index=False)

(ROOT / "webapp" / "models").mkdir(parents=True, exist_ok=True)
joblib.dump({"modele": final, "nom": meilleur, "features": list(X.columns)}, ROOT / "webapp" / "models" / "modele_tension.pkl")
json.dump({
    "v1_fuite": {"r2_regression_lineaire": round(r2_lin, 4), "r2_random_forest": round(r2_rf, 4)},
    "v2": {"nb_metiers": int(len(df)), "seuil_offres": SEUIL_OFFRES, "part_en_tension": round(float(y.mean()), 3),
           "resultats_cv5": resultats, "auc_reference_hasard": auc_hasard, "modele_retenu": meilleur, "top_variables": importances.head(8).round(3).to_dict()},
}, open(ROOT / "data" / "ml_resultats.json", "w"), ensure_ascii=False, indent=2)
print("\nSorties : data/ml_resultats.json · data/predictions_tension.csv · webapp/models/modele_tension.pkl")
