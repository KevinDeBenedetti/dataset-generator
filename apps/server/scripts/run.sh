#!/bin/bash
set -e

run_migrations() {
    if [ ! -f "alembic.ini" ]; then
        echo "alembic.ini file not found"
        exit 1
    fi

    if [ ! -d "migrations" ]; then
        echo "migrations directory not found"
        exit 1
    fi

    echo "⬆️  Applying migrations..."
    if ! alembic upgrade head; then
        echo "Failed to apply migrations"
        echo "   Check the logs above for more details"
        exit 1
    fi

    echo "Migrations applied successfully!"
}

start_api() {
    exec uvicorn main:app
}


main() {
  echo "Running migrations before starting API..."
  run_migrations
  start_api
}

trap 'echo "Stopping service..."; exit 0' SIGTERM SIGINT
main "$@"