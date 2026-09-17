"""Single registry of approved defaults (Master §42 and defaults specified elsewhere).

Every layer (runtime, API, UI, migrations) must read defaults from here rather than
re-declaring values (Meta Prompt D2).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal

GiB = 1024**3
MiB = 1024**2


@dataclass(frozen=True)
class BackupDefaults:
    library_interval: timedelta = timedelta(days=7)
    full_backup_automatic: bool = False
    retain_verified: int = 4


@dataclass(frozen=True)
class CacheDefaults:
    ttl: timedelta
    cap_bytes: int


@dataclass(frozen=True)
class AutoDownloadDefaults:
    enabled: bool = False
    engagement_threshold: float = 0.12
    read_ahead_units: int = 5


@dataclass(frozen=True)
class ReaderDefaults:
    auto_mark_read_threshold: float = 0.97
    smart_controls_hide_after: timedelta = timedelta(seconds=3)
    remember_per_work: bool = True
    preload_next: int = 7
    preload_previous: int = 4


@dataclass(frozen=True)
class DownloadDefaults:
    http_concurrency: int = 4
    browser_concurrency: int = 1
    max_retries: int = 3
    fallback_mode: Literal["preferred_ask", "strict", "automatic"] = "preferred_ask"


@dataclass(frozen=True)
class FollowDefaults:
    check_interval: timedelta = timedelta(hours=12)
    jitter: timedelta = timedelta(minutes=45)


@dataclass(frozen=True)
class NotificationDefaults:
    resolved_visible_for: timedelta = timedelta(hours=1)
    history_max_age: timedelta = timedelta(days=30)
    history_max_entries: int = 500


@dataclass(frozen=True)
class ExportDefaults:
    activity_max_age: timedelta = timedelta(days=30)
    activity_max_jobs: int = 100
    default_output: Literal["folder", "zip"] = "folder"


@dataclass(frozen=True)
class ImportDefaults:
    default_mode: Literal["copy", "move"] = "copy"


@dataclass(frozen=True)
class DiagnosticsDefaults:
    max_age: timedelta = timedelta(days=7)
    max_bytes: int = 100 * MiB


@dataclass(frozen=True)
class StorageDefaults:
    reserve_fraction: float = 0.05
    reserve_cap_bytes: int = 5 * GiB
    warning_multiplier: int = 2


@dataclass(frozen=True)
class StagingDefaults:
    success_leftover_ttl: timedelta = timedelta(hours=24)
    resumable_partial_ttl: timedelta = timedelta(days=7)


@dataclass(frozen=True)
class CatalogDefaults:
    suspicious_loss_fraction: float = 0.5
    suspicious_min_units_lost: int = 5


@dataclass(frozen=True)
class AuthDefaults:
    local_auth_enabled: bool = False
    lan_auth_enabled: bool = False
    remote_session_lifetime: timedelta = timedelta(days=30)


@dataclass(frozen=True)
class Defaults:
    backup: BackupDefaults = field(default_factory=BackupDefaults)
    discovery_cache: CacheDefaults = field(
        default_factory=lambda: CacheDefaults(ttl=timedelta(days=7), cap_bytes=250 * MiB)
    )
    reader_cache: CacheDefaults = field(
        default_factory=lambda: CacheDefaults(ttl=timedelta(days=7), cap_bytes=5 * GiB)
    )
    auto_download: AutoDownloadDefaults = field(default_factory=AutoDownloadDefaults)
    reader: ReaderDefaults = field(default_factory=ReaderDefaults)
    downloads: DownloadDefaults = field(default_factory=DownloadDefaults)
    follow: FollowDefaults = field(default_factory=FollowDefaults)
    notifications: NotificationDefaults = field(default_factory=NotificationDefaults)
    export: ExportDefaults = field(default_factory=ExportDefaults)
    importing: ImportDefaults = field(default_factory=ImportDefaults)
    diagnostics: DiagnosticsDefaults = field(default_factory=DiagnosticsDefaults)
    storage: StorageDefaults = field(default_factory=StorageDefaults)
    staging: StagingDefaults = field(default_factory=StagingDefaults)
    catalog: CatalogDefaults = field(default_factory=CatalogDefaults)
    auth: AuthDefaults = field(default_factory=AuthDefaults)


DEFAULTS = Defaults()
