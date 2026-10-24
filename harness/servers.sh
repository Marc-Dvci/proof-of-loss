#!/usr/bin/env bash
# Start the two local model servers used by the rehearsal.
#   text   (main assistant, experts, extraction): port 8099
#   vision (visual checks, OCR, album indexing):   port 8098
# --cache-ram 0 keeps the prompt cache off host RAM, so each server commits only what the model needs.
#
#   LLAMA_SERVER=... POL_TEXT_MODEL=... POL_VISION_MODEL=... POL_VISION_MMPROJ=... harness/servers.sh text|vision
set -euo pipefail
LLAMA_SERVER="${LLAMA_SERVER:-llama-server}"
LOGS="$(cd "$(dirname "$0")/.." && pwd)/runs"
mkdir -p "$LOGS"
case "${1:-}" in
  text)
    exec "$LLAMA_SERVER" -m "$POL_TEXT_MODEL" -ngl 99 -c 32768 --host 127.0.0.1 --port 8099 --jinja -fa on \
      --parallel 1 --threads 4 --cache-ram 0 --no-webui >"$LOGS/server-text.log" 2>&1 ;;
  vision)
    exec "$LLAMA_SERVER" -m "$POL_VISION_MODEL" --mmproj "$POL_VISION_MMPROJ" -ngl "${POL_VISION_NGL:-24}" -c "${POL_VISION_CTX:-8192}" \
      --host 127.0.0.1 --port 8098 --jinja -fa on --parallel 1 --threads 4 --cache-ram 0 --no-webui \
      >"$LOGS/server-vision.log" 2>&1 ;;
  *) echo "usage: $0 text|vision" >&2; exit 2 ;;
esac
