#!/bin/bash

# Script pour comparer les temps de build avec et sans optimisations

set -e

echo "🔍 Docker Build Performance Benchmark"
echo "======================================"
echo ""

# Couleurs
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Fonction pour mesurer le temps
measure_time() {
    local description=$1
    local command=$2

    echo -e "${BLUE}📊 $description${NC}" >&2
    echo "Commande : $command" >&2

    local start_time=$(date +%s)
    eval $command > /dev/null 2>&1
    local end_time=$(date +%s)

    local duration=$((end_time - start_time))
    echo -e "${GREEN}✓ Durée : ${duration}s${NC}" >&2
    echo "" >&2

    # Retourner la durée via echo (pour la capture)
    echo $duration
}

# Nettoyer l'environnement
echo -e "${YELLOW}🧹 Nettoyage de l'environnement...${NC}"
docker compose down -v > /dev/null 2>&1 || true
docker builder prune -af > /dev/null 2>&1 || true
echo ""

# Test 1 : Build initial (cold cache)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 1 : Build initial (cold cache)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
cold_build_time=$(measure_time "Build avec cache BuildKit" "DOCKER_BUILDKIT=1 docker compose build")

# Test 2 : Rebuild sans changement
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 2 : Rebuild sans modification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
cached_build_time=$(measure_time "Rebuild (tout en cache)" "DOCKER_BUILDKIT=1 docker compose build")

# Test 3 : Rebuild après modification de code
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 3 : Rebuild après modification de code"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
touch apps/next/app/page.tsx
code_change_build_time=$(measure_time "Rebuild (code modifié)" "DOCKER_BUILDKIT=1 docker compose build next")

# Test 4 : Rebuild après modification de dépendances
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 4 : Rebuild après modification de dépendances"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
touch apps/next/package.json
deps_change_build_time=$(measure_time "Rebuild (deps modifiées)" "DOCKER_BUILDKIT=1 docker compose build next")

# Statistiques sur les images
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Statistiques des images Docker"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
docker images --filter=reference='datasets-*' --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
echo ""

# Résumé
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 RÉSUMÉ DES PERFORMANCES"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "Build initial (cold)      : ${YELLOW}${cold_build_time}s${NC}"
echo -e "Rebuild (cache complet)   : ${GREEN}${cached_build_time}s${NC} (${YELLOW}-$((100 - (cached_build_time * 100 / cold_build_time)))%${NC})"
echo -e "Rebuild (code modifié)    : ${GREEN}${code_change_build_time}s${NC}"
echo -e "Rebuild (deps modifiées)  : ${GREEN}${deps_change_build_time}s${NC}"
echo ""

# Calculer les économies
total_saved=$((cold_build_time - cached_build_time))
echo -e "${GREEN}✓ Temps économisé sur rebuild : ${total_saved}s${NC}"
echo ""

# Conseils
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "💡 CONSEILS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "• Utilisez 'make build-cache' pour les builds optimisés"
echo "• Utilisez 'make start' pour démarrer sans rebuild"
echo "• Lancez 'docker builder prune -af' si le cache est corrompu"
echo ""

echo -e "${GREEN}✓ Benchmark terminé !${NC}"
