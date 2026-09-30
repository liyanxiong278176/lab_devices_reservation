#!/bin/sh
set -eu

: "${MYSQL_EXPORTER_PASSWORD:?MYSQL_EXPORTER_PASSWORD must be set}"
umask 077
cat > /tmp/mysqld-exporter.cnf <<EOF
[client]
user=metrics_exporter
password=${MYSQL_EXPORTER_PASSWORD}
host=mysql
port=3306
EOF
chmod 600 /tmp/mysqld-exporter.cnf
unset MYSQL_EXPORTER_PASSWORD

exec /bin/mysqld_exporter --config.my-cnf=/tmp/mysqld-exporter.cnf
