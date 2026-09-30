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
               (SELECT AVG(o.salaire_moyen) FROM offres o WHERE o.code_rome = i.code_rome
                  AND o.source = 'france_travail' AND o.salaire_impute = 0) AS salaire_moyen_ft,
               (SELECT AVG(o.salaire_moyen) FROM offres o WHERE o.code_rome = i.code_rome
                  AND o.source = 'adzuna' AND o.salaire_impute = 0) AS salaire_moyen_adzuna
        FROM indicateurs_tension i JOIN metiers_rome m USING (code_rome)""")
    df["pct_cdi"] = df["part_cdi"]
    df["domaine"] = df["code_rome"].str[0].map(DOMAINES_ROME).fillna("Autre")
    return df

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
    texts = df[col].dropna().str.lower().str.cat(sep=" ")
    def count_kw(kw_list):
        return {kw: texts.count(kw) for kw in kw_list if texts.count(kw) > 0}
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

df_az["source"] = "Adzuna"
df_ft["source"] = "France Travail"
df_all = pd.concat([df_az, df_ft], ignore_index=True)

# ─── SIDEBAR ─────────────────────────────────────────────────
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/c/c3/Python-logo-notext.svg/115px-Python-logo-notext.svg.png", width=40)
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
    if st.button("Rafraichir les donnees", type="primary", use_container_width=True):
        with st.spinner("Mise a jour en cours..."):
            subprocess.run(["python3", str(ROOT / "run_pipeline.py")], cwd=ROOT)   # C1 → C4 (V2)
            subprocess.run(["python3", str(ROOT / "notebook" / "ml_tests.py")], cwd=ROOT)
            st.cache_data.clear()
        st.success("Donnees mises a jour !")
        st.rerun()

    st.markdown("---")
    st.markdown("""
    <div style="font-size:0.75rem;color:#718096;line-height:1.9">
    <b>Sources</b><br>Adzuna API · France Travail API<br><br>
    <b>Base</b><br>data/ppmt.db (pipeline V2)<br><br>
    <b>Perimetre</b><br>Ile-de-France (8 depts)<br><br>
    <b>Modele ML (experimental)</b><br>XGBoost · AUC 0,84
    </div>
    """, unsafe_allow_html=True)

# ─── FILTRES ────────────────────────────────────────────────
def apply_filters(df):
    d = df.copy()
    if filtre_dept != "Tous" and "departement" in d.columns:
        d = d[d["departement"]==filtre_dept]
    if filtre_contrat != "Tous" and "contrat_norm" in d.columns:
        d = d[d["contrat_norm"]==filtre_contrat]
    if filtre_secteur != "Tous" and "categorie" in d.columns:
        d = d[d["categorie"]==filtre_secteur]
    return d

df_filtered = apply_filters(df_all)
df_az_f = apply_filters(df_az)
df_ft_f = apply_filters(df_ft)

# ─── HEADER ──────────────────────────────────────────────────
st.markdown(f"""
<div class="intro-box">
<h2 style="margin:0 0 6px 0;font-size:1.55rem">Plateforme Predictive des Metiers en Tension — IDF</h2>
<p style="margin:0;opacity:0.92;font-size:0.92rem">
PPMT identifie les metiers en tension en Ile-de-France a partir des donnees <b>Adzuna</b> et <b>France Travail</b>.
L'indice de tension (ITM) compare le volume d'offres de chaque metier (code ROME) a la moyenne : 100 = metier moyen. Un modele ML experimental (XGBoost, AUC {ml.get('v2',{}).get('modeles',{}).get('XGBoost',{}).get('roc_auc',0.84):.2f}) repere les metiers en tension a partir du profil de leurs offres.
Utilisez les filtres a gauche pour explorer par departement, contrat ou secteur.
</p>
<div style="margin-top:12px">
<span class="stat-badge">{NB_OFFRES:,} offres</span>
<span class="stat-badge">{NB_METIERS:,} metiers analyses</span>
<span class="stat-badge">8 departements IDF</span>
<span class="stat-badge red">{NB_TRES} TRES EN TENSION</span>
<span class="stat-badge green">Sources : Adzuna + France Travail</span>
</div>
</div>
""", unsafe_allow_html=True)

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
    nb_secteurs = df_filtered.loc[df_filtered["categorie"]!="Non classe","categorie"].nunique()
    sal_az = df_az_f["salaire_moyen"].mean() if "salaire_moyen" in df_az_f.columns else 0
    sal_ft = df_ft_f["salaire_moyen"].mean() if "salaire_moyen" in df_ft_f.columns else 0
    tres = NB_TRES

    c1,c2,c3,c4,c5 = st.columns(5)
    with c1:
        st.markdown(f'<div class="kpi-card"><p class="kpi-val">{nb_total:,}</p><p class="kpi-label">Total offres (filtre)</p><p class="kpi-sub">AZ: {nb_az:,} · FT: {nb_ft:,}</p></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="kpi-card green"><p class="kpi-val">{nb_secteurs}</p><p class="kpi-label">Secteurs</p><p class="kpi-sub">Domaines ROME</p></div>', unsafe_allow_html=True)
    with c3:
        sal_str = f"{sal_az:,.0f} EUR" if sal_az and sal_az>0 else "N/A"
        st.markdown(f'<div class="kpi-card orange"><p class="kpi-val">{sal_str}</p><p class="kpi-label">Salaire moyen Adzuna</p><p class="kpi-sub">Salaires affiches · annuel brut</p></div>', unsafe_allow_html=True)
    with c4:
        sal_ft_str = f"{sal_ft:,.0f} EUR" if sal_ft and sal_ft>0 else "N/A"
        st.markdown(f'<div class="kpi-card purple"><p class="kpi-val">{sal_ft_str}</p><p class="kpi-label">Salaire moyen FT</p><p class="kpi-sub">Salaires affiches · annuel brut</p></div>', unsafe_allow_html=True)
    with c5:
        st.markdown(f'<div class="kpi-card red"><p class="kpi-val">{tres}</p><p class="kpi-label">Metiers TRES EN TENSION</p><p class="kpi-sub">Sur {NB_METIERS:,} analyses</p></div>', unsafe_allow_html=True)

    st.divider()
    col1,col2 = st.columns(2)
    with col1:
        st.subheader("Repartition des statuts ITM")
        st.markdown(f'<div class="section-note">Table <b>indicateurs_tension</b> (base V2, calcul SQL) — {NB_METIERS:,} metiers, Adzuna + France Travail. Seuils : SATURE &lt;50 · EQUILIBRE 50-100 · EN TENSION 100-150 · TRES EN TENSION &gt;150</div>', unsafe_allow_html=True)
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
            top10 = df_itm[df_itm["statut"]=="TRES EN TENSION"].sort_values("indice_tension",ascending=False).head(10)
            fig2 = px.bar(top10, x="indice_tension", y="libelle", orientation="h",
                color="indice_tension", color_continuous_scale=["#FED7D7","#C53030"],
                text="indice_tension",
                labels={"indice_tension":"Indice tension","libelle":"Metier"})
            fig2.update_traces(texttemplate="%{text:.0f}", textposition="outside")
            fig2.update_layout(height=400, showlegend=False, coloraxis_showscale=False,
                xaxis_title="Indice de tension (100 = metier moyen)", yaxis_title="")
            st.plotly_chart(fig2, width="stretch")

    st.divider()
    st.subheader("Offres publiees en mai 2026 — Adzuna vs France Travail")
    df_az_mai = df_az[(df_az["date_publication"].dt.year==2026)&(df_az["date_publication"].dt.month==5)] if "date_publication" in df_az.columns else pd.DataFrame()
    df_ft_mai = df_ft[(df_ft["date_publication"].dt.year==2026)&(df_ft["date_publication"].dt.month==5)] if "date_publication" in df_ft.columns else pd.DataFrame()

    st.markdown(f'<div class="section-note">Offres publiees en mai 2026 (periode de collecte principale), apres dedoublonnage. Adzuna : {len(df_az_mai):,} offres · France Travail : {len(df_ft_mai):,} offres</div>', unsafe_allow_html=True)
    if len(df_az_mai)>0 or len(df_ft_mai)>0:
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Adzuna — Mai 2026 par domaine ROME**")
            if len(df_az_mai)>0 and "categorie" in df_az_mai.columns:
                df_cat_mai = df_az_mai.groupby("categorie").size().reset_index(name="nb")
                df_cat_mai = df_cat_mai[~df_cat_mai["categorie"].isin(["Unknown","","Non classe"])].sort_values("nb",ascending=True).tail(12)
                fig_mai = px.bar(df_cat_mai, x="nb", y="categorie", orientation="h",
                    color="nb", color_continuous_scale=["#EBF8FF","#003189"], text="nb")
                fig_mai.update_traces(textposition="outside")
                fig_mai.update_layout(height=380, showlegend=False, coloraxis_showscale=False,
                    xaxis_title="Offres", yaxis_title="")
                st.plotly_chart(fig_mai, width="stretch")
        with col_b:
            st.markdown("**France Travail — Mai 2026 par departement**")
            if len(df_ft_mai)>0 and "departement" in df_ft_mai.columns:
                df_dept_mai = df_ft_mai.groupby("departement").size().reset_index(name="nb")
                df_dept_mai = df_dept_mai[df_dept_mai["departement"].notna()].sort_values("nb",ascending=True)
                fig_dept = px.bar(df_dept_mai, x="nb", y="departement", orientation="h",
                    color="nb", color_continuous_scale=["#FFF5F5","#C53030"], text="nb")
                fig_dept.update_traces(textposition="outside")
                fig_dept.update_layout(height=380, showlegend=False, coloraxis_showscale=False,
                    xaxis_title="Offres", yaxis_title="")
                st.plotly_chart(fig_dept, width="stretch")

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
            df_co_ft = df_ft.groupby("contrat_norm").size().reset_index(name="nb")
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
        st.markdown("**Adzuna — Contrats normalises**")
        if "contrat_norm" in df_az.columns:
            df_co_az = df_az.groupby("contrat_norm").size().reset_index(name="nb")
            df_co_az = df_co_az[df_co_az["contrat_norm"]!="Non renseigne"].sort_values("nb",ascending=False)
            if len(df_co_az) > 0:
                fig_az_co = px.bar(df_co_az, x="contrat_norm", y="nb", color="contrat_norm",
                    color_discrete_map=colors_ct, text="nb",
                    labels={"contrat_norm":"Type de contrat","nb":"Offres"})
                fig_az_co.update_traces(textposition="outside")
                fig_az_co.update_layout(height=350, showlegend=False,
                    xaxis_title="", yaxis_title="Offres Adzuna")
                st.plotly_chart(fig_az_co, width="stretch")
            else:
                st.info("Aucune donnee pour cette combinaison de filtres.")

# ══════════════════════════════════════════════════════════════
# TAB 3 — COMPETENCES & TECH
# ══════════════════════════════════════════════════════════════
with tab3:
    st.subheader("Competences et Technologies")
    st.markdown(f'<div class="section-note">Extraction depuis les descriptions des <b>{NB_OFFRES_TRES:,} offres des metiers TRES EN TENSION</b> ({NB_TRES} codes ROME). Echelle = nb occurrences. Source : Adzuna + France Travail combines.</div>', unsafe_allow_html=True)

    with st.spinner("Analyse des descriptions en cours..."):
        sk_az, sk_ft = extract_skills_tension(df_az, df_ft, df_itm)

    col1,col2 = st.columns(2)
    with col1:
        st.markdown(f"#### Hard Skills — Metiers TRES EN TENSION ({NB_TRES} metiers, {NB_OFFRES_TRES:,} offres)")
        hard = merge_skills(sk_az, sk_ft, "hard")
        if hard:
            df_h = pd.DataFrame(list(hard.items()),columns=["skill","nb"]).sort_values("nb")
            if len(df_h) > 0:
                fig = px.bar(df_h, x="nb", y="skill", orientation="h",
                    color="nb", color_continuous_scale=["#EBF8FF","#003189"], text="nb",
                    labels={"nb":"Occurrences dans les offres","skill":"Competence"})
                fig.update_traces(textposition="outside")
                fig.update_layout(height=520, showlegend=False, coloraxis_showscale=False,
                    xaxis_title="Nb occurrences dans les offres (tous secteurs)", yaxis_title="")
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
        if fq:
            df_fq = pd.DataFrame(list(fq.items()),columns=["formation","nb"]).sort_values("nb",ascending=False)
            ordre_form = ["doctorat","mba","ingenieur","bac+5","master","licence","bac+3","bac+2","dut","bts"]
            df_fq["formation"] = pd.Categorical(df_fq["formation"], categories=ordre_form, ordered=True)
            df_fq = df_fq.sort_values("formation")
            if len(df_fq) > 0:
                fig = px.bar(df_fq, x="formation", y="nb", color="nb",
                    color_continuous_scale=["#FFFAF0","#DD6B20"], text="nb",
                    labels={"nb":"Occurrences","formation":"Niveau"})
                fig.update_traces(textposition="outside")
                fig.update_layout(height=350, showlegend=False, coloraxis_showscale=False,
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
                name="CDI", x=top10_cdi["libelle"], y=top10_cdi["pct_cdi"],
                marker_color="#003189", text=top10_cdi["pct_cdi"].round(1),
                texttemplate="%{text}%", textposition="outside"
            ))
            fig3.add_trace(go.Bar(
                name="CDD", x=top10_cdi["libelle"], y=top10_cdi["pct_cdd"],
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
    AUC, F1 = _xgb.get("roc_auc", 0.84), _xgb.get("f1", 0.77)
    NB_ML = ml.get("v2", {}).get("nb_metiers", len(df_pred))
    m1,m2,m3,m4 = st.columns(4)
    with m1:
        st.markdown(f'<div class="ml-card"><div class="ml-val" style="color:#003189">{AUC:.2f}</div><div class="ml-label">AUC (validation croisee)</div></div>', unsafe_allow_html=True)
    with m2:
        st.markdown(f'<div class="ml-card"><div class="ml-val" style="color:#38A169">{F1:.2f}</div><div class="ml-label">F1-score</div></div>', unsafe_allow_html=True)
    with m3:
        st.markdown('<div class="ml-card"><div class="ml-val" style="color:#C53030;font-size:1.2rem">XGBoost</div><div class="ml-label">Modele experimental</div></div>', unsafe_allow_html=True)
    with m4:
        st.markdown(f'<div class="ml-card"><div class="ml-val" style="color:#DD6B20">{NB_ML}</div><div class="ml-label">Metiers evalues (≥10 offres)</div></div>', unsafe_allow_html=True)

    st.divider()

    # STATUTS ACTUEL vs PREDIT cote a cote
    col1,col2 = st.columns(2)
    with col1:
        st.markdown("#### Statut actuel (indicateurs_tension)")
        st.markdown(f'<div class="section-note">Statut calcule en SQL sur les donnees reelles — {NB_METIERS:,} metiers. Source : table <b>indicateurs_tension</b></div>', unsafe_allow_html=True)
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
        st.markdown("#### Modele V2 — predit vs reel")
        st.markdown(f'<div class="section-note">{NB_ML} metiers (≥ 10 offres). Chaque metier est predit par un modele qui ne l a pas vu (validation croisee 5 plis). En tension = indice &gt; 100 ; predit en tension = probabilite ≥ 50 %.</div>', unsafe_allow_html=True)
        if len(df_pred)>0:
            conf = pd.crosstab(df_pred["en_tension_reel"].map({True:"En tension (reel)",False:"Pas en tension (reel)"}),
                               df_pred["en_tension_predit"].map({True:"Predit en tension",False:"Predit pas en tension"}))
            conf = conf.reset_index().melt(id_vars=conf.index.name or "en_tension_reel", var_name="prediction", value_name="nb")
            conf.columns = ["reel","prediction","nb"]
            fig_pred = px.bar(conf, x="reel", y="nb", color="prediction", barmode="group", text="nb",
                color_discrete_map={"Predit en tension":"#C53030","Predit pas en tension":"#2B6CB0"},
                labels={"reel":"","nb":"Metiers","prediction":"Prediction XGBoost"})
            fig_pred.update_traces(textposition="outside")
            fig_pred.update_layout(height=350, legend=dict(orientation="h", yanchor="bottom", y=1.02),
                xaxis_title="", yaxis_title="Nb metiers")
            st.plotly_chart(fig_pred, width="stretch")

    st.divider()

    # TOP 10 ACTUEL vs TOP 10 PREDIT cote a cote
    col3,col4 = st.columns(2)
    with col3:
        st.markdown("#### Top 10 metiers en tension — Etat actuel")
        st.markdown('<div class="section-note">Source : table <b>indicateurs_tension</b> — indice tension reel</div>', unsafe_allow_html=True)
        if len(df_itm)>0:
            top_act = df_itm[df_itm["statut"]=="TRES EN TENSION"].sort_values("indice_tension",ascending=False).head(10)
            fig_t1 = px.bar(top_act, x="indice_tension", y="libelle", orientation="h",
                color="indice_tension", color_continuous_scale=["#FED7D7","#C53030"],
                text="indice_tension", labels={"indice_tension":"ITM reel","libelle":""})
            fig_t1.update_traces(texttemplate="%{text:.0f}", textposition="outside")
            fig_t1.update_layout(height=380, showlegend=False, coloraxis_showscale=False,
                xaxis_title="Indice tension reel", yaxis_title="")
            st.plotly_chart(fig_t1, width="stretch")

    with col4:
        st.markdown("#### Top 10 probabilites de tension (modele V2)")
        st.markdown('<div class="section-note">XGBoost sur le profil des offres, sans variable de volume — source : <b>data/predictions_tension.csv</b></div>', unsafe_allow_html=True)
        if len(df_pred)>0:
            top_pred = df_pred.sort_values("proba_tension",ascending=False).head(10).assign(proba=lambda d: d["proba_tension"]*100)
            fig_t2 = px.bar(top_pred, x="proba", y="libelle", orientation="h",
                color="proba", color_continuous_scale=["#FED7D7","#9B2C2C"],
                text="proba", labels={"proba":"Probabilite (%)","libelle":""})
            fig_t2.update_traces(texttemplate="%{text:.0f} %", textposition="outside")
            fig_t2.update_layout(height=380, showlegend=False, coloraxis_showscale=False,
                xaxis_title="Probabilite d etre en tension (%)", xaxis_range=[0,110], yaxis_title="")
            st.plotly_chart(fig_t2, width="stretch")

    st.divider()

    # BUBBLE MAP + METIERS EN TENSION IDF cote a cote
    col5,col6 = st.columns(2)
    with col5:
        st.markdown("#### Offres actives par departement IDF")
        st.markdown('<div class="section-note">Sources combinees Adzuna + France Travail. Contours et centres des departements : fichier de reference <b>data/ref/departements_idf.geojson</b> (collecte C1). Couleur = nb offres.</div>', unsafe_allow_html=True)
        geo = load_geojson()
        if "departement" in df_all.columns and geo:
            df_dept = df_all.assign(code_dept=df_all["departement"].map(code_dept_depuis_libelle))
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
        st.markdown("#### Salaire moyen FT vs Adzuna — Top metiers en tension")
        if len(df_itm)>0:
            df_sal = df_itm[df_itm["statut"]=="TRES EN TENSION"].copy()
            df_sal = df_sal[(df_sal["salaire_moyen_ft"]>0)|(df_sal["salaire_moyen_adzuna"]>0)].sort_values("indice_tension",ascending=False).head(12)
            fig_sal = go.Figure()
            fig_sal.add_trace(go.Bar(
                name="France Travail", x=df_sal["libelle"], y=df_sal["salaire_moyen_ft"],
                marker_color="#C53030", text=df_sal["salaire_moyen_ft"].round(0),
                texttemplate="%{text:,.0f}", textposition="outside"
            ))
            fig_sal.add_trace(go.Bar(
                name="Adzuna", x=df_sal["libelle"], y=df_sal["salaire_moyen_adzuna"],
                marker_color="#63B3ED", text=df_sal["salaire_moyen_adzuna"].round(0),
                texttemplate="%{text:,.0f}", textposition="outside"
            ))
            fig_sal.update_layout(
                barmode="group", height=420, xaxis_tickangle=-35,
                xaxis_title="", yaxis_title="Salaire moyen annuel (EUR)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                legend_title="Source"
            )
            st.plotly_chart(fig_sal, width="stretch")

    with col2:
        st.markdown("#### Salaire moyen par domaine ROME (Adzuna)")
        df_sc = df_az_f[df_az_f["salaire_moyen"].notna()]
        if "categorie" in df_sc.columns:
            df_sc = df_sc[~df_sc["categorie"].isin(["Unknown","Non classe"])]
        if len(df_sc)>0 and "categorie" in df_sc.columns:
            df_sg = df_sc.groupby("categorie")["salaire_moyen"].mean().reset_index().sort_values("salaire_moyen",ascending=True)
            fig2 = px.bar(df_sg, x="salaire_moyen", y="categorie", orientation="h",
                color="salaire_moyen", color_continuous_scale=["#F0FFF4","#276749"],
                text="salaire_moyen", labels={"salaire_moyen":"Salaire moyen (EUR/an)","categorie":""})
            fig2.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
            fig2.update_layout(height=500, showlegend=False, coloraxis_showscale=False,
                xaxis_title="Salaire moyen annuel (EUR)")
            st.plotly_chart(fig2, width="stretch")

    st.divider()
    col3,col4 = st.columns(2)
    with col3:
        st.markdown("#### Distribution salaires Adzuna (15k-150k EUR)")
        df_dist = df_az[(df_az["salaire_moyen"].notna())&(df_az["salaire_moyen"]>15000)&(df_az["salaire_moyen"]<150000)]
        if len(df_dist)>0:
            fig3 = px.histogram(df_dist, x="salaire_moyen", nbins=30,
                color_discrete_sequence=["#003189"],
                labels={"salaire_moyen":"Salaire annuel (EUR)"})
            fig3.update_layout(height=320, xaxis_tickformat=",.0f",
                xaxis_title="Salaire annuel brut (EUR)", yaxis_title="Nb offres")
            st.plotly_chart(fig3, width="stretch")

    with col4:
        st.markdown("#### Salaire moyen par departement (toutes sources)")
        df_sd = df_all[df_all["salaire_moyen"].notna()]
        if "departement" in df_sd.columns and len(df_sd)>0:
            df_sdg = df_sd.groupby("departement")["salaire_moyen"].agg(["mean","count"]).reset_index()
            df_sdg.columns = ["departement","salaire_moyen","nb"]
            df_sdg = df_sdg[df_sdg["nb"]>=5].sort_values("salaire_moyen",ascending=True)
            if len(df_sdg) > 0:
                fig4 = px.bar(df_sdg, x="salaire_moyen", y="departement", orientation="h",
                    color="salaire_moyen", color_continuous_scale=["#F0FFF4","#276749"],
                    text="salaire_moyen", labels={"salaire_moyen":"Salaire (EUR/an)","departement":""})
                fig4.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
                fig4.update_layout(height=380, showlegend=False, coloraxis_showscale=False,
                    xaxis_title="Salaire moyen annuel (EUR)")
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
