# TODO

## 🔴 En cours

## 🟡 À faire
- [ ] feat: ajouter le badget du nombre de collections générer avec qdrant sur le menu 'colelctions' de la side bar

## 🟢 Idées / backlog
- [ ] fix: server-fastapi  | WARNI [root] Skipping https://kevindb.dev/: Failed to crawl https://kevindb.dev/: {"detail":"URL blocked (SSRF protection): URL resolves to a blocked address"}

## 🤖 Claude — recommandations
- [ ] DOCS(auth): ajouter les variables `AUTH_*` et `OIDC_*` à `.env.example` (non modifiable depuis l'agent : bloqué par le sandbox) — documenté dans le README en attendant ; **inclure les nouvelles** `AUTH_REFRESH_TOKEN_TTL_SECONDS` et `AUTH_REFRESH_COOKIE_NAME` (+ `NEXT_PUBLIC_REFRESH_COOKIE_NAME` côté front si custom)
- [ ] DOCS(qdrant): ajouter `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION_PREFIX` à `.env.example` (non modifiable depuis l'agent : bloqué par le sandbox) — sinon la page Collections reste en mode « non configuré »
- [ ] DOCS(crawl): ajouter `CRAWL_DELAY_SECONDS` et `CRAWL_MAX_PAGES_PER_DOMAIN` à `.env.example` (non modifiable depuis l'agent : bloqué par le sandbox) — sinon les nouveaux garde-fous de coût du crawl restent invisibles
- [ ] DOCS(auth): ajouter `REDIS_URL` (+ `REDIS_HOST_PORT`/`REDIS_IMAGE` pour compose) à `.env.example` (non modifiable depuis l'agent : bloqué par le sandbox) — sinon le rate-limiter login reste in-process en dev

## ✅ Fait
