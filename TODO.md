# TODO

## Features
- Datasets hub sourced from Hugging Face
- Display datasets stored on HF
- Deployment => Supervisor + CI-triggered dataset generation, to use the Claude subscription's tokens

## 🔴 En cours

## 🟡 À faire
- [ ] FIX: l'erreur d'hydratation React (id radix-_R_… mismatch) est un artefact dev-only de Next 16.1.5 (boundary interne en tête de `<body>` côté SSR) — absente en build de production. **Upgrade fait (2026-08-08, Next 16.3.0), re-test toujours non fait.** Vérifié le 2026-08-15 : le conteneur `next` sert bien **16.3.0** (version grepée dans le bundle client servi par `localhost:3020`), donc le `make reset` qu'on croyait nécessaire ne l'est pas — le volume `next_node_modules` est à jour. Ne manque plus que l'observation : une erreur d'hydratation ne se voit que dans la console du navigateur, et l'agent n'a pas de navigateur utilisable ici (Chromium refusé par le bac à sable, `bootstrap_check_in … Permission denied`). **À faire côté humain** : ouvrir http://localhost:3020 et regarder la console.
- [ ] CHORE: 10+ branches `dependabot/bun/apps/next/*` ouvertes sur le remote (react 19.2.7, radix-*, @hey-api/openapi-ts 0.98.2, eslint 10.x alors qu'eslint a été retiré au profit d'oxlint). À trier/fermer une fois la branche mergée, plutôt que de rebaser 10 PR sur un diff de 222 fichiers. (Non fait : la branche n'est pas mergée — la condition posée par la tâche elle-même — et l'API GitHub est injoignable depuis le bac à sable, `tls: failed to verify certificate`. Fermer des PR reste de toute façon une action sortante à décider par toi.)

## 🟢 Idées / backlog

## 🤖 Claude — recommandations

- [ ] CHORE: `.claude/settings.json` et `.claude/settings.local.json` gardent une quinzaine d'entrées de permission qui pointent sur des fichiers supprimés (`tests/services/test_langfuse.py`, `services/langfuse.py`…), plus `Skill(langfuse)` et `WebFetch(domain:langfuse.com)`. Sans effet (elles ne matchent plus rien), mais à nettoyer — je ne peux pas écrire dans ces deux fichiers, le bac à sable me les refuse.
- [ ] FEAT: la page **Exports** reste une maquette statique. Le bouton « Export the copy » ne fait rien alors que `POST /dataset/{name}/duplicate` existe désormais côté serveur ; JSON/JSONL/CSV n'ont, eux, aucun endpoint.
- [ ] TEST: `apps/server/api/q_a.py` (72.41 %) et `api/agent.py` (75.86 %) n'ont plus que les branches non couvertes traitées ce coup-ci ailleurs (`except … -> 503 / 404 / 500`). Les deux tables paramétrées ajoutées à `tests/api/test_dataset.py` se transposent telles quelles — gain rapide.
- [ ] CHORE: `apps/next/tsconfig.typecheck.json` recopie `include`/`exclude` du tsconfig principal pour en retirer `.next` ; TS n'a pas d'héritage partiel sur ces clés, donc un changement d'`include` doit être répercuté dans les deux fichiers.
- [ ] TEST: le nouveau limiteur Redis n'est testé que contre un faux backend — le chemin réel (`RateLimitBackend` + vrai Redis, donc le compteur Lua atomique) n'est vérifié nulle part. Les tests tournent déjà avec testcontainers pour Postgres : un conteneur `redis:7-alpine` fermerait le trou, y compris sur le point qui a motivé la migration (deux `hit` concurrents ne doivent pas dépasser le plafond).
- [ ] DOCS: `AUTH_LOGIN_MAX_ATTEMPTS`, `AUTH_LOGIN_WINDOW_SECONDS`, `REDIS_URL` et les réglages du SDK (`REDIS_PREFIX`, `REDIS_RATE_LIMIT_FAIL_CLOSED`) ne sont documentés que dans les commentaires de `core/config.py` / `services/rate_limit.py` — absents du README et de `.env.example`, alors que le README a déjà un tableau d'env pour le crawl.
- [ ] CHORE: bump de l'image Redis (`redis:7-alpine` → 8.x) : le SDK utilise `INCREX` (Redis ≥ 8.8) quand il est là et retombe sinon sur un script Lua — les deux sont atomiques, mais `INCREX` économise le chargement du script et est le chemin nominal du SDK.
- [ ] TEST: `TestClient.stream()` se bloque indéfiniment sur un générateur SSE sans fin — le pont synchrone attend un corps qui ne se termine jamais. C'est pourquoi `tests/api/test_debug.py` pilote `response.body_iterator` directement. À savoir avant d'écrire le test du prochain endpoint SSE.
- [ ] CHORE: décider du sort de `apps/next/AGENTS.md` et `apps/next/CLAUDE.md` — Next 16.3 les (re)génère à chaque `next dev` (`node_modules/next/dist/server/lib/generate-agent-files.js`) ; soit on les commite, soit on les `.gitignore`, sinon le tree est sale en permanence.
- [ ] FIX: `api-check` compare avec `git diff --exit-code` (donc vs l'index) — un client régénéré mais seulement `git add`é passe au vert en local alors que la CI, elle, échouerait. Utiliser `git diff HEAD --exit-code` pour que local et CI disent la même chose.
- [ ] FEAT: rendre le seeding de dev auto-réparateur au lieu d'idempotent-silencieux — aujourd'hui un compte existant est sauté, donc une ligne périmée (mot de passe d'un ancien `DEV_ADMIN_PASSWORD`) empoisonne le dev sans trace. En développement, réaligner le hash sur le mot de passe attendu plutôt que de sauter.
- [ ] REFACTOR: le seeding est derrière deux verrous (`ENVIRONMENT=development` **et** `SEED_DEV_USERS=true`) ; oublier l'un des deux donne zéro utilisateur et un simple 401. Le déclencher par défaut dès `is_development`, en gardant `SEED_DEV_USERS` comme override explicite hors dev.
- [ ] FIX: chemin relatif au CWD — `script_location = server/migrations` (alembic) ne résout correctement que depuis `apps/`. Lancer l'app depuis la racine du repo échoue avec `Path doesn't exist: server/migrations`. L'ancrer sur un chemin absolu dérivé du package. (Le volet `sqlite:///./datasets.db` est réglé : la base est passée sur PostgreSQL.)
- [ ] CHORE: supprimer les 3 `datasets.db` résiduels sur l'hôte (`./`, `./apps/`, `./apps/server/`) — vestiges de SQLite, plus lus par rien depuis le passage à PostgreSQL. Non tracés par git, donc simple `rm`.
- [ ] DOCS: `.env.example` ne contient pas `ENVIRONMENT` alors que `make env` en fait le `.env` de départ. Sans lui l'app retombe sur `production` : le seeding refuse les mots de passe par défaut et le CORS se limite à `frontend_url` (pas de wildcard localhost). Ajouter `ENVIRONMENT=development` juste au-dessus de `SEED_DEV_USERS=true`.
- [ ] FIX: la suppression (déjà indexée) de `conftest.py` à la racine casse la collecte pytest dans le bac à sable de l'agent — `PermissionError` sur `.env`, avant même le premier test. C'est précisément ce que son `collect_ignore_glob` évitait ; la CI n'est pas touchée (pas de `.env` sur un checkout neuf). Soit le restaurer, soit déplacer l'exclusion dans `pytest.ini` (`norecursedirs`/`--ignore`).
- [ ] CHORE: le mockup statique `/dataset-detail` fait doublon avec la vraie page `/datasets/[id]` désormais portée, mais il héberge le CSS `.dd-page` que celle-ci importe. Si le mockup part, le CSS doit partir avec la page, pas avec lui.
- [ ] FEAT: la page globale `/sources` groupe encore par `metadata.source_url` du *dataset* (donc la seule graine du dernier run) : un crawl de 50 pages y compte pour une source. Elle peut maintenant s'appuyer sur `GET /dataset/{name}/sources`, comme `useAllDatasetRuns` le fait pour les runs.
- [ ] REFACTOR: l'onglet « Q/A pairs » du détail rend encore `QAList`/`QAItem` en Tailwind coloré (bleu/vert/jaune) à l'intérieur du shell `.card` : le reste de la page suit le design system. Porter ces deux composants sur `.qa`/`.qa-meta` (déjà stylés dans `dataset-detail.css`) fermerait l'écart.
- [ ] CHORE: un `next dev` lancé hors Docker écrase le `.next` du conteneur (bind-mount `./apps/next:/app`) et met les deux serveurs en boucle de redémarrage. Documenter le point, ou donner un `distDir` distinct au dev local.

## ✅ Fait
