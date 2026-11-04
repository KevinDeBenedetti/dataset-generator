# Repo et dataset publics : employeurs tech en France

*Kevin De Benedetti · 2026-10-18*

Un repo et un dataset publics réussis à partir d'open data ne recopient pas les sources : ils apportent ce qu'aucune source ne fournit seule, à savoir **la jointure, le nettoyage, l'enrichissement et la fraîcheur**. Les sections ci-dessous détaillent les features à retenir pour un référentiel des employeurs tech en France.

## Le dataset : ce qu'il contient

Cinq jeux de données couvrent l'essentiel, du référentiel des employeurs aux statistiques d'offres.

| Dataset | Contenu | Sources | Valeur ajoutée |
| --- | --- | --- | --- |
| Référentiel des employeurs tech | Entreprises actives des codes NAF tech : SIREN, taille, localisation géocodée, date de création, catégorie (ESN, éditeur, ingénierie, R&D, data/hébergement) | Recherche d'entreprises, API Adresse | Le classement ESN ou éditeur n'existe dans aucune source telle quelle |
| Indicateurs par entreprise | Santé financière sur plusieurs années, événements récents, marchés publics gagnés, activité R&D, présence open source, score de dynamisme documenté et reproductible | INPI, BODACC, DECP, scanR, GitHub | Une vue synthétique impossible à obtenir source par source |
| Statistiques d'offres agrégées | Volume d'offres par compétence, département et mois, salaires médians affichés par métier, part de télétravail, type de contrat | API Offres d'emploi France Travail | Publiable sans redistribuer les offres brutes |
| Taxonomie de compétences tech | ROME 4.0 et ESCO enrichis de synonymes et alias (« k8s » → Kubernetes, « React.js » → React), avec catégories (langage, framework, cloud, data) | ROME 4.0, ESCO | Réutilisable par tout projet d'extraction d'offres |
| Tension par métier et territoire | Où les profils dev et ingénieur sont les plus recherchés | Enquête BMO croisée avec les offres | Dataset léger et très parlant |

## Le repo : ce qui le rend fiable et utile

La fiabilité vient d'un pipeline reproductible, mis à jour automatiquement et contrôlé à chaque version.

**Pipeline reproductible**

- Un module d'ingestion par source, avec gestion des limites de débit et reprise sur erreur.
- Des étapes séparées : brut → nettoyé → joint → agrégé (architecture en couches).
- Une commande unique pour tout reconstruire (`make build` ou `uv run pipeline`).

**Mise à jour automatique**

- Un workflow GitHub Actions hebdomadaire qui reconstruit et publie une nouvelle version sur Hugging Face.
- La date de mise à jour indiquée pour chaque source.

**Qualité des données**

- Validation des schémas avec Pydantic, Pandera ou Great Expectations.
- Tests : SIREN valides, absence de doublons, couverture géographique.
- Un rapport de qualité publié à chaque version : taux d'appariement offre → SIREN, part de champs manquants.

**Versionnement**

- Des versions datées du dataset (tags Hugging Face), pour que les utilisateurs puissent reproduire leurs analyses.
- Un changelog des évolutions de schéma.

**Formats**

- Parquet pour l'analyse, CSV pour l'accessibilité.
- Éventuellement un fichier DuckDB ou SQLite prêt à interroger.

## La documentation : ce qui le rend adoptable

Une documentation claire sur les sources, les licences et les limites est ce qui permet à d'autres de réutiliser le dataset en confiance.

- **Dataset card Hugging Face complète** : description, schéma colonne par colonne, sources, méthode de jointure, limites connues, cas d'usage.
- **Licences claires** : Licence Ouverte 2.0 si toutes les sources le permettent, avec un tableau des sources et de leur licence. Des données ODbL (Stack Overflow Survey) imposent la même licence au dataset dérivé.
- **Mention des sources** : obligatoire avec la Licence Ouverte (INSEE, INPI, DILA, France Travail…).
- **Section « données personnelles »** : les personnes physiques (dirigeants, entrepreneurs individuels) sont exclues, avec une procédure de demande de retrait.
- **Exemples** : un notebook qui répond à une question concrète, par exemple « les éditeurs de logiciels en croissance à Lyon qui recrutent en Python ».

## Les extras qui font la différence

Quatre ajouts rendent le projet utilisable directement par des agents IA et par le grand public.

- **Serveur MCP** : expose le dataset aux agents IA, en cohérence avec le harnais de recherche d'emploi.
- **Démo en ligne** : un Hugging Face Space (Gradio ou Streamlit) pour explorer les entreprises sur une carte.
- **Embeddings** : des descriptions d'entreprises et des taxonomies, pour la recherche sémantique.
- **Dataset d'évaluation** : pour l'appariement offre → SIREN, utile pour comparer des méthodes.

## Ressources publiques à utiliser

Toutes ces ressources sont gratuites et se rejoignent par le SIREN/SIRET (entreprises) ou par les codes ROME/FAP (métiers). Vérifiez la licence de chaque source avant publication.

### Entreprises

| Ressource | Type | Usage dans le projet | Accès et limites |
| --- | --- | --- | --- |
| [API Recherche d'entreprises (DINUM)](https://recherche-entreprises.api.gouv.fr/search?q=DINUM) | API REST | Socle : identité, NAF, effectif, adresse, dirigeants, finances | Gratuite, sans clé, environ 7 appels/s, 25 résultats/page, 10 000 résultats max par recherche ; exclut les entreprises non diffusibles |
| [BODACC (DILA)](https://www.data.gouv.fr/dataservices/672cf66ea47b8d4c15d13d5b) | API Opendatasoft, export CSV/JSON/Excel | Événements : créations, cessions, radiations, procédures collectives | Gratuite, Licence Ouverte 2.0 ; contient des données personnelles |
| [INPI – Documents et comptes des entreprises (RNE)](https://www.data.gouv.fr/datasets/documents-et-comptes-des-entreprises/informations) | API (et SFTP sur demande) | Comptes annuels non confidentiels, actes, statuts, filiales | Gratuite après création d'un compte sur data.inpi.fr |
| [DECP consolidées](https://www.data.gouv.fr/fr/datasets/donnees-essentielles-de-la-commande-publique-consolidees-format-tabulaire/) | Fichiers Parquet et CSV | Marchés publics gagnés : titulaire, montant, code CPV | Mise à jour à peu près quotidienne |
| [scanR – export des organisations](https://www.data.gouv.fr/datasets/export-des-organisations-exposees-dans-scanr/informations) | Dump JSON et API | Entreprises et structures de R&D, liens avec brevets et publications | Open data du ministère de la Recherche |
| Annuaire des Entreprises | Site de consultation | Contrôle manuel des fiches et vérification des jointures | Même source que l'API Recherche d'entreprises |

### Emploi et marché du travail

| Ressource | Type | Usage dans le projet | Accès et limites |
| --- | --- | --- | --- |
| [API ROME 4.0 (France Travail)](https://www.data.gouv.fr/fr/dataservices/672cf64aa47b8d4c15d13d58) | 4 API : compétences, métiers, contextes de travail, fiches métiers | Taxonomie de compétences, codes métiers | Inscription sur francetravail.io ; actualisation du ROME prévue en octobre 2026 |
| [ROME – jeu de données](https://www.data.gouv.fr/datasets/58da857388ee384902e505f5/) | Fichiers xlsx et open data | Arborescence des métiers (14 grands domaines, 110 domaines, 1 911 fiches) | Open data |
| API Offres d'emploi (francetravail.io) | API REST | Offres agrégées par compétence, département et mois | Inscription requise ; conditions d'utilisation à vérifier avant toute redistribution |
| La Bonne Boîte et Marché du travail (francetravail.io) | API REST | Entreprises susceptibles de recruter, statistiques locales | Inscription requise |
| [Enquête BMO (France Travail)](https://www.data.gouv.fr/datasets/561fa564c751df4f2acdbb48) | Fichiers xlsx | Intentions d'embauche et tension par métier et bassin d'emploi | Open data, enquête annuelle, nomenclature FAP 2021 |

### Compétences, tech et géographie

| Ressource | Type | Usage dans le projet | Accès et limites |
| --- | --- | --- | --- |
| ESCO (Commission européenne) | API et fichiers | Taxonomie européenne de compétences, complément de ROME | Open data |
| API GitHub | API REST | Organisations, langages, dépôts actifs par entreprise | Gratuite avec token, limites de débit |
| Stack Overflow Developer Survey | Fichiers CSV | Tendances de technos et de salaires | Licence ODbL : le dataset dérivé doit l'être aussi |
| Wikidata | SPARQL et API | Rapprochement avec le SIREN (propriété P1616) et les sites officiels | Open data |
| API Adresse (Géoplateforme) | API REST | Géocodage des adresses d'établissements | Gratuite |
| API Découpage administratif (geo.api.gouv.fr) | API REST | Communes, départements, EPCI | Gratuite |

### Outils pour agents

- [MCP officiel data.gouv.fr (`datagouv-mcp`)](https://github.com/datagouv/datagouv-mcp) pour interroger le catalogue data.gouv.fr depuis un agent.
- [`mcp-recherche-entreprises`](https://glama.ai/mcp/servers/@yoanbernabeu/mcp-recherche-entreprises) (communautaire, non officiel) pour prototyper rapidement avec l'API Recherche d'entreprises.
- [`search-api` (dépôt officiel)](https://github.com/annuaire-entreprises-data-gouv-fr/search-api) pour la documentation et les exemples de requêtes.

### Points d'attention

- **Données personnelles** : le BODACC et le RNE contiennent des noms de dirigeants et d'entrepreneurs individuels ; la DILA précise que cela n'exonère pas du respect de la loi Informatique et Libertés. Écartez les personnes physiques des datasets publics.
- **Offres d'emploi** : ne publiez que des statistiques agrégées, sauf si les conditions de France Travail autorisent la redistribution.
- **Fraîcheur** : conservez une date de collecte (`fetched_at`) par source ; SIRENE, BODACC et DECP sont quasi quotidiens, le BMO est annuel.
- **Éléments non vérifiés** : les lignes sans lien (ESCO, GitHub, Stack Overflow, Wikidata, API Adresse, geo.api.gouv.fr, API Offres d'emploi, La Bonne Boîte) reposent sur ma connaissance générale ; confirmez leurs conditions d'accès sur les sites officiels.

## Matrice de croisement des sources

Le SIREN relie toutes les sources entreprises ; le code ROME et le code commune INSEE relient les sources emploi et géographie. Les sources sans clé native (offres, GitHub) demandent un appariement par nom, site web ou commune.

### Clés de jointure par source

● clé native · ◐ partielle ou à reconstituer · — absente

| Source | SIREN / SIRET | NAF | Commune (INSEE) / code postal | ROME / FAP | Nom ou site web | Date |
| --- | --- | --- | --- | --- | --- | --- |
| Recherche d'entreprises | ● | ● | ● | — | ● nom, ◐ site | ● création |
| INPI – RNE et comptes | ● | ◐ | ● | — | ● nom | ● dépôt des comptes |
| BODACC | ● | — | ● | — | ● nom | ● parution |
| DECP | ● titulaire et acheteur | — | ◐ | — | ● nom | ● notification |
| scanR | ◐ | — | ◐ | — | ● nom | ◐ |
| API Offres d'emploi | ◐ | ◐ | ● | ● ROME | ● nom, ◐ site | ● publication |
| La Bonne Boîte | ● SIRET | ● | ● | ● ROME | ● nom | — |
| BMO | — | ◐ secteur | ● bassin d'emploi | ● FAP | — | ● année |
| ROME 4.0 | — | — | — | ● ROME | — | ● version |
| ESCO | — | — | — | ◐ | — | — |
| GitHub | — | — | — | — | ◐ organisation | ● |
| Wikidata | ◐ SIREN (P1616) | — | ◐ | — | ● site officiel | — |
| API Adresse et geo.api.gouv.fr | — | — | ● | — | — | — |

### Croisements à réaliser

| Croisement | Clé | Ce que ça produit | Fiabilité | Difficulté |
| --- | --- | --- | --- | --- |
| Recherche d'entreprises × INPI | SIREN | Chiffre d'affaires et résultat sur plusieurs années, filiales | Haute | Faible |
| Recherche d'entreprises × BODACC | SIREN | Événements de vie de l'entreprise, signaux de croissance ou de difficulté | Haute | Faible |
| Recherche d'entreprises × DECP | SIREN (titulaire) | Marchés publics gagnés, nombre et montant | Haute | Faible |
| Recherche d'entreprises × scanR | SIREN, sinon nom + commune | Activité R&D, brevets | Moyenne | Moyenne |
| Recherche d'entreprises × Wikidata | SIREN (P1616) | Site officiel, maison mère | Moyenne, grandes entreprises surtout | Moyenne |
| Site officiel × GitHub | Nom de domaine, nom d'organisation | Organisation GitHub, langages, dépôts actifs | Moyenne à faible | Élevée |
| Offres × entreprises | SIRET si présent, sinon nom normalisé + commune | Offres rattachées à un employeur identifié | Moyenne à faible ; arbitrage LLM pour les cas ambigus | Élevée |
| Offres × ROME 4.0 / ESCO | Code ROME, puis compétences extraites | Compétences normalisées par offre | Moyenne | Moyenne |
| Offres × BMO | ROME → FAP, bassin d'emploi | Tension du recrutement par métier et territoire | Moyenne (tables de passage ROME ↔ FAP) | Moyenne |
| La Bonne Boîte × entreprises | SIRET | Entreprises susceptibles de recruter | Haute | Faible |
| Établissements × API Adresse | Adresse | Latitude et longitude pour les distances et temps de trajet | Haute | Faible |
| Toutes sources × geo.api.gouv.fr | Code commune INSEE | Département, région, EPCI harmonisés | Haute | Faible |

### Ordre de mise en œuvre

1. Socle : Recherche d'entreprises avec géocodage (API Adresse et geo.api.gouv.fr) pour obtenir une table `companies` propre, clé SIREN.
2. Croisements à clé forte : INPI, BODACC, DECP et La Bonne Boîte, tous par SIREN ou SIRET.
3. Référentiels métiers : ROME 4.0 et ESCO, puis la table de passage ROME ↔ FAP pour relier les offres au BMO.
4. Croisements à clé faible : offres → entreprises, Wikidata, GitHub, scanR. Mesurez le taux d'appariement et publiez-le dans le rapport de qualité.

Les marques ●, ◐ et — reposent sur la documentation consultée et sur ma connaissance générale des schémas ; vérifiez-les sur un échantillon de données réelles avant de figer le modèle.

## Par où commencer

Une V1 crédible tient en trois éléments ; les indicateurs et les statistiques d'offres viennent en V2.

**V1**

- [ ] Référentiel des employeurs tech
- [ ] Taxonomie de compétences
- [ ] Pipeline hebdomadaire en CI, avec une dataset card complète

**V2**

- [ ] Indicateurs par entreprise (BODACC, DECP, INPI)
- [ ] Statistiques d'offres agrégées
