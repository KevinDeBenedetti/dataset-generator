# TODO

## 🔴 En cours

## 🟡 À faire
- [ ] FIX(apps/next): 8 erreurs d'accessibilité réelles remontées par `jsx-a11y` (désormais en `warn` dans `.oxlintrc.json` pour ne pas casser la CI) — `label-has-associated-control`/`control-has-associated-label` dans `dataset-detail`, `dataset-generate`, `exports`, `jobs`, `prompts`, et `anchor-is-valid` dans `settings`/`app-sidebar` (lien "Legal notice" avec `href="#"`)

## 🟢 Idées / backlog
- [ ] fix: server-fastapi  | WARNI [root] Skipping https://kevindb.dev/: Failed to crawl https://kevindb.dev/: {"detail":"URL blocked (SSRF protection): URL resolves to a blocked address"}
- [ ] CHORE(apps/next): lancer `bun run format` une bonne fois sur tout `apps/next` pour établir la baseline oxfmt (68 fichiers non formatés actuellement, `format:check` échoue) — pas fait automatiquement ici car risqué à exécuter en une seule fois en session ; à faire dans un commit dédié « formatting only »

## 🤖 Claude — recommandations
- [ ] DOCS(auth): ajouter les variables `AUTH_*` et `OIDC_*` à `.env.example` (non modifiable depuis l'agent : bloqué par le sandbox) — documenté dans le README en attendant ; **inclure les nouvelles** `AUTH_REFRESH_TOKEN_TTL_SECONDS` et `AUTH_REFRESH_COOKIE_NAME` (+ `NEXT_PUBLIC_REFRESH_COOKIE_NAME` côté front si custom)
- [ ] DOCS(qdrant): ajouter `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION_PREFIX` à `.env.example` (non modifiable depuis l'agent : bloqué par le sandbox) — sinon la page Collections reste en mode « non configuré »
- [ ] DOCS(crawl): ajouter `CRAWL_DELAY_SECONDS` et `CRAWL_MAX_PAGES_PER_DOMAIN` à `.env.example` (non modifiable depuis l'agent : bloqué par le sandbox) — sinon les nouveaux garde-fous de coût du crawl restent invisibles
- [ ] DOCS(auth): ajouter `REDIS_URL` (+ `REDIS_HOST_PORT`/`REDIS_IMAGE` pour compose) à `.env.example` (non modifiable depuis l'agent : bloqué par le sandbox) — sinon le rate-limiter login reste in-process en dev
- [ ] FIX(.claude/launch.json): la config `server-openapi` lance `uvicorn server.main:app` depuis la racine du repo alors que le package `server` vit dans `apps/server` — `ModuleNotFoundError: No module named 'server'`, ajuster `cwd`/le module path
- [ ] CHORE(repo): les liens `KevinDeBenedetti/dataset-generator` (README badges, `app/page.tsx`, `app-topbar.tsx`, `docs/*.md`, workflows CI) n'ont volontairement pas été touchés — ce sont des références techniques réelles (badges CI/Codecov, workflow réutilisable) et pas des données personnelles privées ; à généricifier seulement si l'objectif est un vrai template forkable, sinon laisser tel quel

## ✅ Fait
- [x] 2026-07-10 — FIX(apps/next): suppression des informations personnelles codées en dur dans l'UI — nom/email fictifs dans `settings/page.tsx` (Profile) et copyright `app/page.tsx` remplacés par les vraies données utilisateur (`useCurrentUser`) ou neutralisés ; helper `initialsFor` mutualisé dans `lib/utils.ts` (déjà utilisé par `app-sidebar.tsx`)
- [x] 2026-07-10 — FIX(apps/next): `typescript` redescendu à `^5.9.3` (le bump WIP non commité vers `^7.0.2` cassait la transpilation de `next.config.ts`) et `Github` remplacé par `GitBranch` dans `app/page.tsx` (icône supprimée par le bump `lucide-react@1.24.0`) — corrige le crash-loop Docker `next` et le 500 sur `/`
- [x] 2026-07-10 — FEAT: ajouter un bouton logout discret dans le menu utilisateur de la sidebar, via un nouveau composant shadcn `DropdownMenu` (`@radix-ui/react-dropdown-menu`)
- [x] 2026-07-10 — FEAT: suggestion d'un plan d'amélioration DX/maintenance (voir résumé de session — non implémenté, plan proposé uniquement)
- [x] 2026-07-10 — FEAT: amélioration des dépendances Next.js — remplacement d'eslint par oxlint (lint) et ajout d'oxfmt (format), configs `.oxlintrc.json`/`.oxfmtrc.json`, mise à jour des hooks pre-commit et de la doc (`.prek.md`, `copilot-instructions.md`)
- [x] 2026-07-09 — FEAT: ajouter le badge du nombre de collections générées avec Qdrant sur le menu 'Collections' de la sidebar
