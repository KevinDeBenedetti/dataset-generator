# Quick Start Guide - Optimized Docker

## Initial Installation

1. **Copy environment variables**
   ```bash
   cp .env.example .env
   ```

2. **Enable BuildKit** (add to your `.env`)
   ```bash
   echo "DOCKER_BUILDKIT=1" >> .env
   echo "COMPOSE_DOCKER_CLI_BUILD=1" >> .env
   ```

3. **Export variables** (once per session)
   ```bash
   export DOCKER_BUILDKIT=1
   export COMPOSE_DOCKER_CLI_BUILD=1
   ```

## Essential Commands

### First time
```bash
# Optimized build with cache
make build-cache

# Or all-in-one (clean + build + start)
make dev
```

### Daily development
```bash
# Start without rebuild (very fast)
make start

# Stop services
make stop

# View logs
docker compose logs -f
```

### After modifications

**Code only modified** (apps/next/app/*.tsx, apps/server/api/*.py)
```bash
# Fast rebuild ~30-60s
make start
```

**Dependencies modified** (package.json, pyproject.toml)
```bash
# Rebuild with cache
make build-cache
```

**Break everything and start over**
```bash
make rebuild
```

## Diagnostics

### Check configuration
```bash
make check-docker
```

### Measure performance
```bash
make benchmark
```

### Common problems

**"ERROR: failed to solve"**
```bash
# Clean cache
docker builder prune -af
make rebuild
```

**"Cannot connect to Docker daemon"**
```bash
# Start Docker Desktop
open -a Docker
```

**"Port already in use"**
```bash
# Find the process
lsof -i :8000
# Or change the port in .env
```

**Builds still slow**
```bash
# Check BuildKit
echo $DOCKER_BUILDKIT  # should display "1"

# Re-enable
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1
```

## Expected Build Times

| Scenario                  | Time        |
| ------------------------- | ----------- |
| First build (cold cache)  | ~3-5 min    |
| Rebuild without changes   | ~30-60s     |
| Code modified             | ~45s-1.5min |
| Dependencies modified     | ~2-3 min    |

## Pro Tips

1. **Never use `--no-cache`** unless absolutely necessary
2. **Use `make start`** instead of `make dev` for restarts
3. **Keep Docker Desktop up to date** for the latest optimizations
4. **Run `make clean`** occasionally to free up space

## Going Further

- Read [DOCKER_OPTIMIZATIONS.md](./DOCKER_OPTIMIZATIONS.md) for technical details
- Use `docker compose build --progress=plain` to see cache in action
- Monitor with `docker stats` to see resource usage
