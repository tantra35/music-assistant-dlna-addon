"""Typing-only contract shared by the provider mixins.

Mixins sit BEFORE MusicProvider in the final bases, so any member declared
here would shadow the real ProviderBase members. Keep this class EMPTY at
runtime: only TYPE_CHECKING-only declarations of cross-mixin members are
allowed (see the vk_music MRO pitfall: a contract-declared `domain` property
crashed provider load).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging

    from .discovery import ServerRegistry


class ProviderContract:
    """Runtime-empty stub; see module docstring."""

    if TYPE_CHECKING:
        _registry: ServerRegistry
        _track_cache: dict[str, dict]
        _track_parent_hints: dict[str, str]
        logger: logging.Logger
        domain: str
        instance_id: str
