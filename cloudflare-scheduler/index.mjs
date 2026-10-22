const API_VERSION = "2026-03-10";
const ACTIVE_UTC_HOURS = new Set([
  ...Array.from({ length: 14 }, (_, index) => index + 5),
  1,
  2,
  3,
  19,
  20,
  21,
  22,
  23,
]);
const ACTIVE_RUN_STATES = new Set(["queued", "in_progress", "waiting", "pending"]);

function required(env, name) {
  const value = env[name];
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`Missing required Worker setting: ${name}`);
  }
  return value.trim();
}

function authorized(request, env) {
  const value = request.headers.get("Authorization") || "";
  return value === `Bearer ${required(env, "BATCH_API_TOKEN")}`;
}

export async function batchApi(request, env) {
  if (!authorized(request, env)) return new Response("unauthorized", { status: 401 });
  if (!env.BATCH_DB) return new Response("batch database unavailable", { status: 503 });
  const body = request.method === "GET" ? null : await request.json();
  const now = new Date().toISOString();
  if (request.method === "POST" && body?.op === "create") {
    await env.BATCH_DB.prepare("INSERT INTO batches(batch_id,created_at,expires_at) VALUES(?,?,?)").bind(body.batch_id, now, body.expires_at).run();
    for (const t of body.targets || []) await env.BATCH_DB.prepare("INSERT INTO targets(batch_id,account,platform,drive_file_id,drive_folder_id,status,updated_at,action_run_id) VALUES(?,?,?,?,?,'pending',?,?)").bind(body.batch_id,t.account,t.platform,t.drive_file_id,t.drive_folder_id,now,body.action_run_id || null).run();
    return Response.json({ ok: true, batch_id: body.batch_id });
  }
  if (request.method === "POST" && body?.op === "claim") {
    const token = crypto.randomUUID();
    const result = await env.BATCH_DB.prepare("UPDATE targets SET status='claimed',claim_token=?,updated_at=? WHERE batch_id=? AND account=? AND platform=? AND drive_file_id=? AND drive_folder_id=? AND status='pending' AND EXISTS(SELECT 1 FROM batches WHERE batch_id=? AND closed_at IS NULL AND expires_at>?)").bind(token,now,body.batch_id,body.account,body.platform,body.drive_file_id,body.drive_folder_id,body.batch_id,now).run();
    return Response.json({ claimed: result.meta.changes === 1, claim_token: result.meta.changes === 1 ? token : null });
  }
  if (request.method === "POST" && body?.op === "finish") {
    if (!["submitted", "confirmed", "failed", "unknown"].includes(body.status)) return new Response("invalid status", { status: 400 });
    const result = await env.BATCH_DB.prepare("UPDATE targets SET status=?,remote_id=?,remote_url=?,error=?,updated_at=? WHERE batch_id=? AND account=? AND platform=? AND status='claimed' AND claim_token=?").bind(body.status,body.remote_id || null,body.remote_url || null,body.error || null,now,body.batch_id,body.account,body.platform,body.claim_token).run();
    return Response.json({ updated: result.meta.changes === 1 });
  }
  const batch = new URL(request.url).searchParams.get("batch_id");
  if (request.method === "GET" && batch) return Response.json(await env.BATCH_DB.prepare("SELECT batch_id,account,platform,drive_file_id,drive_folder_id,status,remote_id,remote_url,error,action_run_id,updated_at FROM targets WHERE batch_id=? ORDER BY account,platform").bind(batch).all());
  return new Response("bad request", { status: 400 });
}

function repositoryPath(env, suffix) {
  const owner = encodeURIComponent(required(env, "GITHUB_OWNER"));
  const repository = encodeURIComponent(required(env, "GITHUB_REPOSITORY"));
  return `https://api.github.com/repos/${owner}/${repository}${suffix}`;
}

async function githubRequest(url, env, fetchImpl, options = {}) {
  const token = required(env, "GITHUB_TOKEN");
  const response = await fetchImpl(url, {
    ...options,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "X-GitHub-Api-Version": API_VERSION,
      "User-Agent": "auto-video-publisher-cloudflare-fallback",
      ...options.headers,
    },
  });

  if (!response.ok) {
    // Never log response bodies or request headers: they can contain sensitive data.
    if (response.body) await response.body.cancel();
    throw new Error(`GitHub API request failed with HTTP ${response.status}`);
  }
  return response;
}

async function listRuns(env, fetchImpl, query) {
  const response = await githubRequest(
    repositoryPath(env, `/actions/runs?${query}`),
    env,
    fetchImpl,
  );
  const result = await response.json();
  if (!Array.isArray(result.workflow_runs)) {
    throw new Error("GitHub API returned an invalid workflow-runs response");
  }
  return result.workflow_runs;
}

function isTargetRun(run, workflowIds) {
  return workflowIds.has(Number(run.workflow_id)) && run.head_branch === "main";
}

function latestTimestamp(runs) {
  return runs.reduce((latest, run) => {
    const timestamp = Date.parse(run.created_at);
    return Number.isFinite(timestamp) ? Math.max(latest, timestamp) : latest;
  }, 0);
}

export function scheduleIsExpected(date) {
  return ACTIVE_UTC_HOURS.has(date.getUTCHours());
}

const UTC_SLOT_MINUTES = new Map([
  [1, [0, 30]], [2, [0]], [3, [30]], [5, [0]], [6, [0, 30]], [7, [0]],
  [8, [0, 30]], [9, [0]], [10, [0, 30]], [11, [0]],
  [12, [0, 30]], [13, [0]], [14, [0, 30]], [15, [0, 30]],
  [16, [0, 30]], [17, [0, 30]], [18, [0, 30]], [19, [0, 30]], [20, [0]],
  [21, [30]], [22, [0]], [23, [0, 30]],
]);

export function isFallbackCheckWindow(date, staleAfterMinutes) {
  const slots = UTC_SLOT_MINUTES.get(date.getUTCHours()) || [];
  return slots.some((minute) => {
    const age = date.getUTCMinutes() - minute;
    return age >= staleAfterMinutes && age < staleAfterMinutes + 10;
  });
}

export async function runFallback(
  scheduledTime,
  env,
  fetchImpl = fetch,
  logger = console,
) {
  const now = new Date(scheduledTime);
  if (!Number.isFinite(now.getTime())) throw new Error("Invalid Cloudflare cron timestamp");
  const mode = env.FALLBACK_MODE || "disabled";
  if (!["disabled", "dry-run", "enabled"].includes(mode)) {
    throw new Error("FALLBACK_MODE must be disabled, dry-run, or enabled");
  }
  if (mode === "disabled") {
    logger.info("Cloudflare fallback is disabled; no GitHub check or dispatch.");
    return { action: "disabled" };
  }
  if (!scheduleIsExpected(now)) {
    logger.info("GitHub schedule is not configured for this UTC hour; no fallback dispatch.");
    return { action: "outside-schedule" };
  }

  const staleAfterMinutes = Number(env.STALE_AFTER_MINUTES || "12");
  if (!Number.isFinite(staleAfterMinutes) || staleAfterMinutes < 5 || staleAfterMinutes > 60) {
    throw new Error("STALE_AFTER_MINUTES must be between 5 and 60");
  }
  if (!isFallbackCheckWindow(now, staleAfterMinutes)) {
    logger.info("No publication slot is currently stale; no GitHub check or dispatch.");
    return { action: "outside-slot-window" };
  }

  const mainWorkflowId = Number(required(env, "MAIN_WORKFLOW_ID"));
  const backupWorkflowId = Number(required(env, "BACKUP_WORKFLOW_ID"));
  if (!Number.isInteger(mainWorkflowId) || !Number.isInteger(backupWorkflowId)) {
    throw new Error("Workflow IDs must be integers");
  }
  const workflowIds = new Set([mainWorkflowId, backupWorkflowId]);

  // Four read-only snapshots: last schedule/dispatch and any queued/running job.
  // The existing GitHub concurrency group and Drive slot state remain the final
  // duplicate-publication safeguards if a delayed GitHub cron races this check.
  const [scheduledRuns, dispatchedRuns, queuedRuns, runningRuns] = await Promise.all([
    listRuns(env, fetchImpl, "branch=main&event=schedule&per_page=100"),
    listRuns(env, fetchImpl, "branch=main&event=workflow_dispatch&per_page=100"),
    listRuns(env, fetchImpl, "branch=main&status=queued&per_page=100"),
    listRuns(env, fetchImpl, "branch=main&status=in_progress&per_page=100"),
  ]);

  const targetSchedules = scheduledRuns.filter((run) => isTargetRun(run, workflowIds));
  const targetDispatches = dispatchedRuns.filter((run) => isTargetRun(run, workflowIds));
  const mostRecentTrigger = Math.max(
    latestTimestamp(targetSchedules),
    latestTimestamp(targetDispatches),
  );
  const activeRun = [...queuedRuns, ...runningRuns].some(
    (run) => isTargetRun(run, workflowIds) && ACTIVE_RUN_STATES.has(run.status),
  );

  if (activeRun) {
    logger.info("A GitHub publishing workflow is already queued or running; no fallback dispatch.");
    return { action: "active-run" };
  }

  const ageMinutes = mostRecentTrigger
    ? (now.getTime() - mostRecentTrigger) / 60_000
    : Number.POSITIVE_INFINITY;
  if (ageMinutes < staleAfterMinutes) {
    logger.info("A recent GitHub schedule/dispatch was found; no fallback dispatch.");
    return { action: "recent-trigger" };
  }

  if (mode === "dry-run") {
    logger.info("GitHub schedule is stale; dry-run only, no workflow dispatch.");
    return { action: "would-dispatch" };
  }

  const workflowFile = encodeURIComponent(required(env, "MAIN_WORKFLOW_FILE"));
  const dispatchUrl = repositoryPath(
    env,
    `/actions/workflows/${workflowFile}/dispatches`,
  );
  await githubRequest(dispatchUrl, env, fetchImpl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ref: "main" }),
  });
  logger.info("No recent GitHub trigger found; dispatched the existing publisher workflow.");
  return { action: "dispatched" };
}

export default {
  async fetch(request, env) { return batchApi(request, env); },
  async scheduled(controller, env, ctx) {
    const task = runFallback(controller.scheduledTime, env);
    ctx.waitUntil(task);
  },
};
