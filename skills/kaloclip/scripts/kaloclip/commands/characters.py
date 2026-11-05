"""`clip character ...|voice ...` — digital avatars that appear in videos, and the voices they speak with."""

from __future__ import annotations

from pathlib import Path

from .. import api, render
from ..core import Command, Flag
from ..errors import ClipError, UsageError
from . import common
from .assets import IMAGE_MAX_BYTES, IMAGE_TYPES

CATEGORIES = ("MODEL", "ANIMAL")
GENDERS = ("male", "female")
NAME_MAX = 50
INTRO_MAX = 300
OTHER_IMAGES_MAX = 3
VOICE_NAME_MAX = 64
CLONE_CREDITS = 20
AUDIO_TYPES = {".mp3", ".wav", ".m4a", ".aac", ".webm", ".ogg", ".mp4"}
AUDIO_MAX_BYTES = 20 * 1024 * 1024
PAGE_DEFAULT = 20
# both calls block until a vendor finishes (character binding, voice cloning); Kaloclip asks for ≥120s
SLOW_TIMEOUT = 180.0

_USE_HINT = (f"Use it in `clip script create` and `clip video create` with --character <id> (the same id for both; "
             f"models {'/'.join(common.CHARACTER_MODELS)}, at most {common.CHARACTER_IMAGES_MAX} product images)")


# --- shared --------------------------------------------------------------------

def _image_file(value: str, flag: str) -> Path:
    p = Path(value).expanduser()
    if not p.is_file():
        raise UsageError(f"{flag}: no such file: {value}")
    if p.suffix.lower() not in IMAGE_TYPES:
        raise UsageError(f"{flag} {value}: only JPEG/PNG/GIF/WebP images are accepted")
    if p.stat().st_size > IMAGE_MAX_BYTES:
        raise UsageError(f"{flag} {value} is {p.stat().st_size // 1024} KB; the limit is 5 MB per image")
    return p


def _character_row(c: dict) -> dict:
    return {
        "character_id": c.get("id"),
        "name": c.get("name"),
        "category": c.get("category"),
        "bind_state": c.get("bindState"),
        "voice_id": c.get("voiceAssetId"),
        "voice": c.get("voiceName"),
        "main_image": (c.get("mainImage") or {}).get("imageUrl") if isinstance(c.get("mainImage"), dict) else None,
    }


def _character_hints(rows: list[dict]) -> list[str]:
    hints = [_USE_HINT]
    if any(r.get("bind_state") in ("BINDING", "FAILED") for r in rows):
        hints.append("bind_state BINDING / FAILED: the character is not ready with the video provider yet — "
                     "use a BOUND one, or create it again if it FAILED")
    if any(r.get("voice_id") is None for r in rows):
        hints.append("No voice bound: videos keep the model's own voice — bind one with "
                     "`clip character voice <character_id> --voice <voice_id>` (voices from `clip voice list`)")
    return hints


def _emit_character(noun: str, data: dict, opts) -> int:
    if opts.get("json"):
        render.emit_json(data)
        return 0
    row = _character_row(data)
    row["intro"] = data.get("personalIntro")
    others = [i.get("imageUrl") for i in data.get("otherImages") or [] if isinstance(i, dict)]
    row["other_images"] = others or None
    render.emit_detail(noun, common.compact(row))
    render.emit_help(_character_hints([row]))
    return 0


def _page(data: dict, page: int, params: dict, noun: str) -> list[str]:
    render.emit_detail("page", {"page": data.get("pageNo") or page, "page_size": data.get("pageSize"),
                                "total": data.get("total")})
    total = data.get("total")
    if isinstance(total, int) and page * (data.get("pageSize") or params["pageSize"]) < total:
        return [f"More {noun}: rerun with --page {page + 1}"]
    return []


def _page_flags() -> list[Flag]:
    return [
        Flag("--page", "page number, from 1", kind="int", default=1, min=1, metavar="N"),
        Flag("--page-size", "rows per page (max 100)", kind="int", default=PAGE_DEFAULT, min=1, max=100, metavar="N"),
    ]


# --- characters ------------------------------------------------------------------

def character_list(cfg, opts, args):
    page = opts.get("page") or 1
    params = {"category": opts.get("category"), "name": opts.get("name"), "pageNo": page,
              "pageSize": opts.get("page_size") or PAGE_DEFAULT}
    data = api.request(cfg, "GET", "/character-assets", params=params) or {}
    if opts.get("json"):
        render.emit_json(data)
        return 0
    items = [c for c in data.get("data") or [] if isinstance(c, dict)]
    if not items:
        render.emit_empty("characters", f"page {page}, {data.get('total') or 0} in total", [
            "Create one from a photo: `clip character create --name <NAME> --main-image front.png` "
            "(--category ANIMAL for pets; without --category the list shows people only)",
        ])
        return 0
    rows = [_character_row(c) for c in items]
    render.emit_table("characters", rows,
                      ("character_id", "name", "category", "bind_state", "voice_id", "voice", "main_image"))
    render.emit_help(_page(data, page, params, "characters") + _character_hints(rows))
    return 0


def character_get(cfg, opts, args):
    character = common.asset_id(args[0], "character_id")
    data = api.request(cfg, "GET", "/character-assets/detail", params={"assetId": character}) or {}
    return _emit_character("character", data, opts)


def character_create(cfg, opts, args):
    common.need(opts, "--name", "--main-image")
    name = opts["name"].strip()
    if not 1 <= len(name) <= NAME_MAX:
        raise UsageError(f"--name must be 1-{NAME_MAX} characters, got {len(name)}")
    intro = (opts.get("intro") or "").strip() or None
    if intro and len(intro) > INTRO_MAX:
        raise UsageError(f"--intro is {len(intro)} chars; the limit is {INTRO_MAX}")
    others = opts.get("other_image") or []
    if len(others) > OTHER_IMAGES_MAX:
        raise UsageError(f"at most {OTHER_IMAGES_MAX} --other-image, got {len(others)}")
    files = [("mainImage", _image_file(opts["main_image"], "--main-image"))]
    files += [("otherImages", _image_file(o, "--other-image")) for o in others]
    form = {"category": opts.get("category") or "MODEL", "name": name, "personalIntro": intro}
    try:
        # no submit idempotency upstream: never resend on our own
        data = api.request(cfg, "POST", "/character-assets", files=files, form=form,
                           timeout=SLOW_TIMEOUT, retries=1) or {}
    except ClipError as e:
        if e.kind == "network":
            e.help_lines = [
                "The outcome is unknown and Kaloclip does not deduplicate this call — run "
                f"`clip character list --name '{name}'` first and create it again only if it is not there",
            ]
        raise
    return _emit_character("character", data, opts)


def character_voice(cfg, opts, args):
    character = common.asset_id(args[0], "character_id")
    voice = common.asset_id(opts.get("voice"), "--voice")
    if (voice is None) == (not opts.get("clear")):
        raise UsageError("pass exactly one of --voice <voice_id> (bind or replace) or --clear (unbind)",
                         ["Voices come from `clip voice list`"])
    data = api.request(cfg, "PUT", "/character-assets/voice", params={"assetId": character},
                       body={"voiceAssetId": voice}) or {}
    return _emit_character("character", data, opts)


# --- voices ----------------------------------------------------------------------

def voice_list(cfg, opts, args):
    page = opts.get("page") or 1
    params = {"pageNo": page, "pageSize": opts.get("page_size") or PAGE_DEFAULT}
    data = api.request(cfg, "GET", "/voice-assets", params=params) or {}
    if opts.get("json"):
        render.emit_json(data)
        return 0
    items = [v for v in data.get("data") or [] if isinstance(v, dict)]
    if not items:
        render.emit_empty("voices", f"page {page}, {data.get('total') or 0} in total", [
            f"Clone the user's voice from a 15-20s recording: `clip voice clone --name <NAME> --language en "
            f"--gender female --audio sample.m4a` ({CLONE_CREDITS} credits); voices favourited on the Kaloclip "
            "website show up here too",
        ])
        return 0
    rows = [{
        "voice_id": v.get("id"), "name": v.get("name"), "source": v.get("source"), "gender": v.get("gender"),
        "languages": ",".join(v.get("languages") or []) or None, "preview": v.get("previewAudioUrl"),
    } for v in items]
    render.emit_table("voices", rows, ("voice_id", "name", "source", "gender", "languages", "preview"))
    render.emit_help(_page(data, page, params, "voices") + [
        "Bind one to a character (`clip character voice <character_id> --voice <voice_id>`), or pass "
        f"--voice <voice_id> to `clip video create` (models {'/'.join(common.CHARACTER_MODELS)})",
    ])
    return 0


def voice_clone(cfg, opts, args):
    common.need(opts, "--name", "--language", "--gender", "--audio")
    name = opts["name"].strip()
    if not 1 <= len(name) <= VOICE_NAME_MAX:
        raise UsageError(f"--name must be 1-{VOICE_NAME_MAX} characters, got {len(name)}")
    audio = Path(opts["audio"]).expanduser()
    if not audio.is_file():
        raise UsageError(f"--audio: no such file: {opts['audio']}")
    if audio.suffix.lower() not in AUDIO_TYPES:
        raise UsageError(f"--audio {opts['audio']}: only {'/'.join(sorted(t[1:] for t in AUDIO_TYPES))} files")
    if audio.stat().st_size > AUDIO_MAX_BYTES:
        raise UsageError(f"--audio is {audio.stat().st_size // (1024 * 1024)} MB; the limit is 20 MB")
    form = {"creditSourceType": common.CREDIT_SOURCE, "name": name, "language": opts["language"],
            "gender": opts["gender"]}
    api.require_auth(cfg)
    if not opts.get("yes"):
        preview = {"method": "POST", "path": "/voice-assets/clone", "credits": CLONE_CREDITS,
                   "form": {**form, "audio": str(audio)}}
        if opts.get("json"):
            render.emit_json({"dry_run": preview})
        else:
            render.emit_detail("dry_run", preview)
            render.emit_help([
                "Nothing was sent and no credits were spent. The recording must be 15-20 seconds of one clear "
                "voice. If the user asked for this clone and `clip credit` covers it, rerun the same command "
                "with --yes; ask them first if the balance is short or they asked to approve costs",
            ])
        return 0
    try:
        # deduplicated upstream by form + audio content, but a resend after an unclear failure can bill again
        data = api.request(cfg, "POST", "/voice-assets/clone", files=[("audio", audio)], form=form,
                           timeout=SLOW_TIMEOUT, retries=1) or {}
    except ClipError as e:
        if e.kind == "network":
            e.help_lines = [
                "The outcome is unknown (Kaloclip keeps the credits until it is checked) — run `clip voice list` "
                "first; if the voice is not there, rerun the identical command with the same recording, never "
                "a different one",
            ]
        raise
    if opts.get("json"):
        render.emit_json(data)
        return 0
    render.emit_detail("voice", common.compact({
        "voice_id": data.get("id"), "name": data.get("name"), "source": data.get("source"),
        "gender": data.get("gender"), "languages": data.get("languages"), "preview": data.get("previewAudioUrl"),
    }))
    render.emit_help([
        f"Bind it: `clip character voice <character_id> --voice {data.get('id')}`, or pass --voice {data.get('id')} "
        "to `clip video create`",
    ])
    return 0


COMMANDS = [
    Command(
        path="character list",
        summary="Characters (digital avatars) of the account, to appear in videos via --character (free)",
        handler=character_list,
        flags=[
            Flag("--category", "MODEL (people, default) | ANIMAL", choices=CATEGORIES, metavar="CATEGORY"),
            Flag("--name", "filter by name (substring)", metavar="TEXT"),
            *_page_flags(),
        ],
        examples=["clip character list", "clip character list --category ANIMAL"],
    ),
    Command(
        path="character get",
        summary="One character: images, intro, bound voice (free)",
        handler=character_get,
        positional="character_id",
        pos_min=1,
        pos_max=1,
        examples=["clip character get 4521"],
    ),
    Command(
        path="character create",
        summary="Create a character from photos of a person or pet (free, but capped per membership; "
                "takes up to 2 minutes)",
        handler=character_create,
        flags=[
            Flag("--name", f"character name (1-{NAME_MAX} chars)", metavar="TEXT"),
            Flag("--category", "MODEL (person) | ANIMAL", default="MODEL", choices=CATEGORIES, metavar="CATEGORY"),
            Flag("--main-image", "front-view photo file (JPEG/PNG/GIF/WebP, ≤5MB)", metavar="PATH"),
            Flag("--other-image", f"another angle (repeat, ≤{OTHER_IMAGES_MAX})", kind="multi", default=[],
                 metavar="PATH"),
            Flag("--intro", f"personal traits the videos should keep (≤{INTRO_MAX} chars)", metavar="TEXT"),
        ],
        examples=["clip character create --name Mia --main-image front.png --other-image side.png "
                  "--intro 'warm, energetic, late 20s'"],
    ),
    Command(
        path="character voice",
        summary="Bind, replace (--voice) or remove (--clear) the voice a character speaks with (free)",
        handler=character_voice,
        flags=[
            Flag("--voice", "voice id from `clip voice list`", metavar="ID"),
            Flag("--clear", "unbind the current voice", kind="flag", default=False),
        ],
        positional="character_id",
        pos_min=1,
        pos_max=1,
        examples=["clip character voice 4521 --voice 88", "clip character voice 4521 --clear"],
    ),
    Command(
        path="voice list",
        summary="Voices of the account: cloned ones and system voices favourited on the website (free)",
        handler=voice_list,
        flags=_page_flags(),
        examples=["clip voice list"],
    ),
    Command(
        path="voice clone",
        summary=f"Clone a voice from a 15-20s recording ({CLONE_CREDITS} credits; takes up to 2 minutes)",
        handler=voice_clone,
        flags=[
            Flag("--name", f"voice name (≤{VOICE_NAME_MAX} chars)", metavar="TEXT"),
            Flag("--language", "language spoken in the recording, e.g. en, zh", metavar="LANG"),
            Flag("--gender", "male | female", choices=GENDERS, metavar="GENDER"),
            Flag("--audio", "recording, 15-20s, ≤20MB: mp3/wav/m4a/aac/webm/ogg/mp4", metavar="PATH"),
            common.yes_flag(),
        ],
        examples=["clip voice clone --name 'Mia voice' --language en --gender female --audio sample.m4a"],
        writes=True,
    ),
]
