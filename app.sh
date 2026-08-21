#!/usr/bin/env bash
#
# Holiday Planning Tool - setup, run and deploy helper.
#
#   ./app.sh setup      create the venv, install deps, write .env if missing
#   ./app.sh migrate    apply database migrations
#   ./app.sh bootstrap  create the tribe + break-glass admin account
#   ./app.sh dev        run the development server (DEBUG=True)
#   ./app.sh prod       run gunicorn with production settings
#   ./app.sh test       run the test suite
#   ./app.sh check      Django's deployment checklist
#   ./app.sh deploy     migrate + collectstatic + check (run on release)
#
set -euo pipefail

cd "$(dirname "$0")"

VENV="${VENV:-.venv}"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"
PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"
WORKERS="${WEB_CONCURRENCY:-3}"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

require_venv() {
  [ -x "$PY" ] || die "No virtualenv at $VENV. Run: ./app.sh setup"
}

# Everything except `dev` and `test` runs against production settings.
use_prod_settings() { export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.prod}"; }
use_dev_settings()  { export DJANGO_SETTINGS_MODULE="config.settings.dev"; }

cmd_setup() {
  if [ ! -x "$PY" ]; then
    log "Creating virtualenv in $VENV"
    python3 -m venv "$VENV"
  fi
  log "Installing dependencies"
  "$PIP" install --quiet --upgrade pip
  "$PIP" install --quiet -r requirements.txt

  if [ ! -f .env ]; then
    log "Creating .env from .env.example"
    cp .env.example .env
    # A real random secret beats the placeholder, so a fresh checkout is
    # never one forgotten edit away from running on a known key.
    local secret
    secret="$("$PY" -c 'from django.core.management.utils import get_random_secret_key as k; print(k())')"
    "$PY" - "$secret" <<'PYEOF'
import pathlib, sys
secret = sys.argv[1]
path = pathlib.Path(".env")
text = path.read_text().replace("DJANGO_SECRET_KEY=changeme", f"DJANGO_SECRET_KEY={secret}")
path.write_text(text)
PYEOF
    warn ".env created with a generated SECRET_KEY - review the email settings before deploying."
  fi

  cmd_migrate
  log "Setup complete. Next: ./app.sh bootstrap   then   ./app.sh dev"
}

cmd_migrate() {
  require_venv
  log "Applying migrations"
  "$PY" manage.py migrate --noinput
}

cmd_bootstrap() {
  require_venv
  log "Bootstrapping tribe and break-glass admin"
  "$PY" manage.py bootstrap_tribe "$@"
}

cmd_dev() {
  require_venv
  use_dev_settings
  log "Development server on http://$HOST:$PORT"
  "$PY" manage.py runserver "$HOST:$PORT"
}

cmd_test() {
  require_venv
  use_dev_settings
  "$PY" manage.py test "$@"
}

cmd_collectstatic() {
  require_venv
  use_prod_settings
  log "Collecting static files into staticfiles/"
  "$PY" manage.py collectstatic --noinput --clear
}

cmd_check() {
  require_venv
  use_prod_settings
  log "Deployment checks"
  "$PY" manage.py check --deploy
}

cmd_deploy() {
  require_venv
  use_prod_settings
  cmd_migrate
  cmd_collectstatic
  cmd_check
  log "Ready to serve: ./app.sh prod"
}

cmd_prod() {
  require_venv
  use_prod_settings
  [ -d staticfiles ] || die "staticfiles/ is missing. Run: ./app.sh deploy"
  log "gunicorn on $HOST:$PORT with $WORKERS worker(s)"
  exec "$VENV/bin/gunicorn" config.wsgi:application \
    --bind "$HOST:$PORT" \
    --workers "$WORKERS" \
    --access-logfile - \
    --error-logfile -
}

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; }

case "${1:-}" in
  setup)         shift; cmd_setup "$@" ;;
  migrate)       shift; cmd_migrate "$@" ;;
  bootstrap)     shift; cmd_bootstrap "$@" ;;
  dev)           shift; cmd_dev "$@" ;;
  prod)          shift; cmd_prod "$@" ;;
  test)          shift; cmd_test "$@" ;;
  check)         shift; cmd_check "$@" ;;
  collectstatic) shift; cmd_collectstatic "$@" ;;
  deploy)        shift; cmd_deploy "$@" ;;
  ""|-h|--help|help) usage ;;
  *)             die "Unknown command: $1 (try: ./app.sh help)" ;;
esac
