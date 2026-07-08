# TODO

## 🔴 En cours

## 🟡 À faire
- [ ] REFACTOR(arch): supprimer à terme les modèles `Dataset`/`QASource` (+ migration Alembic de drop, pas suppression des fichiers de révision). `PageSnapshot`/`CleanedText` **sont déjà droppés** (voir ✅ Fait). **Reste** : dropper `Dataset`/`QASource` supposerait de faire lire `/langfuse/export` + `/langfuse/preview` ailleurs que la DB locale (ex. re-sync direct depuis Langfuse, déjà source de vérité pour les autres lectures) — décision produit **explicitement écartée** cette session au profit de garder `QASource` comme store d'export (voir historique ✅ Fait). Sans cette décision, `Dataset`/`QASource` restent nécessaires : `QASource` sert de store `/langfuse/export`/`/langfuse/preview` (bouton d'export UI live) et la dédup en mémoire ; `Dataset` reste conteneur FK tant que `QASource` existe. Bloqué sur une décision produit, pas sur du travail technique

## 🟢 Idées / backlog
- [ ] feat: ajouter le badget du nombre de collections générer avec qdrant sur le menu 'colelctions' de la side bar
- [ ] fix: server-fastapi  | WARNI [root] Skipping https://kevindb.dev/: Failed to crawl https://kevindb.dev/: {"detail":"URL blocked (SSRF protection): URL resolves to a blocked address"}

## 🤖 Claude — recommandations
- [ ] CHORE(next): régénérer le SDK frontend (`apps/next` → `npm run api:generate`) après la suppression de la route `/q_a/id/{qa_id}` **et** l'ajout de `POST /dataset/generate/file` et `POST /dataset/generate/github` — `getQaByIdQAIdQaIdGet` reste exporté (mort) et les nouveaux endpoints fichier/github ne sont pas encore dans le client généré (nécessite le serveur lancé pour dumper l'OpenAPI)
- [ ] DOCS: documenter `OPENAI_VLM_MODEL` comme **requis** pour la source fichier (le endpoint `/dataset/generate/file` renvoie 400 « No vision model configured » sans lui)
- [ ] PERF(github): `fetch_account_docs` est séquentiel (1 repo après l'autre, plusieurs appels API/repo) — pour un compte avec beaucoup de dépôts, paralléliser/limiter (et exposer `max_repos` dans l'UI) éviterait les temps longs et la pression rate-limit
- [ ] TEST: les tests qui instancient un vrai client OpenAI/httpx (ex. `DatasetPipeline`→`LLMService`→`openai.OpenAI()`) échouent en sandbox car `ssl.create_default_context` lit le bundle certifi `*.pem` (lecture refusée) — mocker le client à la construction dans ces tests (ou rendre `LLMService` lazy) pour faire tourner toute la suite en sandbox
- [ ] DOCS(auth): ajouter les variables `AUTH_*` et `OIDC_*` à `.env.example` (non modifiable depuis l'agent : bloqué par le sandbox) — documenté dans le README en attendant ; **inclure les nouvelles** `AUTH_REFRESH_TOKEN_TTL_SECONDS` et `AUTH_REFRESH_COOKIE_NAME` (+ `NEXT_PUBLIC_REFRESH_COOKIE_NAME` côté front si custom)
- [ ] CHORE(auth): purge périodique de la table `refresh_tokens` — les lignes expirées/révoquées ne sont jamais supprimées (croissance illimitée). Ajouter un `DELETE WHERE revoked_at IS NOT NULL OR expires_at < now()` (tâche startup ou cron) — non bloquant tant que le volume est faible
- [ ] TEST(next): l'intercepteur de refresh `api/sdk.ts` (dédup `refreshInFlight`, rejeu de la requête, garde `NO_REFRESH_PATHS`) n'est couvert par aucun test — non exécutable en sandbox (toolchain front dans Docker) ; ajouter un test vitest avec `fetch` mocké quand la CI front tourne
- [ ] DOCS(qdrant): ajouter `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION_PREFIX` à `.env.example` (non modifiable depuis l'agent : bloqué par le sandbox) — sinon la page Collections reste en mode « non configuré »
- [ ] PERF(qdrant): `sync_dataset_to_qdrant` embed tous les Q/A en un seul appel `embeddings.create` → batcher (ex. 100/req) pour les gros datasets qui dépasseraient la limite de tokens/taille de requête
- [ ] DOCS(crawl): ajouter `CRAWL_DELAY_SECONDS` et `CRAWL_MAX_PAGES_PER_DOMAIN` à `.env.example` (non modifiable depuis l'agent : bloqué par le sandbox) — sinon les nouveaux garde-fous de coût du crawl restent invisibles
- [ ] FEAT(ui): exposer les contrôles de coût du crawl (`max_depth`, `max_pages`, `crawl_delay_seconds`, `max_pages_per_domain`) dans le formulaire /generate — l'API les accepte déjà mais l'UI ne les envoie pas
- [ ] DOCS(arch): documenter que Langfuse est désormais une **dépendance dure** des datasets (lecture/écriture/suppression renvoient 503 si Langfuse indisponible) — n'a plus de fallback local ; valable car Langfuse n'a pas d'API delete-dataset (le shell vide d'un dataset supprimé persiste)
- [ ] DOCS(auth): ajouter `REDIS_URL` (+ `REDIS_HOST_PORT`/`REDIS_IMAGE` pour compose) à `.env.example` (non modifiable depuis l'agent : bloqué par le sandbox) — sinon le rate-limiter login reste in-process en dev

## ✅ Fait
