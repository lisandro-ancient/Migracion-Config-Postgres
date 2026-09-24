#!/usr/bin/env bash
# Reproduce la CI en tu máquina (macOS, Linux, o Windows con Git Bash / WSL 2),
# con los mismos servicios que GitHub Actions:
# un Firebird 5 en Docker con la réplica de CONFIG y una base PostgreSQL aparte
# (config_ci). No toca tu CONFIG.FDB, tu .env ni el esquema 'config' de tu PostgreSQL.
#
#   scripts/ci_local.sh            # todas las etapas
#   scripts/ci_local.sh calidad    # solo una: calidad | seguridad | pruebas | construccion
set -euo pipefail
cd "$(dirname "$0")/.."
# El entorno virtual pone los ejecutables en .venv/bin (macOS/Linux) o .venv/Scripts (Windows).
if [ -d .venv/Scripts ]; then BIN=./.venv/Scripts; else BIN=./.venv/bin; fi
PY=$BIN/python
ETAPA="${1:-todas}"
FB_CONTENEDOR=config_microsip_firebird_ci
FB_PUERTO=3055

paso() { printf '\n\033[1;34m▶ %s\033[0m\n' "$*"; }

calidad() {
  paso "Calidad"
  $BIN/ruff check src dashboard tests ci
  $BIN/ruff format --check src dashboard tests ci
  $BIN/mypy
  $PY ci/version.py actual
  $PY ci/validar_manifiestos.py
  $BIN/actionlint
  $BIN/pytest --collect-only -q -o addopts= > /dev/null
}

seguridad() {
  paso "Seguridad"
  $BIN/pip-audit -r requirements.txt --progress-spinner off
  $BIN/bandit -q -r src dashboard -c pyproject.toml
  docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:latest dir /repo --redact --no-banner --config /repo/.gitleaks.toml
}

servicios() {
  paso "Servicios: PostgreSQL (docker compose, base config_ci) y Firebird 5 (réplica de CONFIG)"
  docker compose up -d --wait
  docker exec config_microsip_postgres psql -U migracion -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='config_ci'" | grep -q 1 \
    || docker exec config_microsip_postgres createdb -U migracion config_ci
  docker rm -f "$FB_CONTENEDOR" > /dev/null 2>&1 || true
  docker run -d --name "$FB_CONTENEDOR" -p "$FB_PUERTO:3050" -e FIREBIRD_ROOT_PASSWORD=masterkey firebirdsql/firebird:5 > /dev/null
  for _ in $(seq 1 30); do
    $PY -c "import socket,sys; socket.create_connection(('localhost', int(sys.argv[1])), 2)" "$FB_PUERTO" 2>/dev/null && break
    sleep 1
  done
  sleep 2
  export FIREBIRD_HOST=localhost FIREBIRD_PORT=$FB_PUERTO FIREBIRD_DATABASE=/var/lib/firebird/data/config_ci.fdb \
         FIREBIRD_USER=SYSDBA FIREBIRD_PASSWORD=masterkey FIREBIRD_RUNTIME_DIR= POSTGRES_DB=config_ci SKIP_ALLURE_REPORT=1
  # Biblioteca cliente de Firebird (modo remoto contra el contenedor). Si ya exportaste
  # FIREBIRD_CLIENT_LIBRARY se respeta; si no, se busca la habitual de cada sistema.
  if [ -z "${FIREBIRD_CLIENT_LIBRARY:-}" ]; then
    for candidata in "$HOME/mcp-firebird/firebird-runtime/Libraries/libfbclient.dylib" \
                     "/c/Program Files/Firebird/Firebird_5_0/fbclient.dll" \
                     "/mnt/c/Program Files/Firebird/Firebird_5_0/fbclient.dll"; do
      [ -f "$candidata" ] && export FIREBIRD_CLIENT_LIBRARY="$candidata" && break
    done
  fi  # en Linux/WSL con libfbclient2 instalado no hace falta: se encuentra sola
  $PY ci/crear_replica.py
  $PY -m config_microsip.cli verificar-conexion > /dev/null
}

pruebas() {
  servicios
  DATOS=$(mktemp -d); cp -R fuentes fixtures "$DATOS"/
  paso "Migración en vivo de la réplica a PostgreSQL (config_ci)"
  CONFIG_MICROSIP_DATOS="$DATOS" COLUMNS=160 $PY -m config_microsip.cli migrar-todo --firebird-real --permitir-borrador --reset-esquema
  paso "Pruebas: unit, integration, differential, e2e (con cobertura, mínimo 80%)"
  $BIN/pytest -q --cov --cov-report=term --cov-fail-under=80 -rs
  rm -rf "$DATOS"
}

construccion() {
  paso "Construcción: paquete y imagen"
  rm -rf dist && $PY -m build -q > /dev/null && $BIN/twine check --strict dist/*
  docker build -q -t config-microsip:ci . > /dev/null
  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest image \
    --exit-code 1 --severity CRITICAL,HIGH --ignore-unfixed --no-progress -q config-microsip:ci > /dev/null
  echo "imagen config-microsip:ci sin vulnerabilidades HIGH/CRITICAL con corrección disponible"
}

case "$ETAPA" in
  calidad) calidad ;;
  seguridad) seguridad ;;
  pruebas) pruebas ;;
  construccion) construccion ;;
  todas) calidad; seguridad; pruebas; construccion ;;
  *) echo "Etapa desconocida: $ETAPA"; exit 2 ;;
esac
paso "OK: $ETAPA"
