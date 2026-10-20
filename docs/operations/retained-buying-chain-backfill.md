# Retained buying-chain backfill

The command plans a bounded page of projects by default and does not enqueue jobs. Use `--after-project-id` with the reported `next_cursor` to advance pages. `--limit` is capped at 100.

For an isolated disposable test database, the default target is `TEST_DATABASE_URL` and its name must end in `_test`:

```powershell
uv run python scripts/backfill_retained_buying_chain.py --limit 25
uv run python scripts/backfill_retained_buying_chain.py --limit 25 --apply --expected-database-name gridlens_test
```

An explicitly authorized application-target run uses `DATABASE_URL`; the exact database name must be supplied and is checked before any transaction:

```powershell
uv run python scripts/backfill_retained_buying_chain.py --database-target application --limit 25
uv run python scripts/backfill_retained_buying_chain.py --database-target application --limit 25 --apply --expected-database-name exact_database_name
```

An application-target `--apply` requires separate owner authorization for that specific backfill. This task does not authorize or execute production writes. Review the dry-run page and cursor first, then obtain authorization before applying each bounded page. The tool never retrieves external data.
