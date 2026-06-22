# TODO

## 🔴 En cours

## 🟡 À faire
- [ ] Ajouter les nouvelles variables d'env au `.env.example` : `CRAWL_MAX_DEPTH`, `CRAWL_MAX_PAGES`, `CRAWL_SAME_DOMAIN`, `LANGFUSE_AUTO_SYNC` (fichier bloqué en écriture côté agent → à faire manuellement)
- [ ] Lancer la stack et tester de bout en bout : redémarrer Docker Desktop (binding fantôme sur le port 8000), puis `make dev` → http://localhost:3000/generate
- [ ] Tester un vrai crawl multi-pages + vérifier la création/versioning du dataset dans Langfuse (runs `v1`, `v2`, …)
- [ ] Lancer la suite serveur complète hors sandbox : `make test` (les échecs SSL/`*.pem` observés sont propres au sandbox)
- [ ] Feat : ajouter un dashboard avec des composants shadcn et un design minimaliste et moderne (suggères moi plusieurs styles de design, je choisirai celui que je préfère)

## 🟢 Idées / backlog
- [ ] feat(auth): Ajouter l'authentification avec email + password ainsi que via oidc infomaniak / 2 roles : user & admin / ajoute 2 utilisateurs de dev dans le readme
- [ ] feat(auth): Ajouter l'authentification avec email + password ainsi que via oidc infomaniak / 2 roles : user & admin / ajoute 2 utilisateurs de dev dans le readme
- [ ] Exposer un endpoint `GET /langfuse/versions/{dataset}` pour lister l'historique des runs/versions depuis l'UI
- [ ] Limiter le coût du crawl : option de throttling / budget de pages par domaine
- [ ] Afficher la progression du crawl en temps réel (SSE/websocket) dans la timeline

## 🤖 Claude — recommandations

- [ ] REFACTOR: `pipelines/dataset.py` gate la sync sur `is_langfuse_configured()` (vars présentes) et non `is_langfuse_available()` (auth OK) — une clé invalide logge un warning à chaque génération au lieu d'être détectée une fois au démarrage
- [ ] REFACTOR: `sync_qa_to_langfuse` appelle `dataset.run_experiment` qui exécute `_snapshot_task` sur *tous* les items à chaque sync (coûteux sur gros datasets) — envisager `create_dataset_run_item` directement si l'API le permet
- [ ] TEST: les tests pytest ne tournent pas en sandbox (stat de `.env` refusé) — ajouter `norecursedirs`/`--ignore` ou déplacer le chargement `.env` hors de la racine collectée pour débloquer `make test` en sandbox
- [ ] FIX: le healthcheck du service `next` (docker-compose) appelle `http://localhost:3000/api/health` mais aucune route handler `app/api/health/route.ts` n'existe → 404, le conteneur ne passe jamais `healthy` et le waiter de `make dev` peut bloquer — ajouter la route ou corriger le chemin du healthcheck
- [ ] CHORE: dédupliquer les deux lignes identiques `feat(auth)` dans `🟢 Idées / backlog` (ajoutées en double)
- [ ] CHORE: la console de logs dev peut afficher des secrets si du code les logge — OK car gated `DEBUG_LOGS` (jamais en prod), mais documenter ce risque / éviter de logger les valeurs sensibles

## ✅ Fait
