# Local runtime isolation

A fresh PostgreSQL 18 cluster was initialized for gl3 at `.artifacts/local-postgres/data`, listening only on 127.0.0.1:55439. The existing Windows PostgreSQL service on 5432 was not changed. The new `gridlens` and `gridlens_test` databases have a generated SCRAM password stored only in the ignored runtime directory. Never add that directory or `.env` to Git.

Start this already-initialized cluster from repository root (PowerShell):

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' -D "$PWD\.artifacts\local-postgres\data" -l "$PWD\.artifacts\local-postgres\server.log" start
```

Stop only this cluster:

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' -D "$PWD\.artifacts\local-postgres\data" stop -m fast
```

Runtime connection values are in `.artifacts/local-postgres/connection.env`. Application startup instructions are maintained in the root README. This local database is not a cloud deployment or a completion of Milestone A. Docker Desktop engine was unavailable during initial checks; the local PostgreSQL cluster provides real integration testing without changing the existing service.
