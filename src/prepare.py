"""
C2 / C3 — Préparation et agrégation des données PPMT.

Entrées :
  - data/offres_idf.csv / data/offres_ft_idf.csv          (bruts produits par collect.py), sinon
  - data/offres_idf_clean.csv / data/offres_ft_idf_clean.csv (versions nettoyées versionnées dans Git)

Sortie :
  - data/processed/offres_unifiees.csv : une ligne par offre, schéma commun aux deux sources

Règles appliquées (voir tableau des anomalies dans le dossier) :
  - déduplication (URL, puis empreinte titre + entreprise + lieu) intra et inter-sources
  - normalisation des salaires en € bruts annuels (horaire × 1 820, mensuel × 12, bornes 10 k€–300 k€)
  - normalisation des contrats (CDI / CDD / Intérim / Libéral / Autre / Non renseigné)
  - conversion des libellés de lieu en code département INSEE (75, 77 … 95)
  - dates au format ISO 8601
  - pseudonymisation RGPD des descriptions (e-mails et téléphones masqués)
  - salaires manquants remplacés par une médiane (imputer_salaires), avec l'indicateur salaire_impute
"""
from __future__ import annotations

import hashlib
import unicodedata
from functools import lru_cache
import logging
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT_DIR = DATA / "processed"
OUT_FILE = OUT_DIR / "offres_unifiees.csv"

log = logging.getLogger("ppmt.prepare")

DEPARTEMENTS = {
    "75": "Paris", "77": "Seine-et-Marne", "78": "Yvelines", "91": "Essonne",
    "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis", "94": "Val-de-Marne", "95": "Val-d'Oise",
}
# pôles connus qui ne sont pas des communes
LIEUX_DITS = {"defense": "92", "marne la vallee": "77", "saint quentin en yvelines": "78",
              "cergy pontoise": "95", "paris saclay": "91", "roissy cdg": "95"}
COMMUNES_CSV = DATA / "ref" / "communes_idf.csv"   # référentiel des 1 276 communes (collect.py --source communes)


def normaliser_nom(nom: str) -> str:
    """'Évry-Courcouronnes' → 'evry courcouronnes' ; 'St-Denis' → 'saint denis' ; 'L'Haÿ-les-Roses' → 'hay les roses'
    (accents, tirets, abréviations, article initial)."""
    s = unicodedata.normalize("NFKD", str(nom)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[-'’]", " ", s)
    s = re.sub(r"\bst\b", "saint", s)
    s = re.sub(r"\bste\b", "sainte", s)
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"^(le|la|les|l) ", "", s)   # le référentiel écrit « Mesnil-Saint-Denis » pour « Le Mesnil-Saint-Denis »


@lru_cache(maxsize=1)
def index_communes() -> dict:
    """nom normalisé → code département. Les 4 noms portés par des communes de deux départements
    (ex. Marolles-en-Brie, 77 et 94) sont exclus : on ne devine pas."""
    if not COMMUNES_CSV.exists():
        log.warning("communes_idf.csv absent — lancer : python src/collect.py --source communes")
        return {}
    ref = pd.read_csv(COMMUNES_CSV, dtype=str)
    ref["cle"] = ref["nom"].map(normaliser_nom)
    depts = ref.groupby("cle")["code_dept"].agg(set)
    return {cle: next(iter(d)) for cle, d in depts.items() if len(d) == 1}


RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
RE_TEL = re.compile(r"(?:(?:\+33|0033)\s?|0)[1-9](?:[\s.-]?\d{2}){4}")
RE_HF = re.compile(r"\s*[\(\-]?\s*[HhFf]\s*/\s*[HhFf]\s*[\)\-]?\s*$")

COLONNES = ["source", "id_source", "hash_offre", "titre", "entreprise", "lieu", "code_dept",
            "code_rome", "appellation_rome", "categorie", "contrat", "temps_travail", "experience",
            "salaire_min", "salaire_max", "salaire_moyen", "date_publication", "description", "url"]


# ───────────────────────────────────────────────────────── règles unitaires
def normaliser_salaire_annuel(val):
    """Ramène un montant en € brut annuel : < 100 → horaire (×1 820 h), < 5 000 → mensuel (×12).
    Hors bornes [10 000 ; 300 000] → valeur aberrante, remplacée par NaN."""
    if val is None or pd.isna(val):
        return None
    val = float(val)
    if val < 100:
        val *= 1820
    elif val < 5000:
        val *= 12
    return val if 10_000 <= val <= 300_000 else None


def extraire_salaire(libelle) -> tuple:
    """'Mensuel de 2000.0 Euros à 2500.0 Euros sur 12 mois' → (2000.0, 2500.0).
    Les nombres de mois (12, 13…) et les valeurs nulles sont ignorés."""
    if libelle is None or pd.isna(libelle) or str(libelle).strip() == "":
        return None, None
    texte = re.sub(r"sur\s+\d+(?:[.,]\d+)?\s+mois", "", str(libelle), flags=re.I)
    nombres = [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", texte)]
    nombres = [n for n in nombres if n > 0]
    if not nombres:
        return None, None
    return min(nombres), max(nombres)


def code_departement(lieu) -> str | None:
    """Département d'un lieu, par ordre de fiabilité :
    1. code écrit dans le libellé : '92 - Nanterre', 'Hauts-de-Seine (92)'
    2. nom de département : 'Paris', 'Essonne'
    3. référentiel des communes IDF, segment par segment : 'Montévrain, Lagny-sur-Marne' → 77
    Sinon None (ex. 'Ile-de-France, France', ou 'Mouvaux, Nord' hors région)."""
    if lieu is None or pd.isna(lieu):
        return None
    s = str(lieu).strip()
    m = re.match(r"^(75|77|78|91|92|93|94|95)\b", s) or re.search(r"\((75|77|78|91|92|93|94|95)\)", s)
    if m:
        return m.group(1)
    segments = [normaliser_nom(x) for x in s.split(",") if x.strip()]
    noms_dept = {normaliser_nom(n): c for c, n in DEPARTEMENTS.items()}
    communes = index_communes()
    for seg in segments:
        if seg in noms_dept:
            return noms_dept[seg]
        if seg.startswith("paris "):          # 'Paris 15e Arrondissement'
            return "75"
        if seg in communes:
            return communes[seg]
        if seg in LIEUX_DITS:
            return LIEUX_DITS[seg]
    # commune fusionnée après l'édition du référentiel (ex. « Évry-Courcouronnes », 2019) :
    # on essaie les débuts de nom, du plus long au plus court (« evry courcouronnes » → « evry »)
    for seg in segments:
        mots = seg.split()
        for k in range(len(mots) - 1, 0, -1):
            if " ".join(mots[:k]) in communes:
                return communes[" ".join(mots[:k])]
    return None


def normaliser_contrat(contrat) -> str:
    """'CDD - 12 Mois' → 'CDD' ; 'Intérim - 1 Mois' → 'Intérim' ; 'permanent' → 'CDI'."""
    if contrat is None or pd.isna(contrat):
        return "Non renseigné"
    c = str(contrat).strip().lower()
    regles = [("cdi", "CDI"), ("permanent", "CDI"), ("cdd", "CDD"), ("contract", "CDD"),
              ("intérim", "Intérim"), ("interim", "Intérim"), ("mis", "Intérim"),
              ("temporary", "Intérim"), ("libéral", "Libéral"), ("franchise", "Autre"),
              ("saisonnier", "CDD"), ("alternance", "Alternance"), ("apprentissage", "Alternance")]
    for motif, valeur in regles:
        if motif in c:
            return valeur
    return "Non renseigné" if c in {"", "non renseigné", "non renseigne", "temps plein",
                                    "temps partiel", "full_time", "part_time"} else "Autre"


def temps_travail(contrat) -> str | None:
    """Adzuna renvoie souvent le temps de travail à la place du type de contrat."""
    c = str(contrat).lower()
    if "plein" in c or "full" in c:
        return "Temps plein"
    if "partiel" in c or "part" in c:
        return "Temps partiel"
    return None


def pseudonymiser(texte) -> str:
    """RGPD : masque les e-mails et numéros de téléphone de recruteurs présents dans le texte libre."""
    if texte is None or pd.isna(texte):
        return ""
    return RE_TEL.sub("[tel]", RE_EMAIL.sub("[email]", str(texte)))


def hash_offre(titre, entreprise, lieu) -> str:
    """Empreinte de déduplication : même intitulé + même entreprise + même lieu = même offre."""
    cle = "|".join(str(x or "").strip().lower() for x in (titre, entreprise, lieu))
    return hashlib.md5(cle.encode("utf-8")).hexdigest()


def nettoyer_titre(titre) -> str:
    t = re.sub(r"\s+", " ", str(titre or "")).strip()
    return RE_HF.sub("", t).strip()


# ──────────────────────────────────────────────────── traitement d'un jeu
def harmoniser(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Applique les règles unitaires et projette sur le schéma commun COLONNES."""
    out = pd.DataFrame(index=df.index)
    out["source"] = source
    out["id_source"] = df.get("id_source", pd.Series(index=df.index, dtype=object))
    out["titre"] = df["titre"].map(nettoyer_titre)
    ent = df["entreprise"].fillna("").astype(str).str.strip()
    out["entreprise"] = ent.replace(["", "N/A", "n/a", "NA", "-", ".", "Unknown", "null",
                                     "Non renseigne"], "Non renseigné")
    out["lieu"] = df["lieu"].astype(str).str.strip()
    lieu_ou_dept = df["departement"].where(df["departement"].notna(), df["lieu"]) \
        if "departement" in df else df["lieu"]
    out["code_dept"] = lieu_ou_dept.map(code_departement)
    out["code_dept"] = out["code_dept"].fillna(df["lieu"].map(code_departement))
    out["code_rome"] = df.get("code_rome")
    out["appellation_rome"] = df.get("appellation_rome")
    out["categorie"] = df.get("categorie")
    out["contrat"] = df["contrat"].map(normaliser_contrat)
    out["temps_travail"] = df["contrat"].map(temps_travail)
    out["experience"] = df.get("experience")
    for c in ("salaire_min", "salaire_max"):
        out[c] = pd.to_numeric(df.get(c), errors="coerce").map(normaliser_salaire_annuel)
    inverses = out["salaire_min"] > out["salaire_max"]          # bornes inversées → on les permute
    out.loc[inverses, ["salaire_min", "salaire_max"]] = out.loc[inverses, ["salaire_max", "salaire_min"]].values
    out["salaire_moyen"] = out[["salaire_min", "salaire_max"]].mean(axis=1)
    dates = pd.to_datetime(df["date_publication"], errors="coerce", utc=True, format="mixed")
    out["date_publication"] = dates.dt.strftime("%Y-%m-%dT%H:%M:%S")
    out["description"] = df["description"].map(pseudonymiser)
    out["url"] = df["url"]
    out["hash_offre"] = [hash_offre(t, e, l) for t, e, l in zip(out.titre, out.entreprise, out.lieu)]
    if source == "adzuna":
        # M1607 sert de code « fourre-tout » dans le mapping catégorie Adzuna → ROME :
        # on ne le conserve que pour les vraies catégories administratives (anomalie A7).
        fourre_tout = out["code_rome"].eq("M1607") & ~out["categorie"].fillna("").str.contains("Administration")
        out.loc[fourre_tout, "code_rome"] = None
    out = out[out["titre"].str.len() >= 3]
    # hors périmètre : lieu identifié hors Île-de-France (ex. « Mouvaux, Nord ») — on ne garde
    # sans département que les offres localisées « Ile-de-France » sans précision de commune
    hors_idf = out["code_dept"].isna() & ~out["lieu"].str.contains("le-de-France", case=False, na=False)
    out = out[~hors_idf]
    return out[COLONNES]


def depuis_brut_ft(df: pd.DataFrame) -> pd.DataFrame:
    """Brut France Travail : le salaire est un libellé texte à parser."""
    df = df.copy()
    sal = df["salaire"].map(extraire_salaire)
    df["salaire_min"] = [s[0] for s in sal]
    df["salaire_max"] = [s[1] for s in sal]
    return df


def depuis_brut_adzuna(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={"date": "date_publication"}).copy()
    df["categorie"] = df["categorie"].fillna("Unknown")
    return df


def dedoublonner(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """1) même URL  2) même empreinte. Priorité à France Travail (codes ROME natifs)."""
    n0 = len(df)
    df = df.sort_values("source", key=lambda s: s.ne("france_travail"))  # FT en premier
    df = df[df["url"].isna() | ~df.duplicated("url")]
    n1 = len(df)
    df = df.drop_duplicates("hash_offre", keep="first")
    return df.reset_index(drop=True), {"doublons_url": n0 - n1, "doublons_empreinte": n1 - len(df)}


NIVEAUX_SALAIRE = ["affiché", "médiane métier × département", "médiane métier", "médiane domaine",
                   "médiane département", "médiane régionale"]


def imputer_salaires(df: pd.DataFrame, min_obs: int = 3) -> tuple[pd.DataFrame, dict]:
    """Salaire non affiché → médiane des salaires AFFICHÉS du groupe le plus précis qui en compte au moins `min_obs` :
      1. même métier ROME dans le même département   (ex. aide-soignant dans le 93)
      2. même métier ROME en Île-de-France
      3. même domaine ROME (3 premiers caractères, ex. J15 = soins)
      4. même département
      5. toute l'Île-de-France
    Combine la V1 (médiane par département puis par catégorie) et la V2 (médiane par métier).
    La médiane, pas la moyenne : quelques salaires très élevés ne la déplacent pas.
    salaire_min / salaire_max restent vides (on n'invente pas de fourchette) ; salaire_impute = 1 et
    salaire_source indiquent la valeur calculée, et les indicateurs n'utilisent que les salaires affichés :
    c'est ce qui évite l'« enrichissement circulaire » (des valeurs imputées qui se confirmeraient elles-mêmes)."""
    df = df.copy()
    for col in ("code_rome", "code_dept"):
        if col not in df:
            df[col] = None
    affiche = df["salaire_moyen"].notna()
    df["salaire_impute"] = (~affiche).astype(int)
    df["salaire_source"] = pd.Series("affiché", index=df.index).where(affiche, None)
    df["_domaine"] = df["code_rome"].str[:3]
    obs = df[affiche]
    niveaux = [(["code_rome", "code_dept"], NIVEAUX_SALAIRE[1]), (["code_rome"], NIVEAUX_SALAIRE[2]),
               (["_domaine"], NIVEAUX_SALAIRE[3]), (["code_dept"], NIVEAUX_SALAIRE[4])]
    for cles, nom in niveaux:
        med = obs.groupby(cles)["salaire_moyen"].agg(["median", "count"])
        med = med.loc[med["count"] >= min_obs, "median"]
        a_remplir = df["salaire_moyen"].isna() & df[cles].notna().all(axis=1)
        if not a_remplir.any() or med.empty:
            continue
        idx = pd.MultiIndex.from_frame(df.loc[a_remplir, cles]) if len(cles) > 1 else df.loc[a_remplir, cles[0]]
        valeurs = pd.Series(med.reindex(idx).to_numpy(), index=df.index[a_remplir])
        ok = valeurs.notna()
        df.loc[valeurs.index[ok], "salaire_moyen"] = valeurs[ok].round(0)
        df.loc[valeurs.index[ok], "salaire_source"] = nom
    mediane_globale = float(obs["salaire_moyen"].median())
    reste = df["salaire_moyen"].isna()
    df.loc[reste, "salaire_moyen"] = round(mediane_globale)
    df.loc[reste, "salaire_source"] = NIVEAUX_SALAIRE[5]
    stats = df["salaire_source"].value_counts().reindex(NIVEAUX_SALAIRE, fill_value=0).to_dict()
    stats["valeur_mediane_globale"] = round(mediane_globale)
    return df.drop(columns="_domaine"), stats


def affiner_rome_adzuna(df: pd.DataFrame, min_occ: int = 2, part_min: float = 0.6) -> tuple[pd.DataFrame, dict]:
    """Code ROME des offres Adzuna, du plus fiable au moins fiable :
      1. intitulé identique à des offres France Travail (au moins `min_occ` offres, et un code ROME
         majoritaire à `part_min` au moins) → ce code ROME   (ex. « Comptable » → M1203)
      2. sinon, correspondance catégorie Adzuna → ROME (V1), sauf le code fourre-tout M1607
      3. sinon, vide.
    rome_source garde la trace de la méthode (france_travail / intitule / categorie)."""
    df = df.copy()
    cle = df["titre"].map(normaliser_nom)
    ft = df["source"].eq("france_travail") & df["code_rome"].notna()
    stats_ft = df[ft].groupby(cle[ft])["code_rome"].agg(
        lambda s: (s.value_counts().index[0], s.value_counts().iloc[0] / len(s), len(s)))
    dico = {k: v[0] for k, v in stats_ft.items() if v[2] >= min_occ and v[1] >= part_min}
    df["rome_source"] = None
    df.loc[ft, "rome_source"] = "france_travail"
    adz = df["source"].eq("adzuna")
    par_titre = cle[adz].map(dico)
    trouve = par_titre.notna()
    df.loc[par_titre.index[trouve], "code_rome"] = par_titre[trouve]
    df.loc[par_titre.index[trouve], "rome_source"] = "intitule"
    cat = adz & df["rome_source"].isna() & df["code_rome"].notna()
    df.loc[cat, "rome_source"] = "categorie"
    return df, {"intitule": int(trouve.sum()), "categorie": int(cat.sum()),
                "sans_code": int((adz & df["code_rome"].isna()).sum())}


def charger_sources() -> tuple[pd.DataFrame, pd.DataFrame, str]:
    brut_ft, brut_adz = DATA / "offres_ft_idf.csv", DATA / "offres_idf.csv"
    if brut_ft.exists() and brut_adz.exists():
        return (depuis_brut_ft(pd.read_csv(brut_ft)), depuis_brut_adzuna(pd.read_csv(brut_adz)),
                "bruts (collect.py)")
    return (pd.read_csv(DATA / "offres_ft_idf_clean.csv"), pd.read_csv(DATA / "offres_idf_clean.csv"),
            "nettoyés versionnés")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
    ft, adz, origine = charger_sources()
    log.info(f"Sources {origine} : France Travail {len(ft):,} · Adzuna {len(adz):,}")
    unifie = pd.concat([harmoniser(ft, "france_travail"), harmoniser(adz, "adzuna")], ignore_index=True)
    unifie, stats = dedoublonner(unifie)
    unifie, rome = affiner_rome_adzuna(unifie)
    log.info(f"Codes ROME Adzuna : {rome['intitule']:,} par intitulé France Travail · "
             f"{rome['categorie']:,} par catégorie · {rome['sans_code']:,} sans code")
    unifie, sal = imputer_salaires(unifie)
    log.info("Salaires : " + " · ".join(f"{k} {v:,}" for k, v in sal.items() if k != "valeur_mediane_globale")
             + f" (médiane régionale {sal['valeur_mediane_globale']:,} €)")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    unifie.to_csv(OUT_FILE, index=False, encoding="utf-8")
    log.info(f"Doublons supprimés : {stats}")
    log.info(f"Offres unifiées : {len(unifie):,} → {OUT_FILE.relative_to(ROOT)}")
    log.info("Répartition :\n" + unifie.groupby("source").size().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
