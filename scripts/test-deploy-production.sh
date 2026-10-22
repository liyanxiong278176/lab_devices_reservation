#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd)"
test_root="$(mktemp -d)"
[[ "$test_root" == /tmp/tmp.* || "$test_root" == "${TMPDIR%/}/tmp."* ]]
trap 'rm -rf "$test_root"' EXIT
revision=0123456789abcdef0123456789abcdef01234567
mkdir -p "$test_root/bin" "$test_root/.releases/$revision.test"
touch "$test_root/.env"
export DEPLOY_TEST_LOG="$test_root/docker.log" DEPLOY_TEST_REVISION="$revision"
cat > "$test_root/bin/docker" <<'MOCK'
#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$DEPLOY_TEST_LOG"
case "$*" in
  *' build '*) [[ "$DEPLOY_TEST_SCENARIO" != build-failure ]] ;;
  'ps -q '*service=mysql) echo mysql ;;
  'ps -q '*service=celery-worker) : ;;
  'exec mysql '*) if [[ "$DEPLOY_TEST_SCENARIO" == no-baseline ]]; then echo 0; else echo 1; fi ;;
  *' ps -q app') echo app ;;
  *' ps -q frontend') echo frontend ;;
  'inspect frontend '*) if [[ "$DEPLOY_TEST_SCENARIO" == stale-image ]]; then echo outdated; else echo "$DEPLOY_TEST_REVISION"; fi ;;
  'inspect app '*) echo "$DEPLOY_TEST_REVISION" ;;
  *' exec -T frontend '*) printf '{"revision":"%s"}\n' "$DEPLOY_TEST_REVISION" ;;
  *' exec -T gateway printenv APP_PUBLIC_ORIGIN') echo https://www.labdevicesreservation.online ;;
esac
MOCK
cat > "$test_root/bin/curl" <<'MOCK'
#!/usr/bin/env bash
if [[ "$DEPLOY_TEST_SCENARIO" == upload-limit ]]; then printf 413; else printf 403; fi
MOCK
chmod +x "$test_root/bin/docker" "$test_root/bin/curl"
export PATH="$test_root/bin:$PATH"
for scenario in build-failure no-baseline stale-image upload-limit success; do
  export DEPLOY_TEST_SCENARIO="$scenario"
  : > "$DEPLOY_TEST_LOG"
  if bash "$script_dir/deploy-production.sh" "$test_root" "$test_root/.releases/$revision.test" "$revision" > "$test_root/output" 2>&1; then
    [[ "$scenario" == success ]]
    test -f "$test_root/current/REVISION"
    grep -q 'app frontend' "$DEPLOY_TEST_LOG"
    grep -q 'labflow.migration=migrate' "$DEPLOY_TEST_LOG"
    grep -q 'up -d --no-deps gateway' "$DEPLOY_TEST_LOG"
  else
    [[ "$scenario" != success ]]
    if [[ "$scenario" == build-failure || "$scenario" == no-baseline ]]; then
      if grep -q ' stop app\|labflow.migration=migrate' "$DEPLOY_TEST_LOG"; then
        echo "FAIL: $scenario interrupted service or migrated" >&2
        exit 1
      fi
    fi
  fi
  printf 'PASS: %s\n' "$scenario"
done
