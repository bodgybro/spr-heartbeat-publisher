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
  return Boolean(env.SPR_COMMAND_KEY) && auth === "Bearer " + env.SPR_COMMAND_KEY;
}

async function status(env) {
  const checked = Math.floor(Date.now() / 1000);
  let upstream = null;
  let source = "none";
  let message = "Online updater unavailable";

  // Prefer the Railway heartbeat written directly to Cloudflare. This avoids
  // making updater availability depend on cPanel's HTTPS/API port.
  try {
    const raw = await env.SPR_COMMANDS.get("heartbeat");
    if (raw) {
      const hb = JSON.parse(raw);
      const seen = Number(hb.last_seen || 0);
      if (seen > 0 && (checked - seen) <= Number(env.MAX_AGE_SECONDS || 7200)) {
        upstream = hb;
        source = "cloudflare";
      }
    }
  } catch {}

  // Backward-compatible fallback while an older updater is still running.
  if (!upstream) {
    try {
      const response = await fetch(env.UPDATER_STATUS_URL, {
        headers: { "cache-control": "no-cache" },
        cf: { cacheTtl: 0, cacheEverything: false },
      });
      if (response.ok) {
        upstream = await response.json();
        source = "cpanel-fallback";
      } else {
        message = "Updater status returned HTTP " + response.status;
      }
    } catch {
      message = "Updater status check failed";
    }
  }

  const lastSeen = Number(upstream?.last_seen || 0);
  const online = Boolean(upstream?.worker_online) && lastSeen > 0 &&
    (checked - lastSeen) <= Number(env.MAX_AGE_SECONDS || 7200);
  if (online) message = upstream?.message || "Online updater ready";
  else if (upstream) message = "Online updater heartbeat is stale";

  let pending = null;
  try {
    const raw = await env.SPR_COMMANDS.get("pending");
    pending = raw ? JSON.parse(raw) : null;
  } catch {}

  let lastSprUpdated = 0, lastRostersUpdated = 0;
  try {
    lastSprUpdated = Number(await env.SPR_COMMANDS.get("last_success:spr") || 0);
    lastRostersUpdated = Number(await env.SPR_COMMANDS.get("last_success:rosters") || 0);
  } catch {}

  return {
    ok: online,
    worker_online: online,
    last_seen: lastSeen,
    checked_at: checked,
    state: online ? (upstream?.state || "idle") : "offline",
    message,
    last_update: upstream?.last_update || 0,
    sprs_last_updated: lastSprUpdated,
    rosters_last_updated: lastRostersUpdated,
    last_ok: upstream?.last_ok ?? null,
    last_message: upstream?.last_message || "",
    build: upstream?.build || 613,
    status_source: source,
    command_pending: Boolean(pending),
    command_type: pending?.command || "",
    command_state: pending ? ((pending.claimed_at || upstream?.state === "updating") ? "running" : "queued") : "",
    command_progress: pending?.progress || upstream?.progress || "",
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

async function cancelCommand(request, env) {
  if (!authorized(request, env)) return json({ok:false,error:"unauthorized"},401);
  const raw = await env.SPR_COMMANDS.get("pending");
  if (!raw) return json({ok:true,cancelled:false});
  const pending = JSON.parse(raw);
  pending.cancelled_at = Math.floor(Date.now()/1000);
  await env.SPR_COMMANDS.put("pending", JSON.stringify(pending), { expirationTtl: 300 });
  return json({ok:true,cancelled:true,id:pending.id});
}

async function cancelStatus(request, env) {
  if (!authorized(request, env)) return json({ok:false,error:"unauthorized"},401);
  const url=new URL(request.url);
  const id=String(url.searchParams.get("id")||"");
  const raw=await env.SPR_COMMANDS.get("pending");
  if (!raw) return json({ok:true,cancelled:false});
  const pending=JSON.parse(raw);
  return json({ok:true,cancelled:Boolean(pending.cancelled_at && (!id || pending.id===id))});
}

async function pollCommand(request, env) {
  if (!authorized(request, env)) return json({ok:false,error:"unauthorized"},401);
  const raw = await env.SPR_COMMANDS.get("pending");
  if (!raw) return json({ok:true, command:null});
  const item = JSON.parse(raw);
  if (!item.claimed_at) {
    item.claimed_at = Math.floor(Date.now()/1000);
    await env.SPR_COMMANDS.put("pending", JSON.stringify(item), { expirationTtl: 3600 });
  }
  return json({ok:true, command:item});
}

async function commandResult(request, env) {
  if (!authorized(request, env)) return json({ok:false,error:"unauthorized"},401);
  const url = new URL(request.url);
  const id = String(url.searchParams.get("id") || "");
  if (!id) return json({ok:false,error:"missing_id"},400);
  const pendingRaw = await env.SPR_COMMANDS.get("pending");
  if (pendingRaw) {
    const pending = JSON.parse(pendingRaw);
    if (pending.id === id) {
      let running = Boolean(pending.claimed_at);
      if (!running) {
        try {
          const heartbeat = await fetch(env.UPDATER_STATUS_URL, {
            headers: { "cache-control": "no-cache" },
            cf: { cacheTtl: 0, cacheEverything: false },
          });
          if (heartbeat.ok) {
            const upstream = await heartbeat.json();
            running = upstream?.state === "updating";
          }
        } catch {}
      }
      return json({
        ok:true,
        state: running ? "running" : "queued",
        command: pending.command,
        created_at: pending.created_at || 0,
        claimed_at: pending.claimed_at || 0,
        progress: pending.progress || "",
        progress_at: pending.progress_at || 0,
      });
    }
  }
  const resultRaw = await env.SPR_COMMANDS.get("result:" + id);
  if (resultRaw) return json({ok:true,state:"done",result:JSON.parse(resultRaw)});
  return json({ok:true,state:"unknown"});
}

async function heartbeatWorker(request, env) {
  if (!authorized(request, env)) return json({ok:false,error:"unauthorized"},401);
  let body;
  try { body = await request.json(); } catch { return json({ok:false,error:"invalid_json"},400); }
  const now = Math.floor(Date.now()/1000);
  const payload = {
    ok: true,
    source: "railway-cloudflare",
    build: Number(body?.build || 619),
    worker_online: true,
    state: String(body?.state || "idle").slice(0,40),
    message: String(body?.message || "Online updater ready").slice(0,800),
    progress: String(body?.progress || "").slice(0,500),
    last_seen: now,
    started_at: Number(body?.started_at || 0),
    last_update: Number(body?.last_update || 0),
    last_ok: body?.last_ok ?? null,
    last_message: String(body?.last_message || "").slice(0,1400),
  };
  await env.SPR_COMMANDS.put("heartbeat", JSON.stringify(payload), { expirationTtl: 10800 });
  return json({ok:true,last_seen:now});
}

async function progressCommand(request, env) {
  if (!authorized(request, env)) return json({ok:false,error:"unauthorized"},401);
  let body;
  try { body = await request.json(); } catch { return json({ok:false,error:"invalid_json"},400); }
  const id = String(body?.id || "");
  const progress = String(body?.progress || "").slice(0, 500);
  if (!id || !progress) return json({ok:false,error:"invalid_progress"},400);
  const raw = await env.SPR_COMMANDS.get("pending");
  if (!raw) return json({ok:false,error:"not_pending"},404);
  const pending = JSON.parse(raw);
  if (pending.id !== id) return json({ok:false,error:"wrong_command"},409);
  pending.progress = progress;
  pending.progress_at = Math.floor(Date.now()/1000);
  if (!pending.claimed_at) pending.claimed_at = pending.progress_at;
  await env.SPR_COMMANDS.put("pending", JSON.stringify(pending), { expirationTtl: 3600 });
  return json({ok:true});
}

async function ackCommand(request, env) {
  if (!authorized(request, env)) return json({ok:false,error:"unauthorized"},401);
  let body;
  try { body = await request.json(); } catch { return json({ok:false,error:"invalid_json"},400); }
  const raw = await env.SPR_COMMANDS.get("pending");
  let completedCommand = "";
  if (raw) {
    const pending = JSON.parse(raw);
    if (!body?.id || body.id === pending.id) {
      completedCommand = String(pending.command || "");
      await env.SPR_COMMANDS.delete("pending");
    }
  }
  const completedAt = Math.floor(Date.now()/1000);
  if (Boolean(body?.ok) && ["spr","rosters"].includes(completedCommand)) {
    await env.SPR_COMMANDS.put("last_success:" + completedCommand, String(completedAt));
  }
  if (body?.id) {
    await env.SPR_COMMANDS.put("result:" + body.id, JSON.stringify({
      id: body.id,
      ok: Boolean(body.ok),
      message: String(body.message || ""),
      completed_at: completedAt,
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
    if (request.method === "POST" && url.pathname === "/cancel") return cancelCommand(request, env);
    if (request.method === "GET" && url.pathname === "/worker/cancel") return cancelStatus(request, env);
    if (request.method === "GET" && url.pathname === "/worker/poll") return pollCommand(request, env);
    if (request.method === "GET" && url.pathname === "/worker/result") return commandResult(request, env);
    if (request.method === "POST" && url.pathname === "/worker/heartbeat") return heartbeatWorker(request, env);
    if (request.method === "POST" && url.pathname === "/worker/progress") return progressCommand(request, env);
    if (request.method === "POST" && url.pathname === "/worker/ack") return ackCommand(request, env);
    return new Response("Not found", { status: 404 });
  },
  async scheduled(controller, env, ctx) { ctx.waitUntil(status(env)); },
};
