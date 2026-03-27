#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
ENV_FILE="${ENV_FILE:-.env}"
MODE="${1:-auto}"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-http://host.docker.internal:1557/health}"
HEALTHCHECK_HOST_HEADER="${HEALTHCHECK_HOST_HEADER:-host.docker.internal}"
HEALTHCHECK_MAX_ATTEMPTS="${HEALTHCHECK_MAX_ATTEMPTS:-24}"
HEALTHCHECK_INTERVAL_SECONDS="${HEALTHCHECK_INTERVAL_SECONDS:-5}"
LOG_DIR="${ROOT_DIR}/.deploy-logs"
METADATA_FILE="${LOG_DIR}/jenkins-deploy.latest.meta"
SERVICE_NAME="discord-bot"
CONTAINER_NAME="discord-bot-shin"
DEPS_IMAGE_REPOSITORY="${DEPS_IMAGE_REPOSITORY:-bot-discord-bot-deps}"

mkdir -p "${LOG_DIR}"

timestamp="$(date +%Y%m%d-%H%M%S)"
log_file="${LOG_DIR}/jenkins-deploy.${timestamp}.log"
latest_log_file="${LOG_DIR}/jenkins-deploy.latest.log"

exec > >(tee "${log_file}") 2>&1

cd "${ROOT_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[ERROR] ${ENV_FILE} not found."
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "[ERROR] docker compose or docker-compose command not found."
  exit 1
fi

run_compose() {
  "${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" "$@"
}

ensure_dependency_image() {
  local requirements_hash

  requirements_hash="$(sha256sum "${ROOT_DIR}/requirements.txt" | awk '{print $1}')"
  DEPS_IMAGE="${DEPS_IMAGE:-${DEPS_IMAGE_REPOSITORY}:${requirements_hash}}"
  export DEPS_IMAGE

  echo "[INFO] Using dependency image: ${DEPS_IMAGE}"

  if docker image inspect "${DEPS_IMAGE}" >/dev/null 2>&1; then
    echo "[INFO] Dependency image already exists. Skipping dependency rebuild."
    return 0
  fi

  echo "[INFO] Building dependency image from Dockerfile.deps..."
  docker build -f "${ROOT_DIR}/Dockerfile.deps" -t "${DEPS_IMAGE}" "${ROOT_DIR}"
}

wait_for_health() {
  local attempt
  for attempt in $(seq 1 "${HEALTHCHECK_MAX_ATTEMPTS}"); do
    if curl --fail --silent --show-error -H "Host: ${HEALTHCHECK_HOST_HEADER}" "${HEALTHCHECK_URL}" >/dev/null; then
      echo "[INFO] Bot health check succeeded."
      return 0
    fi

    echo "[INFO] Waiting for bot health check (${attempt}/${HEALTHCHECK_MAX_ATTEMPTS})..."
    sleep "${HEALTHCHECK_INTERVAL_SECONDS}"
  done

  echo "[ERROR] Bot health check failed: ${HEALTHCHECK_URL}"
  return 1
}

write_metadata() {
  cat > "${METADATA_FILE}" <<EOF
mode=${MODE}
service=${SERVICE_NAME}
container=${CONTAINER_NAME}
displayContainer=discord bot 神
EOF
}

case "${MODE}" in
  auto|force)
    ensure_dependency_image

    echo "[INFO] Building ${SERVICE_NAME} image..."
    run_compose build "${SERVICE_NAME}"

    echo "[INFO] Starting ${SERVICE_NAME} service..."
    if [[ "${MODE}" == "force" ]]; then
      run_compose up -d --no-build --force-recreate "${SERVICE_NAME}"
    else
      run_compose up -d --no-build "${SERVICE_NAME}"
    fi
    wait_for_health
    ;;
  restart)
    echo "[INFO] Restarting ${SERVICE_NAME} service without rebuild..."
    run_compose up -d --no-build --force-recreate "${SERVICE_NAME}"
    wait_for_health
    ;;
  *)
    echo "[ERROR] Unsupported deploy mode: ${MODE}"
    echo "Usage: scripts/jenkins_deploy.sh <auto|force|restart>"
    exit 1
    ;;
esac

write_metadata
run_compose ps
cp "${log_file}" "${latest_log_file}"
echo "[INFO] Latest log: ${latest_log_file}"
echo "[SUCCESS] Jenkins deploy completed."
