#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
ENV_FILE="${ENV_FILE:-.env}"
export ENV_FILE
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

previous_image="$(docker inspect --format '{{.Image}}' "${CONTAINER_NAME}" 2>/dev/null || true)"
replaced_container=false
rollback_on_failure() {
  local result=$?
  trap - EXIT
  if [[ "${result}" != 0 && "${replaced_container}" == true && -n "${previous_image}" ]]; then
    echo "[ERROR] Deployment failed. Restoring previous application image."
    export BOT_IMAGE="${previous_image}"
    if run_compose up -d --no-build --force-recreate "${SERVICE_NAME}" && wait_for_health; then
      echo "[INFO] Previous application restored. Deployment remains failed."
    else
      echo "[ERROR] Rollback did not become healthy. Operator intervention required."
    fi
  fi
  exit "${result}"
}
trap rollback_on_failure EXIT

ensure_dependency_image() {
  local deps_hash

  deps_hash="$(sha256sum requirements.txt Dockerfile.deps | sha256sum | awk '{print $1}')"
  DEPS_IMAGE="${DEPS_IMAGE:-${DEPS_IMAGE_REPOSITORY}:${deps_hash}}"
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
  local health_error
  for attempt in $(seq 1 "${HEALTHCHECK_MAX_ATTEMPTS}"); do
    if health_error="$(curl --fail --silent --show-error --connect-timeout 5 --max-time 10 --output /dev/null -H "Host: ${HEALTHCHECK_HOST_HEADER}" "${HEALTHCHECK_URL}" 2>&1)"; then
      echo "[INFO] Bot health check succeeded."
      return 0
    fi

    echo "[INFO] Waiting for bot health check (${attempt}/${HEALTHCHECK_MAX_ATTEMPTS})..."
    sleep "${HEALTHCHECK_INTERVAL_SECONDS}"
  done

  echo "[ERROR] Bot health check failed: ${HEALTHCHECK_URL}"
  echo "[ERROR] Last health check response: ${health_error}"
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
    export BOT_IMAGE="bot-discord-bot:$(git rev-parse --short HEAD 2>/dev/null || date +%s)"
    ensure_dependency_image

    echo "[INFO] Building ${SERVICE_NAME} image..."
    run_compose build "${SERVICE_NAME}"
    echo "[INFO] Checking application image excludes local secrets..."
    docker run --rm --entrypoint sh "${BOT_IMAGE}" -c 'test ! -f /app/.env && test ! -f /app/.env.deploy && test ! -f /app/cookies.txt'

    echo "[INFO] Starting ${SERVICE_NAME} service..."
    replaced_container=true
    if [[ "${MODE}" == "force" ]]; then
      run_compose up -d --no-build --force-recreate "${SERVICE_NAME}"
    else
      run_compose up -d --no-build "${SERVICE_NAME}"
    fi
    wait_for_health
    ;;
  restart)
    export BOT_IMAGE="${previous_image:-bot-discord-bot}"
    replaced_container=true
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
