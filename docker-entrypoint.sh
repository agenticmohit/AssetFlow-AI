#!/bin/sh
set -eu

data_dir="/data"

# Container deployments (Railway) default to production with SQLite on the
# /data volume. Explicit env vars always win over these defaults.
: "${ASSETFLOW_ENVIRONMENT:=production}"
: "${ASSETFLOW_UPLOAD_DIR:=/data/uploads}"
export ASSETFLOW_ENVIRONMENT ASSETFLOW_UPLOAD_DIR

if [ -z "${DATABASE_URL:-}" ] && [ -z "${ASSETFLOW_DATABASE_URL:-}" ]; then
  ASSETFLOW_DATABASE_URL="sqlite:////data/assetflow.db"
  export ASSETFLOW_DATABASE_URL
  echo "No database URL configured; defaulting to $ASSETFLOW_DATABASE_URL" >&2
fi

upload_dir="$ASSETFLOW_UPLOAD_DIR"

case "$upload_dir" in
  /data|/data/*|/app/var|/app/var/*) ;;
  *)
    echo "ASSETFLOW_UPLOAD_DIR must be inside /data or /app/var" >&2
    exit 1
    ;;
esac

mkdir -p "$data_dir" "$upload_dir"

# Without an explicit secret key, generate one once and persist it on the
# volume so sessions survive restarts and redeploys.
if [ -z "${ASSETFLOW_SECRET_KEY:-}" ]; then
  secret_file="$data_dir/.secret_key"
  if [ ! -s "$secret_file" ]; then
    python -c "import secrets; print(secrets.token_urlsafe(48))" > "$secret_file"
    chmod 600 "$secret_file"
    echo "ASSETFLOW_SECRET_KEY not set; generated one at $secret_file (set the env var to override)" >&2
  fi
  ASSETFLOW_SECRET_KEY="$(cat "$secret_file")"
  export ASSETFLOW_SECRET_KEY
fi

chown -R assetflow:assetflow "$data_dir" "$upload_dir"

exec gosu assetflow "$@"
