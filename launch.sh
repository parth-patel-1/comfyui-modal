#!/usr/bin/env bash
# ComfyUI on Modal -- one-click launcher for macOS/Linux.
#
# Usage:
#   ./launch.sh                                        full launch: setup, model download, deploy, open website
#   ./launch.sh --token-id ak-... --token-secret as-...  authenticate with a Modal API token (non-interactive)
#   ./launch.sh --skip-models                          skip the one-time model pre-download
#   ./launch.sh --no-browser                           deploy but do not open the browser
#   ./launch.sh --profile NAME                         deploy into a specific Modal account/profile
#
# Requirements: Python 3.9+ (https://python.org) and a free Modal account
# (https://modal.com). Authentication uses a Modal API token ID + secret
# (pass --token-id/--token-secret, or set MODAL_TOKEN_ID/MODAL_TOKEN_SECRET); if
# none are provided, a one-time browser sign-in opens on first launch.

set -uo pipefail

# Unicode-safe output (checkmarks) from the modal CLI.
export PYTHONIOENCODING=utf-8

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

SKIP_MODELS=0
NO_BROWSER=0
PROFILE=""
TOKEN_ID=""
TOKEN_SECRET=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --skip-models) SKIP_MODELS=1 ;;
    --no-browser)   NO_BROWSER=1 ;;
    --profile)      shift
                    if [ -z "${1:-}" ]; then echo "--profile needs a value"; exit 1; fi
                    PROFILE="$1" ;;
    --profile=*)    PROFILE="${1#*=}" ;;
    --token-id)     shift
                    if [ -z "${1:-}" ]; then echo "--token-id needs a value"; exit 1; fi
                    TOKEN_ID="$1" ;;
    --token-id=*)   TOKEN_ID="${1#*=}" ;;
    --token-secret) shift
                    if [ -z "${1:-}" ]; then echo "--token-secret needs a value"; exit 1; fi
                    TOKEN_SECRET="$1" ;;
    --token-secret=*) TOKEN_SECRET="${1#*=}" ;;
    *) echo "Unknown option: $1 (options: --skip-models, --no-browser, --profile NAME, --token-id ID, --token-secret SECRET)"; exit 1 ;;
  esac
  shift
done
# Target a specific Modal account (profile) for this launch -- see README.
if [ -n "$PROFILE" ]; then
  export MODAL_PROFILE="$PROFILE"
fi

step() { printf '\n==> %s\n' "$1"; }

# --- 1. Python virtual environment with the Modal CLI -------------------------
step "Setting up Python environment"
PY="$APP_DIR/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PYTHON_BIN="$(command -v python3 || command -v python || true)"
  if [ -z "$PYTHON_BIN" ]; then
    echo "Python 3.9+ required. Install it from https://python.org, then re-run."
    exit 1
  fi
  "$PYTHON_BIN" -m venv "$APP_DIR/.venv" || { echo "Could not create .venv"; exit 1; }
fi
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -r "$APP_DIR/requirements.txt" \
  || { echo "Failed to install the 'modal' package. Check your internet connection."; exit 1; }
echo "Environment ready."

# --- 2. Modal authentication (token ID + secret preferred) ------------------------
step "Checking Modal authentication"
if [ -z "$TOKEN_ID" ];     then TOKEN_ID="${MODAL_TOKEN_ID:-}"; fi
if [ -z "$TOKEN_SECRET" ]; then TOKEN_SECRET="${MODAL_TOKEN_SECRET:-}"; fi

if [ -n "$TOKEN_ID" ] && [ -n "$TOKEN_SECRET" ]; then
  echo "Authenticating with Modal token ID + secret ..."
  # Env vars make every modal command below use these credentials (they take
  # precedence over ~/.modal.toml).
  export MODAL_TOKEN_ID="$TOKEN_ID"
  export MODAL_TOKEN_SECRET="$TOKEN_SECRET"
  # Also persist the credentials so stop.sh and future launches work too.
  "$PY" -m modal token set --token-id "$TOKEN_ID" --token-secret "$TOKEN_SECRET" --verify \
    || { echo "Modal token authentication failed. Check the token ID and token secret."; exit 1; }
else
  if ! "$PY" -m modal app list >/dev/null 2>&1; then
    echo "No Modal credentials found. Starting 'modal token new' ..."
    echo "A browser window will open -- sign in (or create a free account) at modal.com."
    "$PY" -m modal token new || { echo "Modal authentication failed. Re-run this script."; exit 1; }
  else
    echo "Already authenticated with Modal."
  fi
fi

# --- 3. Pre-download models (one-time, ~24 GB for the default Qwen-Image-2.1 set) -------
if [ "$SKIP_MODELS" -eq 0 ]; then
  step "Downloading default models into the Modal volume (one-time)"
  "$PY" -m modal run "$APP_DIR/comfyui_app.py" \
    || { echo "Model download failed. See the output above for the cause."; exit 1; }
else
  echo "Skipping model pre-download (--skip-models)."
fi

# --- 4. Deploy the persistent web app ---------------------------------------------
step "Deploying ComfyUI web app to Modal (first build takes a few minutes)"
DEPLOY_LOG="$("$PY" -m modal deploy "$APP_DIR/comfyui_app.py" 2>&1)"
DEPLOY_STATUS=$?
echo "$DEPLOY_LOG"
if [ "$DEPLOY_STATUS" -ne 0 ]; then
  echo "Deploy failed. See the output above."
  exit 1
fi

# --- 5. Open the website -------------------------------------------------------------
URL="$(echo "$DEPLOY_LOG" | grep -oE 'https://[a-zA-Z0-9.-]+\.modal\.run' | tail -n 1)"
if [ -n "$URL" ]; then
  printf '\nComfyUI is live at: %s\n' "$URL"
  echo "First load may take up to ~1 minute (cold start of the GPU container)."
  echo "Stop GPU billing when you're done:  ./stop.sh"
  if [ "$NO_BROWSER" -eq 0 ]; then
    if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
    elif command -v open >/dev/null 2>&1; then open "$URL" >/dev/null 2>&1 || true
    fi
  fi
else
  echo "Could not parse the web URL from the deploy output -- run: modal app list"
fi
