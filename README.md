# SPR Heartbeat Publisher

Cloudflare Worker that exposes one canonical CORS-enabled updater status endpoint for both SPR Search sites.

## Deploy

In Cloudflare **Workers & Pages**, import this GitHub repository and deploy it. The included `wrangler.toml` creates an hourly Cron Trigger.

After deployment, the status endpoint is:

`https://<worker>.workers.dev/updater-status.json`

The Worker checks the existing bodgybros Railway-published status and reports it as offline when its heartbeat is stale.

No passwords, cPanel tokens, SFTP keys, or Microsoft credentials belong in this repository.
