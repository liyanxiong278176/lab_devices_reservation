#!/usr/bin/env bash
set -euo pipefail

deploy_path="${1:?Deployment root required}"
release_path="${2:?Clean release path required}"
revision="${3:?Commit SHA required}"
[[ "$revision" =~ ^[0-9a-f]{40}$ ]]
[[ "$release_path" == "$deploy_path/.releases/$revision."* ]]
test -r "$deploy_path/.env"
cd "$release_path"
export LABFLOW_REVISION="$revision"
compose=(docker compose --env-file "$deploy_path/.env" --project-directory "$release_path" -f "$release_path/docker-compose.prod.yml")

# Reconcile both services, including changes missed by previously failed deployments.
"${compose[@]}" config --quiet
"${compose[@]}" build --build-arg "APP_REVISION=$revision" app frontend
"${compose[@]}" pull gateway

mysql_id="$(docker ps -q --filter label=com.docker.compose.project=labprod --filter label=com.docker.compose.service=mysql)"
test -n "$mysql_id"
history="$(docker exec "$mysql_id" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N lab_reservation -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=0x666c797761795f736368656d615f686973746f7279"')"
if [[ "$history" != 1 ]]; then
  echo 'First Java cutover requires explicit verify and baseline; see docs/springboot-cutover.md. No running service was stopped.' >&2
  exit 1
fi

cli() {
  "${compose[@]}" run --rm --no-deps app java -jar /app/backend-java/app.jar \
    --spring.main.web-application-type=none "--labflow.migration=$1"
}
# Validate configuration and existing schema before interrupting traffic.
cli verify
ids="$(docker ps -q --filter label=com.docker.compose.project=labprod --filter label=com.docker.compose.service=celery-worker)"
if [[ -n "$ids" ]]; then docker stop $ids; fi
"${compose[@]}" stop app
cli migrate
cli verify
cli invalidate-sessions
"${compose[@]}" run --rm --no-deps --user root app chown -R 10001:10001 /app/backend/.data
"${compose[@]}" up -d --no-deps --wait --wait-timeout 300 app
"${compose[@]}" exec -T app curl --fail --silent http://127.0.0.1:8000/api/v2/ready
"${compose[@]}" up -d --no-deps --force-recreate --wait --wait-timeout 120 frontend
"${compose[@]}" up -d --no-deps gateway

# A healthy old image is insufficient: both containers must identify this commit.
for service in app frontend; do
  id="$("${compose[@]}" ps -q "$service")"
  actual="$(docker inspect "$id" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')"
  [[ "$actual" == "$revision" ]]
done
"${compose[@]}" exec -T frontend wget -q -O - http://127.0.0.1/version.json | grep -F "$revision"
printf '%s\n' "$revision" > "$release_path/REVISION"
ln -sfn "$release_path" "$deploy_path/current"
printf 'Release %s is running from %s\n' "$revision" "$release_path"
