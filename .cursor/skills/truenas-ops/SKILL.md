---
name: truenas-ops
description: >-
  Operate income-share API/web on the TrueNAS SCALE host (k3s ix-charts, not
  host docker compose). Use when the user mentions TrueNAS, NAS deploy,
  income-share-api/web on 192.168.1.185, kubectl/ix-charts, or "redeploy on the NAS".
---

# TrueNAS ops (income-share)

Do not read `.env` or dump secrets. Never write passwords, Hub PATs, or the Postgres password into files or chat.

## Access

- SSH: `ssh ozelen@192.168.1.185` (BatchMode works; key already on this Mac)
- Host: TrueNAS SCALE (`truenas`, Linux 5.15.131+truenas, ~Cobia 23.10)
- User: ozelen (uid 3000, groups ozelen, builtin_users, admin)
- Apps run as **k3s ix-charts**, not host docker compose. `docker` and `k3s kubectl` need **passwordless sudo**.

## Useful commands

- `sudo docker ps`
- `sudo k3s kubectl get pods -A | grep income`
- namespaces: `ix-income-share-api` (SPA + API in one image). Old `ix-income-share-web` can be stopped/deleted.
- logs: `sudo k3s kubectl -n ix-income-share-api logs deploy/income-share-api-ix-chart --tail=50` (verify actual deploy/pod names if needed)

## App facts

- API image: zelenuk/income-share-api (linux/amd64) includes the Vite SPA. Published host port last used: 18022 → container 8000. App: http://192.168.1.185:18022/  Admin: http://192.168.1.185:18022/admin/
- Point `https://fin.zelen.uk` at the API service. No separate web image; no `API_HOST`.
- Postgres is the existing TrueNAS Postgres 16 app (`ix-postgres16`): POSTGRES_HOST=192.168.1.185 POSTGRES_PORT=15432 POSTGRES_DB=income POSTGRES_USER=income (password is on the NAS, never write it into the skill). Live data is `lake/databases/pg16` — do not write dumps there.
- DB dumps: `pg_dump -Fc` of `income` into `lake/finance/backups` (`/mnt/lake/finance/backups/income-share-*.dump`, owner `apps:apps`). Jenkins job `income-share-backup` / `Jenkinsfile.backup`, cron `H 3 * * *`, same SSH credential `ozelen` (writes via sudo). Keep 14 days. Restore: scale API/bot to 0, `kubectl -n ix-postgres16 exec -i deploy/postgres16-ix-chart -- pg_restore --clean --if-exists --no-owner -U postgres -d income < dump`.
- Django: DJANGO_ALLOWED_HOSTS=192.168.1.185,fin.zelen.uk and CSRF_TRUSTED_ORIGINS=http://192.168.1.185:18022,https://fin.zelen.uk
- Volumes on API: host /mnt/lake/finance/staticfiles → /app/staticfiles ; host /mnt/lake/finance/media → /app/media (NOT /apps/media).
- Bot: same image `zelenuk/income-share-api`, command `python manage.py run_telegram_bot`, no published port, same Postgres env + `/app/media`. Needs `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS`, `GEMINI_API_KEY`. TrueNAS app name `income-share-bot` → ns `ix-income-share-bot`. Do not run the bot inside the API container (two long-running processes).

## Images / pull

- TrueNAS caches :latest — pin digest when telling the user to update.
- Build from this Mac (arm64) with: docker buildx --builder amd64builder --platform linux/amd64 --push
- Hub user: zelenuk
- Never docker login with tokens from chat.

## CI/CD already in repo

- GitHub Actions tests + push; Jenkins (ix-jenkins pod) SSHes to the NAS with credential ID `ozelen` and `sudo k3s kubectl set image`s the SCALE apps (not compose).
- GitHub: https://github.com/ozelen/fin-reports

## Jenkins webhook (one job, both siblings)

GHA POSTs `IMAGE_TAG` to Jenkins after pushing `zelenuk/income-share-api`. Job redeploys API (and bot if `ix-income-share-bot` exists). Do not redeploy `ix-income-share-web`.

**Job:** Pipeline from SCM, name `income-share` (or `income-share-deploy`). Root `Jenkinsfile`.

**Generic Webhook Trigger:**
- Token: set one; do not put it in the repo
- Post content Parameters → Variable `IMAGE_TAG`, Expression `$.IMAGE_TAG`, JSONPath
- That maps onto the Jenkinsfile `IMAGE_TAG` parameter

**GHA secret `JENKINS_DEPLOY_URL`:**  
`https://<public-jenkins>/generic-webhook-trigger/invoke?token=<token>`  
(LAN Jenkins is NodePort `http://192.168.1.185:30067`. GitHub needs a public URL — tunnel / reverse proxy.)  
Optional: `JENKINS_USER` + `JENKINS_TOKEN` if the endpoint is auth-gated.

**Agent:** in-cluster `ix-jenkins` pod is fine. It SSHes to `ozelen@192.168.1.185` and runs `sudo k3s kubectl` on the host (SSH from the Jenkins pod to the host works — verified). No host SSH agent / extra SSH Agent plugin.

**Jenkins credential (global domain):**
- Kind: SSH Username with private key
- ID must be `ozelen` (Jenkinsfile `credentialsId: 'ozelen'`)
- Username: `ozelen`
- Private key: the key whose public half is on the NAS for `ozelen`
- Domain: global (not a folder-scoped domain)

Jenkins UI check: **Manage Jenkins → Credentials → System → Global credentials (unrestricted)** — an entry with **ID `ozelen`**, kind SSH Username with private key, username `ozelen`. If the ID is anything else, rename it to `ozelen` (or the job will fail to bind).

**What the job does:** SSH to the NAS, `set image` API (skip missing bot ns) to `zelenuk/income-share-api:$IMAGE_TAG`, then `rollout status` (180s).

Known deploys (SCALE ix-charts, verified):
- `ix-income-share-api` / `income-share-api-ix-chart` / container `ix-chart`
- no `ix-income-share-bot` yet
- `ix-income-share-web` is leftover nginx — stop/delete after the combined image is live
