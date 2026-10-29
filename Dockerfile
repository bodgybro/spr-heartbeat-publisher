# SPR Online Updater — prebuilt dependency image, Build 700 fast-startup.
# ONLY operating-system and Python dependencies live in the image.
# The existing Railway startCommand continues to unpack SPR_BUNDLE_* at runtime,
# apply version-pinned patches, and run /app/start.sh. Never bake credentials
# or the private /data volume into this image.
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    DISPLAY=:99 \
    TZ=Australia/Sydney \
    SPR_UPDATER_DATA_DIR=/data \
    SPR_BROWSER_CHANNEL=bundled \
    SPR_HEADLESS=0

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
       xvfb x11vnc openbox novnc websockify tzdata \
 && rm -rf /var/lib/apt/lists/*

# Current updater bundle (Build 609 base): playwright==1.55.0, requests>=2.32,<3.
# Later tested patches add Paramiko (SFTP) and pypdf (Guards combined PDF).
# Installing them here avoids pip installs on each Railway restart.
RUN python -m pip install --no-cache-dir \
      "playwright==1.55.0" \
      "requests>=2.32,<3" \
      "paramiko>=3.4,<5" \
      "pypdf>=5,<7" \
 && python -c "import playwright, requests, paramiko, pypdf; print('[SPR BUILD DEPENDENCIES READY]')"

RUN mkdir -p /app/novnc /data/tmp \
 && cp -a /usr/share/novnc/. /app/novnc/

WORKDIR /app
EXPOSE 8080

# Do not add CMD/ENTRYPOINT. Railway retains its existing, proven
# startup command (unpacks bundle and runs /app/start.sh).
