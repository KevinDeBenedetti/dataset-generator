#!/bin/bash

# Script to check and enable Docker optimizations

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "Docker Build Optimization Checker"
echo "======================================"
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker is not installed${NC}"
    exit 1
fi
echo -e "${GREEN}Docker installed: $(docker --version)${NC}"

# Check BuildKit
echo ""
echo -e "${BLUE}Checking BuildKit...${NC}"
if docker buildx version &> /dev/null; then
    echo -e "${GREEN}BuildKit available: $(docker buildx version)${NC}"
else
    echo -e "${YELLOW}BuildKit not available - Installation recommended${NC}"
fi

# Check environment variables
echo ""
echo -e "${BLUE}Checking environment variables...${NC}"

check_env_var() {
    local var_name=$1
    local var_value=$(printenv $var_name)

    if [ -z "$var_value" ]; then
        echo -e "${YELLOW}$var_name not defined${NC}"
        return 1
    else
        echo -e "${GREEN}$var_name=$var_value${NC}"
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

# Offer to create .env if needed
if [ ! -f .env ]; then
    echo ""
    echo -e "${YELLOW}.env file not found${NC}"
    echo -e "${BLUE}Do you want to create .env from .env.example? (y/n)${NC}"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        cp .env.example .env
        echo -e "${GREEN}.env file created${NC}"
    fi
fi

# Check .dockerignore files
echo ""
echo -e "${BLUE}Checking .dockerignore files...${NC}"

check_dockerignore() {
    local path=$1
    if [ -f "$path/.dockerignore" ]; then
        echo -e "${GREEN}$path/.dockerignore exists${NC}"
    else
        echo -e "${YELLOW}$path/.dockerignore missing${NC}"
    fi
}

check_dockerignore "apps/next"
check_dockerignore "apps/server"
check_dockerignore "apps/vue"

# Check disk space
echo ""
echo -e "${BLUE}Checking Docker disk space...${NC}"
docker system df

# Cache statistics
echo ""
echo -e "${BLUE}Builder statistics...${NC}"
docker builder ls

# Recommendations
echo ""
echo "--------------------------------------"
echo "RECOMMENDATIONS"
echo "--------------------------------------"

if [ $missing_vars -gt 0 ]; then
    echo ""
    echo -e "${YELLOW}To enable BuildKit, add to your .env:${NC}"
    echo "DOCKER_BUILDKIT=1"
    echo "COMPOSE_DOCKER_CLI_BUILD=1"
    echo ""
    echo "Then source the file:"
    echo "  source .env"
    echo "  export DOCKER_BUILDKIT=1"
    echo "  export COMPOSE_DOCKER_CLI_BUILD=1"
fi

echo ""
echo "For optimal builds:"
echo "  1. Use 'make build-cache' instead of 'docker compose build'"
echo "  2. Run 'docker builder prune' regularly to clean cache"
echo "  3. Use 'make start' to start without rebuild"
echo ""

# Offer cleanup if needed
docker_size=$(docker system df -v | grep 'Build Cache' | awk '{print $3}')
if [ ! -z "$docker_size" ]; then
    echo -e "${BLUE}Current cache size: $docker_size${NC}"
    echo -e "${BLUE}Do you want to clean the cache? (y/n)${NC}"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        docker builder prune -af
        echo -e "${GREEN}Cache cleaned${NC}"
    fi
fi

echo ""
echo -e "${GREEN}Verification completed!${NC}"
