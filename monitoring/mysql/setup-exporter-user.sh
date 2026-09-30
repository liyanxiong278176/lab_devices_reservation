#!/bin/sh
set -eu

: "${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD must be set}"
: "${MYSQL_DATABASE:?MYSQL_DATABASE must be set}"
: "${MYSQL_USER:?MYSQL_USER must be set}"
: "${MYSQL_PASSWORD:?MYSQL_PASSWORD must be set}"
: "${MYSQL_EXPORTER_PASSWORD:?MYSQL_EXPORTER_PASSWORD must be set}"
if [ "${#MYSQL_EXPORTER_PASSWORD}" -lt 32 ]; then
  echo "MYSQL_EXPORTER_PASSWORD must contain at least 32 characters" >&2
  exit 1
fi
case "$MYSQL_EXPORTER_PASSWORD" in
  *[!a-fA-F0-9]*)
    echo "MYSQL_EXPORTER_PASSWORD must be hexadecimal" >&2
    exit 1
    ;;
esac

attempt=0
until MYSQL_PWD="$MYSQL_PASSWORD" mysql \
  --connect-timeout=2 \
  --protocol=TCP \
  --host=mysql \
  --user="$MYSQL_USER" \
  --database="$MYSQL_DATABASE" \
  --batch \
  --skip-column-names \
  --execute='SELECT 1' >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 60 ]; then
    echo "MySQL is not ready for the application account; exporter account was not changed" >&2
    exit 1
  fi
  sleep 2
done

MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --protocol=socket --socket=/var/run/mysqld/mysqld.sock --user=root --batch <<SQL
CREATE USER IF NOT EXISTS 'metrics_exporter'@'%' IDENTIFIED BY '$MYSQL_EXPORTER_PASSWORD' WITH MAX_USER_CONNECTIONS 3;
ALTER USER 'metrics_exporter'@'%' IDENTIFIED BY '$MYSQL_EXPORTER_PASSWORD' WITH MAX_USER_CONNECTIONS 3;
GRANT PROCESS, REPLICATION CLIENT, SELECT ON *.* TO 'metrics_exporter'@'%';
SQL
echo "MySQL metrics account is ready"
