"""Tests unitaires et d'intégration PPMT — lancer avec : pytest tests/ -v"""
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import collect  # noqa: E402
import prepare  # noqa: E402
import store  # noqa: E402

DB = ROOT / "data" / "ppmt.db"
API_KEY = "ppmt-demo-2026"


# ═══════════════════════════════════════════════ C1 — collecte (API simulées)
class FakeResp:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code, self._payload, self.headers = status, payload or {}, headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise collect.requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(params)
        return self.responses.pop(0)


def test_ft_pagination_s_arrete_a_la_derniere_page():
    pleine = FakeResp(206, {"resultats": [{"id": i} for i in range(150)]})
    partielle = FakeResp(206, {"resultats": [{"id": i} for i in range(20)]})
    s = FakeSession([pleine, pleine, partielle])
    offres = collect.ft_offres_departement(s, "token", "92")
    assert len(offres) == 320
    assert [c["range"] for c in s.calls] == ["0-149", "150-299", "300-449"]


def test_ft_pagination_plafonnee_a_3150():
    pleine = FakeResp(206, {"resultats": [{"id": i} for i in range(150)]})
    s = FakeSession([pleine] * 30)
    assert len(collect.ft_offres_departement(s, "token", "75")) == 21 * 150
    assert s.calls[-1]["range"] == "3000-3149"


def test_retry_apres_erreur_429(monkeypatch):
    monkeypatch.setattr(collect.time, "sleep", lambda s: None)
    s = FakeSession([FakeResp(429, headers={"Retry-After": "0"}), FakeResp(200, {"ok": 1})])
    assert collect.get_with_retry(s, "http://x").json() == {"ok": 1}


def test_ft_aplatir_schema():
    o = {"id": "1", "intitule": "Infirmier", "romeCode": "J1502", "lieuTravail": {"libelle": "92 - Nanterre"},
         "entreprise": {"nom": "AP-HP"}, "salaire": {"libelle": "Mensuel de 2000 Euros"}}
    ligne = collect.ft_aplatir(o)
    assert ligne["code_rome"] == "J1502" and ligne["departement"] == "92" and ligne["entreprise"] == "AP-HP"


# ═══════════════════════════════════════════════ C2/C3 — règles de nettoyage
@pytest.mark.parametrize("val,attendu", [(15, 27300), (2500, 30000), (42000, 42000),
                                         (500, None), (900000, None), (None, None)])
def test_normaliser_salaire_annuel(val, attendu):
    assert prepare.normaliser_salaire_annuel(val) == attendu


def test_extraire_salaire_ignore_nombre_de_mois():
    assert prepare.extraire_salaire("Mensuel de 2000.0 Euros à 2500.0 Euros sur 12 mois") == (2000.0, 2500.0)
    assert prepare.extraire_salaire(None) == (None, None)


@pytest.mark.parametrize("lieu,code", [("92 - Nanterre", "92"), ("Hauts-de-Seine (92)", "92"), ("Paris", "75"),
                                       ("Fontenay-sous-Bois, Nogent-sur-Marne", "94"), ("Montévrain, Lagny-sur-Marne", "77"),
                                       ("Viry-Châtillon, Evry", "91"), ("Le Mesnil-Saint-Denis", "78"),
                                       ("Thiais, L'Haÿ-les-Roses", "94"), ("Evry-Courcouronnes", "91"),
                                       ("La Défense", "92"), ("Mouvaux, Nord", None), ("Ile-de-France, France", None)])
def test_code_departement(lieu, code):
    assert prepare.code_departement(lieu) == code


@pytest.mark.parametrize("brut,norm", [("CDD - 12 Mois", "CDD"), ("Intérim - 1 Mois", "Intérim"),
                                       ("CDI", "CDI"), ("permanent", "CDI"), ("Temps plein", "Non renseigné")])
def test_normaliser_contrat(brut, norm):
    assert prepare.normaliser_contrat(brut) == norm


def test_referentiel_communes_complet():
    idx = prepare.index_communes()
    assert len(idx) > 1200 and set(idx.values()) == {"75", "77", "78", "91", "92", "93", "94", "95"}
    assert "marolles en brie" not in idx          # nom ambigu (77 et 94) : écarté


def test_pseudonymisation_rgpd():
    txt = prepare.pseudonymiser("Contact : jean.dupont@acme.fr ou 06 12 34 56 78")
    assert "@" not in txt and "06 12" not in txt and "[email]" in txt and "[tel]" in txt


def test_deduplication_priorite_france_travail():
    df = pd.DataFrame({"source": ["adzuna", "france_travail"], "url": [None, None],
                       "hash_offre": ["h", "h"]})
    out, stats = prepare.dedoublonner(df)
    assert len(out) == 1 and out.loc[0, "source"] == "france_travail"


def test_imputation_salaire_cascade_de_medianes():
    df = pd.DataFrame({
        "code_rome": ["A1101"] * 4 + ["A1101"] * 4 + ["A1102", "B2202", None],
        "code_dept": ["93"] * 4 + ["75"] * 4 + ["75", "75", "91"],
        "salaire_moyen": [20000, 30000, 100000, None,   40000, 42000, 44000, None,   None, None, None]})
    out, st = prepare.imputer_salaires(df, min_obs=3)
    assert out.loc[3, "salaire_moyen"] == 30000 and out.loc[3, "salaire_source"] == "médiane métier × département"
    assert out.loc[7, "salaire_moyen"] == 42000                        # médiane du métier dans le 75
    assert out.loc[8, "salaire_source"] == "médiane domaine"           # A11 : même domaine ROME
    assert out.loc[9, "salaire_source"] == "médiane département"       # B2202 inconnu → médiane du 75
    assert out.loc[10, "salaire_source"] == "médiane régionale"        # ni métier ni département connus
    assert list(out["salaire_impute"]) == [0, 0, 0, 1, 0, 0, 0, 1, 1, 1, 1]


def test_rome_adzuna_par_intitule_france_travail():
    df = pd.DataFrame({"source": ["france_travail"] * 3 + ["adzuna", "adzuna", "adzuna"],
                       "titre": ["Comptable", "Comptable", "COMPTABLE", "Comptable", "Serveur", "Plombier"],
                       "code_rome": ["M1203", "M1203", "M1203", "G1401", "G1803", None]})
    out, st = prepare.affiner_rome_adzuna(df)
    assert out.loc[3, "code_rome"] == "M1203" and out.loc[3, "rome_source"] == "intitule"   # corrige la catégorie
    assert out.loc[4, "rome_source"] == "categorie" and out.loc[5, "rome_source"] is None
    assert st == {"intitule": 1, "categorie": 1, "sans_code": 1}


def test_mediane():
    assert store.mediane([3, 1, 2]) == 2 and store.mediane([1, 2, 3, 100]) == 2.5 and store.mediane([]) is None


def test_titre_sans_mention_hf():
    assert prepare.nettoyer_titre("  Aide-soignant   (H/F) ") == "Aide-soignant"


# ═══════════════════════════════════════════════ C4 — base de données
@pytest.fixture(scope="module")
def conn():
    if not DB.exists():
        pytest.skip("Base absente — lancer python run_pipeline.py")
    c = sqlite3.connect(DB)
    c.execute("PRAGMA foreign_keys = ON")
    yield c
    c.close()


def test_tables_presentes(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"departements", "metiers_rome", "offres", "indicateurs_tension"} <= tables


def test_integrite_referentielle(conn):
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_departements_geolocalises(conn):
    # coordonnées calculées depuis le GeoJSON (C1) : Paris au centre, Seine-et-Marne à l'est, Yvelines à l'ouest
    geo = {c: (lat, lon) for c, lat, lon in conn.execute("SELECT code_dept, latitude, longitude FROM departements")}
    assert all(v[0] is not None for v in geo.values())
    assert geo["77"][1] > geo["75"][1] > geo["78"][1]
    assert abs(geo["75"][0] - 48.86) < 0.05 and abs(geo["75"][1] - 2.34) < 0.05


def test_centre_et_surface_carre():
    lat, lon, km2 = store.centre_et_surface([(2.0, 48.0), (2.1, 48.0), (2.1, 48.1), (2.0, 48.1)])
    assert abs(lat - 48.05) < 1e-9 and abs(lon - 2.05) < 1e-9 and 70 < km2 < 90


def test_aucun_doublon(conn):
    assert conn.execute("SELECT COUNT(*) - COUNT(DISTINCT hash_offre) FROM offres").fetchone()[0] == 0


def test_perimetre_ile_de_france(conn):
    hors = conn.execute("SELECT COUNT(*) FROM offres WHERE code_dept NOT IN "
                        "('75','77','78','91','92','93','94','95')").fetchone()[0]
    assert hors == 0


def test_aucune_donnee_personnelle(conn):
    # aucune adresse e-mail ni numéro de téléphone en clair dans les textes libres
    textes = [r[0] for r in conn.execute("SELECT description FROM offres WHERE description LIKE '%@%' "
                                         "OR description GLOB '*[0-9][0-9]*[0-9][0-9]*'")]
    assert not any(prepare.RE_EMAIL.search(t) or prepare.RE_TEL.search(t) for t in textes)


def test_aucun_salaire_vide_et_indicateur_coherent(conn):
    assert conn.execute("SELECT COUNT(*) FROM offres WHERE salaire_moyen IS NULL").fetchone()[0] == 0
    # une valeur imputée n'a jamais de fourchette min/max
    assert conn.execute("SELECT COUNT(*) FROM offres WHERE salaire_impute = 1 "
                        "AND (salaire_min IS NOT NULL OR salaire_max IS NOT NULL)").fetchone()[0] == 0


def test_vue_analyse_dates(conn):
    r = conn.execute("SELECT MIN(age_jours), MAX(annee), SUM(is_recente) FROM v_offres_analyse").fetchone()
    assert r[0] == 0 and r[1] == 2026 and r[2] > 0


def test_salaire_min_inferieur_max(conn):
    assert conn.execute("SELECT COUNT(*) FROM offres WHERE salaire_min > salaire_max").fetchone()[0] == 0


def test_contrainte_check_rejette_salaire_aberrant(tmp_path):
    c = sqlite3.connect(tmp_path / "t.db")
    store.creer_schema(c)
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO offres (source, hash_offre, titre, salaire_min, date_import) "
                  "VALUES ('adzuna', 'x', 'Test', 5, '2026')")


def test_indicateur_moyen_vaut_100(conn):
    moyenne = conn.execute("SELECT AVG(indice_tension) FROM indicateurs_tension").fetchone()[0]
    assert abs(moyenne - 100) < 0.5


def test_statuts_coherents_avec_seuils(conn):
    incoherents = conn.execute("""SELECT COUNT(*) FROM indicateurs_tension WHERE
        (statut='TRES EN TENSION' AND indice_tension <= 150) OR
        (statut='SATURE' AND indice_tension > 50)""").fetchone()[0]
    assert incoherents == 0


# ═══════════════════════════════════════════════ C5 — API
@pytest.fixture(scope="module")
def client():
    if not DB.exists():
        pytest.skip("Base absente")
    import os
    os.environ.setdefault("PPMT_API_KEY", API_KEY)   # clé de test : l'API refuse de démarrer sans clé
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


H = {"X-API-Key": API_KEY}


def test_health_public(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["nb_offres"] > 0


def test_cle_api_obligatoire(client):
    assert client.get("/offres").status_code == 403
    assert client.get("/offres", headers={"X-API-Key": "mauvaise"}).status_code == 403


def test_stats_departements_avec_coordonnees(client):
    d = client.get("/stats/departements", headers=H).json()
    assert len(d) == 8 and all(x["latitude"] and x["longitude"] and x["offres_pour_100_km2"] for x in d)


def test_offres_filtre_departement(client):
    r = client.get("/offres", params={"departement": "93", "limit": 20}, headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] > 0 and len(body["resultats"]) == 20
    assert all(o["code_dept"] == "93" for o in body["resultats"])


def test_parametre_invalide_422(client):
    assert client.get("/offres", params={"departement": "13"}, headers=H).status_code == 422
    assert client.get("/offres", params={"limit": 5000}, headers=H).status_code == 422


def test_pagination(client):
    p1 = client.get("/offres", params={"limit": 5, "offset": 0}, headers=H).json()["resultats"]
    p2 = client.get("/offres", params={"limit": 5, "offset": 5}, headers=H).json()["resultats"]
    assert not {o["id"] for o in p1} & {o["id"] for o in p2}


def test_metiers_tries_par_tension(client):
    m = client.get("/metiers", params={"limit": 10}, headers=H).json()
    assert [x["indice_tension"] for x in m] == sorted((x["indice_tension"] for x in m), reverse=True)


def test_fiche_metier_et_404(client):
    r = client.get("/metiers/J1502", headers=H)
    assert r.status_code == 200 and len(r.json()["repartition_departements"]) == 8
    assert client.get("/metiers/Z9999", headers=H).status_code == 422
    assert client.get("/metiers/A0000", headers=H).status_code == 404
    assert client.get("/offres/999999999", headers=H).status_code == 404


def test_api_lecture_seule(client):
    assert client.post("/offres", headers=H).status_code == 405
