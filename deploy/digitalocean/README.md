# DigitalOcean + Cloudflare deployment

One droplet runs the API, worker and web containers. DigitalOcean Managed PostgreSQL holds the data. Spaces holds nightly dumps and, later, permitted source artifacts. A Cloudflare Tunnel is the only ingress; the droplet publishes no ports. ntfy pushes health to Nick's phone.

## Resources (create once)

| Resource | Setting |
|---|---|
| Droplet | Ubuntu 24.04, 2 vCPU / 4 GB, Docker installed, firewall: inbound SSH only |
| Managed PostgreSQL | Version 18 if offered, else 17; trusted source = the droplet; daily backups on |
| Spaces bucket | Private, e.g. `gridlens-artifacts`; access key scoped to that bucket |
| Cloudflare Tunnel | Public hostname `gridlens.<domain>` → `http://web:8080`; add a Cloudflare Access policy for Nick's email |
| ntfy | Private topic name; subscribe in the phone app |

## Install on the droplet

```bash
sudo git clone https://github.com/nrsandoval1231-oss/gl3.git /opt/gridlens
cd /opt/gridlens
sudo cp deploy/digitalocean/env.prod.example .env.prod && sudo chmod 600 .env.prod
sudo nano .env.prod   # fill every value
sudo docker compose -f deploy/digitalocean/compose.prod.yaml --env-file .env.prod up -d --build
sudo cp deploy/digitalocean/systemd/* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gridlens-collect.timer gridlens-alert.timer gridlens-backup.timer
sudo /opt/gridlens/deploy/digitalocean/gridlens-run.sh alert   # phone should buzz
```

`WORKER_AUTO_REFRESH=false` makes the 07:00 America/Chicago timer the only collection planner. The worker still drains the queue continuously.

## Update

```bash
cd /opt/gridlens && sudo git pull
sudo docker compose -f deploy/digitalocean/compose.prod.yaml --env-file .env.prod up -d --build
```

## Restore procedure (Requirement 36)

1. Create a new empty database in the managed cluster (`gridlens_restore`).
2. Download the dump: `aws s3 cp s3://$SPACES_BUCKET/backups/<file>.dump . --endpoint-url https://$SPACES_REGION.digitaloceanspaces.com`
3. `pg_restore --no-owner --dbname "<restore URL>" <file>.dump`
4. Point a one-off API container at it (`DATABASE_URL=<restore URL>`), run `alembic upgrade head` and `alembic check`, and confirm `/health/ready` plus record counts.
5. To cut over, change `DATABASE_URL` in `.env.prod` and `up -d`.

The managed cluster's own point-in-time backups are a second path. Record each restore drill with date and counts in `docs/operations/`.

## Alerts

- 08:30 and 18:00 America/Chicago: always one push. "collection healthy" or a list of failed/overdue sources, stale worker, or overdue collection.
- A failed collection or backup run triggers an immediate alert run.
- No morning push means the droplet, timer, or ntfy path is down.
