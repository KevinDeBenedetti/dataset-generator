# TODO

## 🔴 En cours

## 🟡 À faire
- [ ] REFACTOR(arch): supprimer le staging local redondant des `QASource` à la génération (`QAService.process_qa_pairs` + `pipelines/dataset.py`) → dédup en mémoire et sync direct des items accumulés vers Langfuse ; bénéfice marginal (les `QASource` ne sont plus lus, sauf le `/q_a/id/{qa_id}` mort), risque sur le chemin de génération (non testable en sandbox : SSL) + perte de données si Langfuse down → faire échouer la génération si la persistance Langfuse échoue
- [ ] feat: page /generate => modifier les sources possible pour générer un dataset avec une url, un fichier (pdf, image...) ou un compte github utilisant user + token password pour inspecter l'intégralité d'un compte github (informations public uniquement)
- [ ] feat: ajoute la documentation dynamique dans docs/ pour correspondre parfaitement au workflow réutilisable dans github-workflows et le repo qui déploie la doc kevindebenedetti.github.io
- [ ] FIX(auth): mots de passe dev par défaut faibles (`admin1234`/`user1234`, services/users.py) ; risque réel si `SEED_DEV_USERS` fuit en env partagé (aggravé par l'absence de protection des routes) — exiger des mots de passe explicites hors dev

- [ ] FEAT(auth): refresh token + rotation (la partie « envisager » du rate-limit) — access token JWT court-vécu + refresh token httpOnly long-vécu pour éviter la reconnexion à l'expiration du TTL
- [ ] REFACTOR(arch): supprimer à terme les modèles `Dataset`/`QASource`/`PageSnapshot` (+ migration Alembic de drop, pas suppression des fichiers de révision) — bloqué : le scraper dépend de `PageSnapshot` (cache crawl/clean) et `Dataset` (FK conteneur) ; nécessite de rendre le scraper stateless au préalable

## 🟢 Idées / backlog

## 🤖 Claude — recommandations
- [ ] TEST: les tests qui instancient un vrai client OpenAI/httpx (ex. `DatasetPipeline`→`LLMService`→`openai.OpenAI()`) échouent en sandbox car `ssl.create_default_context` lit le bundle certifi `*.pem` (lecture refusée) — mocker le client à la construction dans ces tests (ou rendre `LLMService` lazy) pour faire tourner toute la suite en sandbox
- [ ] DOCS(auth): ajouter les variables `AUTH_*` et `OIDC_*` à `.env.example` (non modifiable depuis l'agent : bloqué par le sandbox) — documenté dans le README en attendant
- [ ] DOCS(qdrant): ajouter `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION_PREFIX` à `.env.example` (non modifiable depuis l'agent : bloqué par le sandbox) — sinon la page Collections reste en mode « non configuré »
- [ ] PERF(qdrant): `sync_dataset_to_qdrant` embed tous les Q/A en un seul appel `embeddings.create` → batcher (ex. 100/req) pour les gros datasets qui dépasseraient la limite de tokens/taille de requête
- [ ] DOCS(crawl): ajouter `CRAWL_DELAY_SECONDS` et `CRAWL_MAX_PAGES_PER_DOMAIN` à `.env.example` (non modifiable depuis l'agent : bloqué par le sandbox) — sinon les nouveaux garde-fous de coût du crawl restent invisibles
- [ ] FEAT(ui): exposer les contrôles de coût du crawl (`max_depth`, `max_pages`, `crawl_delay_seconds`, `max_pages_per_domain`) dans le formulaire /generate — l'API les accepte déjà mais l'UI ne les envoie pas
- [ ] DOCS(arch): documenter que Langfuse est désormais une **dépendance dure** des datasets (lecture/écriture/suppression renvoient 503 si Langfuse indisponible) — n'a plus de fallback local ; valable car Langfuse n'a pas d'API delete-dataset (le shell vide d'un dataset supprimé persiste)
- [ ] DOCS(auth): ajouter `REDIS_URL` (+ `REDIS_HOST_PORT`/`REDIS_IMAGE` pour compose) à `.env.example` (non modifiable depuis l'agent : bloqué par le sandbox) — sinon le rate-limiter login reste in-process en dev

## ✅ Fait
