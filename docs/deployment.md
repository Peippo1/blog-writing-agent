# Publishing Studio deployment

## Cloud resources

Deploy to Cloud Run in `europe-west2` with a dedicated service account. Grant
it only `roles/datastore.user` for the Firestore database and
`roles/secretmanager.secretAccessor` for the named secrets. Enable Cloud Run,
Cloud Build, Artifact Registry, Firestore, Secret Manager, and Cloud Scheduler.

The service must run with `APP_ENV=production`, a Firebase project ID, an
explicit `ALLOWED_EMAILS` allowlist, and a real Cloud Run hostname in
`APP_ALLOWED_HOSTS`. Do not deploy with `DEV_BYPASS_AUTH=true`.

## Secrets and integrations

Create these Secret Manager values outside source control:

- `GOOGLE_API_KEY`
- `GITHUB_APP_PRIVATE_KEY`
- `GITHUB_WEBHOOK_SECRET`
- `SCHEDULER_SECRET`

Set `GITHUB_APP_ID` and `GITHUB_APP_INSTALLATION_ID` as Cloud Run environment
variables. Install the GitHub App only on the private portfolio repository,
with Contents and Pull requests read/write permissions. Configure its webhook
to call `/webhooks/github` for pull-request events.

Set all `PORTFOLIO_*` settings to the portfolio repository’s real content path,
branch, and canonical URL pattern. The service opens a PR but never merges it.

## Release automation

Configure Cloud Scheduler using `cloud-scheduler.yaml` for 09:00 every Friday
in `Europe/London`. Send `SCHEDULER_SECRET` through the protected scheduler
header. Restrict the scheduler job’s service account and the Cloud Run ingress
at the infrastructure layer where available.

After a portfolio PR is manually merged, GitHub sends a signed webhook. The
service checks the canonical page before it marks an article live and enables
the manual LinkedIn package.
