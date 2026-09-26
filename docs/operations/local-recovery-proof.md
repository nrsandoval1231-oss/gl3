# Local recovery proof — first structured path

At the first runtime checkpoint on 2026-09-25, `pg_dump -Fc` of the isolated `gridlens` database succeeded and `pg_restore --exit-on-error` into a newly created `gridlens_restore_first` database succeeded. The application database was not replaced or cleared.

- Server: local PostgreSQL18 at 127.0.0.1:55439.
- Backup: ignored `.artifacts/local-postgres/gridlens-first-path.dump`.
- SHA256: `17C00CDA6DDCFCDEBEEDE6FA2E154D245CC6F7A20D016964B43FF6817F48978F`.
- Restored counts: 77 observations, 77 evidence versions, 1 project, 1 power need, 1 change event.
- Commands: PostgreSQL18 `pg_dump`, `createdb`, `pg_restore --exit-on-error`, `psql` count query; each exit 0.
- Credentials were loaded from the ignored cluster secret file into the command environment and removed after use; never printed.

## Integrated slice snapshot

At 2026-09-25T19:44:54Z the controller repeated dump/restore after the HTML/PDF integration and classification correction. All three commands exited 0. The backup `.artifacts/local-postgres/gridlens-20260925194453.dump` has SHA256 `beb3bd95276fe58b2fd4a57f6435d6fb11f57c6d1aaa3233169d8e7d53b554e8`. It was restored into the new isolated database `gridlens_restore_20260925194453`.

Restored counts: 92 observations, 93 evidence versions, four project/need histories, three active needs, five material-history events. The inactive history is the retained aggregate-report admission corrected during validation. Machine-readable receipt: ignored `.artifacts/final-restore-proof.json`. The application database was not cleared or replaced.

These prove local snapshot restores only. They do not prove a managed backup schedule, off-machine retention, cloud recovery objective, or the PRD seven-day operating gate.
