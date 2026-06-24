# TODO

## 🔴 En cours

## 🟡 À faire
- [ ] feat: ajouter une page collections pour afficher les collections qui sont les datasets avec la possibilité de les ajouter dans qdrant

## 🟢 Idées / backlog
- [ ] Limiter le coût du crawl : option de throttling / budget de pages par domaine

## 🤖 Claude — recommandations
- [ ] TEST: les tests qui instancient un vrai client OpenAI/httpx (ex. `DatasetPipeline`→`LLMService`→`openai.OpenAI()`) échouent en sandbox car `ssl.create_default_context` lit le bundle certifi `*.pem` (lecture refusée) — mocker le client à la construction dans ces tests (ou rendre `LLMService` lazy) pour faire tourner toute la suite en sandbox
- [ ] FEAT(auth): protéger les routes existantes (dataset/generate/q_a/langfuse/agent) derrière `get_current_user` / `require_admin` — actuellement toute l'API est publique, l'auth seule n'apporte rien tant que les endpoints ne sont pas gardés
- [ ] FIX(migrations): `migrations/env.py` ignore la variable d'env OS `DATABASE_URL` (il lit l'option Alembic `DATABASE_URL` ou retombe sur `sqlite:///./datasets.db`), donc `upgrade_db(db_url)` migre la mauvaise base si `DATABASE_URL` est défini — faire lire `os.environ["DATABASE_URL"]` dans env.py
- [ ] FEAT(auth): limiter le débit des tentatives sur `POST /auth/login` (anti-brute-force) + envisager un refresh token / rotation
- [ ] DOCS(auth): ajouter les variables `AUTH_*` et `OIDC_*` à `.env.example` (non modifiable depuis l'agent : bloqué par le sandbox) — documenté dans le README en attendant
- [ ] FIX(auth): vérifier le claim `email_verified` dans `upsert_oidc_user` (services/oidc.py) avant de lier une identité OIDC à un compte local par email — sinon takeover de compte si l'IdP renvoie un email non vérifié correspondant à un admin existant
- [ ] FIX(auth): `getCurrentUser` (api/sdk.ts) renvoie `null` sur toute erreur (pas seulement 401) + `useCurrentUser` en `retry:false` → un 5xx/coupure transitoire déconnecte l'UI ; distinguer le 401 des autres erreurs
- [ ] FIX: `_parse_qa_list` (services/agent.py) court-circuite sur le 1er tableau JSON non vide même si tous les items échouent à la validation (`if raw_items: break`, salvage gardé par `not raw_items`) → un objet valide situé ailleurs n'est plus récupéré (régression vs ancien fallthrough array→object)
- [ ] FIX(auth): le `matcher` de `middleware.ts` n'exclut pas les assets de `public/` (file.svg, globe.svg…) → une requête non authentifiée sur ces assets est redirigée vers /login au lieu d'être servie
- [ ] FIX: la regex de salvage `\{[^{}]*\}` (services/agent.py) ne matche que les objets JSON plats → tout item dont answer/context contient `{`/`}` (ou JSON imbriqué) est ignoré sur réponse tronquée
- [ ] FIX: `analyzeSimilarities`/`cleanSimilarities` (api/sdk.ts) construisent l'URL avec `threshold ? …` → un `threshold=0` valide est silencieusement ignoré (fallback au défaut serveur)
- [ ] FIX(auth): `useLogin` (hooks/use-auth.ts) redirige toujours vers `/dashboard` et ignore le `?from=` posé par le middleware → le deep-link demandé avant login est perdu
- [ ] FIX(auth): mots de passe dev par défaut faibles (`admin1234`/`user1234`, services/users.py) ; risque réel si `SEED_DEV_USERS` fuit en env partagé (aggravé par l'absence de protection des routes) — exiger des mots de passe explicites hors dev
- [ ] REFACTOR(auth): `OctKey.import_key` et `JWTClaimsRegistry()` sont reconstruits à chaque requête dans `decode_access_token` (services/auth.py) — les mettre en cache au niveau module (le secret ne change pas dans le process)

## ✅ Fait
