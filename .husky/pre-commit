cd apps/server && \
    uv run ruff check --fix . && \
    uv run ruff format && \
    echo "✅ Server: Linting et formatage terminés avec succès"

cd apps/client && \
	pnpm lint && \
	pnpm format && \
	echo "✅ Client: Linting et formatage terminés avec succès"

echo "🎉 Pre-commit hook exécuté avec succès !"