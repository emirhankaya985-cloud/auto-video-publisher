import test from "node:test";
import assert from "node:assert/strict";
import worker, { batchApi, runFallback, scheduleIsExpected, isFallbackCheckWindow } from "../cloudflare-scheduler/index.mjs";

const env = {
  GITHUB_OWNER: "example-owner",
  GITHUB_REPOSITORY: "example-repo",
  GITHUB_TOKEN: "test-secret",
  MAIN_WORKFLOW_ID: "10",
  BACKUP_WORKFLOW_ID: "20",
  MAIN_WORKFLOW_FILE: "omnichannel_schedule.yml",
  STALE_AFTER_MINUTES: "12",
  FALLBACK_MODE: "enabled",
};

function mockGitHub({ scheduled = [], dispatched = [], queued = [], running = [], dispatchStatus = 204 } = {}) {
  const requests = [];
  const fetchImpl = async (input, init = {}) => {
    const url = new URL(input);
    requests.push({ url, init });
    if (init.method === "POST") return new Response(null, { status: dispatchStatus });

    let workflow_runs = [];
    if (url.searchParams.get("event") === "schedule") workflow_runs = scheduled;
    if (url.searchParams.get("event") === "workflow_dispatch") workflow_runs = dispatched;
    if (url.searchParams.get("status") === "queued") workflow_runs = queued;
    if (url.searchParams.get("status") === "in_progress") workflow_runs = running;
    return Response.json({ workflow_runs });
  };
  return { fetchImpl, requests };
}

const run = (workflow_id, event, status, created_at, head_branch = "main") => ({
  workflow_id,
  event,
  status,
  created_at,
  head_branch,
});

test("matches only the UTC hours configured by the GitHub cron", () => {
  assert.equal(scheduleIsExpected(new Date("2026-10-14T05:00:00Z")), true);
  assert.equal(scheduleIsExpected(new Date("2026-10-14T23:00:00Z")), true);
  assert.equal(scheduleIsExpected(new Date("2026-10-14T04:55:00Z")), false);
  assert.equal(scheduleIsExpected(new Date("2026-10-14T20:00:00Z")), true);
});

test("checks GitHub only shortly after an actual publication slot becomes stale", () => {
  assert.equal(isFallbackCheckWindow(new Date("2026-10-14T06:15:00Z"), 12), true);
  assert.equal(isFallbackCheckWindow(new Date("2026-10-14T06:45:00Z"), 12), true);
  assert.equal(isFallbackCheckWindow(new Date("2026-10-14T06:25:00Z"), 12), false);
});

test("does not call GitHub between publication slot windows", async () => {
  const { fetchImpl, requests } = mockGitHub();
  const result = await runFallback(Date.parse("2026-10-14T06:25:00Z"), env, fetchImpl, { info() {} });
  assert.equal(result.action, "outside-slot-window");
  assert.equal(requests.length, 0);
});

test("does not call GitHub during an hour where its schedule is inactive", async () => {
  const { fetchImpl, requests } = mockGitHub();
  const logs = [];
  const result = await runFallback(Date.parse("2026-10-14T04:00:00Z"), env, fetchImpl, {
    info: (message) => logs.push(message),
  });
  assert.equal(result.action, "outside-schedule");
  assert.equal(requests.length, 0);
  assert.equal(logs.length, 1);
});

test("disabled bootstrap performs no GitHub API calls", async () => {
  const { fetchImpl, requests } = mockGitHub();
  const result = await runFallback(
    Date.parse("2026-10-14T05:00:00Z"),
    { ...env, FALLBACK_MODE: "disabled" },
    fetchImpl,
    { info() {} },
  );
  assert.equal(result.action, "disabled");
  assert.equal(requests.length, 0);
});

test("does not dispatch if either GitHub schedule recently triggered", async () => {
  const { fetchImpl, requests } = mockGitHub({
    scheduled: [run(20, "schedule", "completed", "2026-10-14T05:08:00Z")],
  });
  const result = await runFallback(Date.parse("2026-10-14T05:15:00Z"), env, fetchImpl, {
    info() {},
  });
  assert.equal(result.action, "recent-trigger");
  assert.equal(requests.some(({ init }) => init.method === "POST"), false);
});

test("does not dispatch while either workflow is queued or running", async () => {
  for (const activeState of ["queued", "in_progress"]) {
    const { fetchImpl, requests } = mockGitHub({
      scheduled: [run(10, "schedule", "completed", "2026-10-14T05:00:00Z")],
      [activeState === "queued" ? "queued" : "running"]: [
        run(20, "schedule", activeState, "2026-10-14T05:00:00Z"),
      ],
    });
    const result = await runFallback(Date.parse("2026-10-14T05:20:00Z"), env, fetchImpl, {
      info() {},
    });
    assert.equal(result.action, "active-run");
    assert.equal(requests.some(({ init }) => init.method === "POST"), false);
  }
});

test("recent workflow_dispatch also acts as a heartbeat", async () => {
  const { fetchImpl, requests } = mockGitHub({
    scheduled: [run(10, "schedule", "completed", "2026-10-14T05:00:00Z")],
    dispatched: [run(10, "workflow_dispatch", "completed", "2026-10-14T05:10:00Z")],
  });
  const result = await runFallback(Date.parse("2026-10-14T05:15:00Z"), env, fetchImpl, {
    info() {},
  });
  assert.equal(result.action, "recent-trigger");
  assert.equal(requests.some(({ init }) => init.method === "POST"), false);
});

test("dispatches only the existing main publisher after a stale interval", async () => {
  const { fetchImpl, requests } = mockGitHub({
    scheduled: [run(10, "schedule", "completed", "2026-10-14T05:00:00Z")],
  });
  const logs = [];
  const result = await runFallback(Date.parse("2026-10-14T05:20:00Z"), env, fetchImpl, {
    info: (message) => logs.push(message),
  });
  const dispatch = requests.find(({ init }) => init.method === "POST");
  assert.equal(result.action, "dispatched");
  assert.ok(dispatch);
  assert.match(dispatch.url.pathname, /\/actions\/workflows\/omnichannel_schedule\.yml\/dispatches$/);
  assert.deepEqual(JSON.parse(dispatch.init.body), { ref: "main" });
  assert.equal(dispatch.init.headers.Authorization, "Bearer test-secret");
  assert.equal(logs.some((message) => message.includes("test-secret")), false);
});

test("dry-run performs stale checks but never dispatches", async () => {
  const { fetchImpl, requests } = mockGitHub({
    scheduled: [run(10, "schedule", "completed", "2026-10-14T05:00:00Z")],
  });
  const result = await runFallback(
    Date.parse("2026-10-14T05:20:00Z"),
    { ...env, FALLBACK_MODE: "dry-run" },
    fetchImpl,
    { info() {} },
  );
  assert.equal(result.action, "would-dispatch");
  assert.equal(requests.filter(({ init }) => init.method === "POST").length, 0);
});

test("does not include response bodies or credentials in API failure messages", async () => {
  const fetchImpl = async () => new Response("sensitive internal response", { status: 403 });
  await assert.rejects(
    runFallback(Date.parse("2026-10-14T05:20:00Z"), env, fetchImpl, { info() {} }),
    /HTTP 403/,
  );
});

test("Cloudflare scheduled handler runs the same fallback decision function", async () => {
  let promise;
  worker.scheduled(
    { scheduledTime: Date.parse("2026-10-14T04:00:00Z") },
    env,
    { waitUntil(task) { promise = task; } },
  );
  assert.deepEqual(await promise, { action: "outside-schedule" });
});

function batchEnv(runFactory, allFactory = async () => ({ results: [] })) {
  return {
    BATCH_API_TOKEN: "batch-secret",
    BATCH_DB: {
      prepare(sql) {
        return {
          bind(...args) {
            return { run: () => runFactory(sql, args), all: () => allFactory(sql, args) };
          },
        };
      },
    },
  };
}

const batchRequest = (body, token = "batch-secret") => new Request("https://worker.example", {
  method: "POST",
  headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

test("batch claim is bound to exact Drive file and folder", async () => {
  const envWithDb = batchEnv(async (sql, args) => ({
    meta: { changes: sql.includes("drive_file_id") && args[5] === "file-1" && args[6] === "folder-1" ? 1 : 0 },
  }));
  const good = await batchApi(batchRequest({ op:"claim", batch_id:"b", account:"a", platform:"facebook", drive_file_id:"file-1", drive_folder_id:"folder-1" }), envWithDb);
  assert.equal((await good.json()).claimed, true);
  const wrong = await batchApi(batchRequest({ op:"claim", batch_id:"b", account:"a", platform:"facebook", drive_file_id:"wrong", drive_folder_id:"folder-1" }), envWithDb);
  assert.equal((await wrong.json()).claimed, false);
});

test("batch finish requires the matching claim token and valid terminal state", async () => {
  const envWithDb = batchEnv(async (_sql, args) => ({ meta: { changes: args.at(-1) === "claim-ok" ? 1 : 0 } }));
  const good = await batchApi(batchRequest({ op:"finish", batch_id:"b", account:"a", platform:"facebook", claim_token:"claim-ok", status:"unknown" }), envWithDb);
  assert.equal((await good.json()).updated, true);
  const wrong = await batchApi(batchRequest({ op:"finish", batch_id:"b", account:"a", platform:"facebook", claim_token:"wrong", status:"confirmed" }), envWithDb);
  assert.equal((await wrong.json()).updated, false);
  const invalid = await batchApi(batchRequest({ op:"finish", batch_id:"b", account:"a", platform:"facebook", claim_token:"claim-ok", status:"pending" }), envWithDb);
  assert.equal(invalid.status, 400);
});

test("batch status response never selects claim tokens", async () => {
  let sqlText = "";
  const envWithDb = batchEnv(async () => ({ meta:{changes:0} }), async (sql) => { sqlText = sql; return { results:[] }; });
  const response = await batchApi(new Request("https://worker.example?batch_id=b", { headers:{Authorization:"Bearer batch-secret"} }), envWithDb);
  assert.equal(response.status, 200);
  assert.equal(sqlText.includes("claim_token"), false);
});
