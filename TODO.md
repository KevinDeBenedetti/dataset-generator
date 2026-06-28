# TODO

## 🔴 En cours

## 🟡 À faire


## 🟢 Idées / backlog
- [ ] Limiter le coût du crawl : option de throttling / budget de pages par domaine

## 🤖 Claude — recommandations
- [ ] TEST: les tests qui instancient un vrai client OpenAI/httpx (ex. `DatasetPipeline`→`LLMService`→`openai.OpenAI()`) échouent en sandbox car `ssl.create_default_context` lit le bundle certifi `*.pem` (lecture refusée) — mocker le client à la construction dans ces tests (ou rendre `LLMService` lazy) pour faire tourner toute la suite en sandbox
- [ ] DOCS(auth): ajouter les variables `AUTH_*` et `OIDC_*` à `.env.example` (non modifiable depuis l'agent : bloqué par le sandbox) — documenté dans le README en attendant
- [ ] FIX: `_parse_qa_list` (services/agent.py) court-circuite sur le 1er tableau JSON non vide même si tous les items échouent à la validation (`if raw_items: break`, salvage gardé par `not raw_items`) → un objet valide situé ailleurs n'est plus récupéré (régression vs ancien fallthrough array→object)
- [ ] FIX(auth): le `matcher` de `middleware.ts` n'exclut pas les assets de `public/` (file.svg, globe.svg…) → une requête non authentifiée sur ces assets est redirigée vers /login au lieu d'être servie
- [ ] FIX: la regex de salvage `\{[^{}]*\}` (services/agent.py) ne matche que les objets JSON plats → tout item dont answer/context contient `{`/`}` (ou JSON imbriqué) est ignoré sur réponse tronquée
- [ ] FIX: `analyzeSimilarities`/`cleanSimilarities` (api/sdk.ts) construisent l'URL avec `threshold ? …` → un `threshold=0` valide est silencieusement ignoré (fallback au défaut serveur)
- [ ] FIX(auth): `useLogin` (hooks/use-auth.ts) redirige toujours vers `/dashboard` et ignore le `?from=` posé par le middleware → le deep-link demandé avant login est perdu
- [ ] FIX(auth): mots de passe dev par défaut faibles (`admin1234`/`user1234`, services/users.py) ; risque réel si `SEED_DEV_USERS` fuit en env partagé (aggravé par l'absence de protection des routes) — exiger des mots de passe explicites hors dev
- [ ] REFACTOR(auth): `OctKey.import_key` et `JWTClaimsRegistry()` sont reconstruits à chaque requête dans `decode_access_token` (services/auth.py) — les mettre en cache au niveau module (le secret ne change pas dans le process)
- [ ] DOCS(qdrant): ajouter `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION_PREFIX` à `.env.example` (non modifiable depuis l'agent : bloqué par le sandbox) — sinon la page Collections reste en mode « non configuré »
- [ ] FEAT(qdrant): ajouter un service `qdrant` à `docker-compose.yml` (ex. `qdrant/qdrant`) pour que la feature Collections marche en dev sans instance externe
- [ ] PERF(qdrant): `sync_dataset_to_qdrant` embed tous les Q/A en un seul appel `embeddings.create` → batcher (ex. 100/req) pour les gros datasets qui dépasseraient la limite de tokens/taille de requête
- [ ] FEAT(qdrant): exposer un endpoint de recherche sémantique (`POST /collections/{id}/search`) qui embed la requête et interroge Qdrant — la feature ne fait qu'ingérer pour l'instant, sans lecture
- [ ] FEAT(auth): réserver les opérations destructrices/coûteuses (`DELETE /dataset/{id}`, `clean-similarities`, `POST /collections/{id}/qdrant`) à `require_admin` — toutes les routes sont maintenant authentifiées mais un simple `user` peut tout supprimer/déclencher
- [ ] FEAT(auth): refresh token + rotation (la partie « envisager » du rate-limit) — access token JWT court-vécu + refresh token httpOnly long-vécu pour éviter la reconnexion à l'expiration du TTL
- [ ] REFACTOR(auth): le rate-limiter login est in-process (`services/rate_limit.py`) → non partagé entre workers/réplicas ; passer sur Redis (ou un limit edge/WAF) pour un déploiement multi-worker
- [ ] REFACTOR(arch): supprimer le staging local redondant des `QASource` à la génération (`QAService.process_qa_pairs` + `pipelines/dataset.py`) → dédup en mémoire et sync direct des items accumulés vers Langfuse ; bénéfice marginal (les `QASource` ne sont plus lus, sauf le `/q_a/id/{qa_id}` mort), risque sur le chemin de génération (non testable en sandbox : SSL) + perte de données si Langfuse down → faire échouer la génération si la persistance Langfuse échoue
- [ ] REFACTOR(arch): supprimer à terme les modèles `Dataset`/`QASource`/`PageSnapshot` (+ migration Alembic de drop, pas suppression des fichiers de révision) — bloqué : le scraper dépend de `PageSnapshot` (cache crawl/clean) et `Dataset` (FK conteneur) ; nécessite de rendre le scraper stateless au préalable
- [ ] DOCS(arch): documenter que Langfuse est désormais une **dépendance dure** des datasets (lecture/écriture/suppression renvoient 503 si Langfuse indisponible) — n'a plus de fallback local ; valable car Langfuse n'a pas d'API delete-dataset (le shell vide d'un dataset supprimé persiste)
- [ ] feat: ajoute la documentation dynamique dans docs/ pour correspondre parfaitement au workflow réutilisable dans github-workflows et le repo qui déploie la doc kevindebenedetti.github.io

## ✅ Fait
- [x] 2026-06-28 — REFACTOR(arch): **migration SoT Langfuse fonctionnellement complète** — create (`POST /dataset` → `create_dataset`) et delete (`DELETE /dataset/{name}` → suppression des items Langfuse + cascade collection Qdrant via `delete_collection_for`) rebranchés sur Langfuse, clés par **nom** ; tests + vérif live (400 dup, 404). Langfuse n'ayant pas d'API delete-dataset (confirmé via docs/context7), le shell de dataset vide reste. `Dataset`/`PageSnapshot` conservés comme infra de scraping. La divergence local↔Langfuse (symptôme badge 0 vs 2) est résolue : lectures + create + delete sont sur Langfuse.
- [x] 2026-06-28 — REFACTOR(arch): **lectures datasets rebranchées sur Langfuse** (source de vérité) — `/collections` + sync Qdrant (Phase 2a), `/dataset` liste/détail, `/q_a`, `analyze`/`clean-similarities` (Phase 2b), tous clés par **nom**. Nouveau service `dataset_reads.py` + `get_dataset_items`/`delete_dataset_item` via REST (la SDK rejette les serveurs sans `media_references`). Frontend rebranché sur le nom. Tests + vérif live. (Écritures/suppressions encore locales → Phase 3) — badge « Datasets » alimenté par le vrai nombre via `useLangfuseDatasets` (même source que la page /datasets, cache react-query partagé) ; suppression des compteurs fictifs Sources (11) et Jobs (3)
- [x] 2026-06-28 — FIX(auth): `getCurrentUser` (api/sdk.ts) ne renvoie `null` que sur 401 et lève sur 5xx/réseau ; `useCurrentUser` repasse en `retry: 2` → une erreur transitoire ne déconnecte plus l'UI (pas de test FE : aucun harness côté next)
- [x] 2026-06-28 — FIX(auth): `upsert_oidc_user` ne lie/n'utilise l'email que s'il est vérifié (`email_verified`), sinon compte distinct sous `{sub}@oidc.local` → anti-takeover ; claim coercé (bool/"true") dans le callback ; tests service + API (dont scénario d'attaque)
- [x] 2026-06-28 — FEAT(auth): rate-limit anti-brute-force sur `POST /auth/login` (sliding-window in-process par IP, `AUTH_LOGIN_MAX_ATTEMPTS`/`AUTH_LOGIN_WINDOW_SECONDS`, 429 + `Retry-After`, reset au succès) ; tests unitaires + API ; vérifié en live
- [x] 2026-06-28 — FIX(migrations): `env.py` résout l'URL avec priorité (URL passée par l'appelant → OS `DATABASE_URL` → défaut sqlite) au lieu d'écraser l'URL fournie par le défaut sqlite ; 2 tests fonctionnels (`tests/migrations/test_env.py`)
- [x] 2026-06-28 — FEAT(auth): protection de toutes les routes feature (dataset/generate/q_a/openai/agent/collections/langfuse) derrière `get_current_user` via `include_router(dependencies=…)` dans main.py ; fetch SSE frontend passé en `credentials: 'include'` ; vérifié en live (401 sans auth, 200 avec cookie)
- [x] 2026-06-28 — FEAT: page Collections (datasets projetés en collections Qdrant) + backend d'ingestion vers Qdrant (service, endpoints `/collections`, embeddings OpenAI, dégradation gracieuse si Qdrant non configuré)
