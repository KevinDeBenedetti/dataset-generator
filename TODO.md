# TODO

## 🔴 En cours

## 🟡 À faire
- [ ] Ajouter les nouvelles variables d'env au `.env.example` : `CRAWL_MAX_DEPTH`, `CRAWL_MAX_PAGES`, `CRAWL_SAME_DOMAIN`, `LANGFUSE_AUTO_SYNC` (fichier bloqué en écriture côté agent → à faire manuellement)
- [ ] Lancer la stack et tester de bout en bout : redémarrer Docker Desktop (binding fantôme sur le port 8000), puis `make dev` → http://localhost:3000/generate
- [ ] Tester un vrai crawl multi-pages + vérifier la création/versioning du dataset dans Langfuse (runs `v1`, `v2`, …)
- [ ] Lancer la suite serveur complète hors sandbox : `make test` (les échecs SSL/`*.pem` observés sont propres au sandbox)
- [ ] Feat : ajouter un dashboard avec des composants shadcn et un design minimaliste et moderne (suggères moi plusieurs styles de design, je choisirai celui que je préfère)
- [ ] Fix : améliorer l'affichage des logs en env de dev via une variable d'env `DEBUG_LOGS` (ex. `DEBUG_LOGS=1 make dev`) pour afficher les logs FastAPI côté frontend (via SSE) et les logs Next.js côté backend (via un proxy SSE) - ainsi que raccourci pour les afficher dans un petit terminale sur laptop

## 🟢 Idées / backlog

- [ ] Exposer un endpoint `GET /langfuse/versions/{dataset}` pour lister l'historique des runs/versions depuis l'UI
- [ ] Limiter le coût du crawl : option de throttling / budget de pages par domaine
- [ ] Afficher la progression du crawl en temps réel (SSE/websocket) dans la timeline

## 🤖 Claude — recommandations

- [ ] REFACTOR: `pipelines/dataset.py` gate la sync sur `is_langfuse_configured()` (vars présentes) et non `is_langfuse_available()` (auth OK) — une clé invalide logge un warning à chaque génération au lieu d'être détectée une fois au démarrage
- [ ] REFACTOR: `sync_qa_to_langfuse` appelle `dataset.run_experiment` qui exécute `_snapshot_task` sur *tous* les items à chaque sync (coûteux sur gros datasets) — envisager `create_dataset_run_item` directement si l'API le permet
- [ ] TEST: les tests pytest ne tournent pas en sandbox (stat de `.env` refusé) — ajouter `norecursedirs`/`--ignore` ou déplacer le chargement `.env` hors de la racine collectée pour débloquer `make test` en sandbox

## ✅ Fait

- [x] 2026-06-17 — FIX: vérification du code Langfuse après ajout de secrets valides — audit des appels SDK (langfuse 4.9.0) : signatures `create_dataset`/`create_dataset_item`/`get_dataset_runs`/`get_dataset`/`run_experiment`/`auth_check`/`flush` toutes conformes, imports top-level valides, gating défensif OK (aucune correction nécessaire)
- [x] (2026-06-16) Feat : sticky header — `HeaderNav` épinglé (`sticky top-0 z-50`) avec fond `backdrop-blur` translucide, défilement du contenu en dessous
- [x] (2026-06-16) Frontend vérifié : `bun install` + `bun run lint` (eslint OK) + `npx tsc --noEmit` (0 erreur) + `bun run build` (Next.js 16.1.5, 7 pages statiques générées) ✓
- [x] Fix : `server-fastapi` unhealthy — un `datasets.db` local était copié dans l'image (`.dockerignore` ne l'excluait pas), bloquant la migration Alembic au démarrage. `.dockerignore` exclut désormais `*.db`/`*.sqlite`. Rebuild requis (`make reset && make dev`)
- [x] DX : `make dev` ré-affiche les URLs (Next/FastAPI/docs) dans le flux une fois les services `healthy` (waiter en arrière-plan + `trap` de nettoyage)
- [x] Backend : crawl en largeur même-domaine (`crawl_site`), pipeline multi-pages agrégé
- [x] Backend : sync Langfuse à la génération + versioning type DVC (runs `v{n}`, items idempotents)
- [x] Backend : params de requête `crawl`/`max_depth`/`max_pages`/`sync_langfuse` + champs réponse `pages_crawled`/`langfuse`
- [x] Frontend : contrôles de crawl + toggle Langfuse sur la page Generate, badges `pages_crawled`/version dans le résultat
- [x] Tests : crawl BFS/limites/erreurs, versioning Langfuse, agrégation multi-pages (verts hors sandbox)
- [x] Docs : README mis à jour (features, workflow, variables d'env crawl & versioning)
