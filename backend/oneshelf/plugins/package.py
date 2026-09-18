"""Load and statically validate .osp packages (Master §9.3, §10 steps 3–6, §11).

Nothing in a package is executed. Validation covers the archive (types, symlinks, names, sizes), YAML
safety, strict schemas, and cross-file consistency (domains, capabilities, browser, auth, templates,
packaged test fixtures). The resulting permission set drives install/update review.
"""
from __future__ import annotations

import hashlib
import posixpath
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import ValidationError

from oneshelf.integrity.validators import _unsafe_entry_name
from oneshelf.net.domains import host_allowed
from oneshelf.plugins.schema import FIELDS, LIST_CAPABILITIES, Manifest, Recipe, SourceConfig, TestSuite
from oneshelf.plugins.templates import TemplateError, validate_url_template
from oneshelf.plugins.yamlsafe import YamlError, load_yaml

MAX_ENTRIES = 300
MAX_PACKAGE_BYTES = 20 * 1024**2
MAX_FILE_BYTES = 5 * 1024**2
ALLOWED_EXTENSIONS = {".yaml", ".yml", ".json", ".html", ".htm", ".xml", ".txt", ".webp", ".png", ".jpg", ".jpeg"}


class PackageError(ValueError):
    pass


@dataclass(frozen=True)
class PluginPackage:
    manifest: Manifest
    source: SourceConfig
    recipes: dict[str, Recipe]
    tests: TestSuite
    files: dict[str, bytes]
    permissions: frozenset[str]
    sha256: str

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def version(self) -> str:
        return self.manifest.version


def _read_archive(path: Path) -> dict[str, bytes]:
    try:
        size = path.stat().st_size
        if size > MAX_PACKAGE_BYTES:
            raise PackageError("package too large")
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise PackageError("not a valid .osp archive") from exc
    files: dict[str, bytes] = {}
    with z:
        infos = z.infolist()
        if len(infos) > MAX_ENTRIES:
            raise PackageError("too many files in package")
        total = 0
        for info in infos:
            name = info.filename
            if _unsafe_entry_name(name):
                raise PackageError(f"unsafe file name in package: {name!r}")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise PackageError(f"symlink entries are not allowed: {name!r}")
            if info.is_dir():
                continue
            if posixpath.splitext(name)[1].lower() not in ALLOWED_EXTENSIONS:
                raise PackageError(f"file type not allowed in declarative packages: {name!r}")
            if info.file_size > MAX_FILE_BYTES:
                raise PackageError(f"file too large: {name!r}")
            total += info.file_size
            if total > MAX_PACKAGE_BYTES:
                raise PackageError("package uncompressed size too large")
            files[name] = z.read(info)
    return files


def _yaml(files: dict[str, bytes], name: str):
    if name not in files:
        raise PackageError(f"missing required file: {name}")
    try:
        return load_yaml(files[name])
    except YamlError as exc:
        raise PackageError(f"{name}: {exc}") from exc


def _model(model, data, name):
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(p) for p in first["loc"])
        raise PackageError(f"{name}: {location}: {first['msg']}") from exc


def _url_allowed(url: str, manifest: Manifest, *, include_cdn: bool) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    schemes = {"https", "http"} if manifest.network.allow_http else {"https"}
    if parts.scheme not in schemes or not parts.hostname or parts.username or parts.password:
        return False
    rules = list(manifest.network.domains) + (list(manifest.network.cdn_domains) if include_cdn else [])
    return host_allowed(parts.hostname, rules)


def _derive_permissions(manifest: Manifest) -> frozenset[str]:
    perms = {f"network:domain:{d}" for d in manifest.network.domains}
    perms |= {f"network:cdn:{d}" for d in manifest.network.cdn_domains}
    if manifest.network.allow_http:
        perms.add("network:http")
    perms |= {f"browser:{c}" for c in manifest.browser.capabilities}
    if manifest.auth:
        perms |= {f"session:required:{c}" for c in manifest.auth.required_for}
        perms |= {f"session:optional:{c}" for c in manifest.auth.optional_for}
    return frozenset(perms)


def validate_templates(extract, *, capability: str, inputs: list[str]) -> None:
    """A template may only use document values, the current item and the recipe's own inputs."""
    from oneshelf.plugins.runtime import template_names

    known = set(extract.values) | {"item"} | set(inputs)
    for name, spec in extract.fields.items():
        if spec.template is None:
            continue
        unknown = sorted(template_names(spec.template) - known)
        if unknown:
            raise PackageError(f"recipes/{capability}: template for {name!r} uses unknown names {unknown}")
    for value_name, spec in extract.values.items():
        if spec.template is not None:
            raise PackageError(f"recipes/{capability}: value {value_name!r} must read the document, not a template")


def _cross_validate(manifest: Manifest, source: SourceConfig, recipes: dict[str, Recipe], tests: TestSuite,
                    files: dict[str, bytes]) -> None:
    declared = set(manifest.capabilities)
    if not _url_allowed(source.base_url, manifest, include_cdn=False):
        raise PackageError("source.yaml: base_url must use https (or declared http) on an allowlisted domain")
    missing = declared - set(recipes)
    if missing:
        raise PackageError(f"declared capabilities without a recipe: {sorted(missing)}")
    browser_caps = set(manifest.browser.capabilities)
    if not browser_caps <= declared:
        raise PackageError("browser capabilities must be declared capabilities")
    auth = manifest.auth
    if auth is not None:
        if not _url_allowed(auth.login_url, manifest, include_cdn=False):
            raise PackageError("auth.login_url must be on an allowlisted source domain")
        for rule in auth.session_domains:
            if rule not in manifest.network.domains:
                raise PackageError("auth.session_domains must be listed in network.domains (not CDN domains)")
        if not set(auth.required_for) | set(auth.optional_for) <= declared:
            raise PackageError("auth capabilities must be declared capabilities")
    required_caps = set(auth.required_for) if auth else set()
    optional_caps = set(auth.optional_for) if auth else set()

    for capability, recipe in recipes.items():
        if (recipe.request.fetch == "browser") != (capability in browser_caps):
            raise PackageError(f"recipes/{capability}: browser fetch must match manifest.browser declaration")
        expected_auth = "required" if capability in required_caps else "optional" if capability in optional_caps else "none"
        if recipe.request.auth != expected_auth:
            raise PackageError(f"recipes/{capability}: auth mode {recipe.request.auth!r} does not match manifest.auth")
        try:
            validate_url_template(recipe.request.url, set(recipe.inputs))
            for value in (recipe.request.form or {}).values():
                validate_url_template("{base_url}" + value if not value.startswith("{base_url}") else value,
                                      set(recipe.inputs))
        except TemplateError as exc:
            raise PackageError(f"recipes/{capability}: {exc}") from exc
        # A recipe may follow a URL the source's own catalog produced (§8); the egress policy still
        # decides whether that URL may be fetched, so nothing is widened here.
        follows_source_url = recipe.request.url.startswith("{url}")
        if not recipe.request.url.startswith("{base_url}") and not follows_source_url and not _url_allowed(
            recipe.request.url.split("{", 1)[0] or "x", manifest, include_cdn=True
        ):
            raise PackageError(f"recipes/{capability}: request origin is not allowlisted")
        if recipe.request.form is not None and recipe.request.method != "POST":
            raise PackageError(f"recipes/{capability}: form body requires POST")
        allowed_fields = FIELDS[capability]
        for field in recipe.extract.fields:
            if field not in allowed_fields:
                raise PackageError(f"recipes/{capability}: unknown field {field!r}")
        for field, required in allowed_fields.items():
            if required and field not in recipe.extract.fields:
                raise PackageError(f"recipes/{capability}: required field {field!r} is not extracted")
        is_list = capability in LIST_CAPABILITIES
        if is_list != (recipe.extract.items is not None):
            raise PackageError(f"recipes/{capability}: items selector {'required' if is_list else 'not allowed'}")
        if not is_list and recipe.pagination.mode != "none":
            raise PackageError(f"recipes/{capability}: pagination only applies to list capabilities")

    for index, case in enumerate(tests.cases):
        if case.capability not in declared:
            raise PackageError(f"tests: case {index} uses undeclared capability {case.capability!r}")
        for fixture in case.fixtures:
            if not _url_allowed(fixture.url, manifest, include_cdn=True):
                raise PackageError(f"tests: case {index} fixture URL is not allowlisted")
            if f"tests/{fixture.file}" not in files:
                raise PackageError(f"tests: case {index} fixture file missing: {fixture.file}")


def load_package(path: str | Path) -> PluginPackage:
    path = Path(path)
    files = _read_archive(path)
    manifest = _model(Manifest, _yaml(files, "manifest.yaml"), "manifest.yaml")
    source = _model(SourceConfig, _yaml(files, "source.yaml"), "source.yaml")
    recipes: dict[str, Recipe] = {}
    for name in sorted(files):
        if name.startswith("recipes/") and name.endswith((".yaml", ".yml")):
            recipe = _model(Recipe, _yaml(files, name), name)
            if recipe.capability not in manifest.capabilities:
                raise PackageError(f"{name}: capability {recipe.capability!r} is not declared in the manifest")
            if recipe.capability in recipes:
                raise PackageError(f"{name}: duplicate recipe for {recipe.capability!r}")
            recipes[recipe.capability] = recipe
    if "tests/tests.yaml" not in files:
        raise PackageError("missing required file: tests/tests.yaml (packaged tests are mandatory)")
    tests = _model(TestSuite, _yaml(files, "tests/tests.yaml"), "tests/tests.yaml")
    _cross_validate(manifest, source, recipes, tests, files)
    return PluginPackage(
        manifest=manifest, source=source, recipes=recipes, tests=tests, files=files,
        permissions=_derive_permissions(manifest), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
