# test_commit
SELECT
  r.rolname AS role_name,
  n.nspname AS schema_name,
  has_schema_privilege(r.rolname, n.nspname, 'usage') AS can_usage,
  has_schema_privilege(r.rolname, n.nspname, 'create') AS can_create,
  has_schema_privilege(r.rolname, n.nspname, 'alter') AS can_alter,
  has_schema_privilege(r.rolname, n.nspname, 'drop') AS can_drop
FROM
  pg_roles r
CROSS JOIN
  pg_namespace n
WHERE
  n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
  AND r.rolname = '対象のロール名'
ORDER BY
  r.rolname, n.nspname;
