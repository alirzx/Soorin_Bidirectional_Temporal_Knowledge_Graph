#!/bin/bash
# Fresh databases only. Existing role passwords are deliberately not rotated.
# The migration owner grants application privileges in migration 0010.
if [ -n "${UTOPIA_APP_DB_PASSWORD:-}" ]; then
    (
        set -e
        psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
            -v role_password="$UTOPIA_APP_DB_PASSWORD" -v database_name="$POSTGRES_DB" <<'SQL'
SELECT format('CREATE ROLE utopia_app LOGIN PASSWORD %L', :'role_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'utopia_app')
\gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO utopia_app', :'database_name')
\gexec
SQL
    )
else
    echo "Runtime database role not provisioned; set UTOPIA_APP_DB_PASSWORD for least privilege." >&2
fi
