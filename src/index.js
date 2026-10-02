const JSON_HEADERS = {
  "content-type": "application/json; charset=UTF-8",
  "access-control-allow-origin": "*",
  "cache-control": "no-store",
};

async function status(env) {
  const checked = Math.floor(Date.now() / 1000);
  let online = false;
  let upstream = null;
  let message = "Online updater unavailable";

  try {
    const response = await fetch(env.UPDATER_STATUS_URL, {
      headers: { "cache-control": "no-cache" },
      cf: { cacheTtl: 0, cacheEverything: false },
    });
    if (response.ok) {
      upstream = await response.json();
      const lastSeen = Number(upstream.last_seen || 0);
      online = Boolean(upstream.worker_online) && lastSeen > 0 &&
        (checked - lastSeen) <= Number(env.MAX_AGE_SECONDS || 7200);
      message = online ? (upstream.message || "Online updater ready") :
        "Online updater heartbeat is stale";
    } else {
      message = "Updater status returned HTTP " + response.status;
    }
  } catch (error) {
    message = "Updater status check failed";
  }

  return {
    ok: online,
    worker_online: online,
    last_seen: upstream?.last_seen || 0,
    checked_at: checked,
    state: online ? (upstream?.state || "idle") : "offline",
    message,
    last_update: upstream?.last_update || 0,
    last_ok: upstream?.last_ok ?? null,
    last_message: upstream?.last_message || "",
    build: upstream?.build || 613,
  };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/" && url.pathname !== "/status" &&
        url.pathname !== "/updater-status.json") {
      return new Response("Not found", { status: 404 });
    }
    return new Response(JSON.stringify(await status(env)), { headers: JSON_HEADERS });
  },

  async scheduled(controller, env, ctx) {
    ctx.waitUntil(status(env));
  },
};
