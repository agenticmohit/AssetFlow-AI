#!/bin/sh
set -eu

data_dir="/data"
upload_dir="${ASSETFLOW_UPLOAD_DIR:-/data/uploads}"

case "$upload_dir" in
  /data|/data/*|/app/var|/app/var/*) ;;
  *)
    echo "ASSETFLOW_UPLOAD_DIR must be inside /data or /app/var" >&2
    exit 1
    ;;
esac

mkdir -p "$data_dir" "$upload_dir"
chown -R assetflow:assetflow "$data_dir" "$upload_dir"

exec gosu assetflow "$@"
