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


def verified_inventory(actors):
    """Summarize distinct active account routes vs. FB/IG platform identities.

    Include only public account names and counts, no IDs or credentials.
    """
    platform_counts = Counter(actor["platform"] for actor in actors.values())
    names = sorted({actor["name"] for actor in actors.values()})
    expected_names = set(ROUTE_NAMES.values())
    return {
        "verified_account_routes": len(names),
        "verified_account_names": names,
        "unverified_account_routes": sorted(expected_names - set(names)),
        "verified_platform_identities": len(actors),
        "verified_facebook_identities": platform_counts["facebook"],
        "verified_instagram_identities": platform_counts["instagram"],
        "facebook_unverified_routes": sorted(expected_names - {
            actor["name"] for actor in actors.values() if actor["platform"] == "facebook"
        }),
        "instagram_unverified_routes": sorted(expected_names - {
            actor["name"] for actor in actors.values() if actor["platform"] == "instagram"
        }),
    }


def verified_like_coverage(actors, ledger):
    """Read-only per-account coverage: granted API rights vs accepted Graph ACK.

    A valid identity or successful workflow is not itself a successful like.
    Never report provider IDs, tokens or unmatched historical actors.
    """
    if ledger.get("schema") != 1 or not isinstance(ledger.get("actions"), dict):
        raise ValueError("invalid engagement ledger; reset forbidden")
    output = {}
    for platform in ("facebook", "instagram"):
        members = {(str(actor["id"])): actor for actor in actors.values()
                   if actor["platform"] == platform}
        eligible = {actor["name"] for actor in members.values()
                    if permission(platform, "like") <= actor["grants"]}
        missing_grant = {actor["name"] for actor in members.values()
                         if not permission(platform, "like") <= actor["grants"]}
        accepted_by = set()
        accepted_targets = set()
        count = 0
        self_count = 0
        for record in ledger["actions"].values():
            if not isinstance(record, dict):
                continue
            if (record.get("operation") != "like" or record.get("platform") != platform
                    or record.get("status") != "accepted" or record.get("api_ack") is not True):
                continue
            actor = members.get(str(record.get("actor", "")))
            target = members.get(str(record.get("owner", "")))
            if (not actor or not target or actor["name"] not in eligible):
                continue
            accepted_by.add(actor["name"])
            accepted_targets.add(target["name"])
            count += 1
            if actor["id"] == target["id"]:
                self_count += 1
        output[platform] = {
            "permission_eligible_actor_routes": sorted(eligible),
            "permission_missing_actor_routes": sorted(missing_grant),
            "confirmed_actor_routes": sorted(accepted_by),
            "eligible_routes_without_confirmed_like": sorted(eligible - accepted_by),
            "confirmed_target_routes": sorted(accepted_targets),
            "confirmed_like_count_in_retained_ledger": count,
            "confirmed_self_like_count_in_retained_ledger": self_count,
            "confirmed_cross_like_count_in_retained_ledger": count - self_count,
        }
    return output


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
    # Keep dedupe receipts longer than the three-calendar-day source window.
    # A 48-hour prune could accidentally let a still-eligible video repeat.
    ledger["actions"] = {k: v for k, v in ledger["actions"].items()
                         if stamp(v["at"]) >= now - timedelta(days=7)}
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


def verified_media(task, actors, *, recent_now=None):
    source = actors[(task["platform"], task["owner"])]
    # The publisher records a Video ID, not a PagePost ID. permalink_url is
    # not a common Video field; do not fail the owner check by requesting it.
    fields = "id,from" if task["platform"] == "facebook" else "id,owner,permalink,media_type"
    if recent_now is not None:
        # Use the provider's publication timestamp, not the publisher run's
        # time or the local calendar day. Fail closed if Meta omits the field.
        fields += ",created_time" if task["platform"] == "facebook" else ",timestamp"
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
    if recent_now is not None:
        if recent_now.tzinfo is None:
            raise ValueError("invalid recent window")
        published = stamp(body.get("created_time") if task["platform"] == "facebook"
                          else body.get("timestamp"))
        latest = recent_now.astimezone(timezone.utc)
        if not latest - timedelta(hours=24) <= published <= latest:
            raise ValueError("outside_recent_24h_window")
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
                    source_checks[source_key] = verified_media(
                        task, actors,
                        **({"recent_now": datetime.now(timezone.utc)}
                           if os.getenv("ENGAGEMENT_MODE") == "account_batch" else {}))
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


def failed_before_source_state(run_id):
    """Skip only proven failed runs that could NOT have issued any Meta POST.

    The modern publisher uses one account-scoped `meta (film)` job and a
    downstream merge job; its first stage can fail in no-write verification.
    A run with a planning, intent or publish attempt is NEVER a fallback.
    """
    body = github(f"actions/runs/{run_id}/jobs?per_page=100").json()
    jobs = body.get("jobs") if isinstance(body, dict) else None
    if (not isinstance(jobs, list) or not 1 <= len(jobs) <= 2
            or type(body.get("total_count")) is not int
            or body["total_count"] != len(jobs)
            or any(not isinstance(j, dict) for j in jobs)):
        return False
    candidates = [j for j in jobs
                  if j.get("name") == "meta" or
                  (isinstance(j.get("name"), str) and
                   re.fullmatch(r"meta \\((?:film|film_second|toonzone|tarladaki|penguen|gonle|daily_laugh)\\)",
                                j["name"]))]
    if len(candidates) != 1:
        return False
    job = candidates[0]
    others = [j for j in jobs if j is not job]
    if others and (len(others) != 1
                   or others[0].get("name") != "merge-account-receipts"
                   or others[0].get("status") != "completed"
                   or others[0].get("conclusion") not in {"failure", "skipped"}):
        return False
    if (str(job.get("run_id")) != str(run_id)
            or job.get("status") != "completed"
            or job.get("conclusion") != "failure"
            or not isinstance(job.get("steps"), list)):
        return False
    steps = job["steps"]
    required = {
        "Fail early on invalid Meta credentials before any video work": "success",
        "Check public folders, captions, histories and prepare intent": "skipped",
        "Prepare verified YouTube channel intents for current plans": "skipped",
        "Persist intent before any Meta upload": "skipped",
        "Publish explicitly planned Meta videos": "skipped",
        "Publish planned YouTube videos with archived intent": "skipped",
    }
    for name, conclusion in required.items():
        rows = [s for s in steps if isinstance(s, dict) and s.get("name") == name]
        if (len(rows) != 1 or rows[0].get("status") != "completed"
                or rows[0].get("conclusion") != conclusion):
            return False
    stages = {}
    for name in ("Install media runtime only after Meta preflight passed",
                 "Verify state, account and caption safety without API writes"):
        rows = [s for s in steps if isinstance(s, dict) and s.get("name") == name]
        if len(rows) != 1 or rows[0].get("status") != "completed":
            return False
        stages[name] = rows[0].get("conclusion")
    return stages["Install media runtime only after Meta preflight passed"] == "failure" and stages[
        "Verify state, account and caption safety without API writes"] == "skipped" or (
        stages["Install media runtime only after Meta preflight passed"] == "success"
        and stages["Verify state, account and caption safety without API writes"] == "failure")


def latest_source_id(*, now, allow_prestate_fallback=False, skipped_runs=None):
    body = github("actions/workflows/public_link_schedule.yml/runs?branch=main&per_page=30").json()
    if not isinstance(body.get("workflow_runs"), list):
        raise ValueError("invalid publisher run list")
    valid = [r for r in body["workflow_runs"] if source_run_valid(r, now)]
    if not valid:
        raise ValueError("no recent completed publisher run")
    for run in sorted(valid, key=lambda r: stamp(r["created_at"]), reverse=True):
        rid = str(run.get("id", ""))
        if not rid.isdigit():
            raise ValueError("invalid source run ID")
        if not allow_prestate_fallback:
            return rid
        body = github(f"actions/runs/{rid}/artifacts?per_page=100").json()
        artifacts = body.get("artifacts") if isinstance(body, dict) else None
        if (not isinstance(artifacts, list) or type(body.get("total_count")) is not int
                or body.get("total_count") != len(artifacts)
                or any(not isinstance(a, dict) or not isinstance(a.get("name"), str)
                       for a in artifacts)):
            raise ValueError("invalid source artifact list")
        results = [a for a in artifacts if a["name"] == "link-state-result"]
        if len(results) == 1 and results[0].get("expired") is False:
            return rid  # read_source still verifies and decodes the actual archive.
        if (results or any(a["name"] == "link-state-intent" for a in artifacts)
                or run.get("conclusion") != "failure" or not failed_before_source_state(rid)):
            raise ValueError("source result unavailable")
        if skipped_runs is not None:
            skipped_runs.append(rid)
    raise ValueError("no recent completed publisher run")


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
    """Choose one live like with fair route/platform coverage and safe preflight.

    Never increase write volume: at most one individually verified like per run.
    Do not retry reserved/ambiguous provider writes, bypass actor grants or
    provider holds, or send saves, reposts or self-likes.
    """
    if ledger.get("schema") != 1 or not isinstance(ledger.get("actions"), dict):
        raise ValueError("invalid engagement ledger; reset forbidden")
    holds = provider_holds(ledger)
    names = {(actor["platform"], actor["id"]): actor["name"]
             for actor in actors.values()}
    never = datetime(1970, 1, 1, tzinfo=timezone.utc)
    last_platform, last_actor, last_owner = {}, {}, {}

    # Activity includes pending/uncertain/rejected receipts to keep a failed
    # identity from monopolizing every new source during subsequent ticks.
    for record in ledger["actions"].values():
        if record.get("operation") != "like" or record.get("platform") not in {"instagram", "facebook"}:
            continue
        at = stamp(record["at"])
        platform = record["platform"]
        last_platform[platform] = max(last_platform.get(platform, never), at)
        actor_name = names.get((platform, str(record.get("actor", ""))))
        owner_name = names.get((platform, str(record.get("owner", ""))))
        if actor_name:
            last_actor[actor_name] = max(last_actor.get(actor_name, never), at)
        if owner_name:
            last_owner[owner_name] = max(last_owner.get(owner_name, never), at)

    # ToonZone retains first priority on an entirely fresh ledger. Thereafter,
    # accounts and platform lanes that received less recent coverage go first.
    routes = ("ToonZone", "Film Mağarası", "Filmmagrasi", "Beyinsiz Penguen",
              "Tarladaki Fasulye", "Gönle Düşen", "Daily Laugh Lab")
    rank = {name: index for index, name in enumerate(routes)}
    for platform in sorted(("instagram", "facebook"),
                           key=lambda p: (last_platform.get(p, never), p != "instagram")):
        if f"{platform}/like" in holds:
            continue
        checked_sources = 0
        eligible_sources = sorted(
            (post for post in posts if post["platform"] == platform),
            key=lambda post: (
                last_owner.get(names.get((platform, post["owner"])), never),
                rank.get(names.get((platform, post["owner"])), len(rank)),
                post["post_id"],
            ),
        )
        for source in eligible_sources:
            candidates = []
            for actor in actors.values():
                if (actor["platform"] != platform or actor["id"] == source["owner"]
                        or not permission(platform, "like") <= actor["grants"]):
                    continue
                task = dict(source, actor=actor["id"], operation="like",
                            source_run_id=source.get("source_run_id", source_run_id))
                if key(task) not in ledger["actions"]:
                    candidates.append((actor, task))
            if not candidates:
                continue
            if checked_sources >= 8:
                break
            checked_sources += 1
            # Owner/source proof is independent of who likes it: a bad source
            # uses only one bounded GET and never consumes all eight checks.
            actor, task = min(candidates, key=lambda pair: (
                last_actor.get(pair[0]["name"], never),
                rank.get(pair[0]["name"], len(rank)),
                pair[0]["id"],
            ))
            try:
                verified_media(task, actors)
            except (GraphFailure, ValueError, KeyError):
                continue
            selected = {(platform, actor["id"]): actor}
            tasks, report = build_plan([source], selected, ledger, run_id,
                                       source_run_id, now=now)
            if len(tasks) != 1 or tasks[0]["operation"] != "like":
                raise ValueError("unexpected single-like reservation")
            return tasks, report
    return [], [{"status": "no_eligible_verified_single_like"}]


def build_account_batch(posts, actors, ledger, run_id, source_run_id, *, now):
    """One account per tick, all its eligible recent posts, same-platform likes only.

    Each actor/post intent is persisted to an artifact before the first POST.
    Other account lanes stay independent; permit verified owner likes, never save or repost.
    """
    if ledger.get("schema") != 1 or not isinstance(ledger.get("actions"), dict):
        raise ValueError("invalid engagement ledger; reset forbidden")
    holds = provider_holds(ledger)
    never = datetime(1970, 1, 1, tzinfo=timezone.utc)
    names = {(a["platform"], a["id"]): a["name"] for a in actors.values()}
    last_target = {}
    for record in ledger["actions"].values():
        if record.get("operation") == "like":
            name = names.get((record.get("platform"), str(record.get("owner", ""))))
            if name:
                last_target[name] = max(last_target.get(name, never), stamp(record["at"]))

    priority = ("ToonZone", "Film Mağarası", "Filmmagrasi",
                "Beyinsiz Penguen", "Tarladaki Fasulye",
                "Gönle Düşen", "Daily Laugh Lab")
    rank = {name: i for i, name in enumerate(priority)}
    by_name = {}
    for post in posts:
        owner = actors.get((post["platform"], post["owner"]))
        if owner and f'{post["platform"]}/like' not in holds:
            by_name.setdefault(owner["name"], []).append(post)

    blocked_across_accounts = []
    for name in sorted(by_name, key=lambda n: (last_target.get(n, never),
                                               rank.get(n, len(rank)), n)):
        planned, report = [], []
        for post in sorted(by_name[name], key=lambda p: (p["platform"], p["post_id"])):
            platform = post["platform"]
            reviewers = {
                (a["platform"], a["id"]): a for a in actors.values()
                if a["platform"] == platform
                and permission(platform, "like") <= a["grants"]
                and key(dict(post, actor=a["id"], operation="like")) not in ledger["actions"]
            }
            if not reviewers:
                continue
            probe = dict(post, actor=next(iter(reviewers.values()))["id"], operation="like")
            try:
                verified_media(probe, actors, recent_now=now)
            except (GraphFailure, ValueError, KeyError):
                report.append({"status": "source_preflight_failed"})
                continue
            reservations, reasons = build_plan([post], reviewers, ledger, run_id,
                                               source_run_id, now=now)
            planned.extend(t for t in reservations if t["operation"] == "like")
            report.extend(reasons)
        if planned:
            return planned, report
        blocked_across_accounts.extend(report)
    return [], blocked_across_accounts or [{"status": "no_eligible_verified_account_batch"}]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("plan", "execute"))
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    run_id, source_id = os.environ["GITHUB_RUN_ID"], os.environ["SOURCE_RUN_ID"]
    if os.getenv("GITHUB_REPOSITORY") != REPO or not run_id.isdigit() or not (source_id.isdigit() or source_id == "latest"):
        raise ValueError("invalid workflow identity")
    mode = os.getenv("ENGAGEMENT_MODE")
    # Main-branch owner approval marker or a regular schedule may perform
    # one verified like only. Manual dispatch stays read-only; no bulk apply.
    single_like = (mode == "single_like"
                   and os.getenv("GITHUB_EVENT_NAME") in {"push", "schedule"}
                   and os.getenv("GITHUB_REF") == "refs/heads/main")
    account_batch = (mode == "account_batch"
                     and os.getenv("GITHUB_EVENT_NAME") in {"schedule", "push"}
                     and os.getenv("GITHUB_REF") == "refs/heads/main")
    live = (os.getenv("META_CROSS_ENGAGEMENT_ENABLED") == "true"
            and (mode == "apply" or single_like or account_batch))
    focus = os.getenv("META_AUDIT_FOCUS", "").strip()
    if focus and live:
        # A focus is exclusively for read-only coverage; never escalate to
        # coordinated cross-account likes via manual apply or old push modes.
        raise ValueError("focused account coverage is read-only")
    actors = accounts(load_meta_auth(), os.getenv("META_ACCESS_TOKEN", ""))
    if not actors:
        raise ValueError("no verified enabled accounts")
    inventory = verified_inventory(actors)
    if args.action == "plan":
        skipped_sources = []
        if source_id == "latest":
            source_id = latest_source_id(now=now,
                allow_prestate_fallback=(mode == "dry_run" and not live
                    and (os.getenv("GITHUB_EVENT_NAME") == "schedule" or bool(focus))
                    and os.getenv("ENGAGEMENT_SCOPE") == "recent_window"),
                skipped_runs=skipped_sources)
        ledger = restore()
        state = read_source(source_id, now=now)
        posts = (recent_posts(state, source_id, actors, now=now)
                 if os.getenv("ENGAGEMENT_SCOPE") == "recent_window"
                 else source_posts(state, source_id, actors))
        posts, focus_info = scope_audit_posts(posts, actors, focus)
        if account_batch:
            tasks, report = build_account_batch(posts, actors, ledger, run_id, source_id, now=now)
        elif single_like:
            tasks, report = build_one_like(posts, actors, ledger, run_id, source_id, now=now)
        else:
            tasks, report = build_plan(posts, actors, ledger, run_id, source_id, now=now)
        if single_like and live and (
                len(tasks) > 1
                or any(t["operation"] != "like" or t["actor"] == t["owner"]
                       for t in tasks)):
            raise ValueError("single-like plan not safe")
        if account_batch and live and (any(t["operation"] != "like"
                for t in tasks)
                or len({a["name"] for t in tasks for a in actors.values()
                        if a["platform"] == t["platform"] and a["id"] == t["owner"]}) > 1):
            raise ValueError("account batch scope invalid")
        # A zero-eligible scheduled tick is a legitimate no-op. Its
        # diagnostic has a status but no platform/operation, unlike task rows.
        blocked_counts = dict(Counter(
            f"{r.get('platform', 'all')}/{r.get('operation', 'like')}/{r['status']}"
            for r in report if isinstance(r, dict) and isinstance(r.get('status'), str)
        ))
        like_coverage = verified_like_coverage(actors, ledger)
        save(PLAN, tasks)
        save(REPORT, {"mode": "apply" if live else "dry_run", "planned": len(tasks),
                      "source_run_id": source_id, "source_posts": len(posts),
                      "source_fallback_skipped_runs": skipped_sources,
                      "verified_accounts": len(actors), **inventory, **focus_info,
                      "verified_like_coverage": like_coverage,
                      "blocked": report, "blocked_counts": blocked_counts,
                      "provider_holds": ledger.get("provider_holds", {})})
        if live:
            save(STATE, ledger)
        print(json.dumps({"mode": "apply" if live else "dry_run", "planned": len(tasks),
                          "source_posts": len(posts), "verified_accounts": len(actors), **inventory,
                          "verified_like_coverage": like_coverage,
                          "source_fallback_skipped_runs": skipped_sources,
                          **focus_info,
                          "blocked": len(report), "blocked_counts": blocked_counts,
                          "provider_holds": ledger.get("provider_holds", {})}))
    elif live:
        ledger = json.loads(STATE.read_text())
        tasks = json.loads(PLAN.read_text())
        if single_like and (
                len(tasks) > 1
                or any(t.get("operation") != "like" or t.get("actor") == t.get("owner")
                       for t in tasks)):
            raise ValueError("single-like execution scope invalid")
        if account_batch and (any(t.get("operation") != "like"
                for t in tasks)
                or len({a["name"] for t in tasks for a in actors.values()
                        if a["platform"] == t.get("platform") and a["id"] == t.get("owner")}) > 1):
            raise ValueError("account batch execution scope invalid")
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
        if (ledger.get("provider_holds") and mode == "apply") or any(counts.get(s) for s in ("source_or_permission_unverified", "uncertain", "rejected", "blocked_actor", "provider_restriction_hold")):
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
