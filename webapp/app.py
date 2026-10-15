import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import sqlite3
from datetime import datetime
import subprocess
from collections import Counter

st.set_page_config(
    page_title="PPMT - Metiers en Tension IDF",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
.kpi-card { background:white; border-radius:10px; padding:18px 20px; border-left:5px solid #003189; box-shadow:0 2px 8px rgba(0,0,0,0.08); margin-bottom:8px; }
.kpi-card.red { border-left-color:#C53030; }
.kpi-card.green { border-left-color:#38A169; }
.kpi-card.orange { border-left-color:#DD6B20; }
.kpi-card.purple { border-left-color:#805AD5; }
.kpi-val { font-size:1.9rem; font-weight:800; color:#1A202C; margin:0; line-height:1.1; }
.kpi-label { font-size:0.82rem; color:#718096; margin:4px 0 0 0; }
.kpi-sub { font-size:0.75rem; color:#A0AEC0; margin:2px 0 0 0; }
.intro-box { background:linear-gradient(135deg,#003189 0%,#1a4aa0 100%); color:white; border-radius:12px; padding:22px 28px; margin-bottom:18px; }
.stat-badge { display:inline-block; background:#EBF8FF; color:#003189; border-radius:6px; padding:3px 10px; font-size:0.82rem; font-weight:600; margin:3px 4px 3px 0; }
.stat-badge.red { background:#FFF5F5; color:#C53030; }
.stat-badge.green { background:#F0FFF4; color:#276749; }
.ml-card { background:white; border-radius:10px; padding:16px; border:1px solid #E2E8F0; box-shadow:0 2px 6px rgba(0,0,0,0.06); text-align:center; }
.ml-val { font-size:1.7rem; font-weight:800; margin:0; line-height:1.1; }
.ml-label { color:#718096; font-size:0.82rem; margin:4px 0 0 0; }
.section-note { background:#EBF8FF; border-left:3px solid #003189; padding:8px 14px; border-radius:0 6px 6px 0; font-size:0.85rem; color:#2D3748; margin-bottom:12px; }
.footer { text-align:center; padding:18px; color:#718096; font-size:0.78rem; border-top:1px solid #E2E8F0; margin-top:40px; }
</style>
""", unsafe_allow_html=True)

def fr(x, dec=0):
    """62435 -> '62 435' ; format français pour l'affichage."""
    try:
        return f"{x:,.{dec}f}".replace(",", " ").replace(".", ",")
    except (TypeError, ValueError):
        return str(x)

import plotly.io as pio
pio.templates["ppmt"] = go.layout.Template(layout=dict(separators=", "))
pio.templates.default = "plotly+ppmt"      # séparateurs français dans tous les graphiques

# ─── CHARGEMENT (V2 : une seule source de vérité, la base data/ppmt.db) ─────
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "ppmt.db"

DOMAINES_ROME = {"A": "Agriculture, pêche", "B": "Arts, artisanat d'art", "C": "Banque, assurance, immobilier",
    "D": "Commerce, vente", "E": "Communication, médias", "F": "BTP", "G": "Hôtellerie, restauration, tourisme",
    "H": "Industrie", "I": "Installation, maintenance", "J": "Santé", "K": "Services à la personne",
    "L": "Spectacle", "M": "Support à l'entreprise", "N": "Transport, logistique"}

def _lire(sql):
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as conn:
        return pd.read_sql(sql, conn)

@st.cache_data
def load_offres():
    """Offres dédoublonnées (store.py) avec les colonnes d'analyse de la vue v_offres_analyse."""
    df = _lire("""SELECT v.*, d.nom AS nom_dept FROM v_offres_analyse v
                  LEFT JOIN departements d USING (code_dept)""")
    df["departement"] = df["nom_dept"] + " (" + df["code_dept"] + ")"
    # Secteur commun aux deux sources : le grand domaine du code ROME (France Travail publie une
    # appellation par offre, Adzuna ses propres catégories : elles ne sont pas comparables).
    df["categorie_source"] = df["categorie"]
    df["categorie"] = df["code_rome"].str[0].map(DOMAINES_ROME).fillna("Non classe")
    # Analyses de salaires : uniquement les salaires AFFICHÉS (les salaires complétés par médiane
    # servent à la complétude de la base, pas aux statistiques — pas de calcul circulaire).
    df["salaire_moyen"] = pd.to_numeric(df["salaire_moyen"], errors="coerce").where(df["salaire_impute"] == 0)
    df["date_publication"] = pd.to_datetime(df["date_publication"], errors="coerce")
    return df

@st.cache_data
def load_adzuna():
    d = load_offres()
    return d[d["source"] == "adzuna"].copy()

@st.cache_data
def load_ft():
    d = load_offres()
    return d[d["source"] == "france_travail"].copy()

@st.cache_data
def load_geojson():
    """Contours des 8 departements (fichier de reference collecte par src/collect.py)."""
    import json
    try:
        with open(ROOT / "data" / "ref" / "departements_idf.geojson", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def code_dept_depuis_libelle(lib):
    """'Hauts-de-Seine (92)' -> '92' ; 'Paris' -> '75' ; libelle sans departement -> None."""
    import re
    lib = str(lib)
    m = re.search(r"\((75|77|78|91|92|93|94|95)\)", lib)
    if m:
        return m.group(1)
    return "75" if lib.strip().lower() == "paris" else None

@st.cache_data
def load_itm():
    """Indicateurs par métier calculés en SQL par store.py (table indicateurs_tension)."""
    df = _lire("""
        SELECT i.*, m.libelle,
               i.salaire_median AS salaire_moyen,
               (SELECT AVG(o.contrat = 'CDD') * 100 FROM offres o WHERE o.code_rome = i.code_rome) AS pct_cdd,
               (SELECT NULL FROM offres o WHERE o.code_rome = i.code_rome
                  AND o.source = 'france_travail' AND o.salaire_impute = 0) AS salaire_moyen_ft,
               (SELECT NULL FROM offres o WHERE o.code_rome = i.code_rome
                  AND o.source = 'adzuna' AND o.salaire_impute = 0) AS salaire_moyen_adzuna
        FROM indicateurs_tension i JOIN metiers_rome m USING (code_rome)""")
    df["pct_cdi"] = df["part_cdi"]
    df["domaine"] = df["code_rome"].str[0].map(DOMAINES_ROME).fillna("Autre")
    sal = load_offres().dropna(subset=["salaire_moyen"]).groupby(["code_rome", "source"])["salaire_moyen"].median().unstack()
    df["salaire_moyen_ft"] = df["code_rome"].map(sal.get("france_travail", pd.Series(dtype=float)))
    df["salaire_moyen_adzuna"] = df["code_rome"].map(sal.get("adzuna", pd.Series(dtype=float)))
    return df

def nom_court(lib):
    """'Conseiller / Conseillere immobilier' -> 'Conseiller immobilier'."""
    lib = str(lib)
    if "/" not in lib:
        return lib[:32]
    gauche, droite = [x.strip() for x in lib.split("/", 1)]
    if " " in gauche:
        return gauche[:32]
    reste = droite.split(" ", 1)[1] if " " in droite else ""
    return (gauche + " " + reste).strip()[:32]

@st.cache_data
def load_predictions():
    """Modèle V2 (XGBoost, notebook/ml_tests.py) : probabilité « en tension » estimée à partir du seul
    profil des offres, en validation croisée (chaque métier est prédit par un modèle qui ne l'a pas vu)."""
    try:
        p = pd.read_csv(ROOT / "data" / "predictions_tension.csv")
    except Exception:
        return pd.DataFrame()
    itm = load_itm()[["code_rome", "libelle", "pct_cdi", "pct_cdd", "nb_offres_total"]]
    p = p.merge(itm, on="code_rome", how="left")
    p["en_tension_reel"] = p["indice_tension"] > 100
    p["en_tension_predit"] = p["proba_tension"] >= 0.5
    return p

@st.cache_data
def load_ml_resultats():
    import json
    try:
        return json.loads((ROOT / "data" / "ml_resultats.json").read_text(encoding="utf-8"))
    except Exception:
        return {}

@st.cache_data
def extract_skills(df, col="description"):
    hard = ["python","sql","excel","power bi","tableau","machine learning","deep learning",
        "tensorflow","pytorch","scikit","pandas","numpy","spark","hadoop","aws","azure","gcp",
        "docker","kubernetes","git","api","java","javascript","react","angular","node",
        "scala","airflow","dbt","looker","snowflake","databricks","nlp","sap","salesforce"]
    soft = ["communication","autonomie","rigueur","organisation","travail en equipe",
        "adaptabilite","leadership","creativite","gestion de projet","analytique",
        "problem solving","esprit d analyse","initiative","polyvalence","relationnel",
        "pedagogie","negociation","curiosite","proactivite"]
    tech = ["llm","gpt","blockchain","iot","devops","mlops","data lake","data mesh",
        "streaming","temps reel","automatisation","rpa","cybersecurite",
        "microservices","api rest","graphql","no-code","low-code","intelligence artificielle"]
    formations_quali = ["bac+2","bac+3","bac+5","master","licence","bts","dut","ingenieur","mba","doctorat"]
    formations_type = ["alternance","apprentissage","certification","diplome"]
    import re, unicodedata
    texts = df[col].dropna().str.lower().str.cat(sep=" ")
    texts = unicodedata.normalize("NFKD", texts).encode("ascii", "ignore").decode()   # é -> e
    def count_kw(kw_list):
        """Mots entiers uniquement : « api » n'est plus compté dans « rapide », « mba » dans « embauche »."""
        res = {}
        for kw in kw_list:
            nb = len(re.findall(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", texts))
            if nb > 0:
                res[kw] = nb
        return res
    return {
        "hard": count_kw(hard),
        "soft": count_kw(soft),
        "tech": count_kw(tech),
        "formations_quali": count_kw(formations_quali),
        "formations_type": count_kw(formations_type)
    }

def merge_skills(s1, s2, key):
    return dict((Counter(s1.get(key, {})) + Counter(s2.get(key, {}))).most_common(15))

@st.cache_data
def extract_skills_tension(df_az, df_ft, df_itm):
    romes = df_itm[df_itm["statut"]=="TRES EN TENSION"]["code_rome"].tolist()
    df_az_t = df_az[df_az["code_rome"].isin(romes)] if "code_rome" in df_az.columns else df_az
    df_ft_t = df_ft[df_ft["code_rome"].isin(romes)] if "code_rome" in df_ft.columns else df_ft
    sk_az = extract_skills(df_az_t) if len(df_az_t)>0 else {}
    sk_ft = extract_skills(df_ft_t) if len(df_ft_t)>0 else {}
    return sk_az, sk_ft

# Contrats déjà normalisés par src/prepare.py (7 catégories) : simple mise en forme des libellés
LIBELLES_CONTRAT = {"CDI": "CDI", "CDD": "CDD", "Intérim": "Interim", "Alternance": "Alternance",
                    "Libéral": "Profession liberale", "Autre": "Autre", "Non renseigné": "Non renseigne"}

# ─── DONNEES ────────────────────────────────────────────────
df_az = load_adzuna()
df_ft = load_ft()
df_pred = load_predictions()
df_itm = load_itm()

df_az["contrat_norm"] = df_az["contrat"].map(LIBELLES_CONTRAT).fillna("Autre")
df_ft["contrat_norm"] = df_ft["contrat"].map(LIBELLES_CONTRAT).fillna("Autre")
ml = load_ml_resultats()
NB_OFFRES = len(df_az) + len(df_ft)
NB_METIERS = len(df_itm)
NB_TRES = int((df_itm["statut"] == "TRES EN TENSION").sum())
ROMES_TRES = set(df_itm.loc[df_itm["statut"] == "TRES EN TENSION", "code_rome"])
NB_OFFRES_TRES = int(df_az["code_rome"].isin(ROMES_TRES).sum() + df_ft["code_rome"].isin(ROMES_TRES).sum())
AUC_ML = ml.get("v2", {}).get("resultats_cv5", {}).get("XGBoost", {}).get("roc_auc", 0.885)

df_az["source"] = "Adzuna"
df_ft["source"] = "France Travail"
df_all = pd.concat([df_az, df_ft], ignore_index=True)

# ─── SIDEBAR ─────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## PPMT")
    st.markdown("*Metiers en Tension IDF*")
    st.markdown("---")
    st.markdown("### Filtres")

    depts = ["Tous"] + sorted([d for d in df_all["departement"].dropna().unique().tolist() if d])
    filtre_dept = st.selectbox("Departement", depts)

    contrats_dispo = ["Tous","CDI","CDD","Interim","Alternance","Profession liberale","Autre"]
    filtre_contrat = st.selectbox("Type de contrat", contrats_dispo)

    secteurs = ["Tous"] + sorted([s for s in df_all["categorie"].dropna().unique().tolist() if s not in ["Unknown","","Non classe"]])
    filtre_secteur = st.selectbox("Secteur", secteurs)

    st.markdown("---")
    st.caption("Base figée pour la soutenance (collecte du 6 octobre 2026)")

    st.markdown("---")
    st.markdown(f"""
    <div style="font-size:0.75rem;color:#718096;line-height:1.9">
    <b>Sources</b><br>Adzuna API · France Travail API<br><br>
    <b>Base</b><br>data/ppmt.db (pipeline V2)<br><br>
    <b>Perimetre</b><br>Ile-de-France (8 depts)<br><br>
    <b>Modele ML (experimental)</b><br>XGBoost · AUC {str(round(AUC_ML, 2)).replace('.', ',')}
    </div>
    """, unsafe_allow_html=True)

# ─── FILTRES ────────────────────────────────────────────────
def apply_filters(df, avec_dept=True):
    d = df.copy()
    if avec_dept and filtre_dept != "Tous" and "departement" in d.columns:
        d = d[d["departement"]==filtre_dept]
    if filtre_contrat != "Tous" and "contrat_norm" in d.columns:
        d = d[d["contrat_norm"]==filtre_contrat]
    if filtre_secteur != "Tous" and "categorie" in d.columns:
        d = d[d["categorie"]==filtre_secteur]
    return d

df_filtered = apply_filters(df_all)
df_sans_dept = apply_filters(df_all, avec_dept=False)   # pour comparer les departements entre eux
df_az_f = apply_filters(df_az)
df_ft_f = apply_filters(df_ft)

# ─── HEADER ──────────────────────────────────────────────────
st.markdown(f"""
<div class="intro-box">
<h2 style="margin:0 0 6px 0;font-size:1.55rem">Plateforme Predictive des Metiers en Tension — IDF</h2>
<p style="margin:0;opacity:0.92;font-size:0.92rem">
PPMT identifie les metiers en tension en Ile-de-France a partir des donnees <b>Adzuna</b> et <b>France Travail</b>.
L'indice de tension (ITM) compare le volume d'offres de chaque metier (code ROME) a la moyenne : 100 = metier moyen. Un modele ML experimental (XGBoost, AUC {fr(ml.get('v2',{}).get('resultats_cv5',{}).get('XGBoost',{}).get('roc_auc',0.885), 2)}) repere les metiers en tension a partir du profil de leurs offres.
Utilisez les filtres a gauche pour explorer par departement, contrat ou secteur.
</p>
<div style="margin-top:12px">
<span class="stat-badge">{fr(NB_OFFRES)} offres</span>
<span class="stat-badge">{fr(NB_METIERS)} metiers analyses</span>
<span class="stat-badge">8 departements IDF</span>
<span class="stat-badge red">{NB_TRES} TRES EN TENSION</span>
<span class="stat-badge green">Sources : Adzuna + France Travail</span>
</div>
</div>
""", unsafe_allow_html=True)

st.caption("Les filtres s'appliquent aux graphiques d'offres (volumes, contrats, salaires, carte). "
           "Les indicateurs par metier (indice de tension, statuts, Top 10, modele ML) sont calcules sur toute l'Ile-de-France.")
tab1,tab2,tab3,tab4,tab5,tab6 = st.tabs([
    "Vue d ensemble",
    "Secteurs",
    "Competences et Tech",
    "Formations et Recrutement",
    "Metiers en Tension",
    "Salaires"
])

# ══════════════════════════════════════════════════════════════
# TAB 1 — VUE D'ENSEMBLE
# ══════════════════════════════════════════════════════════════
with tab1:
    nb_az = len(df_az_f)
    nb_ft = len(df_ft_f)
    nb_total = nb_az + nb_ft
    nb_secteurs = df_filtered["code_rome"].nunique()
    sal_az = df_az_f["salaire_moyen"].median() if "salaire_moyen" in df_az_f.columns else 0
    sal_ft = df_ft_f["salaire_moyen"].median() if "salaire_moyen" in df_ft_f.columns else 0
    tres = NB_TRES

    c1,c2,c3,c4,c5 = st.columns(5)
    with c1:
        st.markdown(f'<div class="kpi-card"><p class="kpi-val">{fr(nb_total)}</p><p class="kpi-label">Total offres (filtre)</p><p class="kpi-sub">AZ: {fr(nb_az)} · FT: {fr(nb_ft)}</p></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="kpi-card green"><p class="kpi-val">{fr(nb_secteurs)}</p><p class="kpi-label">Metiers (codes ROME)</p><p class="kpi-sub">repartis en 14 domaines</p></div>', unsafe_allow_html=True)
    with c3:
        sal_str = f"{fr(sal_az)} EUR" if sal_az and sal_az>0 else "N/A"
        st.markdown(f'<div class="kpi-card orange"><p class="kpi-val">{sal_str}</p><p class="kpi-label">Salaire median Adzuna</p><p class="kpi-sub">Salaires affiches · annuel brut</p></div>', unsafe_allow_html=True)
    with c4:
        sal_ft_str = f"{fr(sal_ft)} EUR" if sal_ft and sal_ft>0 else "N/A"
        st.markdown(f'<div class="kpi-card purple"><p class="kpi-val">{sal_ft_str}</p><p class="kpi-label">Salaire median FT</p><p class="kpi-sub">Salaires affiches · annuel brut</p></div>', unsafe_allow_html=True)
    with c5:
        st.markdown(f'<div class="kpi-card red"><p class="kpi-val">{tres}</p><p class="kpi-label">Metiers TRES EN TENSION</p><p class="kpi-sub">Sur {fr(NB_METIERS)} analyses</p></div>', unsafe_allow_html=True)

    st.divider()
    col1,col2 = st.columns(2)
    with col1:
        st.subheader("Repartition des statuts ITM")
        st.markdown(f'<div class="section-note">Table <b>indicateurs_tension</b> (base V2, calcul SQL) — {fr(NB_METIERS)} metiers, Adzuna + France Travail. Seuils : SATURE &lt;50 · EQUILIBRE 50-100 · EN TENSION 100-150 · TRES EN TENSION &gt;150</div>', unsafe_allow_html=True)
        if len(df_itm)>0:
            df_s = df_itm["statut"].value_counts().reset_index()
            df_s.columns = ["statut","nb"]
            ordre = ["SATURE","EQUILIBRE","EN TENSION","TRES EN TENSION"]
            df_s["statut"] = pd.Categorical(df_s["statut"], categories=ordre, ordered=True)
            df_s = df_s.sort_values("statut")
            if len(df_s) > 0:
                fig = px.bar(df_s, x="statut", y="nb", color="statut",
                    color_discrete_map={"TRES EN TENSION":"#C53030","EN TENSION":"#DD6B20","EQUILIBRE":"#38A169","SATURE":"#2B6CB0"},
                    text="nb",
                    labels={"statut":"Statut ITM","nb":"Nombre de metiers"},
                    category_orders={"statut":ordre})
                fig.update_traces(textposition="outside")
                fig.update_layout(height=380, showlegend=True, legend_title="Statut ITM",
                    xaxis_title="Statut", yaxis_title="Nombre de metiers",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                st.plotly_chart(fig, width="stretch")
            else:
                st.info("Aucune donnee pour cette combinaison de filtres.")

    with col2:
        st.subheader("Top 10 metiers en tension (ITM IDF)")
        st.markdown('<div class="section-note">Indice de tension = offres du metier / offres d un metier moyen x 100. Source : table <b>indicateurs_tension</b> (Adzuna + France Travail)</div>', unsafe_allow_html=True)
        if len(df_itm)>0:
            top10 = df_itm[df_itm["statut"]=="TRES EN TENSION"].sort_values("indice_tension",ascending=False).head(10).copy()
            top10["metier"] = top10["code_rome"] + " · " + top10["libelle"].apply(nom_court)
            top10["etiquette"] = top10.apply(lambda r: fr(int(r["indice_tension"])) + "  (" + fr(r["nb_offres_total"]) + " offres)", axis=1)
            fig2 = go.Figure(go.Bar(x=top10["indice_tension"], y=top10["metier"], orientation="h",
                marker_color="#C2410C", text=top10["etiquette"], textposition="outside", cliponaxis=False))
            fig2.update_layout(height=420, showlegend=False, plot_bgcolor="white",
                xaxis=dict(title="Indice de tension (100 = metier moyen)", range=[0, top10["indice_tension"].max() * 1.35]),
                yaxis=dict(title="", autorange="reversed"), margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig2, width="stretch", key="top10_top10")

    st.divider()
    st.subheader("Offres en base — Adzuna et toutes sources par departement")
    MOIS_FR = ["janvier","fevrier","mars","avril","mai","juin","juillet","aout","septembre","octobre","novembre","decembre"]
    _series = [d["date_publication"] for d in (df_az, df_ft) if "date_publication" in d.columns]
    _mois_dispo = sorted(pd.concat(_series, ignore_index=True).dropna().dt.strftime("%Y-%m").unique(), reverse=True)[:12] if _series else []
    if _mois_dispo:
        _choix = {"Toutes les offres en base": "tous"}
        _choix.update({f"{MOIS_FR[int(m[5:7])-1]} {m[:4]}": m for m in _mois_dispo})
        _mois_sel = _choix[st.selectbox("Periode de publication", list(_choix), index=0, key="mois_pub_compare")]
        if _mois_sel == "tous":
            _annee, _mois, lib_mois = None, None, "toute la base"
        else:
            _annee, _mois = int(_mois_sel[:4]), int(_mois_sel[5:7])
            lib_mois = f"{MOIS_FR[_mois-1]} {_annee}"
    else:
        _annee, _mois, lib_mois = 0, 0, "-"
    def _periode(d):     # filtres de la barre laterale + periode choisie
        if _annee is None:
            return d
        return d[(d["date_publication"].dt.year==_annee)&(d["date_publication"].dt.month==_mois)]
    df_az_mois = _periode(df_az_f)
    df_ft_mois = _periode(df_ft_f)
    df_tout_mois = pd.concat([df_az_mois, df_ft_mois], ignore_index=True)

    st.markdown(f'<div class="section-note">Offres ({lib_mois}, filtres appliques), apres dedoublonnage : {fr(len(df_tout_mois))} offres. Adzuna : {fr(len(df_az_mois))} · France Travail : {fr(len(df_ft_mois))}. Les API ne renvoient que les offres encore actives a la date de collecte.</div>', unsafe_allow_html=True)
    if len(df_az_mois)>0 or len(df_ft_mois)>0:
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"**Adzuna — par domaine ROME ({lib_mois})**")
            if len(df_az_mois)>0 and "categorie" in df_az_mois.columns:
                df_cat_mois = df_az_mois.groupby("categorie").size().reset_index(name="nb")
                df_cat_mois = df_cat_mois[~df_cat_mois["categorie"].isin(["Unknown","","Non classe"])].sort_values("nb",ascending=True).tail(12)
                fig_mois = px.bar(df_cat_mois, x="nb", y="categorie", orientation="h",
                    color="nb", color_continuous_scale=["#EBF8FF","#003189"], text="nb")
                fig_mois.update_traces(textposition="outside", cliponaxis=False)
                fig_mois.update_layout(height=380, showlegend=False, coloraxis_showscale=False,
                    xaxis_title="Offres", yaxis_title="")
                st.plotly_chart(fig_mois, width="stretch")
        with col_b:
            st.markdown(f"**Toutes sources — offres par departement ({lib_mois}), part du total**")
            df_comp = _periode(df_sans_dept)
            if len(df_comp)>0 and "departement" in df_comp.columns:
                df_dept_mois = df_comp.groupby("departement").size().reset_index(name="nb")
                df_dept_mois = df_dept_mois[df_dept_mois["departement"].notna()].sort_values("nb",ascending=False)
                df_dept_mois["part"] = df_dept_mois["nb"] / df_dept_mois["nb"].sum() * 100
                couleurs = ["#C53030" if (filtre_dept == "Tous" or d == filtre_dept) else "#F3C4C4" for d in df_dept_mois["departement"]]
                fig_dept = go.Figure(go.Bar(x=df_dept_mois["nb"], y=df_dept_mois["departement"], orientation="h",
                    marker_color=couleurs, cliponaxis=False, textposition="outside",
                    text=[f"{fr(n)}  ({fr(p_, 0)} %)" for n, p_ in zip(df_dept_mois["nb"], df_dept_mois["part"])]))
                fig_dept.update_layout(height=380, showlegend=False, plot_bgcolor="white",
                    xaxis=dict(title="Offres", range=[0, df_dept_mois["nb"].max() * 1.3]),
                    yaxis=dict(title="", autorange="reversed"), margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig_dept, width="stretch", key="offres_par_dept")
                if filtre_dept != "Tous":
                    st.caption(f"{filtre_dept} mis en evidence parmi les 8 departements (autres filtres appliques).")

# ══════════════════════════════════════════════════════════════
# TAB 2 — SECTEURS
# ══════════════════════════════════════════════════════════════
with tab2:
    col1,col2 = st.columns(2)
    with col1:
        st.subheader("Etat actuel — Offres par secteur")
        st.markdown('<div class="section-note">Sources combinees : Adzuna + France Travail. Filtre actif applique.</div>', unsafe_allow_html=True)
        if "categorie" in df_filtered.columns:
            df_cat = df_filtered.groupby("categorie").size().reset_index(name="nb")
            df_cat = df_cat[~df_cat["categorie"].isin(["Unknown","","Non classe"])].sort_values("nb",ascending=True).tail(15)
            if len(df_cat) > 0:
                fig = px.bar(df_cat, x="nb", y="categorie", orientation="h",
                    color="nb", color_continuous_scale=["#EBF8FF","#003189"], text="nb")
                fig.update_traces(texttemplate="%{text:,}", textposition="outside")
                fig.update_layout(height=520, showlegend=False, coloraxis_showscale=False,
                    xaxis_title="Nombre d offres", yaxis_title="")
                st.plotly_chart(fig, width="stretch")
            else:
                st.info("Aucune donnee pour cette combinaison de filtres.")

    with col2:
        st.subheader("Metiers tres en tension par domaine ROME")
        st.markdown(f'<div class="section-note">{NB_TRES} metiers TRES EN TENSION (table indicateurs_tension), regroupes par grand domaine ROME. ITM moyen par domaine.</div>', unsafe_allow_html=True)
        if len(df_itm)>0:
            tres_df = df_itm[df_itm["statut"]=="TRES EN TENSION"].copy()
            tres_df["secteur"] = tres_df["domaine"]
            df_dem = tres_df.groupby("secteur").agg(nb=("code_rome","count"),itm=("indice_tension","mean")).reset_index()
            df_dem = df_dem.sort_values("itm",ascending=True).tail(15)
            fig2 = px.bar(df_dem, x="itm", y="secteur", orientation="h",
                color="itm", color_continuous_scale=["#FFF5F5","#C53030"],
                text="nb", labels={"itm":"ITM moyen","secteur":"Secteur"})
            fig2.update_traces(texttemplate="%{text} metiers", textposition="outside")
            fig2.update_layout(height=520, showlegend=False, coloraxis_showscale=False,
                xaxis_title="Indice tension moyen", yaxis_title="")
            st.plotly_chart(fig2, width="stretch")

    st.divider()
    st.subheader("Types de contrats — Donnees consolidees Adzuna + France Travail")
    st.markdown('<div class="section-note">Contrats normalises par src/prepare.py : CDI · CDD · Interim · Alternance · Profession liberale · Autre. Adzuna ne publie pas le type de contrat (seulement le temps de travail) : ses offres sont Non renseigne.</div>', unsafe_allow_html=True)

    col_c1, col_c2 = st.columns(2)
    with col_c1:
        st.markdown("**France Travail — Contrats normalises**")
        if "contrat_norm" in df_ft.columns:
            df_co_ft = df_ft_f.groupby("contrat_norm").size().reset_index(name="nb")
            df_co_ft = df_co_ft[df_co_ft["contrat_norm"]!="Non renseigne"].sort_values("nb",ascending=False)
            colors_ct = {"CDI":"#003189","CDD":"#3182CE","Interim":"#63B3ED","Saisonnier":"#90CDF4","Alternance":"#48BB78","Profession liberale":"#9F7AEA","Autre":"#CBD5E0"}
            if len(df_co_ft) > 0:
                fig_ft_co = px.bar(df_co_ft, x="contrat_norm", y="nb", color="contrat_norm",
                    color_discrete_map=colors_ct, text="nb",
                    labels={"contrat_norm":"Type de contrat","nb":"Offres"})
                fig_ft_co.update_traces(textposition="outside")
                fig_ft_co.update_layout(height=350, showlegend=False,
                    xaxis_title="", yaxis_title="Offres France Travail")
                st.plotly_chart(fig_ft_co, width="stretch")
            else:
                st.info("Aucune donnee pour cette combinaison de filtres.")

    with col_c2:
        st.markdown("**Adzuna — Temps de travail**")
        st.caption("Adzuna ne publie pas le type de contrat, seulement le temps de travail.")
        df_tt = df_az_f["temps_travail"].fillna("Non renseigne").value_counts().reset_index()
        df_tt.columns = ["temps_travail", "nb"]
        if len(df_tt) > 0:
            fig_az_co = px.bar(df_tt, x="temps_travail", y="nb", text="nb", color_discrete_sequence=["#3182CE"],
                labels={"temps_travail": "", "nb": "Offres"})
            fig_az_co.update_traces(textposition="outside", cliponaxis=False)
            fig_az_co.update_layout(height=350, showlegend=False, xaxis_title="", yaxis_title="Offres Adzuna")
            st.plotly_chart(fig_az_co, width="stretch")
        else:
            st.info("Aucune donnee pour cette combinaison de filtres.")

# ══════════════════════════════════════════════════════════════
# TAB 3 — COMPETENCES & TECH
# ══════════════════════════════════════════════════════════════
with tab3:
    st.subheader("Competences et Technologies")
    st.markdown(f'<div class="section-note">Extraction depuis les descriptions des <b>{fr(NB_OFFRES_TRES)} offres des metiers TRES EN TENSION</b> ({NB_TRES} codes ROME). Echelle = nb occurrences. Source : Adzuna + France Travail combines.</div>', unsafe_allow_html=True)

    with st.spinner("Analyse des descriptions en cours..."):
        sk_az, sk_ft = extract_skills_tension(df_az, df_ft, df_itm)

    col1,col2 = st.columns(2)
    with col1:
        st.markdown(f"#### Hard Skills — Metiers TRES EN TENSION ({NB_TRES} metiers, {fr(NB_OFFRES_TRES)} offres)")
        hard = merge_skills(sk_az, sk_ft, "hard")
        if hard:
            df_h = pd.DataFrame(list(hard.items()),columns=["skill","nb"]).sort_values("nb")
            if len(df_h) > 0:
                fig = px.bar(df_h, x="nb", y="skill", orientation="h",
                    color="nb", color_continuous_scale=["#EBF8FF","#003189"], text="nb",
                    labels={"nb":"Occurrences dans les offres","skill":"Competence"})
                fig.update_traces(textposition="outside")
                fig.update_layout(height=520, showlegend=False, coloraxis_showscale=False,
                    xaxis_title="Nb occurrences dans les offres des metiers tres en tension", yaxis_title="")
                st.plotly_chart(fig, width="stretch")
            else:
                st.info("Aucune donnee pour cette combinaison de filtres.")

    with col2:
        st.markdown("#### Soft Skills les plus demandes")
        soft = merge_skills(sk_az, sk_ft, "soft")
        if soft:
            df_so = pd.DataFrame(list(soft.items()),columns=["skill","nb"]).sort_values("nb")
            if len(df_so) > 0:
                fig2 = px.bar(df_so, x="nb", y="skill", orientation="h",
                    color="nb", color_continuous_scale=["#F0FFF4","#38A169"], text="nb",
                    labels={"nb":"Occurrences","skill":"Competence"})
                fig2.update_traces(textposition="outside")
                fig2.update_layout(height=520, showlegend=False, coloraxis_showscale=False,
                    xaxis_title="Nb occurrences dans les offres", yaxis_title="")
                st.plotly_chart(fig2, width="stretch")
            else:
                st.info("Aucune donnee pour cette combinaison de filtres.")

    st.divider()
    tech = merge_skills(sk_az, sk_ft, "tech")
    if tech and len(tech) >= 3:
        st.markdown("#### Technologies emergentes (hors termes generiques comme 'ia' ou 'cloud')")
        st.markdown('<div class="section-note">Termes specifiques uniquement : llm, gpt, devops, mlops, data lake, streaming, rpa, blockchain, microservices... Le terme "ia" a ete exclu car trop generique et ecrase les autres resultats.</div>', unsafe_allow_html=True)
        df_t = pd.DataFrame(list(tech.items()),columns=["tech","nb"]).sort_values("nb",ascending=False)
        if len(df_t) > 0:
            fig3 = px.bar(df_t, x="nb", y="tech", orientation="h",
                color="nb", color_continuous_scale=["#FFF5F5","#C53030"], text="nb",
                labels={"nb":"Occurrences","tech":"Technologie"})
            fig3.update_traces(textposition="outside")
            fig3.update_layout(height=max(280, len(df_t)*38), showlegend=False, coloraxis_showscale=False,
                xaxis_title="Nb occurrences dans les offres", yaxis_title="")
            st.plotly_chart(fig3, width="stretch")
        else:
            st.info("Aucune donnee pour cette combinaison de filtres.")
    else:
        st.info("Donnees insuffisantes pour les technologies emergentes — les descriptions ne contiennent pas assez de termes specifiques.")

# ══════════════════════════════════════════════════════════════
# TAB 4 — FORMATIONS & RECRUTEMENT
# ══════════════════════════════════════════════════════════════
with tab4:
    st.subheader("Formations et Tendances Recrutement")

    col1,col2 = st.columns(2)
    with col1:
        st.markdown("#### Niveaux de formation requis par les employeurs")
        st.markdown('<div class="section-note"><b>Prerequis employeurs</b> — niveaux de diplome mentionnes dans les offres d emploi (bac+2, master...). Ce sont les exigences des recruteurs, pas les niveaux des candidats.</div>', unsafe_allow_html=True)
        fq = merge_skills(sk_az, sk_ft, "formations_quali")
        NIVEAUX = {"Bac+2 (BTS, DUT)": ["bac+2", "bts", "dut"],
                   "Bac+3 (licence)": ["bac+3", "licence"],
                   "Bac+5 (master, ingenieur, MBA)": ["bac+5", "master", "ingenieur", "mba"],
                   "Doctorat": ["doctorat"]}
        df_fq = pd.DataFrame({"niveau": list(NIVEAUX), "nb": [sum(fq.get(k, 0) for k in mots) for mots in NIVEAUX.values()]})
        if df_fq["nb"].sum() > 0:
            fig = px.bar(df_fq, x="niveau", y="nb", text="nb", color_discrete_sequence=["#DD6B20"],
                labels={"nb": "Occurrences", "niveau": "Niveau"})
            fig.update_traces(textposition="outside", cliponaxis=False)
            fig.update_layout(height=350, showlegend=False,
                xaxis_title="Niveau de diplome (prerequis employeur)", yaxis_title="Occurrences")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("Aucune donnee pour cette combinaison de filtres.")

    with col2:
        st.markdown("#### Modalites de formation et alternance")
        st.markdown('<div class="section-note">Modalites de recrutement mentionnees dans les offres : alternance, apprentissage, certification, diplome.</div>', unsafe_allow_html=True)
        ft_type = merge_skills(sk_az, sk_ft, "formations_type")
        if ft_type:
            df_ft2 = pd.DataFrame(list(ft_type.items()),columns=["modalite","nb"]).sort_values("nb",ascending=False)
            colors_mod = {"alternance":"#48BB78","apprentissage":"#38A169","certification":"#3182CE","diplome":"#003189"}
            if len(df_ft2) > 0:
                fig2 = px.bar(df_ft2, x="modalite", y="nb", color="modalite",
                    color_discrete_map=colors_mod, text="nb",
                    labels={"modalite":"Modalite","nb":"Occurrences"})
                fig2.update_traces(textposition="outside")
                fig2.update_layout(height=350, showlegend=False,
                    xaxis_title="", yaxis_title="Occurrences dans les offres")
                st.plotly_chart(fig2, width="stretch")
            else:
                st.info("Aucune donnee pour cette combinaison de filtres.")

    st.divider()
    col3,col4 = st.columns(2)
    with col3:
        st.markdown("#### Part CDI vs CDD — Top 10 metiers en tension")
        st.markdown('<div class="section-note">Source : table <b>indicateurs_tension</b> (part de CDI) et offres (part de CDD). Top 10 metiers TRES EN TENSION.</div>', unsafe_allow_html=True)
        if len(df_itm)>0:
            top10_cdi = df_itm[df_itm["statut"]=="TRES EN TENSION"].sort_values("indice_tension",ascending=False).head(10)
            fig3 = go.Figure()
            fig3.add_trace(go.Bar(
                name="CDI", x=top10_cdi["libelle"].apply(nom_court), y=top10_cdi["pct_cdi"],
                marker_color="#003189", text=top10_cdi["pct_cdi"].round(1),
                texttemplate="%{text}%", textposition="outside"
            ))
            fig3.add_trace(go.Bar(
                name="CDD", x=top10_cdi["libelle"].apply(nom_court), y=top10_cdi["pct_cdd"],
                marker_color="#63B3ED", text=top10_cdi["pct_cdd"].round(1),
                texttemplate="%{text}%", textposition="outside"
            ))
            fig3.update_layout(
                barmode="group", height=420,
                xaxis_tickangle=-35,
                xaxis_title="", yaxis_title="Part (%)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                legend_title="Type contrat"
            )
            st.plotly_chart(fig3, width="stretch")

    with col4:
        st.markdown("#### Top 10 profils d offres typiques d un metier en tension")
        st.markdown('<div class="section-note">Modele V2 (XGBoost) : probabilite d etre en tension estimee a partir du seul profil des offres (contrats, temps partiel, description...), sans le nombre d offres. Source : data/predictions_tension.csv</div>', unsafe_allow_html=True)
        if len(df_pred)>0:
            td = df_pred.sort_values("proba_tension",ascending=False).head(10)[["libelle","proba_tension","pct_cdi","pct_cdd"]]
            td.columns = ["Metier","Probabilite tension","% CDI","% CDD"]
            td["% CDI"] = td["% CDI"].round(1)
            td["% CDD"] = td["% CDD"].round(1)
            td["Probabilite tension"] = (td["Probabilite tension"]*100).round(0).astype(int).astype(str) + " %"
            st.dataframe(td, width="stretch", hide_index=True)

# ══════════════════════════════════════════════════════════════
# TAB 5 — METIERS EN TENSION
# ══════════════════════════════════════════════════════════════
with tab5:
    st.subheader("Metiers en Tension — Etat actuel et Predictions")

    _xgb = ml.get("v2", {}).get("resultats_cv5", {}).get("XGBoost", {})
    AUC, F1 = _xgb.get("roc_auc", 0.885), _xgb.get("f1", 0.785)
    NB_ML = ml.get("v2", {}).get("nb_metiers", len(df_pred))
    m1,m2,m3,m4 = st.columns(4)
    with m1:
        st.markdown(f'<div class="ml-card"><div class="ml-val" style="color:#003189">{fr(AUC, 2)}</div><div class="ml-label">AUC (validation croisee)</div></div>', unsafe_allow_html=True)
    with m2:
        st.markdown(f'<div class="ml-card"><div class="ml-val" style="color:#38A169">{fr(F1, 2)}</div><div class="ml-label">F1-score</div></div>', unsafe_allow_html=True)
    with m3:
        st.markdown('<div class="ml-card"><div class="ml-val" style="color:#C53030;font-size:1.2rem">XGBoost</div><div class="ml-label">Modele experimental</div></div>', unsafe_allow_html=True)
    with m4:
        st.markdown(f'<div class="ml-card"><div class="ml-val" style="color:#DD6B20">{NB_ML}</div><div class="ml-label">Metiers evalues (≥10 offres)</div></div>', unsafe_allow_html=True)

    st.divider()

    # STATUTS ACTUEL vs PREDIT cote a cote
    col1,col2 = st.columns(2)
    with col1:
        st.markdown("#### Statut actuel (indicateurs_tension)")
        st.markdown(f'<div class="section-note">Statut calcule en SQL sur les donnees reelles — {fr(NB_METIERS)} metiers. Source : table <b>indicateurs_tension</b></div>', unsafe_allow_html=True)
        if len(df_itm)>0:
            df_s_act = df_itm["statut"].value_counts().reset_index()
            df_s_act.columns = ["statut","nb"]
            ordre = ["SATURE","EQUILIBRE","EN TENSION","TRES EN TENSION"]
            df_s_act["statut"] = pd.Categorical(df_s_act["statut"], categories=ordre, ordered=True)
            df_s_act = df_s_act.sort_values("statut")
            if len(df_s_act) > 0:
                fig_act = px.bar(df_s_act, x="statut", y="nb", color="statut",
                    color_discrete_map={"TRES EN TENSION":"#C53030","EN TENSION":"#DD6B20","EQUILIBRE":"#38A169","SATURE":"#2B6CB0"},
                    text="nb", labels={"statut":"Statut","nb":"Metiers"})
                fig_act.update_traces(textposition="outside")
                fig_act.update_layout(height=350, showlegend=True,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02),
                    xaxis_title="", yaxis_title="Nb metiers",
                    legend_title="Statut actuel")
                st.plotly_chart(fig_act, width="stretch")
            else:
                st.info("Aucune donnee pour cette combinaison de filtres.")

    with col2:
        st.markdown("#### Modele V2 — le modele a-t-il raison ?")
        st.markdown(f'<div class="section-note">{NB_ML} metiers (≥ 10 offres). Chaque metier est predit par un modele qui ne l a pas vu (validation croisee 5 plis). En tension = indice &gt; 100 ; predit en tension = probabilite ≥ 50 %.</div>', unsafe_allow_html=True)
        if len(df_pred)>0:
            vp = int(( df_pred["en_tension_reel"] &  df_pred["en_tension_predit"]).sum())
            fn = int(( df_pred["en_tension_reel"] & ~df_pred["en_tension_predit"]).sum())
            fp = int((~df_pred["en_tension_reel"] &  df_pred["en_tension_predit"]).sum())
            vn = int((~df_pred["en_tension_reel"] & ~df_pred["en_tension_predit"]).sum())
            cases = [[f"<b>{fr(vp)}</b><br>bien reperes", f"<b>{fr(fn)}</b><br>manques"],
                     [f"<b>{fr(fp)}</b><br>fausses alertes", f"<b>{fr(vn)}</b><br>bien ecartes"]]
            fig_pred = go.Figure(go.Heatmap(z=[[1, 0], [0, 1]], text=cases, texttemplate="%{text}", textfont=dict(size=17),
                x=["Le modele dit : EN TENSION", "Le modele dit : PAS en tension"],
                y=["En realite : EN TENSION", "En realite : PAS en tension"],
                colorscale=[[0, "#FBD38D"], [1, "#9AE6B4"]], showscale=False, xgap=4, ygap=4, hoverinfo="skip"))
            fig_pred.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                yaxis=dict(autorange="reversed"), plot_bgcolor="white")
            st.plotly_chart(fig_pred, width="stretch", key="matrice_ml")
            bien = vp + vn
            st.caption(f"Vert = bonne reponse du modele ({fr(bien)} metiers sur {fr(len(df_pred))}, soit {fr(100 * bien / len(df_pred))} %). "
                       f"Orange = erreur. En realite en tension = indice > 100 dans la base ; le modele dit en tension = probabilite >= 50 %.")

    st.divider()

    # TOP 10 ACTUEL vs TOP 10 PREDIT cote a cote
    col3,col4 = st.columns(2)
    with col3:
        st.markdown("#### Top 10 metiers en tension — Etat actuel")
        st.markdown('<div class="section-note">Source : table <b>indicateurs_tension</b> — indice tension reel</div>', unsafe_allow_html=True)
        if len(df_itm)>0:
            top_act = df_itm[df_itm["statut"]=="TRES EN TENSION"].sort_values("indice_tension",ascending=False).head(10).copy()
            top_act["metier"] = top_act["code_rome"] + " · " + top_act["libelle"].apply(nom_court)
            top_act["etiquette"] = top_act.apply(lambda r: fr(int(r["indice_tension"])) + "  (" + fr(r["nb_offres_total"]) + " offres)", axis=1)
            fig_t1 = go.Figure(go.Bar(x=top_act["indice_tension"], y=top_act["metier"], orientation="h",
                marker_color="#C2410C", text=top_act["etiquette"], textposition="outside", cliponaxis=False))
            fig_t1.update_layout(height=420, showlegend=False, plot_bgcolor="white",
                xaxis=dict(title="Indice de tension (100 = metier moyen)", range=[0, top_act["indice_tension"].max() * 1.35]),
                yaxis=dict(title="", autorange="reversed"), margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig_t1, width="stretch", key="top10_top_act")

    with col4:
        st.markdown("#### Ce qui fait pencher le modele (modele V2)")
        st.markdown('<div class="section-note">Importance des variables pour XGBoost : plus la barre est longue, plus la variable aide le modele a reconnaitre un metier en tension. Aucune variable de volume. Source : <b>data/ml_resultats.json</b></div>', unsafe_allow_html=True)
        if len(df_pred)>0:
            NOMS_VAR = {"longueur_description": "Longueur des annonces", "part_temps_partiel": "Part de temps partiel",
                        "part_interim": "Part d'interim", "part_cdd": "Part de CDD", "part_cdi": "Part de CDI",
                        "salaire_affiche_moyen": "Salaire affiche", "part_salaire_absent": "Part sans salaire affiche",
                        "part_debutant": "Part ouverte aux debutants"}
            imp = ml.get("v2", {}).get("top_variables", {})
            if imp:
                df_imp = pd.DataFrame({"var": list(imp), "poids": [v * 100 for v in imp.values()]}).sort_values("poids", ascending=False).head(8)
                df_imp["nom"] = df_imp["var"].apply(lambda v: NOMS_VAR.get(v, "Domaine : " + DOMAINES_ROME.get(v[-1], v[-1]) if v.startswith("famille_rome_") else v))
                fig_t2 = go.Figure(go.Bar(x=df_imp["poids"], y=df_imp["nom"], orientation="h", marker_color="#2B6CB0",
                    text=[fr(v, 1) + " %" for v in df_imp["poids"]], textposition="outside", cliponaxis=False))
                fig_t2.update_layout(height=380, plot_bgcolor="white", margin=dict(l=10, r=10, t=10, b=10),
                    xaxis=dict(title="Importance dans le modele (%)", range=[0, df_imp["poids"].max() * 1.3]),
                    yaxis=dict(title="", autorange="reversed"))
                st.plotly_chart(fig_t2, width="stretch", key="importance_ml")
                st.caption("La longueur des annonces reflete surtout la source (France Travail ou Adzuna) : c'est une limite du modele.")
            else:
                st.info("Importance des variables indisponible (lancer notebook/ml_tests.py).")

    st.divider()

    # BUBBLE MAP + METIERS EN TENSION IDF cote a cote
    col5,col6 = st.columns(2)
    with col5:
        st.markdown("#### Offres actives par departement IDF")
        st.markdown('<div class="section-note">Sources combinees Adzuna + France Travail. Contours et centres des departements : fichier de reference <b>data/ref/departements_idf.geojson</b> (collecte C1). Couleur = nb offres.</div>', unsafe_allow_html=True)
        geo = load_geojson()
        if "departement" in df_filtered.columns and geo:
            df_dept = df_sans_dept.assign(code_dept=df_sans_dept["departement"].map(code_dept_depuis_libelle))
            df_dept = df_dept.dropna(subset=["code_dept"]).groupby("code_dept").size().reset_index(name="nb")
            noms = {f["properties"]["code"]: f["properties"]["nom"] for f in geo["features"]}
            df_dept["departement"] = df_dept["code_dept"].map(noms)
            if len(df_dept) > 0:
                carte_args = dict(geojson=geo, locations="code_dept",
                    featureidkey="properties.code", color="nb", hover_name="departement",
                    hover_data={"nb":True,"code_dept":False},
                    color_continuous_scale=["#EBF8FF","#003189"], opacity=0.75,
                    zoom=7.6, center={"lat":48.72,"lon":2.5}, labels={"nb":"Offres"})
                if hasattr(px, "choropleth_map"):      # plotly >= 5.24
                    fig_map = px.choropleth_map(df_dept, map_style="carto-positron", **carte_args)
                else:
                    fig_map = px.choropleth_mapbox(df_dept, mapbox_style="carto-positron", **carte_args)
                fig_map.update_layout(height=420, margin=dict(l=0,r=0,t=0,b=0))
                st.plotly_chart(fig_map, width="stretch")
            else:
                st.info("Aucune donnee pour cette combinaison de filtres.")
        else:
            st.info("Carte indisponible : lancer python src/collect.py --source geojson")

    with col6:
        st.markdown("#### Metiers en tension IDF vs offres actives")
        st.markdown('<div class="section-note">Croisement : nb offres actives (axe X) vs indice tension ITM (axe Y). Les metiers en haut a droite sont les plus prioritaires.</div>', unsafe_allow_html=True)
        if len(df_itm)>0:
            df_cross = df_itm[df_itm["statut"].isin(["TRES EN TENSION","EN TENSION"])].copy()
            fig_cross = px.scatter(df_cross,
                x="nb_offres_total", y="indice_tension",
                color="statut", size="nb_offres_total",
                hover_name="libelle",
                color_discrete_map={"TRES EN TENSION":"#C53030","EN TENSION":"#DD6B20"},
                labels={"nb_offres_total":"Nb offres actives","indice_tension":"Indice tension ITM","statut":"Statut"},
                size_max=40)
            fig_cross.update_layout(height=420,
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                legend_title="Statut metier")
            st.plotly_chart(fig_cross, width="stretch")


# ══════════════════════════════════════════════════════════════
# TAB 6 — SALAIRES
# ══════════════════════════════════════════════════════════════
with tab6:
    st.subheader("Salaires — Adzuna et France Travail")
    st.markdown('<div class="section-note">Salaires annuels bruts <b>affiches</b> dans les offres uniquement (les salaires completes par mediane sont exclus des statistiques). Source : base V2 data/ppmt.db.</div>', unsafe_allow_html=True)

    col1,col2 = st.columns(2)
    with col1:
        st.markdown("#### Salaire median FT vs Adzuna — Top metiers en tension")
        if len(df_itm)>0:
            df_sal = df_itm[df_itm["statut"]=="TRES EN TENSION"].copy()
            df_sal = df_sal[(df_sal["salaire_moyen_ft"]>0)|(df_sal["salaire_moyen_adzuna"]>0)].sort_values("indice_tension",ascending=False).head(12)
            fig_sal = go.Figure()
            fig_sal.add_trace(go.Bar(
                name="France Travail", x=df_sal["libelle"].apply(nom_court), y=df_sal["salaire_moyen_ft"],
                marker_color="#C53030", text=df_sal["salaire_moyen_ft"].apply(lambda v: fr(v) if pd.notna(v) else ""), textposition="outside"
            ))
            fig_sal.add_trace(go.Bar(
                name="Adzuna", x=df_sal["libelle"].apply(nom_court), y=df_sal["salaire_moyen_adzuna"],
                marker_color="#63B3ED", text=df_sal["salaire_moyen_adzuna"].apply(lambda v: fr(v) if pd.notna(v) else ""), textposition="outside"
            ))
            fig_sal.update_layout(
                barmode="group", height=420, xaxis_tickangle=-35,
                xaxis_title="", yaxis_title="Salaire median annuel (EUR)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                legend_title="Source"
            )
            st.plotly_chart(fig_sal, width="stretch")

    with col2:
        st.markdown("#### Salaire median par domaine ROME (Adzuna)")
        df_sc = df_az_f[df_az_f["salaire_moyen"].notna()]
        if "categorie" in df_sc.columns:
            df_sc = df_sc[~df_sc["categorie"].isin(["Unknown","Non classe"])]
        if len(df_sc)>0 and "categorie" in df_sc.columns:
            df_sg = df_sc.groupby("categorie")["salaire_moyen"].median().reset_index().sort_values("salaire_moyen",ascending=True)
            fig2 = px.bar(df_sg, x="salaire_moyen", y="categorie", orientation="h",
                color="salaire_moyen", color_continuous_scale=["#F0FFF4","#276749"],
                text="salaire_moyen", labels={"salaire_moyen":"Salaire median (EUR/an)","categorie":""})
            fig2.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
            fig2.update_layout(height=500, showlegend=False, coloraxis_showscale=False,
                xaxis_title="Salaire median annuel (EUR)")
            st.plotly_chart(fig2, width="stretch")

    st.divider()
    col3,col4 = st.columns(2)
    with col3:
        st.markdown("#### Repartition des salaires affiches")
        df_dist = df_filtered[(df_filtered["salaire_moyen"].notna())&(df_filtered["salaire_moyen"]>15000)&(df_filtered["salaire_moyen"]<150000)]
        if len(df_dist)>0:
            med, moy = df_dist["salaire_moyen"].median(), df_dist["salaire_moyen"].mean()
            fig3 = px.histogram(df_dist, x="salaire_moyen", color="source", nbins=40, histnorm="percent",
                barmode="overlay", opacity=0.6,
                color_discrete_map={"France Travail": "#C53030", "Adzuna": "#3182CE"},
                labels={"salaire_moyen": "Salaire annuel brut (EUR)", "source": "Source"})
            fig3.add_vline(x=med, line_width=3, line_color="#1A202C",
                annotation_text=f"Mediane {fr(med)} €", annotation_position="top right")
            fig3.add_vline(x=moy, line_width=2, line_dash="dash", line_color="#DD6B20",
                annotation_text=f"Moyenne {fr(moy)} €", annotation_position="bottom right",
                annotation_font_color="#DD6B20")
            fig3.update_layout(height=360, plot_bgcolor="white", xaxis_tickformat=",.0f",
                xaxis_title="Salaire annuel brut (EUR)", yaxis_title="% des offres de la source",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            st.plotly_chart(fig3, width="stretch", key="repartition_salaires")
            st.caption(f"{fr(len(df_dist))} offres avec un salaire affiche (entre 15 000 et 150 000 €). "
                       f"Quelques salaires tres eleves tirent la moyenne ({fr(moy)} €) au-dessus de la mediane ({fr(med)} €) : "
                       "c'est pourquoi les indicateurs utilisent la mediane.")
        else:
            st.info("Aucune donnee pour cette combinaison de filtres.")

    with col4:
        st.markdown("#### Salaire median par departement (toutes sources)")
        df_sd = df_filtered[df_filtered["salaire_moyen"].notna()]
        if "departement" in df_sd.columns and len(df_sd)>0:
            df_sdg = df_sd.groupby("departement")["salaire_moyen"].agg(["median","count"]).reset_index()
            df_sdg.columns = ["departement","salaire_moyen","nb"]
            df_sdg = df_sdg[df_sdg["nb"]>=5].sort_values("salaire_moyen",ascending=True)
            if len(df_sdg) > 0:
                fig4 = px.bar(df_sdg, x="salaire_moyen", y="departement", orientation="h",
                    color="salaire_moyen", color_continuous_scale=["#F0FFF4","#276749"],
                    text="salaire_moyen", labels={"salaire_moyen":"Salaire (EUR/an)","departement":""})
                fig4.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
                fig4.update_layout(height=380, showlegend=False, coloraxis_showscale=False,
                    xaxis_title="Salaire median annuel (EUR)")
                st.plotly_chart(fig4, width="stretch")
            else:
                st.info("Aucune donnee pour cette combinaison de filtres.")

# ─── FOOTER ──────────────────────────────────────────────────
st.markdown(f"""
<div class="footer">
    <strong>PPMT &copy; 2026</strong> &nbsp;&middot;&nbsp;
    Projet RNCP37827BC01 &mdash; Data Analyst &nbsp;&middot;&nbsp;
    Formation Artefact &nbsp;&middot;&nbsp;
    Sources : Adzuna + France Travail &nbsp;&middot;&nbsp;
    Equipe : Bernard &amp; Claire &nbsp;&middot;&nbsp;
    Derniere mise a jour : {datetime.now().strftime("%d/%m/%Y %H:%M")}
</div>
""", unsafe_allow_html=True)
