"""Load runbook YAML and check it against the JSON Schema."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from rehearse.locate import schema_path
from rehearse.models import (
    Asset,
    Contact,
    Owner,
    Precondition,
    Review,
    Runbook,
    Step,
)

MAX_YAML_BYTES = 1_048_576

HOST_RE = re.compile(
    r"^(localhost|"
    r"((25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\.){3}"
    r"(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])|"
    r"([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*)$"
)
URL_RE = re.compile(r"^https?://[^\s]+$")
LOCAL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


class LoadError(Exception):
    def __init__(self, path: Path, messages: list[str]):
        self.path = path
        self.messages = messages
        super().__init__(f"{path}: {messages[0] if messages else 'invalid runbook'}")


class RunbookLoader(yaml.SafeLoader):
    """Safe YAML loader that keeps dates as strings and rejects aliases."""


RunbookLoader.yaml_implicit_resolvers = {
    key: [
        (tag, pattern)
        for tag, pattern in patterns
        if tag != "tag:yaml.org,2002:timestamp"
    ]
    for key, patterns in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _construct_mapping(loader: RunbookLoader, node, deep: bool = False):
    if not isinstance(node, yaml.MappingNode):
        raise yaml.YAMLError("expected a mapping")
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.YAMLError(f"duplicate key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


def _compose_node(loader: RunbookLoader, parent, index):
    if loader.check_event(yaml.events.AliasEvent):
        raise yaml.YAMLError("YAML anchors and aliases are not allowed in runbooks")
    event = loader.peek_event()
    if getattr(event, "anchor", None):
        raise yaml.YAMLError("YAML anchors and aliases are not allowed in runbooks")
    return yaml.SafeLoader.compose_node(loader, parent, index)


RunbookLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)
RunbookLoader.compose_node = _compose_node  # type: ignore[method-assign]


def load_schema() -> dict:
    import json

    raw = schema_path().read_text(encoding="utf-8")
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    return schema


_VALIDATOR: Draft202012Validator | None = None


def validator() -> Draft202012Validator:
    global _VALIDATOR
    if _VALIDATOR is None:
        try:
            schema = load_schema()
        except SchemaError as exc:
            raise LoadError(schema_path(), [f"bundled schema is invalid: {exc}"]) from exc
        _VALIDATOR = Draft202012Validator(
            schema,
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )
    return _VALIDATOR


def _normalize(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def parse_yaml(text: str):
    try:
        loaded = yaml.load(text, Loader=RunbookLoader)
    except yaml.YAMLError as exc:
        raise ValueError(str(exc).strip()) from exc
    if loaded is None:
        raise ValueError("document is empty")
    if not isinstance(loaded, dict):
        raise ValueError("document must be a mapping")
    return _normalize(loaded)


def discover_runbooks(path: Path) -> list[Path]:
    path = path.expanduser()
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(path)
    found: list[Path] = []
    for pattern in ("*.yaml", "*.yml"):
        for candidate in sorted(path.rglob(pattern)):
            if candidate.name in {"rehearse.yaml", "rehearse.yml"}:
                continue
            if any(part.startswith(".") for part in candidate.relative_to(path).parts):
                continue
            found.append(candidate)
    return found


def load_runbook(path: Path) -> Runbook:
    path = path.resolve()
    if not path.is_file():
        raise LoadError(path, ["file not found"])
    raw_bytes = path.read_bytes()
    if len(raw_bytes) > MAX_YAML_BYTES:
        raise LoadError(path, [f"runbook is larger than {MAX_YAML_BYTES} bytes"])
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LoadError(path, [f"runbook is not UTF-8: {exc}"]) from exc
    try:
        document = parse_yaml(text)
    except ValueError as exc:
        raise LoadError(path, [str(exc)]) from exc

    messages = [
        f"{error.json_path}: {error.message}"
        for error in sorted(validator().iter_errors(document), key=lambda item: item.json_path)
    ]
    messages.extend(_structural_messages(document))
    if messages:
        raise LoadError(path, messages[:20] if len(messages) > 20 else messages)

    digest = hashlib.sha256(raw_bytes).hexdigest()
    return _to_runbook(path, document, digest)


def _structural_messages(document: dict) -> list[str]:
    messages: list[str] = []
    review = document.get("review") or {}
    if isinstance(review, dict):
        interval = review.get("intervalDays")
        max_age = review.get("maxAgeDays")
        if isinstance(interval, int) and isinstance(max_age, int) and max_age < interval:
            messages.append("$.review: maxAgeDays is shorter than intervalDays")

    seen: set[str] = set()
    orders: set[int] = set()
    for index, contact in enumerate(document.get("contacts") or []):
        if not isinstance(contact, dict):
            continue
        order = contact.get("escalationOrder")
        if isinstance(order, int):
            if order in orders:
                messages.append(f"$.contacts[{index}]: duplicate escalationOrder {order}")
            orders.add(order)

    def take(kind: str, index: int, local_id: object) -> None:
        if not isinstance(local_id, str):
            return
        if local_id in seen:
            messages.append(f"{kind}[{index}]: duplicate id {local_id!r}")
        elif not LOCAL_ID_RE.fullmatch(local_id):
            messages.append(f"{kind}[{index}]: id {local_id!r} does not match {LOCAL_ID_RE.pattern}")
        else:
            seen.add(local_id)

    for index, item in enumerate(document.get("preconditions") or []):
        if isinstance(item, dict):
            take("$.preconditions", index, item.get("id"))
    for step_index, step in enumerate(document.get("steps") or []):
        if not isinstance(step, dict):
            continue
        take("$.steps", step_index, step.get("id"))
        for asset_index, asset in enumerate(step.get("assets") or []):
            if not isinstance(asset, dict):
                continue
            take(f"$.steps[{step_index}].assets", asset_index, asset.get("id"))
            messages.extend(_asset_messages(step_index, asset_index, asset))
    return messages


def _asset_messages(step_index: int, asset_index: int, asset: dict) -> list[str]:
    prefix = f"$.steps[{step_index}].assets[{asset_index}]"
    kind = asset.get("kind")
    target = asset.get("target")
    messages: list[str] = []
    if kind == "host":
        if not isinstance(target, str) or not HOST_RE.fullmatch(target) or len(target) > 253:
            messages.append(f"{prefix}.target: host must be a hostname, localhost, or IPv4 address")
    elif kind == "url":
        if not isinstance(target, str) or not URL_RE.fullmatch(target):
            messages.append(f"{prefix}.target: url must start with http:// or https:// and contain no spaces")
        elif _url_has_userinfo(target):
            messages.append(f"{prefix}.target: remove credentials from the URL")
    elif kind == "script" and not asset.get("language"):
        messages.append(f"{prefix}: script assets require language")
    if asset.get("port") is not None and kind != "host":
        messages.append(f"{prefix}.port: port is only valid on a host asset")
    if asset.get("language") is not None and kind != "script":
        messages.append(f"{prefix}.language: language is only valid on a script asset")
    if asset.get("directory") is not None and kind != "group":
        messages.append(f"{prefix}.directory: directory is only valid on a group asset")
    return messages


def _url_has_userinfo(target: str) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(target)
    return bool(parsed.username or parsed.password)


def _to_runbook(path: Path, document: dict, digest: str) -> Runbook:
    owner = document["owner"]
    review = document["review"]
    return Runbook(
        path=path,
        schema_version=document["schemaVersion"],
        id=document["id"],
        title=document["title"],
        summary=document["summary"].strip(),
        execution=document["execution"],
        owner=Owner(
            name=owner["name"],
            email=owner["email"],
            team=owner.get("team"),
        ),
        service=document["service"],
        severity=document["severity"],
        frameworks=list(document.get("frameworks") or []),
        review=Review(
            last_reviewed=date.fromisoformat(review["lastReviewed"]),
            interval_days=review["intervalDays"],
            max_age_days=review["maxAgeDays"],
        ),
        contacts=[
            Contact(
                name=item["name"],
                role=item["role"],
                email=item["email"],
                phone=item.get("phone"),
                escalation_order=item.get("escalationOrder"),
            )
            for item in document["contacts"]
        ],
        preconditions=[
            Precondition(
                id=item["id"],
                description=item["description"].strip(),
                evidence=item.get("evidence"),
            )
            for item in document["preconditions"]
        ],
        steps=[_to_step(item) for item in document["steps"]],
        reviewed_by=document.get("reviewedBy"),
        sha256=digest,
    )


def _to_step(item: dict) -> Step:
    return Step(
        id=item["id"],
        title=item["title"],
        description=item["description"].strip(),
        expected_outcome=item["expectedOutcome"].strip(),
        owner=item.get("owner"),
        duration_minutes=item.get("durationMinutes"),
        prompts=list(item.get("prompts") or []),
        assets=[
            Asset(
                id=asset["id"],
                kind=asset["kind"],
                target=asset["target"],
                port=asset.get("port"),
                language=asset.get("language"),
                directory=asset.get("directory"),
                description=asset.get("description"),
            )
            for asset in item.get("assets") or []
        ],
    )
