#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
src="${1:?Usage: bash deploy/restore.sh backups/TIMESTAMP --replace-database}"
test "${2:-}" = --replace-database || { printf 'Restoring replaces database contents. Supply --replace-database explicitly.\n'; exit 2; }
test -s "$src/database.dump"
test -s "$src/files.tar.gz"
compose=(docker compose --env-file .env -f deploy/compose.yaml)
"${compose[@]}" stop frontend api worker beat
"${compose[@]}" exec -T postgres pg_restore -U classbridge -d classbridge --clean --if-exists --no-owner < "$src/database.dump"
"${compose[@]}" run --rm --no-deps -T --entrypoint tar api -C /data -xzf - < "$src/files.tar.gz"
"${compose[@]}" run --rm --no-deps api alembic upgrade head
"${compose[@]}" start api worker beat frontend
printf 'Restore complete. Verify /api/health and open a saved session.\n'
