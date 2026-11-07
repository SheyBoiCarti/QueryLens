#!/bin/sh
set -e

# Restricted analyst role creation for MySQL fixture
mysql -u root -p"$MYSQL_ROOT_PASSWORD" <<-EOSQL
    CREATE USER IF NOT EXISTS 'analyst_read'@'%' IDENTIFIED BY 'analyst_secret_123';
    GRANT SELECT ON analytics_my.* TO 'analyst_read'@'%';
    FLUSH PRIVILEGES;
EOSQL
