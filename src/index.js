const JSON_HEADERS = {
  "content-type": "application/json; charset=UTF-8",
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "authorization, content-type",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "cache-control": "no-store",
};

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });

function authorized(request, env) {
  const auth = request.headers.get("authorization") || "";
  return Boolean(env.SPR_COMMAND_KEY) &&
    auth === "Bearer " + env.SPR_COMMAND_KEY;
}

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
  } catch {
    message = "Updater status check failed";
  }
  return {
    ok: online, worker_online: online,
    last_seen: upstream?.last_seen || 0, checked_at: checked,
    state: online ? (upstream?.state || "idle") : "offline",
    message, last_update: upstream?.last_update || 0,
    last_ok: upstream?.last_ok ?? null,
    last_message: upstream?.last_message || "",
    build: upstream?.build || 613,
  };
}

async function queueCommand(request, env) {
  if (!authorized(request, env)) return json({ ok:false, error:"unauthorized" }, 401);
  let body;
  try { body = await request.json(); } catch { return json({ok:false,error:"invalid_json"},400); }
  const command = String(body?.command || "").toLowerCase();
  if (!["spr","rosters"].includes(command)) return json({ok:false,error:"invalid_command"},400);
  const existing = await env.SPR_COMMANDS.get("pending");
  if (existing) return json({ok:false,error:"busy"},409);
  const item = { id: crypto.randomUUID(), command, created_at: Math.floor(Date.now()/1000) };
  await env.SPR_COMMANDS.put("pending", JSON.stringify(item), { expirationTtl: 3600 });
  return json({ok:true, queued:true, id:item.id, command});
}

async function pollCommand(request, env) {
  if (!authorized(request, env)) return json({ok:false,error:"unauthorized"},401);
  const raw = await env.SPR_COMMANDS.get("pending");
  return json({ok:true, command: raw ? JSON.parse(raw) : null});
}

async function ackCommand(request, env) {
  if (!authorized(request, env)) return json({ok:false,error:"unauthorized"},401);
  let body;
  try { body = await request.json(); } catch { return json({ok:false,error:"invalid_json"},400); }
  const raw = await env.SPR_COMMANDS.get("pending");
  if (raw) {
    const pending = JSON.parse(raw);
    if (!body?.id || body.id === pending.id) await env.SPR_COMMANDS.delete("pending");
  }
  if (body?.id) {
    await env.SPR_COMMANDS.put("result:" + body.id, JSON.stringify({
      id: body.id, ok: Boolean(body.ok), message: String(body.message || ""),
      completed_at: Math.floor(Date.now()/1000)
    }), { expirationTtl: 86400 });
  }
  return json({ok:true});
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, {status:204, headers:JSON_HEADERS});
    const url = new URL(request.url);
    if (request.method === "GET" && ["/","/status","/updater-status.json"].includes(url.pathname))
      return json(await status(env));
    if (request.method === "POST" && url.pathname === "/command") return queueCommand(request, env);
    if (request.method === "GET" && url.pathname === "/worker/poll") return pollCommand(request, env);
    if (request.method === "POST" && url.pathname === "/worker/ack") return ackCommand(request, env);
    return new Response("Not found", { status: 404 });
  },
  async scheduled(controller, env, ctx) { ctx.waitUntil(status(env)); },
};
