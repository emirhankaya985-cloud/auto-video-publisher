"""Official Meta API engagement; independent from video publication.

Facebook/Instagram likes and Facebook link shares only. Unsupported save and
native Instagram repost requests are reported, never simulated as successes.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import time
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from meta_auth_loader import ALLOWED_NAMES, KNOWN_IDS, load_meta_auth
from publisher_recovery import read_with_retry
from publication_safety import route_paused

REPO = "emirhankaya985-cloud/auto-video-publisher"
VERSION = "v24.0"
GRAPH = f"https://graph.facebook.com/{VERSION}"
SOURCE_WORKFLOW = ".github/workflows/public_link_schedule.yml"
WORKFLOW = ".github/workflows/meta_cross_engagement.yml"
ROOT = Path("cross-engagement")
STATE = ROOT / "engagement.json"
PLAN = ROOT / "plan.json"
REPORT = ROOT / "report.json"
ROUTE_NAMES = {
    "tarladaki": "Tarladaki Fasulye", "penguen": "Beyinsiz Penguen",
    "gonle": "Gönle Düşen", "daily_laugh": "Daily Laugh Lab",
    "film": "Film Mağarası", "film_second": "Filmmagrasi", "toonzone": "ToonZone",
}
OPERATIONS = ("like", "save", "repost")


def repost_enabled():
    """Explicit opt-in only: owner has disabled all Facebook repost writes."""
    return os.getenv("META_CROSS_REPOST_ENABLED") == "true"

SUPPORTED = {("facebook", "like"), ("instagram", "like"), ("facebook", "repost")}
ID = re.compile(r"[0-9]+(?:_[0-9]+)?\Z")


def stamp(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError()
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError, TypeError):
        raise ValueError("invalid timestamp") from None


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


class GraphFailure(RuntimeError):
    def __init__(self, http=None, code=None, *, definite=False):
        self.http, self.code, self.definite = http, code, definite
        super().__init__("Meta request rejected" if definite else "Meta result uncertain")


def graph(method, node, token, data=None, *, get=None, post=None):
    """Fixed host, bounded reads, exactly one write attempt, no provider text."""
    if not token or not re.fullmatch(r"[A-Za-z0-9_]+(?:/[A-Za-z_]+)?", node):
        raise ValueError("invalid graph request")
    try:
        headers = {"Authorization": f"Bearer {token}"}
        if method == "GET":
            response = read_with_retry(
                get or requests.get, f"{GRAPH}/{node}", params=data or {}, headers=headers,
                timeout=20, allow_redirects=False, graph_read=True,
            )
        elif method == "POST":
            response = (post or requests.post)(
                f"{GRAPH}/{node}", data=data or {}, headers=headers,
                timeout=30, allow_redirects=False,
            )
        else:
            raise ValueError("unsupported HTTP method")
        try:
            body = response.json()
        except ValueError:
            body = None
        status = response.status_code
        response.close()
    except (requests.RequestException, OSError):
        raise GraphFailure() from None
    error = body.get("error") if isinstance(body, dict) else None
    if not 200 <= status < 300 or not isinstance(body, dict) or error:
        code = error.get("code") if isinstance(error, dict) else None
        raise GraphFailure(status, code if type(code) is int else None,
                           definite=400 <= status < 500 and status != 408
                           and isinstance(error, dict))
    return body


def rows(node, token, fields=None):
    params = {"limit": 100}
    if fields:
        params["fields"] = fields
    output, cursors = [], set()
    for _ in range(30):
        body = graph("GET", node, token, params)
        if not isinstance(body.get("data"), list):
            raise ValueError("invalid Meta list")
        output.extend(body["data"])
        paging = body.get("paging") or {}
        if not isinstance(paging, dict):
            raise ValueError("invalid pagination")
        if not paging.get("next"):
            return output
        cursor = (paging.get("cursors") or {}).get("after")
        if not isinstance(cursor, str) or not cursor or cursor in cursors:
            raise ValueError("invalid pagination")
        cursors.add(cursor)
        params["after"] = cursor
    raise ValueError("pagination limit")


def account_enabled(name, platform):
    route = next((r for r, n in ROUTE_NAMES.items() if n == name), None)
    if route is None:
        return False
    route = "film" if route == "film_second" else route
    if platform == "instagram" and route in {"gonle", "daily_laugh"}:
        route = "gonle_ig" if route == "gonle" else "daily_laugh_instagram"
    return not route_paused(route)


def accounts(auth, default_user_token):
    """Confirm each Page identity and each User token's managed IG accounts.

    User tokens are required for IG likes; never substitute a Page token.
    Secrets exist only in this process, never in the plan or ledger.
    """
    pages = auth.get("pages") if isinstance(auth, dict) else None
    if not isinstance(pages, list):
        raise ValueError("invalid Meta account config")
    result, seen, grants_cache = {}, set(), {}
    for page in pages:
        name = str(page.get("page_name", ""))
        pid = str(page.get("page_id", ""))
        if name.casefold() not in ALLOWED_NAMES or not pid.isdecimal() or pid in seen:
            raise ValueError("invalid or duplicate Page identity")
        if ((pid in KNOWN_IDS and KNOWN_IDS[pid] != name)
                or (name in KNOWN_IDS.values() and KNOWN_IDS.get(pid) != name)):
            raise ValueError("pinned Page identity mismatch")
        seen.add(pid)
        try:
            token = page.get("page_token", "")
            identity = graph("GET", "me", token, {"fields": "id"})
            if str(identity.get("id")) != pid:
                raise ValueError("Page token identity mismatch")
            user_token = page.get("user_token") or default_user_token
            if user_token not in grants_cache:
                permissions = rows("me/permissions", user_token)
                grants = {x["permission"] for x in permissions
                          if isinstance(x, dict) and x.get("status") == "granted"
                          and isinstance(x.get("permission"), str)}
                managed = rows("me/accounts", user_token, "id,instagram_business_account{id}")
                mapping = {str(x["id"]): str((x.get("instagram_business_account") or {}).get("id", ""))
                           for x in managed if isinstance(x, dict) and x.get("id")}
                grants_cache[user_token] = (grants, mapping)
            grants, mapping = grants_cache[user_token]
            if pid not in mapping:
                raise ValueError("Page not managed by authorized User")
            ig = str(page.get("instagram_id") or "")
            if ig and (not ig.isdecimal() or mapping[pid] != ig):
                raise ValueError("Instagram identity mismatch")
            if account_enabled(name, "facebook"):
                result[("facebook", pid)] = dict(platform="facebook", id=pid, name=name,
                    token=token, grants=grants, owner_page=pid)
            if ig and account_enabled(name, "instagram"):
                if ("instagram", ig) in result:
                    raise ValueError("duplicate Instagram identity")
                result[("instagram", ig)] = dict(platform="instagram", id=ig, name=name,
                    token=user_token, grants=grants, owner_page=pid)
        except (GraphFailure, ValueError):
            # A rejected account cannot supply actors OR source posts.
            continue
    return result


def source_posts(state, source_run_id, actors):
    if not isinstance(state, dict) or not isinstance(state.get("entries"), dict):
        raise ValueError("invalid publisher state")
    output, seen = [], set()
    by_name = {(a["platform"], a["name"]): a for a in actors.values()}
    for row in state["entries"].values():
        if not isinstance(row, dict):
            raise ValueError("invalid publisher row")
        platform, route = row.get("platform"), row.get("route")
        post_id = str(row.get("post_id") or "")
        source = by_name.get((platform, ROUTE_NAMES.get(route)))
        if (row.get("status") != "done" or str(row.get("run_id")) != source_run_id
                or not source or not ID.fullmatch(post_id)
                or row.get("duplicate_of_file_id") or row.get("reconciled_in_run_id")
                or row.get("reconciliation_proof")):
            continue
        identity = (platform, post_id)
        if identity in seen:
            continue
        seen.add(identity)
        output.append(dict(platform=platform, post_id=post_id, owner=source["id"]))
    return output


def scope_audit_posts(posts, actors, focus):
    """Scope read-only source review without changing or forging engagement.

    Only native, verified recent publisher posts are eligible. This is not a
    historical backfill or a confirmation that any other account liked them.
    """
    if not focus:
        return posts, {"focus_account": "all", "focus_source_posts": len(posts),
                       "other_source_posts_excluded": 0, "candidate_review_accounts": []}
    if focus not in ROUTE_NAMES.values():
        raise ValueError("unrecognized focus account")
    owners = {(a["platform"], a["id"]) for a in actors.values() if a["name"] == focus}
    selected = [p for p in posts if (p["platform"], p["owner"]) in owners]
    platforms = {p["platform"] for p in selected}
    reviewers = sorted({a["name"] for a in actors.values()
                        if a["name"] != focus and a["platform"] in platforms
                        and permission(a["platform"], "like") <= a["grants"]})
    return selected, {"focus_account": focus, "focus_source_posts": len(selected),
                      "other_source_posts_excluded": len(posts) - len(selected),
                      "candidate_review_accounts": reviewers}


def key(task):
    raw = ":".join(task[k] for k in ("platform", "actor", "post_id", "operation"))
    return hashlib.sha256(raw.encode()).hexdigest()


def permission(platform, operation):
    if platform == "instagram":
        return {"instagram_basic", "instagram_manage_engagement"}
    return {"pages_manage_engagement"} if operation == "like" else {"pages_manage_posts"}


def provider_holds(ledger):
    """Persist Meta policy restrictions; never rotate actors to continue a lane.

    Migrate definitive 368 receipts from earlier runners before pruning their
    action records. A hold is not cleared by time, a fresh source or a new run.
    """
    holds = ledger.setdefault("provider_holds", {})
    if not isinstance(holds, dict):
        raise ValueError("invalid provider hold state")
    for record in ledger["actions"].values():
        lane = (record.get("platform"), record.get("operation"))
        if (record.get("status") == "rejected" and type(record.get("graph_code")) is int
                and record["graph_code"] == 368 and lane in SUPPORTED):
            holds.setdefault("/".join(lane), {"graph_code": 368, "reason": "meta_provider_restriction",
                                              "run_id": str(record.get("run_id", ""))})
    return holds


def build_plan(posts, actors, ledger, run_id, source_run_id, *, now):
    if ledger.get("schema") != 1 or not isinstance(ledger.get("actions"), dict):
        raise ValueError("invalid engagement ledger; reset forbidden")
    holds = provider_holds(ledger)
    # Old source runs cannot be replayed after 24h; retain intent/results 48h.
    ledger["actions"] = {k: v for k, v in ledger["actions"].items()
                         if stamp(v["at"]) >= now - timedelta(hours=48)}
    tasks, report = [], []
    for source in posts:
        for actor in actors.values():
            if actor["platform"] != source["platform"]:
                continue
            for operation in OPERATIONS:
                task = dict(source, actor=actor["id"], operation=operation,
                            source_run_id=source.get("source_run_id", source_run_id))
                action_key = key(task)
                prior = ledger["actions"].get(action_key, {})
                # Audited first batch made ZERO POSTs: only these exact local
                # preflight failures may use the corrected Video field set.
                repair_preflight = (task["platform"] == "facebook" and operation == "repost"
                    and prior.get("status") == "source_or_permission_unverified"
                    and prior.get("run_id") == "41044986946"
                    and "source_check_version" not in prior
                    and all(prior.get(k) == v for k, v in task.items()))
                if operation == "repost" and not repost_enabled():
                    report.append(dict(task, status="disabled_by_owner"))
                elif (task["platform"], operation) not in SUPPORTED:
                    report.append(dict(task, status="unsupported_by_verified_api"))
                elif operation == "repost" and task["owner"] == task["actor"]:
                    report.append(dict(task, status="self_share_not_applicable"))
                elif not permission(task["platform"], operation) <= actor["grants"]:
                    report.append(dict(task, status="missing_permission"))
                elif action_key in ledger["actions"] and not repair_preflight:
                    report.append(dict(task, status="already_recorded"))
                elif f"{task['platform']}/{operation}" in holds:
                    report.append(dict(task, status="provider_restriction_hold"))
                else:
                    # Reserve the ENTIRE batch in a GitHub artifact before POST.
                    ledger["actions"][action_key] = dict(task, status="reserved",
                        run_id=run_id, at=now.isoformat(), source_check_version=2)
                    tasks.append(task)
    return tasks, report


def verified_media(task, actors):
    source = actors[(task["platform"], task["owner"])]
    # The publisher records a Video ID, not a PagePost ID. permalink_url is
    # not a common Video field; do not fail the owner check by requesting it.
    fields = "id,from" if task["platform"] == "facebook" else "id,owner,permalink,media_type"
    body = graph("GET", task["post_id"], source["token"], {"fields": fields})
    owner = body.get("from" if task["platform"] == "facebook" else "owner")
    if str(body.get("id")) != task["post_id"]:
        raise ValueError("source_id_mismatch")
    if not isinstance(owner, dict):
        raise ValueError("source_owner_missing")
    if str(owner.get("id")) != task["owner"]:
        raise ValueError("source_owner_mismatch")
    if task["platform"] == "instagram" and body.get("media_type") not in {"IMAGE", "VIDEO", "CAROUSEL_ALBUM"}:
        raise ValueError("unsupported Instagram media")
    if task["platform"] == "facebook" and task["operation"] == "repost":
        if task["post_id"].isdigit():
            # Canonical Facebook Watch URL of the verified owned Video ID.
            # This is a link share, never a claim that Meta returned a permalink.
            return f"https://www.facebook.com/watch/?v={task['post_id']}"
        # Composite PagePost IDs, if ever present, have a separate field read.
        link = graph("GET", task["post_id"], source["token"], {"fields": "id,permalink_url"}).get("permalink_url")
        parsed = urlsplit(link) if isinstance(link, str) else None
        if (not parsed or parsed.scheme != "https" or parsed.hostname not in
                {"www.facebook.com", "facebook.com", "m.facebook.com"}
                or parsed.username or parsed.password or parsed.fragment):
            raise ValueError("unverified Facebook permalink")
        return link
    return None


def perform(task, actor, link):
    if task["operation"] == "like":
        node = f"{actor['id']}/likes" if task["platform"] == "instagram" else f"{task['post_id']}/likes"
        data = {"media_id": task["post_id"]} if task["platform"] == "instagram" else {}
        body = graph("POST", node, actor["token"], data)
        if body.get("success") is not True:
            raise GraphFailure()
        return {"api_ack": True}
    if task["operation"] == "repost" and not repost_enabled():
        raise ValueError("repost disabled by owner")
    if task["operation"] == "repost" and task["platform"] == "facebook":
        body = graph("POST", f"{actor['id']}/feed", actor["token"], {"link": link})
        if not ID.fullmatch(str(body.get("id", ""))):
            raise GraphFailure()
        return {"api_ack": True, "share_post_id": str(body["id"])}
    raise ValueError("unsupported operation")


def execute(tasks, actors, ledger, run_id, *, persist, sleep=time.sleep):
    stopped = set()
    source_checks = {}
    holds = provider_holds(ledger)
    for task in tasks:
        record = ledger["actions"].get(key(task))
        if (not record or record.get("status") != "reserved" or record.get("run_id") != run_id
                or any(record.get(k) != v for k, v in task.items())):
            continue
        if task["operation"] == "repost" and not repost_enabled():
            record["status"] = "disabled_by_owner"
            persist(ledger)
            continue
        actor_key = (task["platform"], task["actor"])
        lane = f"{task['platform']}/{task['operation']}"
        if lane in holds:
            record["status"] = "provider_restriction_hold"
            persist(ledger)
            continue
        actor = actors.get(actor_key)
        if not actor or actor_key in stopped or not account_enabled(actor["name"], task["platform"]):
            record["status"] = "blocked_actor"
            persist(ledger)
            continue
        try:
            if (task["platform"], task["operation"]) not in SUPPORTED:
                raise ValueError("unsupported operation")
            if not permission(task["platform"], task["operation"]) <= actor["grants"]:
                raise ValueError("missing permission")
            source_key = (task["platform"], task["post_id"], task["owner"], task["operation"])
            if source_key not in source_checks:
                try:
                    source_checks[source_key] = verified_media(task, actors)
                except (GraphFailure, ValueError, KeyError) as exc:
                    source_checks[source_key] = exc
            link = source_checks[source_key]
            if isinstance(link, Exception):
                raise link
        except (GraphFailure, ValueError, KeyError) as exc:
            record["status"] = "source_or_permission_unverified"
            record["preflight_error_type"] = type(exc).__name__
            if isinstance(exc, GraphFailure):
                record.update(http_status=exc.http, graph_code=exc.code)
            elif str(exc) in {"source_id_mismatch", "source_owner_missing", "source_owner_mismatch"}:
                record["preflight_reason"] = str(exc)
            persist(ledger)
            continue
        # Crash, malformed acknowledgement, transport/5xx: never repeat a POST.
        record["status"] = "uncertain"
        persist(ledger)
        sleep(1)  # No burst: below the documented IG 50 requests / 5 seconds.
        try:
            result = perform(task, actor, link)
            record.update(status="accepted", **result)
        except GraphFailure as exc:
            record.update(status="rejected" if exc.definite else "uncertain",
                          http_status=exc.http, graph_code=exc.code)
            if exc.http in {401, 403, 429} or exc.code in {4, 10, 17, 32, 190, 200, 613}:
                stopped.add(actor_key)
            if exc.code == 368:
                holds[lane] = {"graph_code": 368, "reason": "meta_provider_restriction", "run_id": run_id}
        persist(ledger)
    return ledger


def github(path):
    token = os.environ["GH_TOKEN"]
    try:
        r = read_with_retry(requests.get, f"https://api.github.com/repos/{REPO}/{path}",
                            headers={"Authorization": f"Bearer {token}"}, timeout=30,
                            allow_redirects=False)
        # Artifact downloads use a GitHub-signed redirect. Never forward the
        # credential to the storage host; requests strips cross-host auth.
        if r.status_code in {301, 302, 303, 307, 308} and path.endswith("/zip"):
            url = r.headers.get("Location", "")
            host = urlsplit(url).hostname or ""
            if urlsplit(url).scheme != "https" or not host.endswith((".blob.core.windows.net", ".actions.githubusercontent.com")):
                raise ValueError("untrusted artifact host")
            r.close()
            r = requests.get(url, timeout=30, allow_redirects=False)
        if r.status_code != 200:
            raise ValueError("GitHub read failed")
        return r
    except requests.RequestException:
        raise ValueError("GitHub read failed") from None


def archive(artifact_id, member):
    response = github(f"actions/artifacts/{int(artifact_id)}/zip")
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        if z.namelist() != [member] or z.getinfo(member).file_size > 8_000_000:
            raise ValueError("invalid state archive")
        return json.loads(z.read(member))


def source_run_valid(run, now):
    try:
        return (run.get("path") == SOURCE_WORKFLOW and run.get("head_branch") == "main"
            and run.get("head_repository", {}).get("full_name") == REPO
            and run.get("status") == "completed" and run.get("conclusion") in {"success", "failure"}
            and now - timedelta(hours=24) <= stamp(run.get("created_at")) <= now)
    except (ValueError, AttributeError):
        return False


def latest_source_id(*, now):
    body = github("actions/workflows/public_link_schedule.yml/runs?branch=main&per_page=30").json()
    if not isinstance(body.get("workflow_runs"), list):
        raise ValueError("invalid publisher run list")
    valid = [r for r in body["workflow_runs"] if source_run_valid(r, now)]
    if not valid:
        raise ValueError("no recent completed publisher run")
    newest = max(valid, key=lambda r: stamp(r["created_at"]))
    if not str(newest.get("id", "")).isdigit():
        raise ValueError("invalid source run ID")
    return str(newest["id"])


def recent_posts(state, anchor_id, actors, *, now):
    """One latest ledger supplies all original posts from verified recent runs.

    Validate the provenance run of every candidate, including partial publisher
    failures; never substitute a foreign run or an unverified historical alias.
    """
    if not isinstance(state, dict) or not isinstance(state.get("entries"), dict):
        raise ValueError("invalid publisher state")
    candidate_ids = set()
    for row in state["entries"].values():
        if not isinstance(row, dict):
            raise ValueError("invalid publisher row")
        day, rid = row.get("day", ""), str(row.get("run_id", ""))
        if (isinstance(day, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)
                and (now - timedelta(days=2)).date().isoformat() <= day <= now.date().isoformat()
                and row.get("status") == "done" and rid.isdigit()):
            candidate_ids.add(rid)
    if len(candidate_ids) > 128:
        raise ValueError("too many provenance runs; no partial batch")
    result = []
    for rid in sorted(candidate_ids, key=int):
        if rid != anchor_id and not source_run_valid(github(f"actions/runs/{rid}").json(), now):
            continue
        result.extend(dict(p, source_run_id=rid) for p in source_posts(state, rid, actors))
    return result


def read_source(source_run_id, *, now):
    run = github(f"actions/runs/{source_run_id}").json()
    if not source_run_valid(run, now):
        raise ValueError("invalid or stale source run")
    data = github(f"actions/runs/{source_run_id}/artifacts?per_page=100").json()
    artifacts = [a for a in data.get("artifacts", []) if a.get("name") == "link-state-result" and not a.get("expired")]
    if len(artifacts) != 1:
        raise ValueError("source result unavailable")
    return archive(artifacts[0]["id"], "state.json")


def restore():
    artifacts = []
    for name in ("cross-engagement-result", "cross-engagement-intent"):
        body = github(f"actions/artifacts?per_page=100&name={name}").json()
        if not isinstance(body.get("artifacts"), list):
            raise ValueError("invalid artifact list")
        artifacts.extend(body["artifacts"])
    if not artifacts:
        return {"schema": 1, "actions": {}}
    artifacts.sort(key=lambda a: (int(a["workflow_run"]["id"]), a["name"] == "cross-engagement-result"), reverse=True)
    newest = artifacts[0]
    run = github(f"actions/runs/{newest['workflow_run']['id']}").json()
    if (newest.get("expired") or run.get("path") != WORKFLOW or run.get("head_branch") != "main"
            or run.get("head_repository", {}).get("full_name") != REPO):
        raise ValueError("prior engagement state unverified; reset forbidden")
    return archive(newest["id"], "engagement.json")



def build_one_like(posts, actors, ledger, run_id, source_run_id, *, now):
    """One authorized, cross-account like only; no write before live preflight.

    This is a limited, owner-requested one-time API smoke trial, NOT a
    bulk-engagement runner. Do not reserve any save or repost intents.
    """
    if ledger.get("schema") != 1 or not isinstance(ledger.get("actions"), dict):
        raise ValueError("invalid engagement ledger; reset forbidden")
    holds = provider_holds(ledger)
    for platform in ("instagram", "facebook"):
        if f"{platform}/like" in holds:
            continue
        checked = 0
        for source in sorted((p for p in posts if p["platform"] == platform),
                             key=lambda p: p["post_id"]):
            for actor in sorted((a for a in actors.values()
                                 if a["platform"] == platform and a["id"] != source["owner"]
                                 and permission(platform, "like") <= a["grants"]),
                                key=lambda a: a["id"]):
                task = dict(source, actor=actor["id"], operation="like",
                            source_run_id=source.get("source_run_id", source_run_id))
                if key(task) in ledger["actions"]:
                    continue
                if checked >= 8:
                    break
                checked += 1
                try:
                    verified_media(task, actors)
                except (GraphFailure, ValueError, KeyError):
                    continue
                # Reuse the hardened ledger reservation, then keep only
                # the one verified like; no other operation can be reserved.
                selected = {("like", platform, actor["id"]): actor}
                # build_plan works from actor.values(); key shape is not used.
                tasks, report = build_plan([source], selected, ledger, run_id,
                                           source_run_id, now=now)
                if len(tasks) != 1 or tasks[0]["operation"] != "like":
                    raise ValueError("unexpected single-like reservation")
                return tasks, report
            if checked >= 8:
                break
    return [], [{"status": "no_eligible_verified_single_like"}]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("plan", "execute"))
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    run_id, source_id = os.environ["GITHUB_RUN_ID"], os.environ["SOURCE_RUN_ID"]
    if os.getenv("GITHUB_REPOSITORY") != REPO or not run_id.isdigit() or not (source_id.isdigit() or source_id == "latest"):
        raise ValueError("invalid workflow identity")
    mode = os.getenv("ENGAGEMENT_MODE")
    single_like = (mode == "single_like" and os.getenv("GITHUB_EVENT_NAME") == "push"
                   and os.getenv("GITHUB_REF") == "refs/heads/main")
    live = (os.getenv("META_CROSS_ENGAGEMENT_ENABLED") == "true"
            and (mode == "apply" or single_like))
    focus = os.getenv("META_AUDIT_FOCUS", "").strip()
    if focus and live:
        # A focus is exclusively for read-only coverage; never escalate to
        # coordinated cross-account likes via manual apply or old push modes.
        raise ValueError("focused account coverage is read-only")
    actors = accounts(load_meta_auth(), os.getenv("META_ACCESS_TOKEN", ""))
    if not actors:
        raise ValueError("no verified enabled accounts")
    if args.action == "plan":
        if source_id == "latest":
            source_id = latest_source_id(now=now)
        ledger = restore()
        state = read_source(source_id, now=now)
        posts = (recent_posts(state, source_id, actors, now=now)
                 if os.getenv("ENGAGEMENT_SCOPE") == "recent_window"
                 else source_posts(state, source_id, actors))
        posts, focus_info = scope_audit_posts(posts, actors, focus)
        tasks, report = (build_one_like(posts, actors, ledger, run_id, source_id, now=now)
                         if single_like else build_plan(posts, actors, ledger, run_id,
                                                        source_id, now=now))
        if single_like and live and (len(tasks) != 1 or tasks[0]["operation"] != "like"
                                     or tasks[0]["actor"] == tasks[0]["owner"]):
            raise ValueError("single-like plan not safe")
        blocked_counts = dict(Counter(f"{r['platform']}/{r['operation']}/{r['status']}" for r in report))
        save(PLAN, tasks)
        save(REPORT, {"mode": "apply" if live else "dry_run", "planned": len(tasks),
                      "source_run_id": source_id, "source_posts": len(posts),
                      "verified_accounts": len(actors), **focus_info,
                      "blocked": report, "blocked_counts": blocked_counts,
                      "provider_holds": ledger.get("provider_holds", {})})
        if live:
            save(STATE, ledger)
        print(json.dumps({"mode": "apply" if live else "dry_run", "planned": len(tasks),
                          "source_posts": len(posts), "verified_accounts": len(actors),
                          **focus_info,
                          "blocked": len(report), "blocked_counts": blocked_counts,
                          "provider_holds": ledger.get("provider_holds", {})}))
    elif live:
        ledger = json.loads(STATE.read_text())
        tasks = json.loads(PLAN.read_text())
        if single_like and (len(tasks) != 1 or tasks[0].get("operation") != "like"
                            or tasks[0].get("actor") == tasks[0].get("owner")):
            raise ValueError("single-like execution scope invalid")
        execute(tasks, actors, ledger, run_id, persist=lambda x: save(STATE, x))
        counts = {}
        for value in ledger["actions"].values():
            if value.get("run_id") == run_id:
                status = value["status"]
                counts[status] = counts.get(status, 0) + 1
        by_operation = dict(Counter(f"{v['platform']}/{v['operation']}/{v['status']}"
                                    for v in ledger["actions"].values() if v.get("run_id") == run_id))
        print(json.dumps({"results": counts, "by_operation": by_operation,
                          "provider_holds": ledger.get("provider_holds", {}), "publication_state_modified": False}))
        if (ledger.get("provider_holds") and not single_like) or any(counts.get(s) for s in ("source_or_permission_unverified", "uncertain", "rejected", "blocked_actor", "provider_restriction_hold")):
            raise SystemExit(1)
    else:
        print('{"mode":"dry_run","writes":0}')


# Only allow known, fixed diagnostic labels. Never print provider messages,
# exceptions or credential data in logs or artifacts.
_HOLD_REASON_CODES = {
    "no verified enabled accounts": "no_verified_enabled_accounts",
    "no recent completed publisher run": "no_recent_completed_publisher_run",
    "invalid publisher run list": "publisher_run_list_invalid",
    "invalid or stale source run": "source_run_not_verified",
    "source result unavailable": "source_result_artifact_missing",
    "invalid publisher state": "publisher_state_invalid",
    "invalid engagement ledger; reset forbidden": "engagement_ledger_invalid",
    "invalid artifact list": "artifact_inventory_invalid",
    "invalid workflow identity": "workflow_identity_invalid",
}


def safe_hold_reason(exc):
    # A known Graph 190/463 denial is an expired User token, not a code,
    # source-content or scheduled-post failure. Return only a fixed label.
    # Never persist or print provider text or credential material.
    if type(exc) is RuntimeError and str(exc).startswith(
            "Meta hesap erişimi reddedildi (HTTP 401, kod 190, alt_kod 463)"):
        return "meta_user_token_expired"
    if type(exc) is ValueError:
        return _HOLD_REASON_CODES.get(str(exc), "preflight_validation_failed")
    return "read_or_runtime_failure"


def preserve_failed_audit(exc):
    """Keep an actionable, redacted report even when planning fails early.

    Preserve nonzero exit and never create engagement intents or perform API
    writes as part of failure reporting.
    """
    reason = safe_hold_reason(exc)
    report = {}
    try:
        if REPORT.exists():
            prior = json.loads(REPORT.read_text(encoding="utf-8"))
            if isinstance(prior, dict):
                report = prior
    except (OSError, ValueError):
        report = {}
    report.update(runtime_status="held", runtime_reason_code=reason,
                  writes_retried=False)
    save(REPORT, report)
    return reason


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Keep a redacted audit artifact; do not convert any failure to success.
        reason = preserve_failed_audit(exc)
        print(json.dumps({"status": "held", "reason_code": reason,
                          "error_type": type(exc).__name__, "writes_retried": False}))
        raise SystemExit(1) from None
