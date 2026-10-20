# Production database identity and scheduled backups

Status: **PLAN — not applied.** Every step below needs Nick's explicit go. It was written
from a read-only audit on 2026-10-20 (see #93).

## Verified facts (2026-10-20)

| Fact | Evidence |
|---|---|
| The app's `DATABASE_URL` points at `gridlens_restore_20261014` on container `gridlens-db-1` (Postgres 18.6). | `printenv DATABASE_URL` in `gridlens-worker-1` (password masked) |
| A database named `gridlens` exists and holds **no** Grid Lens tables. | `information_schema.tables` query returned no rows |
| About 45 other databases sit beside production (`*_preflight_*`, `*_ci_*`, `*_test`, `gridlens_evalpost_*`, and others). | `pg_database` listing |
| No `gridlens-*` systemd timers exist. The repo's `gridlens-run.sh backup` path is not installed. | `systemctl list-timers --all` |
| One verified manual dump exists: `/opt/gridlens/backups/pre-deploy-20261020T151920Z.dump` (18 MB, 54 table-data entries, sha256 `b74583c1…`). | `pg_restore --list` |
| The DigitalOcean droplet page shows an **Automated Backups** panel and a "Backup" activity entry. | Owner's screenshot. Frequency and retention are **unverified**. |
| The deploy uses `/etc/gridlens/compose.app.yaml` with an `env_file` of `/etc/gridlens/runtime.env` and timestamped `compose.app.pre-*.yaml` copies. | Host listing |

## Risk 1: the live database is named like a disposable copy

**Why it matters.** Anyone cleaning up the ~45 scratch databases will reasonably delete
`*_restore_*` copies. That would delete production. Postgres refuses `DROP DATABASE` while
the app holds connections, but `DROP DATABASE … WITH (FORCE)` or a stopped stack removes
that protection.

### Step 1A: label it now (no downtime, reversible)

```bash
docker exec gridlens-db-1 psql -U gridlens -d postgres -c "COMMENT ON DATABASE gridlens_restore_20261014 IS 'LIVE PRODUCTION for app.grid-lens.com - do not drop or rename without a verified backup and owner approval'"
```

To undo, run the same command with `IS NULL`.

### Step 1B: rename it to `gridlens_prod` (planned window, about 2–5 minutes of downtime)

Do this only together with the next deploy, because that deploy restarts the services anyway.
A rename needs zero open connections.

1. **Take and verify a fresh dump.** Use the backup script below, run once by hand.
2. **Find where the URL is set.** This prints file and line, with the value masked:
   `grep -n DATABASE_URL /etc/gridlens/runtime.env /etc/gridlens/compose.app.yaml | sed -E 's#//([^:/@]+):[^@]*@#//\1:***@#'`
3. **Save a copy of that file:**
   `cp /etc/gridlens/runtime.env /etc/gridlens/runtime.env.pre-dbrename-$(date -u +%Y%m%dT%H%M%SZ)`
4. **Stop the app services.** Leave `db` running:
   `docker stop gridlens-api-1 gridlens-worker-1 gridlens-browse-1 gridlens-web-1`
5. **Rename the database:**
   `docker exec gridlens-db-1 psql -U gridlens -d postgres -c "ALTER DATABASE gridlens_restore_20261014 RENAME TO gridlens_prod"`
6. **Point the app at the new name.** In the file found in step 2, change only the database
   name at the end of `DATABASE_URL` from `/gridlens_restore_20261014` to `/gridlens_prod`.
7. **Start the services** with the normal compose command for the release.
8. **Verify:**
   - `/api/health` returns 200.
   - The worker heartbeat is less than 1 minute old.
   - Row counts match the pre-rename dump: evidence 18,008; projects 1,620; logical_calls 10.

**Rollback** (database and app both stay intact):
1. `ALTER DATABASE gridlens_prod RENAME TO gridlens_restore_20261014`
2. Restore the saved `runtime.env` copy.
3. Restart the services.

### Step 1C: clean up the scratch databases (destructive, separate approval)

Not proposed yet. Before any database is dropped, it needs all of the following:
- An explicit list.
- Proof that nothing references it, from a `grep` across `/etc/gridlens`, the releases and the running env.
- A dump of each one.
- Nick's approval of the exact list.

The empty `gridlens` database stays until then.

## Risk 2: no scheduled, verified backups

The droplet snapshot (if enabled) protects the whole disk. It is not a database-consistent,
restorable, verified logical backup, and it lives on the same provider account.

### Step 2A: daily verified logical dump (host systemd timer)

`/usr/local/sbin/gridlens-db-backup` (root, mode 0700):

```bash
#!/usr/bin/env bash
set -euo pipefail
DB="${GRIDLENS_DB:-gridlens_restore_20261014}"   # becomes gridlens_prod after Step 1B
DIR=/opt/gridlens/backups
KEEP_DAYS=14
stamp=$(date -u +%Y%m%dT%H%M%SZ)
out="$DIR/daily-$stamp.dump"
tmp="$out.partial"
mkdir -p "$DIR"; chmod 700 "$DIR"
docker exec gridlens-db-1 pg_dump -U gridlens -Fc "$DB" > "$tmp"
tables=$(docker exec -i gridlens-db-1 pg_restore --list < "$tmp" | grep -c 'TABLE DATA')
if [ "$tables" -lt 50 ]; then echo "backup verification failed: $tables tables" >&2; exit 1; fi
mv "$tmp" "$out"
sha256sum "$out" > "$out.sha256"
find "$DIR" -name 'daily-*.dump*' -mtime +"$KEEP_DAYS" -delete
echo "ok $out tables=$tables size=$(stat -c %s "$out")"
```

`/etc/systemd/system/gridlens-db-backup.service`:

```ini
[Unit]
Description=Grid Lens verified daily database dump
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/gridlens-db-backup
```

`/etc/systemd/system/gridlens-db-backup.timer`:

```ini
[Unit]
Description=Daily Grid Lens database dump
[Timer]
OnCalendar=*-*-* 08:17:00 UTC
Persistent=true
RandomizedDelaySec=300
[Install]
WantedBy=timers.target
```

Enable and test it once:

```bash
systemctl daemon-reload && systemctl enable --now gridlens-db-backup.timer && systemctl start gridlens-db-backup.service && journalctl -u gridlens-db-backup.service -n 5 --no-pager
```

**Properties of this script:**
- It never touches the live database except to read it.
- It deletes only its own `daily-*` files older than 14 days. The manual `pre-deploy-*` dump is kept.
- The dump is about 18 MB a day, so 14 days is roughly 250 MB against 136 GB free.
- A failure is visible in `journalctl` and `systemctl list-timers` (last run result).

### Step 2B: prove a restore (weekly, or at least before each deploy)

```bash
docker exec gridlens-db-1 psql -U gridlens -d postgres -c "DROP DATABASE IF EXISTS gridlens_restore_check" -c "CREATE DATABASE gridlens_restore_check" && docker exec -i gridlens-db-1 pg_restore -U gridlens -d gridlens_restore_check --no-owner < $(ls -t /opt/gridlens/backups/daily-*.dump | head -1) && docker exec gridlens-db-1 psql -U gridlens -d gridlens_restore_check -c "select (select count(*) from evidence) evidence, (select count(*) from projects) projects, (select count(*) from logical_calls) calls" && docker exec gridlens-db-1 psql -U gridlens -d postgres -c "DROP DATABASE gridlens_restore_check"
```

The scratch database has a fixed name, `gridlens_restore_check`. It is created and dropped
by this command only, and its name cannot collide with production.

### Step 2C: off-host copy (recommended; needs a decision)

Local dumps share the droplet's disk. Choose one of these:
- **(a)** Confirm that DigitalOcean droplet backups are enabled, and record their frequency
  and retention in this document. This costs nothing new to set up, but it is the same provider.
- **(b)** Copy each daily dump to DigitalOcean Spaces. The repo's `gridlens-run.sh backup`
  already contains this path. It needs Spaces credentials in the host env, which may cost a
  few dollars a month. This is a new paid resource, so it needs the owner's approval.

## Order of operations

1. **1A label:** now, no downtime.
2. **2A daily dump and 2B restore proof:** now, no downtime.
3. **2C decision:** the owner chooses (a) or (b).
4. **1B rename:** in the next deploy window.
5. **1C scratch-database cleanup:** separate list and separate approval.
