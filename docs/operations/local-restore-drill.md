# Local backup restore drill

This procedure restores an authorized private dump into a **new, disposable local PostgreSQL 18 database**. It does not restore, rename, or modify a production database and does not establish production recovery or cutover readiness. The October 20 run used `127.0.0.1:55520`, a fresh `gl3_audit_20261020_corpus_test` database, and `pg_restore` with `--no-owner --no-privileges --exit-on-error`; see the [dated sanitized observation](observations/2026-10-20-production-readonly.md).

## Preconditions

- Obtain a private copy through an authorized channel and keep it under ignored `.artifacts/`; do not add the dump to Git, attach it to a report, or put it in a shared/public directory. Keep the source copy unchanged. Off-host retention and the method for retrieving a copy remain UNKNOWN.
- Use PostgreSQL 18 client tools and a local PostgreSQL 18 server bound to `127.0.0.1`. The documented execution was on port `55520`; set `$pgPort` to the port of the disposable local server you have verified.
- Choose a new target name matching `gl3_restore_YYYYMMDD_runN_test`. The script below refuses a non-loopback endpoint, an unsafe name, an existing database, a dump with the wrong expected digest, or an unreadable archive.
- Use a local PostgreSQL role permitted to create databases. Enter its password only at the secure prompt; the helper places it in the PowerShell process environment temporarily for the local client processes and clears it afterward. It is never a command-line argument or printed value.
- Do not start the GridLens API or worker for this drill. `pg_restore` and the read-only SQL checks do not invoke providers, dispatch jobs, or perform source retrieval.

## Verify and restore

Run from the repository root in PowerShell. Replace only the PostgreSQL 18 tool path, local role, port, private dump path, and unique fresh database name. The expected digest and size below are for the October 20 pre-deploy dump used in the observed drill; for another dump, obtain both from an independently trusted receipt before proceeding.

```powershell
$pgBin = 'C:\Program Files\PostgreSQL\18\bin'
$pgHost = '127.0.0.1'
$pgPort = 55520
$pgRole = '<LOCAL_CREATEDB_ROLE>'
$targetDb = 'gl3_restore_20261021_run1_test'
$dump = '<PRIVATE_IGNORED_PATH_TO_AUTHORIZED_DUMP>'
$expectedSha256 = 'b74583c19cf03fc6a290d736d4aa942388157cece729358da7c6f2e834d742e1'
$restoreLog = Join-Path $PWD ".artifacts\local-restore-$targetDb.log"

if ($pgHost -ne '127.0.0.1') { throw 'Refusing non-loopback database host' }
if ($pgRole -notmatch '^[a-z_][a-z0-9_]*$') { throw 'Use a simple local PostgreSQL role name' }
if ($targetDb -notmatch '^gl3_restore_[0-9]{8}_run[0-9]+_test$') { throw 'Use a new disposable restore target name' }
if (-not (Test-Path -LiteralPath $dump -PathType Leaf)) { throw 'Private dump file is missing' }
if ((Get-Item -LiteralPath $dump).Length -ne 18796646) { throw 'Dump size does not match the October 20 receipt' }
if ((Get-FileHash -LiteralPath $dump -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedSha256) { throw 'Dump digest does not match trusted receipt' }

$pgRestore = Join-Path $pgBin 'pg_restore.exe'
$psql = Join-Path $pgBin 'psql.exe'
if (-not (Test-Path $pgRestore) -or -not (Test-Path $psql)) { throw 'PostgreSQL 18 client tools not found' }
& $pgRestore --list $dump *> $null
if ($LASTEXITCODE -ne 0) { throw 'Dump archive listing failed' }

$secure = Read-Host 'Local PostgreSQL role password' -AsSecureString
$secretPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPtr)
    $endpoint = & $psql --no-psqlrc --host $pgHost --port $pgPort --username $pgRole --dbname postgres --tuples-only --no-align --command "SELECT inet_server_addr()::text || ':' || inet_server_port()"
    if ($LASTEXITCODE -ne 0 -or $endpoint.Trim() -ne "${pgHost}:$pgPort") { throw 'Database endpoint is not the verified loopback PostgreSQL server' }

    $exists = & $psql --no-psqlrc --host $pgHost --port $pgPort --username $pgRole --dbname postgres --tuples-only --no-align --command "SELECT count(*) FROM pg_database WHERE datname = '$targetDb'"
    if ($LASTEXITCODE -ne 0) { throw 'Could not check target database' }
    if ($exists.Trim() -ne '0') { throw 'Refusing to overwrite an existing database; choose another fresh name' }

    & $psql --no-psqlrc --host $pgHost --port $pgPort --username $pgRole --dbname postgres --set ON_ERROR_STOP=1 --command "CREATE DATABASE `"$targetDb`" OWNER `"$pgRole`""
    if ($LASTEXITCODE -ne 0) { throw 'Could not create fresh restore target' }

    New-Item -ItemType Directory -Force -Path (Split-Path $restoreLog) | Out-Null
    & $pgRestore --host $pgHost --port $pgPort --username $pgRole --dbname $targetDb --no-owner --no-privileges --exit-on-error $dump *> $restoreLog
    if ($LASTEXITCODE -ne 0) { throw 'pg_restore failed; preserve the target and log for diagnosis' }

    $revision = & $psql --no-psqlrc --host $pgHost --port $pgPort --username $pgRole --dbname $targetDb --tuples-only --no-align --set ON_ERROR_STOP=1 --command 'SELECT version_num FROM alembic_version'
    if ($LASTEXITCODE -ne 0 -or $revision.Trim() -ne '0032_power_need_titles') { throw 'Restored schema revision does not match the receipt' }
    $counts = & $psql --no-psqlrc --host $pgHost --port $pgPort --username $pgRole --dbname $targetDb --tuples-only --no-align --field-separator ',' --set ON_ERROR_STOP=1 --command 'SELECT (SELECT count(*) FROM projects), (SELECT count(*) FROM evidence), (SELECT count(*) FROM observations)'
    if ($LASTEXITCODE -ne 0 -or $counts.Trim() -ne '1620,18016,16694') { throw 'Restored row counts do not match the receipt' }
    Write-Host "Restore readback passed: schema $($revision.Trim()); projects,evidence_versions,observations=$($counts.Trim())"
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPtr)
}
```

Compare the restored schema revision and row counts with the expected source receipt. For the October 20 dump the revision was `0032_power_need_titles` (schema revision 0032), with 1,620 projects, 18,016 evidence versions, and 16,694 observations. Preserve the dump digest, restore log, exact database name, timestamp, and readback result in the private local evidence directory. Do not add a `pg_restore --clean` or `--create` flag, overwrite an existing target, or drop the restored database as part of this drill. Retain or remove the disposable database only under a separately recorded local cleanup decision.

## Evidence boundary

The October 20 execution harness checked that its exact target did not exist, verified a loopback PostgreSQL endpoint on port `55520`, set `PGPASSWORD` only in the child process environment without logging it, restored with the flags above, and read back the table counts. The sanitized receipt records the dump digest and observed counts; hashes of the harness and its empty successful restore log are included there. This makes the **local isolated restore pattern reproducible**. It does not establish the production backup service body, off-host retention, host secret-injection wrapper, production restore command, rollback command, recovery time, or production cutover. Later dated release evidence is linked from the [operations authority](README.md); it must be assessed for its exact images, schema and environment. This October 20 drill does not establish current production recovery readiness or authorize a production action.
