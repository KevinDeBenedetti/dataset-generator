# Crawling — configuration & fonctionnement

Ce document explique comment fonctionne le crawl (exploration de site) du Dataset
Generator et comment le régler, via les variables d'environnement, l'API et l'UI.

## 1. Vue d'ensemble

Pour générer un dataset, le serveur récupère le contenu d'une URL, le nettoie puis
génère des paires question/réponse. Deux modes de récupération existent :

- **Page unique** (`crawl = false`) : seule l'URL fournie (le « seed ») est
  scrapée.
- **Crawl de site** (`crawl = true`, défaut) : le scraper part du seed et suit en
  **largeur d'abord** (breadth-first) les liens internes pour couvrir tout le
  site et maximiser le dataset. Chaque page découverte déclenche un nettoyage +
  une génération de Q/R, donc les limites (`max_depth`, `max_pages`) bornent le
  coût.

L'extraction du HTML/Markdown n'est pas faite en interne : le serveur appelle un
service **crawl4ai** (conteneur Docker dédié) via son API REST. Le serveur, lui,
gère la logique de parcours du site (la file BFS, les filtres de domaine, les
limites).

```
┌──────────┐   POST /dataset/generate(/stream)   ┌─────────────┐   POST /md, /crawl   ┌──────────┐
│ Next.js  │ ──────────────────────────────────► │  server     │ ───────────────────► │ crawl4ai │
│ (UI)     │                                     │ (FastAPI)   │   (rend la page)     │ (Docker) │
└──────────┘                                     └─────────────┘                      └──────────┘
                                                  ▲ ScraperService.crawl_site() : BFS, filtres, limites
```

Code de référence :
- Parcours du site : [apps/server/services/scraper.py](../apps/server/services/scraper.py) (`crawl_site`)
- Branchement dans le pipeline : [apps/server/pipelines/dataset.py](../apps/server/pipelines/dataset.py)
- Schéma de requête : [apps/server/schemas/generate.py](../apps/server/schemas/generate.py) (`DatasetGenerationRequest`)
- Valeurs par défaut / config : [apps/server/core/config.py](../apps/server/core/config.py)

## 2. Les deux niveaux de réglage

Le crawl se règle à **deux niveaux** qui se combinent :

1. **Variables d'environnement** → définissent les **valeurs par défaut** du
   serveur et la connexion au service crawl4ai.
2. **Paramètres par requête** (API / UI) → **surchargent** les défauts pour une
   génération donnée.

> Règle de résolution : si la requête fournit `max_depth` / `max_pages`, ces
> valeurs sont utilisées. Sinon, le serveur retombe sur `CRAWL_MAX_DEPTH` /
> `CRAWL_MAX_PAGES`. Voir `crawl_site()` :
> `max_depth = config.crawl_max_depth if max_depth is None else max_depth`.

## 3. Variables d'environnement

À placer dans le `.env` à la racine (copié depuis `.env.example`).

### 3.1 Limites de crawl (comportement du parcours)

| Variable            | Défaut  | Type | Rôle |
|---------------------|---------|------|------|
| `CRAWL_MAX_DEPTH`   | `2`     | int  | Profondeur maximale de suivi des liens à partir du seed. `0` = seed seul, `1` = seed + liens directs, etc. |
| `CRAWL_MAX_PAGES`   | `50`    | int  | Nombre maximal de pages récupérées sur l'ensemble du crawl. Plafonne le coût (chaque page = 1 nettoyage + 1 génération Q/R). |
| `CRAWL_SAME_DOMAIN` | `true`  | bool | Si vrai, seuls les liens du **même hôte** que le seed sont suivis. Mettre à `false`/`0`/`no` pour autoriser les domaines externes. |

Notes :
- `CRAWL_SAME_DOMAIN` est interprété comme **faux** uniquement pour `0`, `false`
  ou `no` (insensible à la casse) ; toute autre valeur vaut `true`.
- `max_depth` et `max_pages` agissent **ensemble** : le crawl s'arrête dès que
  l'une des deux limites est atteinte (file vide, profondeur dépassée, ou quota
  de pages atteint).

### 3.2 Connexion au service crawl4ai

| Variable             | Défaut                      | Type | Rôle |
|----------------------|-----------------------------|------|------|
| `CRAWL4AI_BASE_URL`  | `http://crawl4ai:11235`     | str  | URL de base du service crawl4ai. Par défaut pointe sur le service Docker Compose. Mettre une URL distante pour utiliser une instance externe. |
| `CRAWL4AI_API_TOKEN` | *(vide)*                    | str  | Jeton d'authentification. S'il est défini, il est envoyé en `Authorization: Bearer <token>` à chaque requête. |
| `CRAWL4AI_TIMEOUT`   | `120`                       | int  | Délai max (secondes) pour une requête de rendu. crawl4ai rend la page dans un navigateur, donc cette valeur doit dépasser confortablement le timeout de la page. |
| `CRAWL4AI_IMAGE`     | `unclecode/crawl4ai:0.8.9`  | str  | (Docker Compose) Image du conteneur crawl4ai. |

### 3.3 Réglages de scraping connexes (non configurables par `.env`)

Définis en dur dans `Config` (modifiables dans le code si besoin) :

| Champ          | Valeur | Rôle |
|----------------|--------|------|
| `max_retries`  | `3`    | Tentatives par requête. |
| `timeout`      | `10`   | Timeout HTTP générique. |
| `scrape_delay` | `0.2`  | Délai entre requêtes. |

### 3.4 Exemple de `.env`

```bash
# --- Crawl : limites de parcours ---
CRAWL_MAX_DEPTH=2
CRAWL_MAX_PAGES=50
CRAWL_SAME_DOMAIN=true

# --- Crawl : service crawl4ai ---
CRAWL4AI_BASE_URL=http://crawl4ai:11235
CRAWL4AI_API_TOKEN=
CRAWL4AI_TIMEOUT=120
# CRAWL4AI_IMAGE=unclecode/crawl4ai:0.8.9
```

## 4. Paramètres par requête (API)

Endpoints : `POST /dataset/generate` (synchrone) et `POST /dataset/generate/stream`
(progression en SSE). Corps = `DatasetGenerationRequest` :

| Champ          | Type            | Défaut  | Effet sur le crawl |
|----------------|-----------------|---------|--------------------|
| `url`          | URL             | —       | Seed du crawl (point de départ). |
| `dataset_name` | string          | —       | Nom du dataset créé. |
| `crawl`        | bool            | `true`  | `true` = explorer le site, `false` = scraper uniquement le seed. |
| `max_depth`    | int ≥ 0 \| null | `null`  | Surcharge `CRAWL_MAX_DEPTH`. `null` ⇒ valeur du `.env`. |
| `max_pages`    | int ≥ 1 \| null | `null`  | Surcharge `CRAWL_MAX_PAGES`. `null` ⇒ valeur du `.env`. |

> `max_depth` et `max_pages` ne sont pris en compte que si `crawl = true`.
> Lorsque `crawl = false`, ces champs sont ignorés.

Exemple :

```bash
curl -X POST http://localhost:8000/dataset/generate \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/docs",
    "dataset_name": "exemple_docs",
    "crawl": true,
    "max_depth": 3,
    "max_pages": 100
  }'
```

Pour suivre la progression page par page, utiliser `/dataset/generate/stream`
(Server-Sent Events). Les événements émis ont un champ `type` :
- `step` — une étape du pipeline s'est terminée ;
- `page` — une page a été crawlée (`{ url, depth, crawled, max_pages }`) ;
- `result` — payload final ;
- `error` — erreur.

## 5. Réglage depuis l'UI (Next.js)

Dans le formulaire de génération ([dataset-generate.tsx](../apps/next/components/dataset/dataset-generate.tsx)) :

- Case **« Crawl entire site (follow same-domain links) »** → champ `crawl`
  (activée par défaut).
- Quand elle est cochée, deux champs apparaissent :
  - **Max depth** (`min = 0`) → `max_depth`.
  - **Max pages** (`min = 1`) → `max_pages`.

Si les champs sont laissés vides, l'UI envoie `null` et le serveur applique les
défauts du `.env`. Quand la case est décochée, l'UI force `max_depth` et
`max_pages` à `null`.

## 6. Fonctionnement détaillé du parcours (BFS)

`ScraperService.crawl_site(seed_url, dataset_id, max_depth, max_pages, same_domain, on_page)` :

1. **Résolution des limites** : pour chaque paramètre `None`, on prend la valeur
   de `config` (issue du `.env`).
2. **Normalisation du seed** : les fragments (`#...`) sont retirés
   (`urldefrag`) ; l'hôte du seed est mémorisé pour le filtre same-domain.
3. **File BFS** : une `deque` de `(url, depth)` initialisée avec `(seed, 0)`. Un
   ensemble `visited` évite de traiter deux fois la même URL.
4. **Boucle** tant que la file n'est pas vide **et** que `len(snapshots) < max_pages` :
   - dépiler `(current, depth)`, normaliser, ignorer si déjà visité ;
   - récupérer la page via crawl4ai `/crawl` (Markdown + liens internes) ;
   - **une page en échec est ignorée** (log `warning`) et n'interrompt pas le
     crawl — un lien cassé ne fait pas échouer tout le dataset ;
   - si du contenu est récupéré : sauvegarder un `PageSnapshot` et appeler
     `on_page(...)` (progression live) ;
   - si `depth >= max_depth` : ne pas enfiler les liens de cette page ;
   - sinon, pour chaque lien interne : résoudre l'URL absolue, ignorer si déjà
     visité, **filtrer** par domaine (si `same_domain`), ne garder que les schémas
     `http(s)`, puis enfiler à `depth + 1`.
5. **Fin** : retourne la liste des `PageSnapshot`. Le pipeline marque l'étape
   `scrape` en `success` (au moins une page) ou `warning` (aucune page).

### Comprendre `max_depth`

| `max_depth` | Pages explorées |
|-------------|-----------------|
| `0`         | seed uniquement (équivaut à un crawl d'une page) |
| `1`         | seed + pages liées directement depuis le seed |
| `2` (défaut)| + pages liées depuis le niveau 1 |
| `n`         | jusqu'à `n` sauts de lien depuis le seed |

Le nombre de pages reste **toujours** plafonné par `max_pages`, quel que soit
`max_depth`.

## 7. Recommandations de réglage

| Objectif | Réglage suggéré |
|----------|-----------------|
| Test rapide / une page | `crawl = false` (ou `max_depth = 0`) |
| Petite section de doc | `max_depth = 1`, `max_pages = 10–20` |
| Site complet (défaut) | `max_depth = 2`, `max_pages = 50` |
| Gros site / dataset volumineux | `max_depth = 3+`, `max_pages = 100+`, surveiller le coût LLM |
| Inclure des sous-domaines / domaines liés | `CRAWL_SAME_DOMAIN=false` (attention à la portée) |

Garde-fous :
- Chaque page crawlée = appels LLM (nettoyage + Q/R). Augmenter `max_pages`
  augmente proportionnellement le **coût** et la **durée**.
- Pour des pages lourdes/lentes à rendre, augmenter `CRAWL4AI_TIMEOUT`.
- `CRAWL_SAME_DOMAIN=false` peut faire diverger le crawl hors du site cible :
  à n'utiliser qu'avec un `max_pages` raisonnable.

## 8. Dépannage

| Symptôme | Piste |
|----------|-------|
| « No pages crawled » / dataset vide | Le seed est-il accessible ? crawl4ai répond-il (`/health`) ? Vérifier `CRAWL4AI_BASE_URL`. |
| Timeouts de rendu | Augmenter `CRAWL4AI_TIMEOUT`. Pages très dynamiques/lourdes. |
| Crawl trop large / trop long | Baisser `max_depth` et/ou `max_pages` ; vérifier `CRAWL_SAME_DOMAIN`. |
| 401/403 depuis crawl4ai | Renseigner/corriger `CRAWL4AI_API_TOKEN`. |
| Seul le seed est scrapé | `crawl` est `false`, ou `max_depth = 0`, ou la page n'expose aucun lien interne same-domain. |

Le service crawl4ai est lancé par Docker Compose (voir
[docker-compose.yml](../docker-compose.yml), service `crawl4ai`). Il n'est pas
publié sur l'hôte par défaut ; mappez un port pour accéder à son `/playground`.
