"""
C5 — API REST PPMT (FastAPI) : mise à disposition des offres et des indicateurs de tension.

Lancement :  uvicorn api.main:app --reload        → Swagger : http://localhost:8000/docs
Sécurité  :  en-tête X-API-Key (variable d'environnement PPMT_API_KEY), sauf /health
             méthodes GET uniquement (API en lecture seule), requêtes SQL paramétrées,
             pagination plafonnée (limit ≤ 500).
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Path as P, Query, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

DB_PATH = Path(os.getenv("PPMT_DB", Path(__file__).resolve().parents[1] / "data" / "ppmt.db"))
API_KEY = os.getenv("PPMT_API_KEY")   # secret fourni à l'exécution, jamais écrit dans le code
if not API_KEY:
    raise RuntimeError("Variable d'environnement PPMT_API_KEY absente : définissez-la avant de lancer l'API "
                       "(ex. : export PPMT_API_KEY=<votre clé>).")

app = FastAPI(
    title="API PPMT — Métiers en tension Île-de-France",
    version="2.0.0",
    description=("Offres d'emploi France Travail + Adzuna (8 départements franciliens) et indicateurs "
                 "de tension par code ROME. Authentification : en-tête `X-API-Key`."),
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verifier_cle(key: Optional[str] = Security(_api_key_header)) -> None:
    if key != API_KEY:
        raise HTTPException(status_code=403, detail="Clé API invalide ou manquante")


@contextmanager
def db():
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail="Base de données indisponible — lancer run_pipeline.py")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)   # connexion en lecture seule
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def mediane(valeurs: list):
    v = sorted(valeurs)
    if not v:
        return None
    m = len(v) // 2
    return round(v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2)


def lignes(conn, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ─────────────────────────────────────────────────────────────── modèles
class Source(str, Enum):
    france_travail = "france_travail"
    adzuna = "adzuna"


class Statut(str, Enum):
    tres_en_tension = "TRES EN TENSION"
    en_tension = "EN TENSION"
    equilibre = "EQUILIBRE"
    sature = "SATURE"


class Offre(BaseModel):
    id: int
    source: str
    titre: str
    entreprise: Optional[str] = None
    lieu: Optional[str] = None
    code_dept: Optional[str] = None
    code_rome: Optional[str] = None
    contrat: Optional[str] = None
    salaire_moyen: Optional[float] = None
    salaire_impute: Optional[int] = None
    date_publication: Optional[str] = None
    url: Optional[str] = None


class OffreDetail(Offre):
    categorie: Optional[str] = None
    experience: Optional[str] = None
    temps_travail: Optional[str] = None
    salaire_min: Optional[float] = None
    salaire_max: Optional[float] = None
    description: Optional[str] = None


class PageOffres(BaseModel):
    total: int
    limit: int
    offset: int
    resultats: list[Offre]


class Indicateur(BaseModel):
    code_rome: str
    libelle: str
    nb_offres_ft: int
    nb_offres_adzuna: int
    nb_offres_total: int
    nb_entreprises: Optional[int] = None
    part_cdi: Optional[float] = None
    salaire_median: Optional[float] = None
    part_salaire_affiche: Optional[float] = None
    indice_tension: float
    statut: str


class MetierDetail(Indicateur):
    repartition_departements: list[dict]
    repartition_contrats: list[dict]


# ─────────────────────────────────────────────────────────────── endpoints
@app.get("/health", tags=["Service"], summary="Disponibilité du service (public)")
def health():
    with db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM offres").fetchone()[0]
        m = conn.execute("SELECT COUNT(*) FROM indicateurs_tension").fetchone()[0]
        maj = conn.execute("SELECT MAX(date_calcul) FROM indicateurs_tension").fetchone()[0]
    return {"status": "ok", "nb_offres": n, "nb_metiers": m, "derniere_mise_a_jour": maj}


@app.get("/offres", response_model=PageOffres, tags=["Offres"], dependencies=[Depends(verifier_cle)],
         summary="Liste paginée et filtrable des offres")
def lister_offres(
    departement: Optional[str] = Query(None, pattern=r"^(75|77|78|91|92|93|94|95)$", description="Code département"),
    code_rome: Optional[str] = Query(None, pattern=r"^[A-N]\d{4}$", description="Code ROME, ex. J1502"),
    source: Optional[Source] = None,
    contrat: Optional[str] = Query(None, description="CDI, CDD, Intérim, Libéral, Autre…"),
    q: Optional[str] = Query(None, min_length=2, description="Mot-clé dans l'intitulé"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    filtres, params = [], []
    for col, val in (("code_dept", departement), ("code_rome", code_rome),
                     ("source", source.value if source else None), ("contrat", contrat)):
        if val:
            filtres.append(f"{col} = ?")
            params.append(val)
    if q:
        filtres.append("titre LIKE ?")
        params.append(f"%{q}%")
    where = f"WHERE {' AND '.join(filtres)}" if filtres else ""
    with db() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM offres {where}", params).fetchone()[0]
        res = lignes(conn, f"""SELECT id, source, titre, entreprise, lieu, code_dept, code_rome, contrat,
                                      salaire_moyen, salaire_impute, date_publication, url
                               FROM offres {where}
                               ORDER BY date_publication DESC LIMIT ? OFFSET ?""", params + [limit, offset])
    return {"total": total, "limit": limit, "offset": offset, "resultats": res}


@app.get("/offres/{offre_id}", response_model=OffreDetail, tags=["Offres"],
         dependencies=[Depends(verifier_cle)], summary="Détail d'une offre")
def detail_offre(offre_id: int = P(..., ge=1)):
    with db() as conn:
        res = lignes(conn, "SELECT * FROM offres WHERE id = ?", (offre_id,))
    if not res:
        raise HTTPException(status_code=404, detail=f"Offre {offre_id} introuvable")
    return res[0]


@app.get("/metiers", response_model=list[Indicateur], tags=["Tension"], dependencies=[Depends(verifier_cle)],
         summary="Indicateurs de tension par métier (tri décroissant)")
def lister_metiers(statut: Optional[Statut] = None,
                   limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    where, params = ("WHERE i.statut = ?", [statut.value]) if statut else ("", [])
    with db() as conn:
        return lignes(conn, f"""SELECT i.*, m.libelle FROM indicateurs_tension i
                                JOIN metiers_rome m USING (code_rome) {where}
                                ORDER BY i.indice_tension DESC LIMIT ? OFFSET ?""", params + [limit, offset])


@app.get("/metiers/{code_rome}", response_model=MetierDetail, tags=["Tension"],
         dependencies=[Depends(verifier_cle)], summary="Fiche métier : tension, départements, contrats")
def detail_metier(code_rome: str = P(..., pattern=r"^[A-N]\d{4}$")):
    with db() as conn:
        res = lignes(conn, """SELECT i.*, m.libelle FROM indicateurs_tension i
                              JOIN metiers_rome m USING (code_rome) WHERE code_rome = ?""", (code_rome,))
        if not res:
            raise HTTPException(status_code=404, detail=f"Code ROME {code_rome} absent de la base")
        fiche = res[0]
        fiche["repartition_departements"] = lignes(conn, """
            SELECT d.code_dept, d.nom, COUNT(o.id) AS nb_offres
            FROM departements d LEFT JOIN offres o ON o.code_dept = d.code_dept AND o.code_rome = ?
            GROUP BY d.code_dept ORDER BY nb_offres DESC""", (code_rome,))
        fiche["repartition_contrats"] = lignes(conn, """
            SELECT contrat, COUNT(*) AS nb_offres FROM offres WHERE code_rome = ?
            GROUP BY contrat ORDER BY nb_offres DESC""", (code_rome,))
    return fiche


@app.get("/stats/departements", tags=["Statistiques"], dependencies=[Depends(verifier_cle)],
         summary="Volume d'offres, densité, part de CDI, salaire médian et coordonnées par département")
def stats_departements():
    with db() as conn:
        # salaire médian calculé sur les seuls salaires affichés (valeurs imputées exclues)
        sal: dict[str, list] = {}
        for code, v in conn.execute("SELECT code_dept, salaire_moyen FROM offres "
                                    "WHERE salaire_impute = 0 AND code_dept IS NOT NULL"):
            sal.setdefault(code, []).append(v)
        res = lignes(conn, """
            SELECT d.code_dept, d.nom, d.latitude, d.longitude, d.superficie_km2,
                   COUNT(o.id)                                   AS nb_offres,
                   ROUND(COUNT(o.id) * 100.0 / d.superficie_km2, 1) AS offres_pour_100_km2,
                   SUM(o.source = 'france_travail')              AS nb_offres_ft,
                   SUM(o.source = 'adzuna')                      AS nb_offres_adzuna,
                   ROUND(AVG(o.contrat = 'CDI') * 100, 1)        AS part_cdi,
                   ROUND(AVG(o.salaire_impute = 0) * 100, 1)     AS part_salaire_affiche
            FROM departements d LEFT JOIN offres o USING (code_dept)
            GROUP BY d.code_dept ORDER BY nb_offres DESC""")
    for r in res:
        r["salaire_median"] = mediane(sal.get(r["code_dept"], []))
    return res


@app.get("/stats/tension", tags=["Statistiques"], dependencies=[Depends(verifier_cle)],
         summary="Répartition des métiers par statut de tension")
def stats_tension():
    with db() as conn:
        return lignes(conn, """
            SELECT statut, COUNT(*) AS nb_metiers, SUM(nb_offres_total) AS nb_offres
            FROM indicateurs_tension GROUP BY statut
            ORDER BY CASE statut WHEN 'TRES EN TENSION' THEN 1 WHEN 'EN TENSION' THEN 2
                                 WHEN 'EQUILIBRE' THEN 3 ELSE 4 END""")
