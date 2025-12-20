#!/bin/bash

# Script pour vérifier et activer les optimisations Docker

set -e

# Couleurs
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "🔍 Docker Build Optimization Checker"
echo "======================================"
echo ""

# Vérifier si Docker est installé
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker n'est pas installé${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker installé : $(docker --version)${NC}"

# Vérifier BuildKit
echo ""
echo -e "${BLUE}🔧 Vérification de BuildKit...${NC}"
if docker buildx version &> /dev/null; then
    echo -e "${GREEN}✓ BuildKit disponible : $(docker buildx version)${NC}"
else
    echo -e "${YELLOW}⚠ BuildKit non disponible - Installation recommandée${NC}"
fi

# Vérifier les variables d'environnement
echo ""
echo -e "${BLUE}🔧 Vérification des variables d'environnement...${NC}"

check_env_var() {
    local var_name=$1
    local var_value=$(printenv $var_name)

    if [ -z "$var_value" ]; then
        echo -e "${YELLOW}⚠ $var_name non défini${NC}"
        return 1
    else
        echo -e "${GREEN}✓ $var_name=$var_value${NC}"
        return 0
    fi
}

missing_vars=0

if ! check_env_var "DOCKER_BUILDKIT"; then
    missing_vars=$((missing_vars + 1))
fi

if ! check_env_var "COMPOSE_DOCKER_CLI_BUILD"; then
    missing_vars=$((missing_vars + 1))
fi

# Proposer de créer .env si nécessaire
if [ ! -f .env ]; then
    echo ""
    echo -e "${YELLOW}⚠ Fichier .env non trouvé${NC}"
    echo -e "${BLUE}Voulez-vous créer .env depuis .env.example ? (y/n)${NC}"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        cp .env.example .env
        echo -e "${GREEN}✓ Fichier .env créé${NC}"
    fi
fi

# Vérifier les fichiers .dockerignore
echo ""
echo -e "${BLUE}🔧 Vérification des fichiers .dockerignore...${NC}"

check_dockerignore() {
    local path=$1
    if [ -f "$path/.dockerignore" ]; then
        echo -e "${GREEN}✓ $path/.dockerignore existe${NC}"
    else
        echo -e "${YELLOW}⚠ $path/.dockerignore manquant${NC}"
    fi
}

check_dockerignore "apps/next"
check_dockerignore "apps/server"
check_dockerignore "apps/vue"

# Vérifier l'espace disque
echo ""
echo -e "${BLUE}🔧 Vérification de l'espace disque Docker...${NC}"
docker system df

# Statistiques du cache
echo ""
echo -e "${BLUE}🔧 Statistiques du builder...${NC}"
docker builder ls

# Recommandations
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "💡 RECOMMANDATIONS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $missing_vars -gt 0 ]; then
    echo ""
    echo -e "${YELLOW}Pour activer BuildKit, ajoutez à votre .env :${NC}"
    echo "DOCKER_BUILDKIT=1"
    echo "COMPOSE_DOCKER_CLI_BUILD=1"
    echo ""
    echo "Puis sourcez le fichier :"
    echo "  source .env"
    echo "  export DOCKER_BUILDKIT=1"
    echo "  export COMPOSE_DOCKER_CLI_BUILD=1"
fi

echo ""
echo "Pour des builds optimaux :"
echo "  1. Utilisez 'make build-cache' au lieu de 'docker compose build'"
echo "  2. Lancez 'docker builder prune' régulièrement pour nettoyer le cache"
echo "  3. Utilisez 'make start' pour démarrer sans rebuild"
echo ""

# Proposer un nettoyage si nécessaire
docker_size=$(docker system df -v | grep 'Build Cache' | awk '{print $3}')
if [ ! -z "$docker_size" ]; then
    echo -e "${BLUE}Taille du cache actuel : $docker_size${NC}"
    echo -e "${BLUE}Voulez-vous nettoyer le cache ? (y/n)${NC}"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        docker builder prune -af
        echo -e "${GREEN}✓ Cache nettoyé${NC}"
    fi
fi

echo ""
echo -e "${GREEN}✓ Vérification terminée !${NC}"
