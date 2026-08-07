# TODO

> Audit du 2026-08-05 — branche `feat/google-adk`, 21 commits d'avance sur
> `origin/main`, synchro avec `origin/feat/google-adk`. Diff : 222 fichiers,
> +24 858 / −6 219. Working tree propre hormis 2 fichiers indexés
> (`.gitignore` : dé-ignore `TODO.md` ; `TODO.md` ajouté).
>
> État vérifié localement : `pytest` **352 passed**, couverture **86.45 %**
> (seuil CI 70 %), `ruff check` + `ruff format --check` + `ty check` OK.
> Chaîne Alembic linéaire, une seule head (`a7b8c9d0e1f2`).
> Front non vérifiable dans cette session (l'install `bun` passe par proto et
> le registre de plugins ghcr.io est bloqué) → `oxlint` / `tsc` / `vitest` non exécutés.

## 🔴 En cours

## 🟡 À faire


## 🟢 Idées / backlog

- [ ] FIX: l'erreur d'hydratation React (id radix-_R_… mismatch) est un artefact dev-only de Next 16.1.5 (boundary interne en tête de `<body>` côté SSR) — absente en build de production. **Bloquée** : à re-tester après l'upgrade Next (16.1.5 → 16.3.0 disponible), pas avant d'investiguer davantage.
- [ ] CHORE: 10+ branches `dependabot/bun/apps/next/*` ouvertes sur le remote (react 19.2.7, radix-*, @hey-api/openapi-ts 0.98.2, eslint 10.x alors qu'eslint a été retiré au profit d'oxlint). À trier/fermer une fois la branche mergée, plutôt que de rebaser 10 PR sur un diff de 222 fichiers.

## 🤖 Claude — recommandations

- [ ] TEST: `apps/server/api/debug.py` est à 0 % de couverture (27/27 lignes non couvertes) — c'est un endpoint SSE non authentifié (monté sans `auth_required` dans `main.py`, seulement gaté par `DEBUG_LOGS`) qui diffuse les logs bruts ; au minimum un test vérifiant qu'il n'est PAS monté quand `DEBUG_LOGS` est absent.
- [ ] TEST: couverture faible sur `apps/server/api/collections.py` (58.97 %) et `apps/server/api/dataset.py` (69.14 %) — sous le seuil CI de 70 % pris fichier par fichier, tenu uniquement par la moyenne globale (86.45 %).
- [ ] CHORE(URGENT): relancer `make api-client` (API démarrée) et commiter le résultat — `baseUrl: false` et `entryFile: false` viennent d'être ajoutés à `openapi-ts.config.ts`, donc le `client.gen.ts` versionné (qui contient encore `baseUrl: 'http://localhost:8020'`) ne correspond plus à ce que le générateur produit ; le nouveau job CI « API client drift » restera rouge jusque-là.
- [ ] CHORE: avertissement de dépréciation au runtime des tests — `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead`. À traiter avant qu'il ne devienne une erreur.
- [ ] DOCS: `docs/` ne contient que `crawling.md` et `getting-started.md`, alors que l'auth (JWT + refresh tokens rotatifs, OIDC, rate-limit login) n'est documentée que dans le README. Vu que la CI publie `docs/` sur le site central, un `docs/authentication.md` serait mieux placé.
- [ ] CHORE: la CI n'exécute pas `run-typecheck` côté Node (`ci-cd.yml`, `run-typecheck: false`) — aucun `tsc --noEmit` ne garde le front, seul oxlint tourne.

## ✅ Fait

- [x] 2026-08-05 — FEAT: `apps/next/api/index.ts` supprimé plutôt que documenté — `output.entryFile: false` ajouté dans `openapi-ts.config.ts` (option vérifiée présente dans le `@hey-api/openapi-ts` 0.99.0 épinglé, défaut `true`), fichier retiré via `git rm`. Vérifié qu'aucun code applicatif n'importait `@/api`. Motif : le barrel exposait la surface brute `sdk.gen`, un second chemin d'appel qui contourne le refresh de session silencieux de `sdk.ts`. Commentaires de `sdk.ts` / `types.ts` réalignés.
- [x] 2026-08-05 — TEST: job CI « API client drift » — `apps/server/scripts/dump_openapi.py` (dump du schéma sans démarrer de serveur, `/debug/logs` exclu, 30 paths), cibles `make api-schema` / `make api-check`, job GitHub Actions (actions épinglées par SHA) ajouté en `needs` de `release`, `openapi.json` gitignoré, README documenté. `baseUrl: false` ajouté au plugin client dans `openapi-ts.config.ts` : sans ça la sortie dépendait de l'URL d'entrée et le check n'aurait jamais pu être vert. **Le premier run CI échouera** tant que `make api-client` n'aura pas été relancé et le résultat commité (le `client.gen.ts` versionné contient encore `baseUrl: 'http://localhost:8020'`).
- [x] 2026-08-05 — REFACTOR: états de chargement react-query passés sur `isPending` dans `datasets/page.tsx`, `datasets/[id]/page.tsx`, `jobs/page.tsx`, `sources/page.tsx`, `agent-test/page.tsx` et `quality/page.tsx` (variable renommée `datasetsPending`). **Cas particulier traité** : `statsQuery` est `enabled: !!selectedDataset` et une requête désactivée reste `pending` indéfiniment — le swap seul aurait figé « Loading scores… » ; la condition est donc gardée par `selectedDataset`. Vérifié qu'aucune autre requête migrée n'est conditionnellement désactivée (`useDatasets`, `useLangfuseDatasets`, `useAllDatasetRuns`, `openai-models` sont toujours actives). **Non vérifié au runtime** (`bun install` bloqué dans cette session).
- [x] 2026-08-05 — DOCS: ports du tableau de services exprimés en variables (`NEXT_PORT` / `SERVER_PORT` + défauts compose) plutôt qu'en URLs figées, avec renvoi aux URLs que `make dev` affiche. Choix délibéré de ne PAS écrire 3020/8020 en dur : `docs/` est publié sur le site public, le slot 2 appartient au `.env` local.
- [x] 2026-08-05 — DOCS: contradiction Langfuse levée — comportement vérifié dans le code (`_require_langfuse()` → `LangfuseUnavailableError` → 503 sur tous les endpoints de lecture). Le README disait juste ; c'est docs/getting-started.md (« Optional: Langfuse keys ») et le commentaire de `.env.example` qui étaient faux, tous deux corrigés.
- [x] 2026-08-05 — DOCS: cibles Make inexistantes corrigées — `make start`/`make stop`/`make build-cache`/`make rebuild` remplacées par les vraies cibles dans le Quick Start du README et dans docs/getting-started.md (bloc « Useful commands » réécrit à partir du Makefile). Vérifié : les 9 cibles citées existent toutes.
- [x] 2026-08-05 — REFACTOR: `apps/next/middleware.ts` → `apps/next/proxy.ts` (`git mv`, export `middleware` renommé `proxy`), convention Next 16. Aucun flag `skipMiddlewareUrlNormalize`/`experimental.middleware*` à migrer dans `next.config.ts`, `Dockerfile` en `COPY . .`. Commentaires et README réalignés. **Non vérifié au runtime** : `bun install` est bloqué dans cette session (registre de plugins proto/ghcr.io injoignable), donc ni `next build` ni `next dev` n'ont pu tourner.
- [x] 2026-08-05 — FIX: CORS restreint — `allow_origins=["*"]` remplacé par `config.cors_allow_origins` (nouvelle var `CORS_ALLOW_ORIGINS`, repli sur `FRONTEND_URL`) plus un `allow_origin_regex` localhost actif uniquement quand `ENVIRONMENT=development`. `apps/server/core/config.py`, `apps/server/main.py`, README (tableau auth + explication), 5 tests dans `apps/server/tests/core/test_config.py`.
- [x] 2026-08-05 — FIX: `.env.example` — retrait des variables mortes `VITE_API_BASE_URL` (pas de Vite dans le repo) et `OWUI_URL` / `OWUI_TOKEN` (`api/owui.py` supprimé sur cette branche). Contenu livré à l'utilisateur (écriture sur `.env.example` refusée par le sandbox).
- [x] 2026-08-05 — FIX: `.env.example` — ports alignés sur le slot 2 du projet (`NEXT_PORT=3020`, `SERVER_PORT=8020`, `NEXT_PUBLIC_API_BASE_URL=http://localhost:8020`, `FRONTEND_URL=http://localhost:3020`), `NEXT_HOST_PORT`/`SERVER_HOST_PORT` conservés en surcharge optionnelle, espace parasite retiré sur `QDRANT_URL`. Contenu livré à l'utilisateur.
- [x] 2026-08-05 — FIX(URGENT): `.env.example` — ajout des 20 variables manquantes (`AUTH_SECRET_KEY`, `ENVIRONMENT`, `DATABASE_URL`, `FRONTEND_URL`, `REDIS_URL`, `DEBUG_LOGS`, `API_INTERNAL_BASE_URL`, `AUTH_TOKEN_TTL_SECONDS`, `AUTH_COOKIE_NAME`, `AUTH_COOKIE_SECURE`, `AUTH_LOGIN_MAX_ATTEMPTS`, `AUTH_LOGIN_WINDOW_SECONDS`, `NEXT_PUBLIC_AUTH_COOKIE_NAME`, `OIDC_*`, `CRAWL4AI_*`, `CRAWL_MAX_PAGES_PER_DOMAIN`, `OPENAI_REASONING_EFFORT`, `DEV_ADMIN_PASSWORD`, `DEV_USER_PASSWORD`), chacune commentée. `LANGFUSE_BASE_URL` documenté comme alias de `LANGFUSE_HOST` plutôt que dupliqué. Contenu livré à l'utilisateur.
- [x] 2026-08-05 — CHORE: préparer la PR `feat/google-adk` → `main` — titre de squash retenu `feat!: authentification, stockage Langfuse/Qdrant et refonte de l'app Next` (bump `v0.7.7` → `v0.8.0` avec release-please `simple` en 0.x) ; corps de PR complet + liste des breaking changes rédigés dans le brouillon de session.
