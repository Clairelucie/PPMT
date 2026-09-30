"""
C1 — Collecte automatisée des données PPMT.

Trois types de sources :
  1. API REST France Travail « Offres d'emploi v2 » (OAuth2 client_credentials)
  2. API REST Adzuna (clé applicative app_id / app_key)
  3. Fichiers de référence : contours des départements (GeoJSON) et liste des communes d'Île-de-France,
     téléchargés et contrôlés (MD5, complétude)

Principes :
  - pagination complète (France Travail : tranches de 150, plafond 3 150 offres / requête
    → une requête par département pour couvrir l'Île-de-France)
  - reprise sur erreur (3 tentatives, back-off exponentiel, gestion du 429 « Too Many Requests »)
  - idempotence : un fichier brut par source et par jour ; s'il existe déjà, il n'est pas re-téléchargé
  - journalisation horodatée dans logs/collect_YYYYMMDD_HHMMSS.log
  - secrets lus dans .env (jamais dans le code)

Usage :
  python src/collect.py                 # toutes les sources
  python src/collect.py --source ft     # France Travail seulement
  python src/collect.py --force         # ignore l'idempotence
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
LOG_DIR = ROOT / "logs"

DEPARTEMENTS_IDF = ["75", "77", "78", "91", "92", "93", "94", "95"]

FT_TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire"
FT_SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
FT_PAGE = 150          # taille maximale d'une page France Travail
FT_MAX_START = 3000    # l'API refuse un range qui commence au-delà de 3000

ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/fr/search/{page}"
ADZUNA_PAGE = 50       # résultats par page (maximum autorisé)
ADZUNA_MAX_PAGES = 250 # 250 × 50 = 12 500 offres

GEOJSON_URL = ("https://raw.githubusercontent.com/gregoiredavid/france-geojson/"
               "master/departements.geojson")

log = logging.getLogger("ppmt.collect")


# ─────────────────────────────────────────────────────────────── utilitaires
def setup_logging() -> Path:
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"collect_{datetime.now():%Y%m%d_%H%M%S}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )
    return log_file


def md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_with_retry(session: requests.Session, url: str, *, params=None, headers=None,
                   tries: int = 3, timeout: int = 30) -> requests.Response:
    """GET avec 3 tentatives et back-off exponentiel (1 s, 2 s, 4 s).
    Respecte l'en-tête Retry-After renvoyé avec un HTTP 429."""
    for attempt in range(1, tries + 1):
        try:
            r = session.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 2 ** attempt))
                log.warning(f"HTTP 429 — pause {wait}s (tentative {attempt}/{tries})")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if attempt == tries:
                raise
            log.warning(f"Erreur réseau ({e}) — nouvelle tentative dans {2 ** (attempt - 1)}s")
            time.sleep(2 ** (attempt - 1))
    raise RuntimeError(f"Échec après {tries} tentatives : {url}")


def fichier_du_jour(prefixe: str, ext: str = "json") -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    return RAW_DIR / f"{prefixe}_{datetime.now():%Y%m%d}.{ext}"


# ──────────────────────────────────────────────────── 1. API France Travail
def ft_token(session: requests.Session, client_id: str, client_secret: str) -> str:
    r = session.post(FT_TOKEN_URL, data={
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "api_offresdemploiv2 o2dsoffre",
    }, timeout=30)
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("Token France Travail absent de la réponse")
    return token


def ft_offres_departement(session: requests.Session, token: str, dept: str) -> list[dict]:
    """Parcourt toutes les pages d'un département : range=0-149, 150-299, … jusqu'à 3000-3149."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    offres: list[dict] = []
    for start in range(0, FT_MAX_START + 1, FT_PAGE):
        params = {"departement": dept, "range": f"{start}-{start + FT_PAGE - 1}"}
        r = get_with_retry(session, FT_SEARCH_URL, params=params, headers=headers)
        if r.status_code == 204:          # plus aucun résultat
            break
        page = r.json().get("resultats", [])
        offres.extend(page)
        if len(page) < FT_PAGE:           # dernière page atteinte
            break
        time.sleep(0.1)                   # quota : 10 appels / seconde
    log.info(f"  France Travail dépt {dept} : {len(offres)} offres")
    return offres


def ft_aplatir(o: dict) -> dict:
    """Transforme une offre JSON imbriquée en ligne plate (schéma attendu par prepare.py)."""
    lieu = o.get("lieuTravail") or {}
    return {
        "id_source": o.get("id"),
        "titre": o.get("intitule"),
        "code_rome": o.get("romeCode"),
        "appellation_rome": o.get("appellationlibelle"),
        "entreprise": (o.get("entreprise") or {}).get("nom"),
        "lieu": lieu.get("libelle"),
        "departement": (lieu.get("libelle") or "")[:2],
        "salaire": (o.get("salaire") or {}).get("libelle"),
        "contrat": o.get("typeContratLibelle"),
        "experience": o.get("experienceLibelle"),
        "date_publication": o.get("dateCreation"),
        "description": (o.get("description") or "")[:300],
        "url": (o.get("origineOffre") or {}).get("urlOrigine"),
    }


def collect_france_travail(force: bool = False) -> Path | None:
    dest = fichier_du_jour("france_travail")
    if dest.exists() and not force:
        log.info(f"France Travail : déjà collecté aujourd'hui ({dest.name}) — ignoré")
        return dest
    cid, secret = os.getenv("FT_CLIENT_ID"), os.getenv("FT_CLIENT_SECRET")
    if not cid or not secret:
        log.error("FT_CLIENT_ID / FT_CLIENT_SECRET absents du .env — collecte France Travail ignorée")
        return None
    with requests.Session() as s:
        token = ft_token(s, cid, secret)
        brut = [o for d in DEPARTEMENTS_IDF for o in ft_offres_departement(s, token, d)]
    dest.write_text(json.dumps(brut, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame([ft_aplatir(o) for o in brut]).to_csv(RAW_DIR.parent / "offres_ft_idf.csv", index=False)
    log.info(f"France Travail : {len(brut)} offres → {dest.name} (MD5 {md5(dest)})")
    return dest


# ────────────────────────────────────────────────────────────── 2. API Adzuna
def adzuna_aplatir(o: dict) -> dict:
    return {
        "id_source": o.get("id"),
        "titre": o.get("title"),
        "entreprise": (o.get("company") or {}).get("display_name"),
        "lieu": (o.get("location") or {}).get("display_name"),
        "salaire_min": o.get("salary_min"),
        "salaire_max": o.get("salary_max"),
        "date": o.get("created"),
        "contrat": o.get("contract_type") or o.get("contract_time"),
        "categorie": (o.get("category") or {}).get("label", "Unknown"),
        "description": o.get("description"),
        "url": o.get("redirect_url"),
    }


def collect_adzuna(force: bool = False, max_pages: int = ADZUNA_MAX_PAGES) -> Path | None:
    dest = fichier_du_jour("adzuna")
    if dest.exists() and not force:
        log.info(f"Adzuna : déjà collecté aujourd'hui ({dest.name}) — ignoré")
        return dest
    app_id, app_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        log.error("ADZUNA_APP_ID / ADZUNA_APP_KEY absents du .env — collecte Adzuna ignorée")
        return None
    brut: list[dict] = []
    with requests.Session() as s:
        for page in range(1, max_pages + 1):
            params = {"app_id": app_id, "app_key": app_key, "where": "Ile-de-France",
                      "results_per_page": ADZUNA_PAGE, "content-type": "application/json"}
            res = get_with_retry(s, ADZUNA_URL.format(page=page), params=params).json().get("results", [])
            brut.extend(res)
            if len(res) < ADZUNA_PAGE:
                break
            time.sleep(0.2)
    dest.write_text(json.dumps(brut, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame([adzuna_aplatir(o) for o in brut]).to_csv(RAW_DIR.parent / "offres_idf.csv", index=False)
    log.info(f"Adzuna : {len(brut)} offres → {dest.name} (MD5 {md5(dest)})")
    return dest


# ─────────────────────────────────────────────────── 3. Fichier de référence
REF_DIR = ROOT / "data" / "ref"
GEOJSON_PATH = REF_DIR / "departements_idf.geojson"   # fichier de référence versionné (117 Ko)


def collect_geojson(force: bool = False) -> Path | None:
    """Contours des 8 départements franciliens (source : données IGN/Insee via gregoiredavid/france-geojson).
    Utilisé par store.py (centre géographique de chaque département) et par le dashboard (carte)."""
    dest = GEOJSON_PATH
    if dest.exists() and not force:
        log.info(f"GeoJSON : déjà présent (MD5 {md5(dest)}) — ignoré")
        return dest
    REF_DIR.mkdir(parents=True, exist_ok=True)
    with requests.Session() as s:
        r = get_with_retry(s, GEOJSON_URL)
    features = r.json().get("features", [])
    idf = [f for f in features if f["properties"]["code"] in DEPARTEMENTS_IDF]
    if len(idf) != len(DEPARTEMENTS_IDF):
        raise ValueError(f"GeoJSON incomplet : {len(idf)}/8 départements IDF")
    dest.write_text(json.dumps({"type": "FeatureCollection", "features": idf}), encoding="utf-8")
    log.info(f"GeoJSON : 8 départements IDF → {dest.name} (MD5 {md5(dest)})")
    return dest


COMMUNES_URL = ("https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/"
                "departements/{slug}/communes-{slug}.geojson")
DEPT_SLUGS = ["75-paris", "77-seine-et-marne", "78-yvelines", "91-essonne", "92-hauts-de-seine",
              "93-seine-saint-denis", "94-val-de-marne", "95-val-d-oise"]
COMMUNES_PATH = REF_DIR / "communes_idf.csv"


def collect_communes(force: bool = False) -> Path | None:
    """Référentiel des communes d'Île-de-France (code INSEE, nom, département), extrait des fichiers GeoJSON
    communaux (données IGN/Insee). Sert à prepare.py pour retrouver le département d'un lieu Adzuna
    (« Montévrain, Lagny-sur-Marne » → 77). Seules les propriétés sont gardées : fichier CSV de ~40 Ko."""
    if COMMUNES_PATH.exists() and not force:
        log.info(f"Communes : déjà présent (MD5 {md5(COMMUNES_PATH)}) — ignoré")
        return COMMUNES_PATH
    lignes = []
    with requests.Session() as s:
        for slug in DEPT_SLUGS:
            feats = get_with_retry(s, COMMUNES_URL.format(slug=slug), timeout=60).json()["features"]
            lignes += [(f["properties"]["code"], f["properties"]["nom"], f["properties"]["code"][:2]) for f in feats]
    if len(lignes) < 1200 or {c[2] for c in lignes} != set(DEPARTEMENTS_IDF):
        raise ValueError(f"Référentiel communes incomplet : {len(lignes)} communes")
    REF_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(lignes, columns=["code_insee", "nom", "code_dept"]).sort_values("code_insee") \
        .to_csv(COMMUNES_PATH, index=False, encoding="utf-8")
    log.info(f"Communes : {len(lignes)} communes IDF → {COMMUNES_PATH.name} (MD5 {md5(COMMUNES_PATH)})")
    return COMMUNES_PATH


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="PPMT — collecte C1")
    p.add_argument("--source", choices=["all", "ft", "adzuna", "geojson", "communes"], default="all")
    p.add_argument("--force", action="store_true", help="re-télécharge même si déjà collecté")
    args = p.parse_args(argv)
    load_dotenv(ROOT / ".env")
    log_file = setup_logging()
    log.info("=== PPMT — Collecte C1 ===")
    etapes = {"ft": collect_france_travail, "adzuna": collect_adzuna, "geojson": collect_geojson,
              "communes": collect_communes}
    a_lancer = etapes if args.source == "all" else {args.source: etapes[args.source]}
    echecs = 0
    for nom, fn in a_lancer.items():
        try:
            if fn(force=args.force) is None:
                echecs += 1
        except Exception as e:  # une source en échec n'arrête pas les autres
            log.error(f"{nom} : échec — {e}")
            echecs += 1
    log.info(f"Terminé — {len(a_lancer) - echecs}/{len(a_lancer)} sources OK — journal : {log_file.name}")
    return 1 if echecs else 0   # code retour non nul → exploitable par cron / CI


if __name__ == "__main__":
    sys.exit(main())
