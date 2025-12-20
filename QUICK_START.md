# 🚀 Guide de Démarrage Rapide - Docker Optimisé

## ⚡ Installation Initiale

1. **Copier les variables d'environnement**
   ```bash
   cp .env.example .env
   ```

2. **Activer BuildKit** (ajoutez à votre `.env`)
   ```bash
   echo "DOCKER_BUILDKIT=1" >> .env
   echo "COMPOSE_DOCKER_CLI_BUILD=1" >> .env
   ```

3. **Exporter les variables** (une seule fois par session)
   ```bash
   export DOCKER_BUILDKIT=1
   export COMPOSE_DOCKER_CLI_BUILD=1
   ```

## 🎯 Commandes Essentielles

### Première fois
```bash
# Build optimisé avec cache
make build-cache

# Ou tout en un (clean + build + start)
make dev
```

### Développement quotidien
```bash
# Démarrer sans rebuild (très rapide)
make start

# Arrêter les services
make stop

# Voir les logs
docker compose logs -f
```

### Après modifications

**Code seulement modifié** (apps/next/app/*.tsx, apps/server/api/*.py)
```bash
# Rebuild rapide ~30-60s
make start
```

**Dépendances modifiées** (package.json, pyproject.toml)
```bash
# Rebuild avec cache
make build-cache
```

**Tout casser et recommencer** 😅
```bash
make rebuild
```

## 🔍 Diagnostic

### Vérifier la configuration
```bash
make check-docker
```

### Mesurer les performances
```bash
make benchmark
```

### Problèmes courants

**❌ "ERROR: failed to solve"**
```bash
# Nettoyer le cache
docker builder prune -af
make rebuild
```

**❌ "Cannot connect to Docker daemon"**
```bash
# Démarrer Docker Desktop
open -a Docker
```

**❌ "Port already in use"**
```bash
# Trouver le processus
lsof -i :8000
# Ou changer le port dans .env
```

**❌ Builds toujours lents**
```bash
# Vérifier BuildKit
echo $DOCKER_BUILDKIT  # doit afficher "1"

# Réactiver
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1
```

## 📊 Temps de Build Attendus

| Scénario                   | Temps       |
| -------------------------- | ----------- |
| Premier build (cold cache) | ~3-5 min    |
| Rebuild sans changement    | ~30-60s ⚡   |
| Code modifié               | ~45s-1.5min |
| Dépendances modifiées      | ~2-3 min    |

## 💡 Astuces Pro

1. **Ne jamais utiliser `--no-cache`** sauf si vraiment nécessaire
2. **Utiliser `make start`** au lieu de `make dev` pour les redémarrages
3. **Garder Docker Desktop à jour** pour les dernières optimisations
4. **Lancer `make clean`** de temps en temps pour libérer de l'espace

## 🎓 Pour aller plus loin

- Lire [DOCKER_OPTIMIZATIONS.md](./DOCKER_OPTIMIZATIONS.md) pour les détails techniques
- Utiliser `docker compose build --progress=plain` pour voir le cache en action
- Monitorer avec `docker stats` pour voir l'utilisation des ressources
