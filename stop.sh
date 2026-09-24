#!/usr/bin/env bash
# Stops the deployed ComfyUI app on Modal (stops GPU billing; the web URL
# goes offline until you run launch.sh again). Model files stored in the
# Modal volumes are kept.

# Usage: ./stop.sh [--profile NAME]   stop the app in a specific Modal account
set -uo pipefail

while [ "$#" -gt 0 ]; do
  case "$1" in
    --profile)   shift
                 if [ -z "${1:-}" ]; then echo "--profile needs a value"; exit 1; fi
                 export MODAL_PROFILE="$1" ;;
    --profile=*) export MODAL_PROFILE="${1#*=}" ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
  shift
done

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$APP_DIR/.venv/bin/python"
[ ! -x "$PY" ] && PY="python3"

echo "Stopping Modal app 'comfyui-hosting' ..."
"$PY" -m modal app stop comfyui-hosting -y
echo "Done. Your ComfyUI URL is offline and billing has stopped."
echo "Re-launch any time with: ./launch.sh"
