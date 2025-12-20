#!/bin/bash

# Script to compare build times with and without optimizations

set -e

echo "Docker Build Performance Benchmark"
echo "======================================"
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to measure time
measure_time() {
    local description=$1
    local command=$2

    echo -e "${BLUE}$description${NC}" >&2
    echo "Command: $command" >&2

    local start_time=$(date +%s)
    eval $command > /dev/null 2>&1
    local end_time=$(date +%s)

    local duration=$((end_time - start_time))
    echo -e "${GREEN}Duration: ${duration}s${NC}" >&2
    echo "" >&2

    # Return duration via echo (for capture)
    echo $duration
}

# Clean environment
echo -e "${YELLOW}Cleaning environment...${NC}"
docker compose down -v > /dev/null 2>&1 || true
docker builder prune -af > /dev/null 2>&1 || true
echo ""

# Test 1: Initial build (cold cache)
echo "--------------------------------------"
echo "Test 1: Initial build (cold cache)"
echo "--------------------------------------"
cold_build_time=$(measure_time "Build with BuildKit cache" "DOCKER_BUILDKIT=1 docker compose build")

# Test 2: Rebuild without changes
echo "--------------------------------------"
echo "Test 2: Rebuild without changes"
echo "--------------------------------------"
cached_build_time=$(measure_time "Rebuild (fully cached)" "DOCKER_BUILDKIT=1 docker compose build")

# Test 3: Rebuild after code modification
echo "--------------------------------------"
echo "Test 3: Rebuild after code modification"
echo "--------------------------------------"
touch apps/next/app/page.tsx
code_change_build_time=$(measure_time "Rebuild (code modified)" "DOCKER_BUILDKIT=1 docker compose build next")

# Test 4: Rebuild after dependency modification
echo "--------------------------------------"
echo "Test 4: Rebuild after dependency modification"
echo "--------------------------------------"
touch apps/next/package.json
deps_change_build_time=$(measure_time "Rebuild (deps modified)" "DOCKER_BUILDKIT=1 docker compose build next")

# Image statistics
echo "--------------------------------------"
echo "Docker Image Statistics"
echo "--------------------------------------"
docker images --filter=reference='datasets-*' --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
echo ""

# Summary
echo "--------------------------------------"
echo "PERFORMANCE SUMMARY"
echo "--------------------------------------"
echo -e "Initial build (cold)      : ${YELLOW}${cold_build_time}s${NC}"
echo -e "Rebuild (full cache)      : ${GREEN}${cached_build_time}s${NC} (${YELLOW}-$((100 - (cached_build_time * 100 / cold_build_time)))%${NC})"
echo -e "Rebuild (code modified)   : ${GREEN}${code_change_build_time}s${NC}"
echo -e "Rebuild (deps modified)   : ${GREEN}${deps_change_build_time}s${NC}"
echo ""

# Calculate savings
total_saved=$((cold_build_time - cached_build_time))
echo -e "${GREEN}Time saved on rebuild: ${total_saved}s${NC}"
echo ""

# Tips
echo "--------------------------------------"
echo "TIPS"
echo "--------------------------------------"
echo "- Use 'make build-cache' for optimized builds"
echo "- Use 'make start' to start without rebuild"
echo "- Run 'docker builder prune -af' if cache is corrupted"
echo ""

echo -e "${GREEN}Benchmark completed!${NC}"
