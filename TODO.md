# TODO

## 🔴 En cours

## 🟡 À faire

## 🟢 Idées / backlog
- [ ] feat(auth): Ajouter l'authentification avec email + password ainsi que via oidc infomaniak / 2 roles : user & admin / ajoute 2 utilisateurs de dev dans le readme
- [ ] Limiter le coût du crawl : option de throttling / budget de pages par domaine

## 🤖 Claude — recommandations
- [ ] TEST: les tests qui instancient un vrai client OpenAI/httpx (ex. `DatasetPipeline`→`LLMService`→`openai.OpenAI()`) échouent en sandbox car `ssl.create_default_context` lit le bundle certifi `*.pem` (lecture refusée) — mocker le client à la construction dans ces tests (ou rendre `LLMService` lazy) pour faire tourner toute la suite en sandbox

## ✅ Fait
