"""`clip tiktok ...` — publish a video asset to the user's TikTok account as a shoppable post (free)."""

from __future__ import annotations

import datetime
import string
import time

from .. import api, render
from ..core import Command, Flag
from ..errors import ClipError, UsageError
from . import common

BASE = "/tiktok-publish"
TITLE_MAX = 30
CAPTION_MAX = 4000
SCHEDULE_MAX_DAYS = 30
STATUSES = ("INIT", "UPLOADING", "PRE_CHECKING", "PRE_CHECK_SUCCESS", "PENDING_PUBLISH", "PRE_CHECK_FAIL",
            "PUBLISHING", "SUCCESS", "FAIL", "CANCEL")
TERMINAL = ("SUCCESS", "FAIL", "PRE_CHECK_FAIL", "CANCEL")
MODES = ("NOW", "SCHEDULE")
# the product anchor text: no ASCII punctuation and none of these
_TITLE_FORBIDDEN = set(string.punctuation) | set("×–°—−‐‑‒―，。、；：？！…《》【】")


def _account_flag() -> Flag:
    return Flag("--account", "linkId of a publishable account from `clip tiktok accounts`", metavar="LINK_ID")


def _link(opts) -> int:
    common.need(opts, "--account")
    return common.asset_id(opts["account"], "--account")


def _record_id(value: str) -> int:
    return common.asset_id(value, "record_id")


def _page_token_hint(token, cmd: str) -> list[str]:
    return [f"More: rerun with --page-token {token}" + cmd] if token else []


# --- accounts ----------------------------------------------------------------------

def auth(cfg, opts, args):
    data = api.request(cfg, "POST", f"{BASE}/auth-url", params={"region": opts.get("region")}, retries=1) or {}
    if opts.get("json"):
        render.emit_json(data)
        return 0
    render.emit_detail("tiktok_auth", {"auth_url": data.get("authUrl")})
    render.emit_help([
        "Give auth_url to the user to open in a browser and authorize their TikTok creator account; "
        "it is bound to this key's Kaloclip account",
        "Once they are done, `clip tiktok accounts` shows it (can_publish must be true)",
    ])
    return 0


def accounts(cfg, opts, args):
    data = api.request(cfg, "GET", f"{BASE}/accounts") or []
    if opts.get("json"):
        render.emit_json(data)
        return 0
    rows = [{
        "link_id": a.get("linkId"), "name": a.get("accountName"), "type": a.get("accountUserType"),
        "region": a.get("region"), "expired": bool(a.get("expired")), "can_publish": bool(a.get("canPublishVideo")),
    } for a in data if isinstance(a, dict)]
    if not rows:
        render.emit_empty("accounts", "no TikTok account linked", [
            "Link one: `clip tiktok auth [--region US]` and let the user open the URL",
        ])
        return 0
    render.emit_table("accounts", rows, ("link_id", "name", "type", "region", "expired", "can_publish"))
    hints = ["Publish with a row where type is CREATOR and can_publish is true: --account <link_id>"]
    if any(r["expired"] for r in rows):
        hints.append("expired accounts need authorizing again: `clip tiktok auth`")
    if not any(r["can_publish"] and r["type"] == "CREATOR" for r in rows):
        hints.append("No account can publish yet — authorize a TikTok Shop creator account with `clip tiktok auth`")
    render.emit_help(hints)
    return 0


def products(cfg, opts, args):
    link = _link(opts)
    params = {"linkId": link, "pageSize": opts.get("page_size"), "pageToken": opts.get("page_token")}
    data = api.request(cfg, "GET", f"{BASE}/products", params=params) or {}
    if opts.get("json"):
        render.emit_json(data)
        return 0
    rows = [{
        "product_id": p.get("productId"), "title": p.get("productTitle"),
        "price": " ".join(str(v) for v in (p.get("priceAmount"), p.get("priceCurrency")) if v) or None,
        "sales": p.get("salesCount"), "added": p.get("addedStatus"), "image": p.get("imageUrl"),
    } for p in data.get("products") or [] if isinstance(p, dict)]
    if not rows:
        render.emit_empty("products", "this account has no product to attach",
                          ["Add products to the creator's showcase on TikTok first"])
        return 0
    render.emit_table("products", rows, ("product_id", "title", "price", "sales", "added", "image"))
    render.emit_help([
        "Attach one with --product-id <product_id> --product-title <title> (added must be ADDED)",
        *_page_token_hint(data.get("nextPageToken"), f" --account {link}"),
    ])
    return 0


def music(cfg, opts, args):
    link = _link(opts)
    if opts.get("page_token") and not opts.get("search_id"):
        raise UsageError("--page-token needs the --search-id of the first page")
    params = {"linkId": link, "keyword": args[0], "pageSize": opts.get("page_size"),
              "pageToken": opts.get("page_token"), "searchId": opts.get("search_id")}
    data = api.request(cfg, "GET", f"{BASE}/music/search", params=params) or {}
    if opts.get("json"):
        render.emit_json(data)
        return 0
    rows = [{
        "music_id": m.get("id"), "title": m.get("title"), "author": m.get("author"),
        "seconds": m.get("duration"), "preview": (m.get("playUrls") or [None])[0],
    } for m in data.get("music") or [] if isinstance(m, dict)]
    if not rows:
        render.emit_empty("music", f"nothing for '{args[0]}'", ["Try another keyword"])
        return 0
    render.emit_table("music", rows, ("music_id", "title", "author", "seconds", "preview"))
    hints = ["--music <music_id> on `clip tiktok publish` REPLACES the video's whole audio track, voice-over "
             "included — use it only when the user wants that"]
    if data.get("hasMore") and data.get("nextPageToken"):
        hints += _page_token_hint(data["nextPageToken"], f" --search-id {data.get('searchId')} --account {link}")
    render.emit_help(hints)
    return 0


# --- publish records ------------------------------------------------------------------

def _record_row(r: dict) -> dict:
    return common.compact({
        "record_id": r.get("id"),
        "status": r.get("status"),
        "need_confirm": r.get("needConfirm") or None,
        "mode": r.get("publishMode"),
        "publish_time": common.ms_iso(r.get("publishTime")),
        "posted": common.ms_iso(r.get("postTime")),
        "publish_url": r.get("publishUrl"),
        "fail_code": r.get("failCode"),
        "fail_reason": r.get("failReason"),
        "account": r.get("accountName"),
        "asset_id": r.get("assetId"),
        "product_id": r.get("productId"),
        "title": r.get("title"),
        "credit_reward": r.get("creditRewardOutcome"),
    })


def _record_hints(r: dict) -> list[str]:
    rid, status = r.get("id"), r.get("status")
    if r.get("needConfirm"):
        return ["The pre-check found the issues above — show them to the user; if they still want it posted, "
                f"`clip tiktok confirm {rid}`; otherwise leave it (fix the video and publish again)"]
    if status == "SUCCESS":
        return ["Posted — give publish_url to the user"]
    if status in ("FAIL", "PRE_CHECK_FAIL"):
        return [f"Not posted ({r.get('failCode') or 'no code'}) — tell the user the reason; after fixing it, "
                "`clip tiktok publish` the asset again"]
    if status == "CANCEL":
        return ["Cancelled by the user; nothing was posted"]
    if status == "PENDING_PUBLISH":
        return [f"Scheduled for {common.ms_iso(r.get('publishTime'))} — cancel with `clip tiktok cancel {rid}`"]
    return [f"Still {status} — poll with `clip tiktok status {rid} --wait`; don't publish the asset again"]


def _emit_record(r: dict, opts) -> int:
    if opts.get("json"):
        render.emit_json(r)
        return 0
    render.emit_detail("publish", _record_row(r))
    issues = [{"risk": i.get("risk"), "suggestions": i.get("suggestions")}
              for i in r.get("issues") or [] if isinstance(i, dict)]
    if issues:
        render.emit_table("issues", issues, ("risk", "suggestions"))
    render.emit_help(_record_hints(r))
    return 0


def _settled(r: dict) -> bool:
    return r.get("status") in TERMINAL or r.get("status") == "PENDING_PUBLISH" or bool(r.get("needConfirm"))


def _get_record(cfg, rid) -> dict:
    return api.request(cfg, "GET", f"{BASE}/videos/result", params={"id": rid}) or {}


def _wait_record(cfg, rid, timeout: int, *, sleep=time.sleep, clock=time.monotonic) -> dict:
    deadline = clock() + timeout
    while True:
        r = _get_record(cfg, rid)
        if _settled(r) or clock() + common.POLL_SECONDS > deadline:
            return r
        sleep(common.POLL_SECONDS)


def status(cfg, opts, args):
    rid = _record_id(args[0])
    if opts.get("wait"):
        return _emit_record(_wait_record(cfg, rid, int(opts.get("timeout") or common.WAIT_DEFAULT)), opts)
    return _emit_record(_get_record(cfg, rid), opts)


def records(cfg, opts, args):
    page = opts.get("page") or 1
    for s in opts.get("status") or []:
        if s not in STATUSES:
            raise UsageError(f"invalid --status '{s}'", [f"valid values: {', '.join(STATUSES)}"])
    params = {
        "assetId": common.asset_id(opts.get("asset"), "--asset"),
        "statuses": ",".join(opts.get("status") or []) or None,
        "publishMode": opts.get("mode"),
        "linkId": common.asset_id(opts.get("account"), "--account"),
        "pageNo": page,
        "pageSize": opts.get("page_size") or 20,
    }
    data = api.request(cfg, "GET", f"{BASE}/videos/page", params=params) or {}
    if opts.get("json"):
        render.emit_json(data)
        return 0
    items = [r for r in data.get("data") or [] if isinstance(r, dict)]
    if not items:
        render.emit_empty("publishes", f"page {page}, {data.get('total') or 0} in total",
                          ["Publish a video asset with `clip tiktok publish`"])
        return 0
    rows = []
    for r in items:
        row = _record_row(r)
        perf = r.get("performance") if isinstance(r.get("performance"), dict) else {}
        row["orders"] = perf.get("orderCount")
        row["gmv"] = " ".join(str(v) for v in (perf.get("gmvAmount"), perf.get("gmvCurrency")) if v) or None
        rows.append(row)
    render.emit_table("publishes", rows, ("record_id", "status", "mode", "publish_time", "account", "asset_id",
                                          "product_id", "publish_url", "orders", "gmv", "fail_reason"))
    hints = []
    total = data.get("total")
    if isinstance(total, int) and page * (data.get("pageSize") or params["pageSize"]) < total:
        hints.append(f"More: rerun with --page {page + 1}")
    hints.append("Details and pre-check issues of one: `clip tiktok status <record_id>`")
    render.emit_help(hints)
    return 0


# --- publish / confirm / cancel ----------------------------------------------------------

def _check_title(title: str) -> None:
    if not title.strip():
        raise UsageError("--title must not be empty")
    if len(title) > TITLE_MAX:
        raise UsageError(f"--title is {len(title)} characters; the limit is {TITLE_MAX}")
    bad = sorted({c for c in title if c in _TITLE_FORBIDDEN})
    if bad:
        raise UsageError(f"--title must not contain punctuation, found: {' '.join(bad)}",
                         ["It is the short text on the product anchor, e.g. 'Wireless Earbuds Deal'"])


def _publish_time(value: str | None) -> int | None:
    """ISO 8601 (no zone = local time) or epoch milliseconds -> epoch ms within the next 30 days."""
    if not value:
        return None
    v = value.strip()
    if v.isdigit():
        ms = int(v)
    else:
        try:
            dt = datetime.datetime.fromisoformat(v)
        except ValueError:
            raise UsageError(f"--schedule expects an ISO time like 2026-12-01T20:00+08:00, got '{value}'") from None
        if dt.tzinfo is None:
            dt = dt.astimezone()
        ms = int(dt.timestamp() * 1000)
    now = int(time.time() * 1000)
    if ms <= now:
        raise UsageError("--schedule must be in the future")
    if ms > now + SCHEDULE_MAX_DAYS * 86400 * 1000:
        raise UsageError(f"--schedule can be at most {SCHEDULE_MAX_DAYS} days ahead")
    return ms


def publish(cfg, opts, args):
    common.need(opts, "--account", "--asset", "--product-id", "--product-title", "--title", "--caption")
    _check_title(opts["title"])
    caption = opts["caption"]
    if len(caption) > CAPTION_MAX:
        raise UsageError(f"--caption is {len(caption)} characters; the limit is {CAPTION_MAX}")
    if opts.get("auto_confirm") and not opts.get("precheck"):
        raise UsageError("--auto-confirm only applies with --precheck")
    when = _publish_time(opts.get("schedule"))
    body = {
        "linkId": _link(opts),
        "assetId": common.asset_id(opts["asset"], "--asset"),
        "publishMode": "SCHEDULE" if when else "NOW",
        "productId": opts["product_id"],
        "productTitle": opts["product_title"],
        "title": opts["title"],
        "description": caption,
        "isAiGenerated": not opts.get("no_ai_label"),
        "needPrecheck": bool(opts.get("precheck")),
        **common.compact({
            "publishTime": when,
            "productImage": opts.get("product_image"),
            "productPriceAmount": opts.get("price"),
            "productPriceCurrency": opts.get("currency"),
            "coverImageUrl": opts.get("cover"),
            "musicId": opts.get("music"),
            "autoConfirmPrecheckIssues": True if opts.get("auto_confirm") else None,
        }),
    }
    api.require_auth(cfg)
    if not opts.get("yes"):
        preview = {"method": "POST", "path": f"{BASE}/videos", "credits": 0, "body": body}
        if opts.get("json"):
            render.emit_json({"dry_run": preview})
            return 0
        render.emit_detail("dry_run", preview)
        render.emit_help([
            "Nothing was sent. This posts publicly on the user's TikTok account — rerun with --yes only after "
            "the user has seen and agreed to this account, video, product, title, caption and time",
        ])
        return 0
    try:
        # deduplicated upstream only by asset (409 PUBLISH_DUPLICATE): never resend on our own
        data = api.request(cfg, "POST", f"{BASE}/videos", body=body, retries=1) or {}
    except ClipError as e:
        if e.kind == "network":
            e.help_lines = [f"The outcome is unknown — find the record with `clip tiktok records --asset "
                            f"{body['assetId']}` before publishing again"]
        raise
    rid = data.get("id")
    if opts.get("wait") and rid is not None:
        return _emit_record(_wait_record(cfg, rid, int(opts.get("timeout") or common.WAIT_DEFAULT)), opts)
    if opts.get("json"):
        render.emit_json(data)
        return 0
    render.emit_detail("publish", {"record_id": rid, "status": data.get("status")})
    render.emit_help([f"Poll it: `clip tiktok status {rid} --wait`; don't publish the asset again meanwhile"])
    return 0


def confirm(cfg, opts, args):
    rid = _record_id(args[0])
    if not opts.get("yes"):
        record = _get_record(cfg, rid)
        if opts.get("json"):
            render.emit_json({"dry_run": {"method": "POST", "path": f"{BASE}/videos/confirm", "body": {"id": rid},
                                          "record": record}})
            return 0
        _emit_record(record, {})
        render.emit_help([f"Nothing was sent. Rerun with --yes to post it despite these issues — only if the "
                          "user agreed after seeing them"])
        return 0
    api.request(cfg, "POST", f"{BASE}/videos/confirm", body={"id": rid}, retries=1)
    return _emit_record(_get_record(cfg, rid), opts)


def cancel(cfg, opts, args):
    rid = _record_id(args[0])
    api.request(cfg, "POST", f"{BASE}/videos/cancel", body={"id": rid}, retries=1)
    return _emit_record(_get_record(cfg, rid), opts)


def _record_cmd(path, summary, handler, flags=(), writes=False, example=None):
    return Command(path=path, summary=summary, handler=handler, flags=list(flags), positional="record_id",
                   pos_min=1, pos_max=1, examples=[example or f"clip {path} 9012"], writes=writes)


COMMANDS = [
    Command(
        path="tiktok auth",
        summary="Link a TikTok creator account: a URL for the user to open and authorize (free)",
        handler=auth,
        flags=[Flag("--region", "creator region, e.g. US (default app if omitted)", metavar="CC")],
        examples=["clip tiktok auth --region US"],
    ),
    Command(
        path="tiktok accounts",
        summary="TikTok accounts linked to the Kaloclip account; link_id is --account (free)",
        handler=accounts,
        examples=["clip tiktok accounts"],
    ),
    Command(
        path="tiktok products",
        summary="TikTok Shop products the account can attach to a post (free)",
        handler=products,
        flags=[_account_flag(),
               Flag("--page-size", "rows per page (1-100)", kind="int", min=1, max=100, metavar="N"),
               Flag("--page-token", "next page, from the previous output", metavar="TOKEN")],
        examples=["clip tiktok products --account 31"],
    ),
    Command(
        path="tiktok music",
        summary="Search commercial music for a post (free); it replaces the video's audio",
        handler=music,
        flags=[_account_flag(),
               Flag("--page-size", "rows per page (1-50)", kind="int", min=1, max=50, metavar="N"),
               Flag("--page-token", "next page, from the previous output", metavar="TOKEN"),
               Flag("--search-id", "search id of the first page (needed with --page-token)", metavar="ID")],
        positional="keyword",
        pos_min=1,
        pos_max=1,
        examples=["clip tiktok music upbeat --account 31"],
    ),
    Command(
        path="tiktok publish",
        summary="Post a video asset to TikTok with a product attached (free; public — dry run unless --yes)",
        handler=publish,
        flags=[
            _account_flag(),
            Flag("--asset", "video asset id (`clip asset list --type VID`, or a finished video job's userAssetId)",
                 metavar="ID"),
            Flag("--product-id", "product from `clip tiktok products`", metavar="ID"),
            Flag("--product-title", "that product's title", metavar="TEXT"),
            Flag("--title", f"product anchor text, ≤{TITLE_MAX} chars, no punctuation", metavar="TEXT"),
            Flag("--caption", f"post caption, ≤{CAPTION_MAX} chars", metavar="TEXT"),
            Flag("--schedule", f"post later instead of now: ISO time (no zone = local) or epoch ms, "
                 f"≤{SCHEDULE_MAX_DAYS} days ahead", metavar="TIME"),
            Flag("--cover", "cover image URL (JPEG/PNG/WEBP ≤10MB; falls back to the first frame)", metavar="URL"),
            Flag("--music", "music id from `clip tiktok music` — replaces the whole audio, voice-over included",
                 metavar="ID"),
            Flag("--product-image", "product image URL for the record", metavar="URL"),
            Flag("--price", "product price for the record", metavar="AMOUNT"),
            Flag("--currency", "currency of --price", metavar="CUR"),
            Flag("--no-ai-label", "don't tag the post as AI-generated (only for the user's own footage)",
                 kind="flag", default=False),
            Flag("--precheck", "run TikTok's pre-publish check; issues stop it for `clip tiktok confirm`",
                 kind="flag", default=False),
            Flag("--auto-confirm", "with --precheck: post even if the check finds issues", kind="flag", default=False),
            Flag("--yes", "really publish; without --yes the request is only printed", kind="flag", default=False),
            *common.wait_flags(),
        ],
        examples=["clip tiktok publish --account 31 --asset 207630 --product-id 1729384756 "
                  "--product-title 'Wireless Earbuds' --title 'Wireless Earbuds' --caption 'Tiny buds, big sound'"],
        writes=True,
    ),
    _record_cmd("tiktok status", "State of one publish: status, pre-check issues, publish_url (free)", status,
                common.wait_flags(), example="clip tiktok status 9012 --wait"),
    Command(
        path="tiktok records",
        summary="Publish history incl. the website's, newest first, with sales performance (free)",
        handler=records,
        flags=[
            Flag("--asset", "only this video asset", metavar="ID"),
            Flag("--status", "filter by status (repeat): " + "|".join(STATUSES), kind="multi", default=[],
                 metavar="STATUS"),
            Flag("--mode", "NOW | SCHEDULE", choices=MODES, metavar="MODE"),
            _account_flag(),
            Flag("--page", "page number, from 1", kind="int", default=1, min=1, metavar="N"),
            Flag("--page-size", "rows per page (max 100)", kind="int", default=20, min=1, max=100, metavar="N"),
        ],
        examples=["clip tiktok records", "clip tiktok records --asset 207630"],
    ),
    _record_cmd("tiktok confirm", "Post a publish held by pre-check issues (dry run shows the issues unless --yes)",
                confirm, [Flag("--yes", "really post it", kind="flag", default=False)], writes=True),
    _record_cmd("tiktok cancel", "Cancel a scheduled publish that hasn't been posted yet", cancel),
]
