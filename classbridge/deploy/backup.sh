#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose --env-file .env -f deploy/compose.yaml)
dest="${1:-backups/$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$dest"
chmod 700 "$dest"
"${compose[@]}" stop frontend api worker beat
trap '"${compose[@]}" start api worker beat frontend' EXIT
"${compose[@]}" exec -T postgres pg_dump -U classbridge -d classbridge -Fc > "$dest/database.dump"
"${compose[@]}" run --rm --no-deps -T --entrypoint tar api -C /data -czf - . > "$dest/files.tar.gz"
chmod 600 "$dest"/*
printf 'Backup written to %s. Store .env separately in a secure secrets backup.\n' "$dest"
