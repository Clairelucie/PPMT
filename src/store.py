"""
C4 — Création et alimentation de la base SQLite PPMT (data/ppmt.db).

Modèle relationnel (3e forme normale) :
  departements (code_dept PK)
  metiers_rome (code_rome PK)
  offres (id PK, hash_offre UNIQUE, code_dept FK, code_rome FK)
  indicateurs_tension (code_rome PK/FK) ← calculé en SQL à partir de la table offres

C3 — les règles d'agrégation (volume, salaire médian, part de CDI, indice de tension)
sont exprimées en SQL (GROUP BY + fonction fenêtre) : voir SQL_INDICATEURS.

RGPD : pas de donnée personnelle de candidat ; descriptions pseudonymisées en amont
(prepare.py) ; durée de conservation 12 mois appliquée par purger_offres_anciennes().
"""
from __future__ import annotations

import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "ppmt.db"
SRC = ROOT / "data" / "processed" / "offres_unifiees.csv"
sys.path.insert(0, str(ROOT / "src"))
from prepare import DEPARTEMENTS  # noqa: E402

log = logging.getLogger("ppmt.store")

RETENTION_JOURS = 365

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS departements (
    code_dept   TEXT PRIMARY KEY CHECK (length(code_dept) = 2),
    nom         TEXT NOT NULL,
    latitude    REAL CHECK (latitude IS NULL OR latitude BETWEEN 48.0 AND 49.5),
    longitude   REAL CHECK (longitude IS NULL OR longitude BETWEEN 1.4 AND 3.6),
    superficie_km2 REAL
);

CREATE TABLE IF NOT EXISTS metiers_rome (
    code_rome   TEXT PRIMARY KEY CHECK (code_rome GLOB '[A-N][0-9][0-9][0-9][0-9]'),
    libelle     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offres (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source           TEXT NOT NULL CHECK (source IN ('france_travail', 'adzuna')),
    id_source        TEXT,
    hash_offre       TEXT NOT NULL UNIQUE,
    titre            TEXT NOT NULL,
    entreprise       TEXT,
    lieu             TEXT,
    code_dept        TEXT REFERENCES departements(code_dept),
    code_rome        TEXT REFERENCES metiers_rome(code_rome),
    categorie        TEXT,
    contrat          TEXT CHECK (contrat IN ('CDI','CDD','Intérim','Libéral','Alternance','Autre','Non renseigné')),
    temps_travail    TEXT,
    experience       TEXT,
    salaire_min      REAL CHECK (salaire_min IS NULL OR salaire_min BETWEEN 10000 AND 300000),
    salaire_max      REAL CHECK (salaire_max IS NULL OR salaire_max BETWEEN 10000 AND 300000),
    salaire_moyen    REAL,
    salaire_impute   INTEGER NOT NULL DEFAULT 0 CHECK (salaire_impute IN (0, 1)),
    salaire_source   TEXT,
    rome_source      TEXT CHECK (rome_source IS NULL OR rome_source IN ('france_travail', 'intitule', 'categorie')),
    date_publication TEXT,
    description      TEXT,
    url              TEXT,
    date_import      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS indicateurs_tension (
    code_rome            TEXT PRIMARY KEY REFERENCES metiers_rome(code_rome),
    nb_offres_ft         INTEGER NOT NULL,
    nb_offres_adzuna     INTEGER NOT NULL,
    nb_offres_total      INTEGER NOT NULL,
    nb_entreprises       INTEGER,
    nb_departements      INTEGER,
    part_cdi             REAL,
    salaire_median       REAL,
    part_salaire_affiche REAL,
    indice_tension       REAL NOT NULL,
    statut               TEXT NOT NULL,
    date_calcul          TEXT NOT NULL
);

-- vue d'analyse : colonnes de date calculées à la volée (pas de redondance dans la table)
CREATE VIEW IF NOT EXISTS v_offres_analyse AS
SELECT o.*,
       CAST(strftime('%Y', date_publication) AS INTEGER) AS annee,
       CAST(strftime('%m', date_publication) AS INTEGER) AS mois,
       CAST(julianday((SELECT MAX(date_publication) FROM offres)) - julianday(date_publication) AS INTEGER) AS age_jours,
       (julianday((SELECT MAX(date_publication) FROM offres)) - julianday(date_publication)) <= 30 AS is_recente
FROM offres o;

CREATE INDEX IF NOT EXISTS idx_offres_dept     ON offres(code_dept);
CREATE INDEX IF NOT EXISTS idx_offres_rome     ON offres(code_rome);
CREATE INDEX IF NOT EXISTS idx_offres_source   ON offres(source);
CREATE INDEX IF NOT EXISTS idx_offres_contrat  ON offres(contrat);
CREATE INDEX IF NOT EXISTS idx_offres_date     ON offres(date_publication);
CREATE INDEX IF NOT EXISTS idx_tension_statut  ON indicateurs_tension(statut);
"""

# C3 — agrégation en SQL : 1 ligne par code ROME.
# Indice de tension (ITM) = volume d'offres du métier rapporté au volume moyen d'un métier × 100.
#   100 = métier « moyen » ; 200 = deux fois plus d'offres que la moyenne.
# C'est un indicateur de pression de la DEMANDE des employeurs (côté offres uniquement :
# PPMT ne dispose pas du nombre de candidats).
SQL_INDICATEURS = """
INSERT INTO indicateurs_tension
WITH agg AS (
    SELECT code_rome,
           SUM(source = 'france_travail')                   AS nb_offres_ft,
           SUM(source = 'adzuna')                           AS nb_offres_adzuna,
           COUNT(*)                                         AS nb_offres_total,
           COUNT(DISTINCT NULLIF(entreprise, 'Non renseigné')) AS nb_entreprises,
           COUNT(DISTINCT code_dept)                        AS nb_departements,
           ROUND(AVG(contrat = 'CDI') * 100, 1)             AS part_cdi,
           NULL                                             AS salaire_median,   -- calculée ensuite (médiane)
           ROUND(AVG(salaire_impute = 0) * 100, 1)          AS part_salaire_affiche
    FROM offres
    WHERE code_rome IS NOT NULL
    GROUP BY code_rome
)
SELECT code_rome, nb_offres_ft, nb_offres_adzuna, nb_offres_total, nb_entreprises,
       nb_departements, part_cdi, salaire_median, part_salaire_affiche,
       ROUND(nb_offres_total * 100.0 / AVG(nb_offres_total) OVER (), 1) AS indice_tension,
       CASE
           WHEN nb_offres_total * 100.0 / AVG(nb_offres_total) OVER () > 150 THEN 'TRES EN TENSION'
           WHEN nb_offres_total * 100.0 / AVG(nb_offres_total) OVER () > 100 THEN 'EN TENSION'
           WHEN nb_offres_total * 100.0 / AVG(nb_offres_total) OVER () > 50  THEN 'EQUILIBRE'
           ELSE 'SATURE'
       END AS statut,
       :date_calcul
FROM agg;
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def creer_schema(conn: sqlite3.Connection, reset: bool = True) -> None:
    if reset:
        conn.execute("DROP VIEW IF EXISTS v_offres_analyse")
        for t in ("indicateurs_tension", "offres", "metiers_rome", "departements"):
            conn.execute(f"DROP TABLE IF EXISTS {t}")
    conn.executescript(SCHEMA)


GEOJSON = ROOT / "data" / "ref" / "departements_idf.geojson"


def centre_et_surface(anneau: list) -> tuple[float, float, float]:
    """Centre de gravité et surface d'un polygone (formule du lacet).
    Coordonnées WGS84 ; la surface est convertie en km² avec une projection locale (1° lat ≈ 111,32 km)."""
    import math
    lat0 = sum(p[1] for p in anneau) / len(anneau)
    kx, ky = 111.32 * math.cos(math.radians(lat0)), 111.32
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(anneau, anneau[1:] + anneau[:1]):
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    a /= 2
    return cy / (6 * a), cx / (6 * a), abs(a) * kx * ky   # latitude, longitude, km²


def lire_geojson(path: Path = GEOJSON) -> dict:
    """code_dept → (latitude, longitude, superficie) calculés depuis le fichier de référence (C1)."""
    if not path.exists():
        log.warning(f"{path.name} absent — départements sans coordonnées (lancer collect.py --source geojson)")
        return {}
    import json
    res = {}
    for f in json.loads(path.read_text(encoding="utf-8"))["features"]:
        geom = f["geometry"]
        polygones = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        exterieur = max((p[0] for p in polygones), key=len)   # anneau extérieur le plus grand
        res[f["properties"]["code"]] = centre_et_surface([tuple(pt[:2]) for pt in exterieur])
    return res


def charger_referentiels(conn, offres: pd.DataFrame) -> None:
    geo = lire_geojson()
    conn.executemany("INSERT OR IGNORE INTO departements VALUES (?, ?, ?, ?, ?)",
                     [(code, nom, *(round(v, 4) for v in geo[code][:2]), round(geo[code][2], 0))
                      if code in geo else (code, nom, None, None, None)
                      for code, nom in DEPARTEMENTS.items()])
    # libellé ROME : appellation France Travail la plus fréquente pour ce code
    # (priorité au libellé officiel France Travail ; à défaut, catégorie Adzuna)
    def libelle(g: pd.DataFrame) -> str:
        for col in ("appellation_rome", "categorie"):
            vals = g[col].dropna()
            if not vals.empty:
                return str(vals.mode().iat[0])
        return g.name
    lib = offres.dropna(subset=["code_rome"]).groupby("code_rome")[["appellation_rome", "categorie"]].apply(libelle)
    conn.executemany("INSERT OR IGNORE INTO metiers_rome VALUES (?, ?)", lib.items())


def charger_offres(conn, offres: pd.DataFrame) -> int:
    cols = ["source", "id_source", "hash_offre", "titre", "entreprise", "lieu", "code_dept",
            "code_rome", "categorie", "contrat", "temps_travail", "experience", "salaire_min",
            "salaire_max", "salaire_moyen", "salaire_impute", "salaire_source", "rome_source", "date_publication", "description", "url"]
    df = offres[cols].copy()
    df["date_import"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    df = df.astype(object).where(df.notna(), None)
    ph = ", ".join("?" * len(df.columns))
    cur = conn.executemany(
        f"INSERT OR IGNORE INTO offres ({', '.join(df.columns)}) VALUES ({ph})",
        df.itertuples(index=False, name=None))
    return cur.rowcount


def calculer_indicateurs(conn) -> int:
    conn.execute("DELETE FROM indicateurs_tension")
    conn.execute(SQL_INDICATEURS, {"date_calcul": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")})
    return conn.execute("SELECT COUNT(*) FROM indicateurs_tension").fetchone()[0]


def mediane(valeurs: list) -> float | None:
    """Médiane (SQLite n'a pas de fonction MEDIAN) : valeur du milieu, ou moyenne des deux du milieu."""
    v = sorted(x for x in valeurs if x is not None)
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2


def calculer_medianes(conn) -> None:
    """Salaire médian par métier, sur les seuls salaires AFFICHÉS (les valeurs imputées sont exclues)."""
    par_rome: dict[str, list] = {}
    for code, sal in conn.execute("SELECT code_rome, salaire_moyen FROM offres "
                                  "WHERE code_rome IS NOT NULL AND salaire_impute = 0"):
        par_rome.setdefault(code, []).append(sal)
    conn.executemany("UPDATE indicateurs_tension SET salaire_median = ? WHERE code_rome = ?",
                     [(round(mediane(v)), c) for c, v in par_rome.items()])


def purger_offres_anciennes(conn, jours: int = RETENTION_JOURS) -> int:
    """RGPD (limitation de conservation) + cohérence analytique : fenêtre glissante de `jours` jours.
    Les offres publiées plus de `jours` jours avant la collecte la plus récente sont supprimées."""
    cur = conn.execute(
        "DELETE FROM offres WHERE date_publication < "
        "datetime((SELECT MAX(date_publication) FROM offres), ?)", (f"-{jours} days",))
    return cur.rowcount


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
    offres = pd.read_csv(SRC, dtype={"code_dept": str, "code_rome": str, "id_source": str})
    with connect() as conn:
        creer_schema(conn)
        charger_referentiels(conn, offres)
        n = charger_offres(conn, offres)
        purges = purger_offres_anciennes(conn)
        k = calculer_indicateurs(conn)
        calculer_medianes(conn)
        conn.commit()
        log.info(f"Base {DB_PATH.relative_to(ROOT)} : {n:,} offres insérées, {purges} purgées (> {RETENTION_JOURS} j)")
        log.info(f"Indicateurs de tension calculés pour {k:,} codes ROME")
        for t in ("departements", "metiers_rome", "offres", "indicateurs_tension"):
            log.info(f"  {t:22s} {conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:>7,} lignes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
