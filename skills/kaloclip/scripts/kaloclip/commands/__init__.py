"""Command registry: every module contributes Command objects."""

from __future__ import annotations

from ..core import Command
from . import assets, characters, creation, meta

COMMANDS: list[Command] = []
for _mod in (assets, characters, creation, meta):
    COMMANDS.extend(_mod.COMMANDS)

# noun -> default subcommand when invoked bare
DEFAULT_SUB = {"config": "show", "asset": "list", "character": "list", "voice": "list"}

ALIASES = {
    "assets": "asset",
    "characters": "character",
    "voices": "voice",
    "credits": "credit",
    "images": "image",
    "products": "product",
    "scripts": "script",
    "videos": "video",
    "jobs": "job",
}
