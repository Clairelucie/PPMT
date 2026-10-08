#!/usr/bin/env python3
"""
validation_marche_travail.py : comparaison de l'indice de tension PPMT avec les
statistiques officielles de l'API « Marché du travail » (France Travail / DARES).

Script AUTONOME, hors pipeline : il ne modifie ni la base, ni run_pipeline.py,
ni les tests. La base ppmt.db est ouverte en LECTURE SEULE.

Trois étapes, à lancer dans l'ordre depuis la racine du projet :

  python notebook/validation_marche_travail.py decouverte
      Interroge les référentiels de l'API (catalogue des indicateurs, codes des
      nomenclatures, code de la région Île-de-France) et les enregistre dans
      data/marche_travail/. À lire AVANT la collecte : on y voit les codes exacts.

  python notebook/validation_marche_travail.py collecte --limit 5      (test)
  python notebook/validation_marche_travail.py collecte                (complet)
      Pour chaque code ROME de metiers_rome, demande 3 indicateurs :
        - PERSP_2 : difficultés de recrutement (indicateur de tension officiel)
        - DE_1    : demandeurs d'emploi inscrits en fin de trimestre
        - OFF_1   : offres enregistrées
      Reprise automatique : relancer la commande continue là où elle s'est arrêtée.

  python notebook/validation_marche_travail.py analyse
      Compare l'indice PPMT aux indicateurs officiels (corrélation de rang de
      Spearman + test de permutation), liste les métiers en désaccord, et écrit
      un résumé dans data/marche_travail/resultats_validation.md.

Identifiants : lus dans l'environnement ou dans le fichier .env (jamais affichés).
Noms acceptés : FT_CLIENT_ID / FT_CLIENT_SECRET (ou FRANCE_TRAVAIL_CLIENT_ID /
FRANCE_TRAVAIL_CLIENT_SECRET, ou POLE_EMPLOI_CLIENT_ID / POLE_EMPLOI_CLIENT_SECRET).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd
import requests

# --------------------------------------------------------------------------- #
# Constantes tirées de la spécification OpenAPI de l'API (v1)
# --------------------------------------------------------------------------- #
URL_TOKEN = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"
SCOPES = "offresetdemandesemploi api_stats-offres-demandes-emploiv1"
BASE = "https://api.francetravail.io/partenaire/stats-offres-demandes-emploi"

# (nom court, chemin, type de période, type de nomenclature)
INDICATEURS = {
    "tension":   ("/v1/indicateur/stat-perspective-employeur", "ANNEE",     "TYPE_TENSION"),
    "demandeurs": ("/v1/indicateur/stat-demandeurs",           "TRIMESTRE", "CATCAND"),
    "offres":    ("/v1/indicateur/stat-offres",                "TRIMESTRE", "ORIGINEOFF"),
}


def _racine() -> Path:
    """Racine du projet : le dossier qui contient data/ (parent de notebook/ si on y est)."""
    ici = Path(__file__).resolve().parent
    return ici.parent if ici.name == "notebook" else Path.cwd()


RACINE = _racine()
DOSSIER = RACINE / "data" / "marche_travail"
DB = next((p for p in (RACINE / "data" / "ppmt.db", RACINE / "ppmt.db") if p.exists()), RACINE / "data" / "ppmt.db")
CACHE = DOSSIER / "cache_brut.jsonl"
CSV_PLAT = DOSSIER / "marche_travail_par_rome.csv"
PAUSE = 0.25          # 4 appels/s (limite annoncée : 10 appels/s)


# --------------------------------------------------------------------------- #
# Identifiants et jeton
# --------------------------------------------------------------------------- #
def _lire_env(chemin: Path) -> dict:
    out = {}
    if chemin.exists():
        for ligne in chemin.read_text(encoding="utf-8").splitlines():
            ligne = ligne.strip()
            if ligne and not ligne.startswith("#") and "=" in ligne:
                k, v = ligne.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def identifiants() -> tuple[str, str]:
    env = {**_lire_env(RACINE / ".env"), **os.environ}
    for prefixe in ("FT", "FRANCE_TRAVAIL", "POLE_EMPLOI"):
        cid, sec = env.get(f"{prefixe}_CLIENT_ID"), env.get(f"{prefixe}_CLIENT_SECRET")
        if cid and sec:
            return cid, sec
    noms = sorted(_lire_env(RACINE / ".env"))   # noms uniquement, jamais les valeurs
    sys.exit("Identifiants introuvables. Noms cherchés : FT_CLIENT_ID / FT_CLIENT_SECRET "
             "(ou FRANCE_TRAVAIL_*, POLE_EMPLOI_*).\n"
             f"Noms de variables présents dans le fichier .env (valeurs jamais affichées) : {noms}\n"
             "→ renomme tes variables ou adapte la fonction identifiants().")


class Client:
    def __init__(self):
        self.s = requests.Session()
        self.jeton, self.t0, self.appels = None, 0.0, 0
        self.cid, self.sec = identifiants()

    def _token(self):
        r = self.s.post(URL_TOKEN, data={"grant_type": "client_credentials", "client_id": self.cid,
                                         "client_secret": self.sec, "scope": SCOPES}, timeout=30)
        if r.status_code != 200:
            sys.exit(f"Jeton refusé (HTTP {r.status_code}). Vérifie que l'API « Marché du travail » est "
                     f"bien associée à ton application sur francetravail.io. Réponse : {r.text[:200]}")
        self.jeton, self.t0 = r.json()["access_token"], time.time()

    def appel(self, methode: str, chemin: str, **kw):
        """Retourne (statut, json|None). Gère jeton expiré, 429 et erreurs 5xx."""
        for essai in range(5):
            if self.jeton is None or time.time() - self.t0 > 20 * 60:
                self._token()
            time.sleep(PAUSE)
            self.appels += 1
            r = self.s.request(methode, BASE + chemin, timeout=60,
                               headers={"Authorization": f"Bearer {self.jeton}", "Accept": "application/json"}, **kw)
            if r.status_code == 401:
                self.jeton = None
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** essai)
                continue
            if r.status_code == 200 and r.content:
                return 200, r.json()
            return r.status_code, None
        return 599, None


# --------------------------------------------------------------------------- #
# 1. Découverte des référentiels
# --------------------------------------------------------------------------- #
def decouverte():
    DOSSIER.mkdir(parents=True, exist_ok=True)
    c = Client()
    demandes = {
        "indicateur_PERSP_2": ("GET", "/v1/referentiel/details-indicateurs", {"params": {"codeIndicateur": "PERSP_2"}}),
        "indicateur_DE_1":    ("GET", "/v1/referentiel/details-indicateurs", {"params": {"codeIndicateur": "DE_1"}}),
        "indicateur_OFF_1":   ("GET", "/v1/referentiel/details-indicateurs", {"params": {"codeIndicateur": "OFF_1"}}),
        "nomenclature_TYPE_TENSION": ("GET", "/v1/referentiel/nomenclatures/TYPE_TENSION", {}),
        "nomenclature_CATCAND":      ("GET", "/v1/referentiel/nomenclatures/CATCAND", {}),
        "nomenclature_ORIGINEOFF":   ("GET", "/v1/referentiel/nomenclatures/ORIGINEOFF", {}),
        "territoires_REG":           ("GET", "/v1/referentiel/territoires/REG", {}),
        "periodes_ANNEE":            ("GET", "/v1/referentiel/periodes/ANNEE", {}),
        "periodes_TRIMESTRE":        ("GET", "/v1/referentiel/periodes/TRIMESTRE", {}),
        "rome_fap":                  ("GET", "/v1/referentiel/rechercherActivitesRomeFap", {}),
    }
    for nom, (m, chemin, kw) in demandes.items():
        statut, data = c.appel(m, chemin, **kw)
        (DOSSIER / f"ref_{nom}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        taille = len(data) if isinstance(data, (list, dict)) else 0
        print(f"[{statut}] {nom:28s} -> data/marche_travail/ref_{nom}.json  ({taille} éléments)")

    # Aperçu lisible des points qui décident de la suite
    def charger(n):
        p = DOSSIER / f"ref_{n}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def liste(d):
        if isinstance(d, list):
            return d
        if isinstance(d, dict):
            return next((v for v in d.values() if isinstance(v, list)), [])
        return []

    print("\n--- Nomenclature TYPE_TENSION (code principal : PERSPECTIVE) ---")
    for n in liste(charger("nomenclature_TYPE_TENSION")):
        print("  ", n.get("codeNomenclature"), "-", n.get("libelleNomenclature"))
    print("\n--- Région Île-de-France ---")
    for t in liste(charger("territoires_REG")):
        if "ILE" in str(t.get("libelleTerritoire", "")).upper().replace("Î", "I"):
            print("  ", t.get("codeTerritoire"), "-", t.get("libelleTerritoire"))
    print("\nOuvre data/marche_travail/ref_indicateur_PERSP_2.json : il liste les territoires, périodes "
          "et nomenclatures réellement disponibles pour l'indicateur de tension.")


# --------------------------------------------------------------------------- #
# 2. Collecte
# --------------------------------------------------------------------------- #
def romes(limite: int | None, min_offres: int) -> list[str]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    df = pd.read_sql("SELECT code_rome FROM indicateurs_tension WHERE nb_offres_total >= ? "
                     "ORDER BY nb_offres_total DESC", con, params=(min_offres,))
    con.close()
    liste = df["code_rome"].tolist()
    return liste[:limite] if limite else liste


def deja_fait() -> set:
    if not CACHE.exists():
        return set()
    out = set()
    for ligne in CACHE.read_text(encoding="utf-8").splitlines():
        try:
            j = json.loads(ligne)
            out.add((j["rome"], j["indic"]))
        except Exception:
            pass
    return out


def collecte(args):
    DOSSIER.mkdir(parents=True, exist_ok=True)
    c = Client()
    faits = deja_fait()
    liste = romes(args.limit, args.min_offres)
    total = len(liste) * len(INDICATEURS)
    print(f"{len(liste)} codes ROME × {len(INDICATEURS)} indicateurs = {total} appels "
          f"(dont {len(faits)} déjà en cache). Région {args.region}.")
    n = 0
    with CACHE.open("a", encoding="utf-8") as f:
        for rome in liste:
            for indic, (chemin, periode, nomencl) in INDICATEURS.items():
                if (rome, indic) in faits:
                    continue
                corps = {"codeTypeTerritoire": "REG", "codeTerritoire": args.region,
                         "codeTypeActivite": "ROME", "codeActivite": rome,
                         "codeTypePeriode": periode, "codeTypeNomenclature": nomencl,
                         "dernierePeriode": True, "sansCaracteristiques": True}
                statut, data = c.appel("POST", chemin, json=corps)
                f.write(json.dumps({"rome": rome, "indic": indic, "statut": statut, "data": data},
                                   ensure_ascii=False) + "\n")
                f.flush()
                n += 1
                if n % 100 == 0:
                    print(f"  {n} appels faits…")
    print(f"Collecte terminée : {n} nouveaux appels. Cache : {CACHE}")
    aplatir()


def aplatir():
    """Cache JSONL -> CSV à plat (une ligne par ROME × indicateur × nomenclature × période)."""
    lignes = []
    for ligne in CACHE.read_text(encoding="utf-8").splitlines():
        j = json.loads(ligne)
        if j["statut"] != 200 or not j["data"]:
            lignes.append({"code_rome": j["rome"], "indic": j["indic"], "statut_http": j["statut"]})
            continue
        for v in j["data"].get("listeValeursParPeriode", []) or []:
            v = {k: x for k, x in v.items() if k != "listeValeurParCaract"}
            lignes.append({"code_rome": j["rome"], "indic": j["indic"], "statut_http": 200, **v})
    pd.DataFrame(lignes).to_csv(CSV_PLAT, index=False, encoding="utf-8")
    print(f"CSV à plat : {CSV_PLAT}  ({len(lignes)} lignes)")


# --------------------------------------------------------------------------- #
# 3. Analyse
# --------------------------------------------------------------------------- #
def md(df: pd.DataFrame) -> str:
    """Tableau Markdown sans dépendance (évite l'installation de tabulate)."""
    cols = [str(c) for c in df.columns]
    lignes = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for r in df.astype(object).itertuples(index=False):
        lignes.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |")
    return "\n".join(lignes)


def spearman(x: pd.Series, y: pd.Series, n_perm: int = 10000, graine: int = 42):
    """Corrélation de rang + p-value par permutation (sans scipy)."""
    import numpy as np
    d = pd.concat([x, y], axis=1).dropna()
    if len(d) < 5:
        return None, None, len(d)
    rx, ry = d.iloc[:, 0].rank().to_numpy(), d.iloc[:, 1].rank().to_numpy()
    rho = float(np.corrcoef(rx, ry)[0, 1])
    rng = np.random.default_rng(graine)
    sup = sum(abs(np.corrcoef(rx, rng.permutation(ry))[0, 1]) >= abs(rho) for _ in range(n_perm))
    return rho, (sup + 1) / (n_perm + 1), len(d)


def choisir_valeur(df: pd.DataFrame) -> pd.Series:
    """Première colonne de valeur principale renseignée (Taux > Rang > Montant > Nombre)."""
    for col in ("valeurPrincipaleDecimale", "valeurPrincipaleTaux", "valeurPrincipaleRang",
                "valeurPrincipaleMontant", "valeurPrincipaleNombre"):
        if col in df and df[col].notna().any():
            return df[col]
    return pd.Series(dtype=float)


def analyse(args):
    if not CSV_PLAT.exists():
        sys.exit("Lance d'abord : collecte")
    plat = pd.read_csv(CSV_PLAT, dtype={"code_rome": str})
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ppmt = pd.read_sql("SELECT i.code_rome, m.libelle, i.nb_offres_total, i.indice_tension, i.statut "
                       "FROM indicateurs_tension i JOIN metiers_rome m USING(code_rome)", con)
    con.close()
    out = ["# Validation de l'indice PPMT par l'API Marché du travail (France Travail / DARES)\n"]

    ok = plat[plat["statut_http"] == 200]
    couv = ok.groupby("indic")["code_rome"].nunique()
    out.append(f"Codes ROME interrogés : {plat['code_rome'].nunique()} ; "
               f"couverts par indicateur : {couv.to_dict()}.\n")

    # --- Tension officielle -------------------------------------------------
    t_off = None
    t = ok[ok["indic"] == "tension"].copy()
    if t.empty:
        out.append("Aucune valeur de tension reçue (indicateur PERSP_2) : voir ref_indicateur_PERSP_2.json.\n")
    else:
        codes = t.groupby(["codeNomenclature", "libNomenclature"], dropna=False).size().reset_index(name="n")
        out.append("Nomenclatures reçues pour la tension :\n\n" + md(codes) + "\n")
        code = args.nomenclature or "PERSPECTIVE"
        if code not in set(codes["codeNomenclature"]):
            code = codes.sort_values("n", ascending=False).iloc[0]["codeNomenclature"]
        out.append(f"Nomenclature utilisée pour la comparaison : **{code}** "
                   f"(PERSPECTIVE = indicateur principal ; change avec --nomenclature CODE).\n")
        # Corrélation de l'indice PPMT avec CHACUN des 7 indicateurs officiels (principal + 6 d'éclairage)
        lignes = []
        for cn, g in t.groupby("codeNomenclature"):
            g = g.copy()
            g["v"] = choisir_valeur(g)
            g = g.sort_values("codePeriode").groupby("code_rome").tail(1)[["code_rome", "v"]]
            mm = ppmt.merge(g, on="code_rome")
            r_, p_, n_ = spearman(mm["indice_tension"], mm["v"])
            lignes.append({"indicateur_officiel": cn, "rho": None if r_ is None else round(r_, 2),
                           "p_permutation": None if p_ is None else round(p_, 4), "n_metiers": n_})
        out.append("Corrélation de rang de l'indice PPMT avec chaque indicateur officiel :\n\n"
                   + md(pd.DataFrame(lignes)) + "\n")
        t = t[t["codeNomenclature"] == code]
        t["tension_officielle"] = choisir_valeur(t)
        t = t.sort_values("codePeriode").groupby("code_rome").tail(1)[["code_rome", "tension_officielle"]]
        t_off = t
        m = ppmt.merge(t, on="code_rome", how="inner")
        rho, p, n = spearman(m["indice_tension"], m["tension_officielle"])
        if rho is None:
            out.append(f"Trop peu de métiers communs ({n}) pour calculer une corrélation.\n")
        else:
            out.append(f"**Corrélation de rang (Spearman) indice PPMT ↔ tension officielle : "
                       f"ρ = {rho:+.2f} (n = {n} métiers, p de permutation = {p:.4f}).**\n")
            m["rang_ppmt"] = m["indice_tension"].rank(ascending=False)
            m["rang_officiel"] = m["tension_officielle"].rank(ascending=False)
            m["ecart_rang"] = (m["rang_ppmt"] - m["rang_officiel"]).abs()
            m.sort_values("ecart_rang", ascending=False).to_csv(DOSSIER / "ecarts_tension.csv", index=False)
            k = max(5, n // 10)
            commun = len(set(m.nlargest(k, "indice_tension")["code_rome"]) &
                         set(m.nlargest(k, "tension_officielle")["code_rome"]))
            attendu = k * k / n
            out.append(f"Parmi les {k} métiers les plus en tension selon PPMT, {commun} le sont aussi selon "
                       f"l'indicateur officiel (hasard attendu : {attendu:.0f} ; écarts détaillés : ecarts_tension.csv).\n")
            rob = []
            for seuil in (1, 10, 30, 100):
                sub = m[m["nb_offres_total"] >= seuil]
                r_, p_, n_ = spearman(sub["indice_tension"], sub["tension_officielle"])
                rob.append({"offres_PPMT_minimum": seuil, "n_metiers": n_,
                            "rho": None if r_ is None else round(r_, 2),
                            "p_permutation": None if p_ is None else round(p_, 4)})
            out.append("Robustesse selon le volume d'offres PPMT (métiers à très peu d'offres = bruit) :\n\n"
                       + md(pd.DataFrame(rob)) + "\n")

    # --- Offres par demandeur ----------------------------------------------
    def derniere(ind, nom, codes):
        d = ok[ok["indic"] == ind].copy()
        if d.empty:
            return pd.DataFrame(columns=["code_rome", nom])
        if codes != "*":
            d = d[d["codeNomenclature"].isin(codes.split(","))]
        d = d.groupby(["code_rome", "codePeriode"])["valeurPrincipaleNombre"].sum().reset_index()
        d = d.sort_values("codePeriode").groupby("code_rome").tail(1)
        return d.rename(columns={"valeurPrincipaleNombre": nom})[["code_rome", nom]]

    de = derniere("demandeurs", "demandeurs_ft", args.codes_demandeurs)
    of = derniere("offres", "offres_ft", args.codes_offres)
    r = ppmt.merge(de, on="code_rome").merge(of, on="code_rome")
    r = r[(r["demandeurs_ft"] > 0) & (r["offres_ft"] > 0)]
    if len(r) >= 5:
        r["offres_par_demandeur"] = r["offres_ft"] / r["demandeurs_ft"]
        rho2, p2, n2 = spearman(r["indice_tension"], r["offres_par_demandeur"])
        out.append(f"**Corrélation de rang indice PPMT ↔ rapport offres/demandeurs (France Travail, région) : "
                   f"ρ = {rho2:+.2f} (n = {n2}, p = {p2:.4f}).**\n")
        r.to_csv(DOSSIER / "offres_par_demandeur.csv", index=False)
        if t_off is not None:
            x = r.merge(t_off, on="code_rome")
            lg = []
            for a, b, nom in (("indice_tension", "offres_ft", "PPMT ↔ nb d'offres France Travail"),
                              ("indice_tension", "demandeurs_ft", "PPMT ↔ nb de demandeurs cat. A"),
                              ("tension_officielle", "offres_par_demandeur", "tension officielle ↔ offres/demandeurs"),
                              ("tension_officielle", "offres_ft", "tension officielle ↔ nb d'offres"),
                              ("tension_officielle", "demandeurs_ft", "tension officielle ↔ nb de demandeurs"),
                              ("indice_tension", "tension_officielle", "PPMT ↔ tension officielle (mêmes métiers)")):
                r_, p_, n_ = spearman(x[a], x[b])
                lg.append({"paire": nom, "rho": None if r_ is None else round(r_, 2),
                           "p_permutation": None if p_ is None else round(p_, 4), "n_metiers": n_})
            out.append("Recoupements (qui ressemble à quoi) :\n\n" + md(pd.DataFrame(lg)) + "\n")
    else:
        out.append("Pas assez de métiers avec offres ET demandeurs pour le rapport offres/demandeurs "
                   "(voir marche_travail_par_rome.csv, colonne statut_http).\n")

    out.append("\n## Limites à citer\n"
               "- Les deux sources mesurent la tension différemment : PPMT = demande des employeurs (offres), "
               "l'indicateur officiel combine plusieurs indicateurs (dont le côté demandeurs d'emploi).\n"
               "- Périodes différentes : offres collectées le 6 octobre 2026 vs dernière période publiée par l'API.\n"
               "- Échelle : l'API est interrogée au niveau région Île-de-France ; certains codes ROME de notre "
               "base n'existent pas dans l'API (voir couverture ci-dessus).\n"
               "- Une corrélation n'est pas une causalité ; l'ordre de grandeur compte plus que le chiffre exact.\n")
    texte = "\n".join(out)
    (DOSSIER / "resultats_validation.md").write_text(texte, encoding="utf-8")
    print(texte)


# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("decouverte")
    c = sp.add_parser("collecte")
    c.add_argument("--limit", type=int, help="ne traiter que les N métiers les plus demandés (test)")
    c.add_argument("--min-offres", type=int, default=1)
    c.add_argument("--region", default="11", help="code région (11 = Île-de-France, à confirmer via 'decouverte')")
    a = sp.add_parser("analyse")
    a.add_argument("--nomenclature", help="code de nomenclature TYPE_TENSION à comparer")
    a.add_argument("--codes-demandeurs", default="A",
                   help="catégories de demandeurs à additionner (défaut A ; '*' = toutes ; ex. A,B,C)")
    a.add_argument("--codes-offres", default="TOFF",
                   help="codes d'offres à additionner (défaut TOFF ; l'API renvoie PE, TOFF et leurs cumuls 12 mois : "
                        "ne pas tous additionner, ce serait du double comptage)")
    args = p.parse_args()
    if args.cmd == "decouverte":
        decouverte()
    elif args.cmd == "collecte":
        collecte(args)
    else:
        analyse(args)


if __name__ == "__main__":
    main()
