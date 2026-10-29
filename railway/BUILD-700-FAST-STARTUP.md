# SPR Online Updater — prebuilt dependency image (Build 700)

## Why

The previous Railway service used the public image `mcr.microsoft.com/playwright/python:v1.55.0-noble`
and ran `apt-get update`, `apt-get install`, and `pip install` in its Railway
startup command on EVERY deployment, including restarts. This lengthened startup,
consumed transient memory/CPU/network usage, and repeated work.

## What changes

This repository root `Dockerfile` builds FROM the same Playwright image and
installs exactly the runtime packages:
- apt: xvfb, x11vnc, openbox, novnc, websockify, tzdata
- pip: playwright==1.55.0, requests>=2.32,<3, paramiko>=3.4,<5, pypdf>=5,<7

The existing Railway startCommand is preserved except the two install sections.
It still reconstructs the updater from the `SPR_BUNDLE_*` Railway environment
variables, applies ALL existing version-pinned GitHub patches, runs
`/app/start.sh`, and uses the existing persistent `/data` volume.

The production service source should be pinned to an exact Git commit containing
this Dockerfile so future frontend/Cloudflare GitHub commits do not trigger
unrelated updater rebuilds.

**Never** put passwords, SFTP private keys, Railway environment variables,
session data or stored SPR/roster PDFs in the Docker image or this repository.

## Verification

Before calling the migration complete, confirm:
1. Railway BUILD log uses the Dockerfile and shows
   `[SPR BUILD DEPENDENCIES READY]`.
2. Runtime deploy log contains NO apt or pip install stages.
3. Runtime log shows the normal patched updater and `SPR Online Updater READY`.
4. Startup patches include 08:00/12:00/16:00/22:00 Australia/Sydney,
   Guards-role checks and existing single-site SFTP publishing.
5. The existing Bodgybros SPR Search Build 700 website is unaffected.

## Rollback

If the custom image fails, reconnect source image
`mcr.microsoft.com/playwright/python:v1.55.0-noble` to the SAME existing service
in Railway, restore the original apt and pip install commands into
the startup command, and deploy. Do not delete the service or persistent
`/data` volume. RC1 backup remains independent.

This migration improves deploy/restart efficiency. It does NOT, by itself,
eliminate regular browser automation CPU/RAM usage during scheduled updates.
