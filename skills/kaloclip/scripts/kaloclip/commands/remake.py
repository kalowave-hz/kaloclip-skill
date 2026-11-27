"""`clip remake ...` — a new product video that follows a reference video (paid async job)."""

from __future__ import annotations

import urllib.parse

from .. import api, render
from ..core import Command, Flag
from ..errors import ClipError, UsageError
from . import common
from .creation import creation_fields, product_flags, require

REFERENCE_MAX_SECONDS = 30
RESOLUTIONS = ("720P", "1080P")
SOURCES = ("TikTok", "Kalodata", "YouTube")
BGM_OPTIONS = {"regenerate": "REGENERATE_BGM", "keep": "KEEP_REFERENCE_BGM", "remove": "REMOVE_BGM"}
# Kaloclip waits up to 120s for an external reference video to be fetched
SLOW_TIMEOUT = 180.0

_HOSTS = (("tiktok.com", "TikTok"), ("kalodata.com", "Kalodata"), ("youtube.com", "YouTube"), ("youtu.be", "YouTube"))


# --- reference video -------------------------------------------------------------

def _source_of(url: str) -> str | None:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    for suffix, source in _HOSTS:
        if host == suffix or host.endswith("." + suffix):
            return source
    return None


def reference(opts) -> dict:
    """--video URL (TikTok / Kalodata / YouTube) or --video-asset ID (a video already in the account)."""
    url = (opts.get("video") or "").strip()
    asset = common.asset_id(opts.get("video_asset"), "--video-asset")
    if bool(url) == (asset is not None):
        raise UsageError("pass exactly one of --video <url> or --video-asset <asset_id>",
                         ["Videos already in the account: `clip asset list --type VID`"])
    if asset is not None:
        if opts.get("source"):
            raise UsageError("--source only applies to --video")
        return {"videoSource": "Kaloclip", "videoAssetId": asset}
    if not url.startswith(("http://", "https://")):
        raise UsageError(f"--video expects a TikTok, Kalodata or YouTube link, got '{url}'")
    if "instagram.com" in url.lower():
        raise UsageError("Instagram videos can't be remade; use a TikTok, Kalodata or YouTube link")
    source = opts.get("source") or _source_of(url)
    if not source:
        raise UsageError(f"cannot tell where '{url}' is from",
                         [f"Add --source {'|'.join(SOURCES)}"])
    return {"videoSource": source, "videoUrl": url}


def _video_flags() -> list[Flag]:
    return [
        Flag("--video", f"reference video link: TikTok / Kalodata / YouTube, ≤{REFERENCE_MAX_SECONDS}s", metavar="URL"),
        Flag("--video-asset", "or a video asset of the account (`clip asset list --type VID`)", metavar="ID"),
        Flag("--source", "platform of --video when the link doesn't show it", choices=SOURCES, metavar="SOURCE"),
    ]


def _model_flags() -> list[Flag]:
    return [
        Flag("--model", "internalModelId from `clip remake options` (never hard-code it)", metavar="MODEL"),
        Flag("--resolution", "|".join(RESOLUTIONS) + ", from `clip remake options`", default="720P",
             choices=RESOLUTIONS, metavar="RES"),
    ]


def _preview(cfg, ref: dict, opts, character) -> object:
    body = {**ref, "resolution": opts.get("resolution") or "720P", "internalModelId": opts.get("model"),
            **common.compact({"characterAssetId": character})}
    return api.request(cfg, "POST", "/remakes/preview", body=body, timeout=SLOW_TIMEOUT, retries=1)


# --- commands ----------------------------------------------------------------------

def remake_options(cfg, opts, args):
    duration = opts.get("duration")
    if duration is not None and duration < 1:
        raise UsageError("--duration must be at least 1 second")
    data = api.request(cfg, "GET", "/remakes/options", params={"duration": duration}) or {}
    if opts.get("json"):
        render.emit_json(data)
        return 0
    default_model = data.get("defaultModel")
    models = [{"model": m.get("value"), "label": m.get("label"), "default": m.get("value") == default_model,
               "description": m.get("description")}
              for m in data.get("modelOptions") or [] if isinstance(m, dict)]
    if not models:
        render.emit_empty("models", "no remake model can be submitted right now", ["Try again later"])
        return 0
    render.emit_table("models", models, ("model", "label", "default", "description"))

    def values(key):
        return [o.get("value") if isinstance(o, dict) else o for o in data.get(key) or []]

    render.emit_detail("other", common.compact({
        "resolutions": values("resolutionOptions"),
        "ratios": values("aspectRatioOptions"),
        "default_resolution": data.get("defaultResolution"),
        "default_ratio": data.get("defaultAspectRatio"),
        "ratio_resolution": (data.get("rules") or {}).get("ratio_resolution"),
    }))
    render.emit_help([
        "Pick --model and --resolution from this output only; pass the reference video's length as "
        "--duration to get the matching default model",
        "The price depends on the reference video's real length: `clip remake preview --video <url> --model <M>`",
    ])
    return 0


def remake_preview(cfg, opts, args):
    common.need(opts, "--model")
    ref = reference(opts)
    character = common.asset_id(opts.get("character"), "--character")
    data = _preview(cfg, ref, opts, character)
    if opts.get("json"):
        render.emit_json(data)
        return 0
    render.emit_detail("remake_preview", common.compact({
        "video": ref.get("videoUrl") or ref.get("videoAssetId"), "source": ref["videoSource"],
        "model": opts.get("model"), "resolution": opts.get("resolution") or "720P", "credits": data,
    }))
    render.emit_help(["An estimate only: the submit can still be refused (queue, balance, inputs)"])
    return 0


_FIELD_NAMES = {"creationDescription": "userInputPrompt", "country": "productCountry", "language": "videoLanguage"}
_REMAKE_FIELDS = ("imageInfos", "productTitle", "categoryNames", "sellingPoints", "creationDescription",
                  "productId", "country", "sellingCountry", "language", "internalModelId", "characterAssetId")


def remake_create(cfg, opts, args):
    ref = reference(opts)
    fields = creation_fields(cfg, opts)
    fields.setdefault("language", "en")
    require(fields, {"imageInfos": "--image (or --product-link)", "productTitle": "--title",
                     "productId": "--product-id (or --product-link)", "internalModelId": "--model"},
            "Models come from `clip remake options`")
    body = {
        "creditSourceType": common.CREDIT_SOURCE,
        **ref,
        **{_FIELD_NAMES.get(k, k): v for k, v in fields.items() if k in _REMAKE_FIELDS},
        "aspectRatio": common.ratio(opts),
        "quantity": 1,
        "resolution": opts.get("resolution") or "720P",
        "bgmOption": BGM_OPTIONS[opts.get("bgm") or "regenerate"],
    }
    extra = None
    if not opts.get("yes"):
        api.require_auth(cfg)
        try:
            extra = {"credits": _preview(cfg, ref, opts, fields.get("characterAssetId"))}
        except ClipError as e:  # a reference over 30s or not fetchable fails here already
            if "VIDEO_REMAKE_DURATION_EXCEEDED" in str(e):
                raise
            extra = {"credits": f"unknown ({e})"}
    job_id = common.submit(cfg, opts, "/remakes", body, extra_preview=extra, timeout=SLOW_TIMEOUT)
    if job_id is None:
        return 0
    if opts.get("wait"):
        if not opts.get("json"):
            render.emit_detail("remake_job", {"job_id": job_id})
        job = common.wait_job(cfg, "/jobs", str(job_id), int(opts.get("timeout") or common.WAIT_DEFAULT))
        return common.emit_job(job, str(job_id), opts, waited=True)
    return common.emit_submitted("remake_job", job_id,
                                 f"Remakes take about as long as videos: `clip job {job_id} --wait`", opts)


def _remake_product_flags() -> list[Flag]:
    flags = [f for f in product_flags() if f.name != "--character"]
    flags.append(Flag("--character", "character (digital avatar) id from `clip character list` — it replaces "
                      "the reference's presenter; a bound voice re-voices it at no extra cost", metavar="ID"))
    return flags


COMMANDS = [
    Command(
        path="remake options",
        summary="Models, resolutions and ratios a remake accepts right now (free)",
        handler=remake_options,
        flags=[Flag("--duration", "reference video length in seconds — picks the matching default model",
                    kind="int", metavar="SECONDS")],
        examples=["clip remake options --duration 15"],
    ),
    Command(
        path="remake preview",
        summary="Credits a remake of this reference video would cost (free, no job)",
        handler=remake_preview,
        flags=[*_video_flags(), *_model_flags(),
               Flag("--character", "character id (doesn't change the price)", metavar="ID")],
        examples=["clip remake preview --video https://www.tiktok.com/@shop/video/7312345678901234567 --model sd2"],
    ),
    Command(
        path="remake create",
        summary="Make a product video that follows a reference video's script, shots and pacing "
                f"(reference ≤{REFERENCE_MAX_SECONDS}s; credits = its seconds × model; async job)",
        handler=remake_create,
        flags=[
            *_video_flags(), *_remake_product_flags(), *_model_flags(), common.ratio_flag(),
            Flag("--bgm", "background music: regenerate (default) | keep (the reference's) | remove",
                 choices=tuple(BGM_OPTIONS), metavar="MODE"),
            common.yes_flag(), common.key_flag(), *common.wait_flags(),
        ],
        examples=[
            "clip remake create --video https://www.tiktok.com/@shop/video/7312345678901234567 "
            "--product-link https://shop.tiktok.com/view/product/1732052189676081387 --model sd2",
            "clip remake create --video-asset 207630 --image 739230=https://resource.kaloclip.com/.../a.png "
            "--title 'Wireless Earbuds' --product-id 1234567890 --model sd25 --yes --idempotency-key <KEY> --wait",
        ],
        writes=True,
    ),
]
