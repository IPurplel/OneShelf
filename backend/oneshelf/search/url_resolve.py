"""Direct URL entry (Master §8): an alternate discovery path, not a separate extraction architecture.

A pasted URL is matched against the declared url_patterns of installed, active plugins whose domains
cover the URL host. Resolution then uses the plugin's normal capabilities (so session scoping and network
policy still apply) and the same matching/grouping rules as search. Nothing is persisted by a preview.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from urllib.parse import urlsplit

from oneshelf.net.domains import host_allowed, to_ascii_host
from oneshelf.net.governor import Priority
from oneshelf.plugins.manager import PluginManager, PluginUnavailable
from oneshelf.plugins.package import PluginPackage
from oneshelf.plugins.results import WorkDetails
from oneshelf.plugins.transforms import TransformError, _compile
from oneshelf.search.grouping import LiveListing, ResultWork, group_results


class UnsupportedUrl(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedUrl:
    plugin_id: str
    capability: str
    identifier: str
    url: str
    package: PluginPackage


@dataclass(frozen=True)
class UrlPreview:
    resolved: ResolvedUrl
    result: ResultWork
    details: WorkDetails | None


def resolve_url(plugins: PluginManager, url: str) -> ResolvedUrl:
    try:
        parts = urlsplit(url)
        host = to_ascii_host(parts.hostname or "")
    except ValueError as exc:
        raise UnsupportedUrl(f"not a usable URL: {url!r}") from exc
    if parts.scheme not in ("http", "https") or not host:
        raise UnsupportedUrl("only http(s) source URLs can be opened")
    for record in plugins.list():
        if record.state != "active":
            continue
        try:
            package = plugins.load_active(record.id)
        except PluginUnavailable:
            continue
        network = package.manifest.network
        if not host_allowed(host, list(network.domains) + list(network.cdn_domains)):
            continue
        for pattern in package.source.url_patterns:
            try:
                match = _compile(pattern.pattern).search(url)
            except TransformError:
                continue
            if match is None:
                continue
            identifier = match.group(pattern.id_group)
            if identifier:
                return ResolvedUrl(record.id, pattern.capability, identifier, url, package)
    raise UnsupportedUrl("no installed source recognises this URL")


class UrlResolver:
    def __init__(self, conn: sqlite3.Connection, plugins: PluginManager, sources) -> None:
        self.conn = conn
        self.plugins = plugins
        self.sources = sources

    async def preview(self, url: str) -> UrlPreview:
        resolved = resolve_url(self.plugins, url)
        details: WorkDetails | None = None
        if "work" in resolved.package.recipes:
            details = await self.sources.run(resolved.plugin_id, "work", {"listing_key": resolved.identifier},
                                             priority=Priority.INTERACTIVE)
        listing = LiveListing(
            source_id=resolved.plugin_id, listing_key=resolved.identifier,
            title=details.title if details else resolved.identifier, url=url,
            content_type=details.content_type if details else None,
            language=(details.language if details else None) or resolved.package.manifest.defaults.language,
            cover_url=details.cover_url if details else None, creator=details.creator if details else None,
            original_title=details.original_title if details else None,
        )
        return UrlPreview(resolved, group_results(self.conn, [listing])[0], details)
