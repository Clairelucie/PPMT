# Registre du traitement — PPMT (article 30 RGPD)

| Rubrique | Contenu |
|---|---|
| **Traitement** | Veille des offres d'emploi publiées en Île-de-France et calcul d'indicateurs de tension par métier (code ROME) |
| **Responsable** | Claire DIOUF — projet de formation Artefact (RNCP37827BC01) |
| **Finalité** | Statistiques agrégées sur le marché du travail francilien : volume d'offres, contrats, salaires, métiers en tension |
| **Base légale** | Intérêt légitime (art. 6.1.f) — réutilisation de données publiées publiquement par les employeurs, via les API officielles (France Travail) et un agrégateur (Adzuna), dans le respect de leurs conditions d'utilisation |
| **Personnes concernées** | Aucune donnée de candidat ni de demandeur d'emploi. Les offres peuvent contenir, dans le texte libre, les coordonnées d'un recruteur |
| **Données collectées** | Intitulé, entreprise (personne morale), commune / département, code ROME, contrat, salaire affiché, expérience demandée, date, extrait de description (300 caractères), URL |
| **Minimisation** | Description tronquée ; aucun champ nominatif collecté ; e-mails et numéros de téléphone masqués (`[email]`, `[tel]`) par `prepare.pseudonymiser()` avant tout stockage |
| **Durée de conservation** | 12 mois glissants — `store.purger_offres_anciennes()` à chaque exécution du pipeline |
| **Destinataires** | Utilisateurs du dashboard et de l'API (lecture seule, clé API obligatoire) |
| **Sécurité** | Secrets API dans `.env` (non versionné) ; base SQLite ouverte en lecture seule par l'API ; requêtes SQL paramétrées ; API limitée au verbe GET ; CORS restreint à GET |
| **Transferts hors UE** | Aucun pour la base. Adzuna est une société britannique (pays bénéficiant d'une décision d'adéquation de la Commission européenne) |
| **Contrôle** | Test automatisé `test_aucune_donnee_personnelle` : aucune adresse e-mail ni numéro de téléphone en clair en base |
