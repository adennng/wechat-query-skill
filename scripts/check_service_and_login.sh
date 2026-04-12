#!/usr/bin/env bash

set -u

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_DIR="$BASE_DIR/services/wechat-download-api"
CURL_BIN="${CURL_BIN:-curl}"
HEALTH_RETRIES="${HEALTH_RETRIES:-3}"
HEALTH_RETRY_DELAY="${HEALTH_RETRY_DELAY:-3}"
COMPOSE_CMD="${WECHAT_QUERY_COMPOSE_CMD:-${WECHAT_WATCH_COMPOSE_CMD:-}}"

resolve_base_url() {
  if [[ -n "${WECHAT_QUERY_BASE_URL:-}" ]]; then
    echo "$WECHAT_QUERY_BASE_URL"
    return 0
  fi

  if [[ -n "${WECHAT_WATCH_BASE_URL:-}" ]]; then
    echo "$WECHAT_WATCH_BASE_URL"
    return 0
  fi

  local env_file="$SERVICE_DIR/.env"
  if [[ -f "$env_file" ]]; then
    local site_url
    site_url="$(grep -E '^SITE_URL=' "$env_file" | tail -n 1 | cut -d= -f2- || true)"
    if [[ -n "$site_url" ]]; then
      echo "$site_url"
      return 0
    fi

    local port
    port="$(grep -E '^PORT=' "$env_file" | tail -n 1 | cut -d= -f2- || true)"
    if [[ -n "$port" ]]; then
      echo "http://localhost:${port}"
      return 0
    fi
  fi

  echo "http://localhost:5000"
}

BASE_URL="$(resolve_base_url)"
HEALTH_URL="${BASE_URL}/api/health"
STATUS_URL="${BASE_URL}/api/admin/status"

json_escape() {
  python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"
}

print_result() {
  local ok="$1"
  local service_healthy="$2"
  local service_restarted="$3"
  local status_checked="$4"
  local login_state="$5"
  local authenticated="$6"
  local is_expired="$7"
  local action="$8"
  local message="$9"

  printf '{\n'
  printf '  "ok": %s,\n' "$ok"
  printf '  "service_healthy": %s,\n' "$service_healthy"
  printf '  "service_restarted": %s,\n' "$service_restarted"
  printf '  "status_checked": %s,\n' "$status_checked"
  printf '  "login_state": %s,\n' "$(json_escape "$login_state")"
  printf '  "authenticated": %s,\n' "$authenticated"
  printf '  "is_expired": %s,\n' "$is_expired"
  printf '  "action": %s,\n' "$(json_escape "$action")"
  printf '  "message": %s\n' "$(json_escape "$message")"
  printf '}\n'
}

fetch_health() {
  "$CURL_BIN" -fsS --max-time 10 "$HEALTH_URL" >/dev/null 2>&1
}

fetch_status() {
  "$CURL_BIN" -fsS --max-time 10 "$STATUS_URL" 2>/dev/null
}

resolve_compose_cmd() {
  if [[ -n "$COMPOSE_CMD" ]]; then
    echo "$COMPOSE_CMD"
    return 0
  fi

  if docker compose version >/dev/null 2>&1; then
    echo "docker compose"
    return 0
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    echo "docker-compose"
    return 0
  fi

  return 1
}

wait_for_health() {
  local i
  for ((i=1; i<=HEALTH_RETRIES; i++)); do
    if fetch_health; then
      return 0
    fi
    sleep "$HEALTH_RETRY_DELAY"
  done
  return 1
}

restart_service() {
  local compose_cmd

  if [[ ! -d "$SERVICE_DIR" ]]; then
    return 1
  fi

  compose_cmd="$(resolve_compose_cmd)" || return 1

  (
    cd "$SERVICE_DIR" || exit 1
    $compose_cmd up -d >/dev/null 2>&1
  )
}

parse_status_field() {
  local json="$1"
  local field="$2"
  python3 - "$json" "$field" <<'PY'
import json
import sys

raw = sys.argv[1]
field = sys.argv[2]
data = json.loads(raw)
value = data.get(field)
if isinstance(value, bool):
    print("true" if value else "false")
elif value is None:
    print("")
else:
    print(str(value))
PY
}

main() {
  local service_healthy="false"
  local service_restarted="false"
  local status_checked="false"
  local login_state="unknown"
  local authenticated="false"
  local is_expired="false"
  local action="none"
  local message=""
  local status_json=""

  if fetch_health; then
    service_healthy="true"
  else
    if restart_service && wait_for_health; then
      service_healthy="true"
      service_restarted="true"
    else
      print_result \
        "false" \
        "false" \
        "$service_restarted" \
        "false" \
        "$login_state" \
        "$authenticated" \
        "$is_expired" \
        "notify_service_down" \
        "service health check failed and auto restart did not recover it"
      exit 0
    fi
  fi

  status_json="$(fetch_status)"
  if [[ -z "$status_json" ]]; then
    print_result \
      "false" \
      "$service_healthy" \
      "$service_restarted" \
      "false" \
      "$login_state" \
      "$authenticated" \
      "$is_expired" \
      "notify_service_down" \
      "service is healthy but admin status endpoint is unavailable"
    exit 0
  fi

  status_checked="true"
  login_state="$(parse_status_field "$status_json" "loginState")"
  authenticated="$(parse_status_field "$status_json" "authenticated")"
  is_expired="$(parse_status_field "$status_json" "isExpired")"

  if [[ "$login_state" == "invalid" ]]; then
    action="notify_login_invalid"
    message="service is healthy but wechat login is invalid"
    print_result \
      "false" \
      "$service_healthy" \
      "$service_restarted" \
      "$status_checked" \
      "$login_state" \
      "$authenticated" \
      "$is_expired" \
      "$action" \
      "$message"
    exit 0
  fi

  if [[ "$authenticated" != "true" ]]; then
    action="notify_not_logged_in"
    message="service is healthy but no active wechat login was found"
    print_result \
      "false" \
      "$service_healthy" \
      "$service_restarted" \
      "$status_checked" \
      "$login_state" \
      "$authenticated" \
      "$is_expired" \
      "$action" \
      "$message"
    exit 0
  fi

  if [[ "$is_expired" == "true" ]]; then
    action="warn_login_expiring"
    message="service is healthy and login still exists, but it is estimated to be expired"
    print_result \
      "true" \
      "$service_healthy" \
      "$service_restarted" \
      "$status_checked" \
      "$login_state" \
      "$authenticated" \
      "$is_expired" \
      "$action" \
      "$message"
    exit 0
  fi

  print_result \
    "true" \
    "$service_healthy" \
    "$service_restarted" \
    "$status_checked" \
    "$login_state" \
    "$authenticated" \
    "$is_expired" \
    "none" \
    "service and login are healthy"
}

main "$@"
