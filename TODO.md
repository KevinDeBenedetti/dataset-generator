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
