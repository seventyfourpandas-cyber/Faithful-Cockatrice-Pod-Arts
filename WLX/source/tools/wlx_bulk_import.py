#!/usr/bin/env python3
"""Process one persistent, filename-driven WLX card-art batch.

Incoming files live under imports/incoming/<player>/.  The repository itself is
the queue: a cancelled or superseded workflow cannot lose a request because the
image remains committed until a successful publication commit removes it.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable


SOURCE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SOURCE_ROOT.parents[1]
AUTOMATION_DIR = SOURCE_ROOT / "automation"
sys.path.insert(0, str(AUTOMATION_DIR))
import wlxlib  # noqa: E402


SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
IGNORED_INPUT_SUFFIXES = {".txt", ".md"}
UPDATE_RE = re.compile(r"^WLX-(?P<collector>[0-9]{3,})(?:-(?P<face>front|back))?$", re.I)
DEFAULT_CONFIG = Path("bulk_import_config.json")
SCRYFALL_REQUEST_INTERVAL_SECONDS = 0.55
SCRYFALL_RATE_LIMIT_COOLDOWN_SECONDS = 35.0
SCRYFALL_LOOKUP_ATTEMPTS = 3


class BulkImportError(RuntimeError):
    """A fatal batch/repository error. No repository commit should be made."""


class TemporaryServiceError(BulkImportError):
    """A temporary external lookup failure. All inputs stay in incoming."""


@dataclasses.dataclass(frozen=True)
class IncomingFile:
    path: Path
    player: str
    relative_path: str
    stem: str


@dataclasses.dataclass(frozen=True)
class PreparedImage:
    incoming: IncomingFile
    sha256: str
    suffix: str
    width: int
    height: int
    lookup_name: str
    variant: str


@dataclasses.dataclass(frozen=True)
class AddSingle:
    image: PreparedImage
    details: dict[str, Any]


@dataclasses.dataclass(frozen=True)
class AddDoubleFaced:
    player: str
    details: dict[str, Any]
    front: PreparedImage
    back: PreparedImage


@dataclasses.dataclass(frozen=True)
class AddToken:
    image: PreparedImage
    creator_card: str
    token_metadata: dict[str, Any]


@dataclasses.dataclass(frozen=True)
class UpdateArt:
    image: PreparedImage
    collector: str
    face: str


@dataclasses.dataclass
class Plan:
    singles: list[AddSingle] = dataclasses.field(default_factory=list)
    double_faced: list[AddDoubleFaced] = dataclasses.field(default_factory=list)
    tokens: list[AddToken] = dataclasses.field(default_factory=list)
    updates: list[UpdateArt] = dataclasses.field(default_factory=list)
    noops: list[PreparedImage] = dataclasses.field(default_factory=list)
    errors: dict[Path, str] = dataclasses.field(default_factory=dict)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_config(root: Path, config_path: Path) -> dict[str, Any]:
    path = config_path if config_path.is_absolute() else root / config_path
    if not path.is_file() and not config_path.is_absolute():
        path = wlxlib.source_root(root) / config_path
    value = wlxlib.read_json(path)
    required = {
        "schema_version",
        "incoming_dir",
        "needs_attention_dir",
        "report_json",
        "report_markdown",
        "max_images_per_batch",
        "duplicate_separator",
        "token_prefix",
        "player_folders",
    }
    missing = sorted(required - set(value))
    if missing:
        raise BulkImportError(f"{path.name} is missing: {', '.join(missing)}")
    if value["schema_version"] != 1:
        raise BulkImportError(f"Unsupported {path.name} schema_version")
    maximum = int(value["max_images_per_batch"])
    if maximum < 1 or maximum > 100:
        raise BulkImportError("max_images_per_batch must be from 1 through 100")
    folders = value.get("player_folders")
    if not isinstance(folders, dict) or not folders:
        raise BulkImportError("player_folders must be a non-empty object")
    return value


def split_variant(stem: str, separator: str) -> tuple[str, str]:
    if separator and separator in stem:
        requested, variant = stem.split(separator, 1)
        return requested.strip(), variant.strip()
    return stem.strip(), ""


def discover_inputs(root: Path, config: dict[str, Any]) -> list[IncomingFile]:
    incoming_root = root / str(config["incoming_dir"])
    incoming_root.mkdir(parents=True, exist_ok=True)
    folder_map = {
        str(folder).casefold(): str(player)
        for folder, player in dict(config["player_folders"]).items()
    }
    discovered: list[IncomingFile] = []
    for path in sorted(incoming_root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.casefold() in IGNORED_INPUT_SUFFIXES:
            continue
        relative = path.relative_to(incoming_root)
        player = ""
        if len(relative.parts) >= 2:
            player = folder_map.get(relative.parts[0].casefold(), "")
        discovered.append(
            IncomingFile(
                path=path,
                player=player,
                relative_path=relative.as_posix(),
                stem=path.stem.strip(),
            )
        )
    return discovered


def detected_suffix(path: Path) -> str:
    with path.open("rb") as handle:
        signature = handle.read(8)
    if signature.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if signature.startswith(b"\xff\xd8"):
        return ".jpg"
    raise ValueError("The file is not a real PNG or JPEG image")


def prepare_image(
    incoming: IncomingFile,
    *,
    separator: str,
    minimum_width: int,
    minimum_height: int,
    minimum_bytes: int,
    maximum_bytes: int,
) -> PreparedImage:
    if not incoming.player:
        raise ValueError(
            "Put the image inside imports/incoming/alex, will, miguel, or jay; "
            "root-level images are never assigned automatically."
        )
    if incoming.path.suffix.casefold() not in SUPPORTED_IMAGE_SUFFIXES:
        raise ValueError("Only PNG, JPG, and JPEG card images are supported")
    size = incoming.path.stat().st_size
    if size < minimum_bytes:
        raise ValueError(f"The image is suspiciously small ({size} bytes)")
    if size > maximum_bytes:
        raise ValueError(
            f"The image is {size} bytes; the importer limit is {maximum_bytes} bytes"
        )
    suffix = detected_suffix(incoming.path)
    width, height = wlxlib.image_dimensions(incoming.path)
    if width < minimum_width or height < minimum_height:
        raise ValueError(
            f"The image is {width}x{height}; use at least {minimum_width}x{minimum_height}"
        )
    lookup_name, variant = split_variant(incoming.stem, separator)
    if not lookup_name:
        raise ValueError("The filename does not contain a card name")
    return PreparedImage(
        incoming=incoming,
        sha256=wlxlib.sha256_file(incoming.path),
        suffix=suffix,
        width=width,
        height=height,
        lookup_name=lookup_name,
        variant=variant,
    )


def fixture_path(directory: Path, prefix: str, name: str) -> Path:
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
    return directory / f"{prefix}{digest}.json"


def cache_card_details(
    official_cache: dict[str, Any], requested: str, details: dict[str, Any]
) -> None:
    aliases = {requested.casefold(), str(details.get("name", "")).casefold()}
    faces = details.get("faces")
    if isinstance(faces, list):
        aliases.update(
            str(face.get("official_name", "")).casefold()
            for face in faces
            if isinstance(face, dict)
        )
    for alias in aliases:
        if alias:
            official_cache["cards"][alias] = details


def scryfall_retry_delay(error: wlxlib.WlxError, attempt: int) -> float:
    """Return a safe retry delay for Scryfall's named-card endpoint."""
    if re.search(r"\bHTTP\s+429\b", str(error), flags=re.I):
        return SCRYFALL_RATE_LIMIT_COOLDOWN_SECONDS
    return float(2**attempt)


def official_details(
    requested: str,
    project: dict[str, Any],
    official_cache: dict[str, Any],
    fixture_dir: Path | None,
) -> dict[str, Any]:
    cached = official_cache["cards"].get(requested.casefold())
    if isinstance(cached, dict) and str(cached.get("name", "")).strip():
        return cached
    if fixture_dir is not None:
        path = fixture_path(fixture_dir, "", requested)
        if not path.exists():
            raise ValueError(f"No exact official Magic card named {requested!r} was found")
        details = wlxlib.read_json(path)
    else:
        final_error = ""
        details: dict[str, Any] | None = None
        for attempt in range(SCRYFALL_LOOKUP_ATTEMPTS):
            try:
                details = wlxlib.scryfall_exact(requested, project)
                final_error = ""
                break
            except wlxlib.WlxError as exc:
                final_error = str(exc)
                if attempt < SCRYFALL_LOOKUP_ATTEMPTS - 1:
                    delay = scryfall_retry_delay(exc, attempt)
                    if delay == SCRYFALL_RATE_LIMIT_COOLDOWN_SECONDS:
                        print(
                            f"Scryfall rate limit reached while checking {requested!r}; "
                            f"waiting {delay:g} seconds before retry "
                            f"{attempt + 2} of {SCRYFALL_LOOKUP_ATTEMPTS}.",
                            flush=True,
                        )
                    time.sleep(delay)
        if final_error:
            raise TemporaryServiceError(
                f"Could not verify {requested!r} after three attempts: {final_error}"
            )
        if details is None:
            raise ValueError(f"No exact official Magic card named {requested!r} was found")
        # /cards/named is limited to two requests per second.  A small buffer
        # keeps large batches safely below that boundary, including network jitter.
        time.sleep(SCRYFALL_REQUEST_INTERVAL_SECONDS)
    if not isinstance(details, dict) or not str(details.get("name", "")).strip():
        raise TemporaryServiceError("The official-card lookup returned malformed data")
    cache_card_details(official_cache, requested, details)
    return details


def token_details(
    creator: str,
    project: dict[str, Any],
    fixture_dir: Path | None,
) -> dict[str, Any]:
    if fixture_dir is not None:
        path = fixture_path(fixture_dir, "token-", creator)
        if not path.exists():
            raise ValueError(f"No unambiguous Cockatrice token is linked to {creator!r}")
        return wlxlib.read_json(path)
    final_error = ""
    for attempt in range(3):
        try:
            return wlxlib.verify_official_token_for_creator(creator, project)
        except wlxlib.WlxError as exc:
            final_error = str(exc)
            if "no official token" in final_error or "creates more than one" in final_error:
                raise ValueError(final_error) from exc
            if attempt < 2:
                time.sleep(2**attempt)
    raise TemporaryServiceError(
        f"Could not verify the token for {creator!r} after three attempts: {final_error}"
    )


def all_existing_hashes(catalogs: dict[str, dict[str, Any]]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for catalog in catalogs.values():
        for printing in catalog["printings"]:
            collector = str(printing.get("collector_number", ""))
            faces = printing.get("faces")
            if isinstance(faces, list):
                for face in faces:
                    if isinstance(face, dict) and face.get("image_sha256"):
                        hashes[str(face["image_sha256"])] = (
                            f"WLX #{collector}-{face.get('side', 'face')}"
                        )
            elif printing.get("image_sha256"):
                hashes[str(printing["image_sha256"])] = f"WLX #{collector}"
    return hashes


def existing_official_names(catalogs: dict[str, dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for catalog in catalogs.values():
        for printing in catalog["printings"]:
            faces = printing.get("faces")
            if isinstance(faces, list):
                names.update(
                    str(face.get("official_name", "")).casefold()
                    for face in faces
                    if isinstance(face, dict)
                )
            elif printing.get("official_name"):
                names.add(str(printing["official_name"]).casefold())
    return {name for name in names if name}


def printing_and_hash(
    catalogs: dict[str, dict[str, Any]], collector: str, face: str
) -> tuple[str, dict[str, Any], dict[str, Any], str]:
    player, _catalog, _index, printing = wlxlib.find_printing(catalogs, collector)
    if printing.get("card_kind") == "official_double_faced":
        if face not in {"front", "back"}:
            raise ValueError(
                f"WLX #{collector} is double-faced; name the replacement "
                f"WLX-{collector}-front or WLX-{collector}-back"
            )
        faces = printing.get("faces")
        if not isinstance(faces, list):
            raise ValueError(f"WLX #{collector} has malformed face data")
        match = next(
            (
                candidate
                for candidate in faces
                if isinstance(candidate, dict) and candidate.get("side") == face
            ),
            None,
        )
        if match is None:
            raise ValueError(f"WLX #{collector} has no {face} face")
        return player, printing, match, str(match.get("image_sha256", ""))
    if face:
        raise ValueError(f"WLX #{collector} is single-faced; omit -{face}")
    return player, printing, printing, str(printing.get("image_sha256", ""))


def mark_error(plan: Plan, images: list[PreparedImage] | PreparedImage, message: str) -> None:
    values = images if isinstance(images, list) else [images]
    for image in values:
        plan.errors[image.incoming.path] = message


def create_plan(
    root: Path,
    config: dict[str, Any],
    project: dict[str, Any],
    catalogs: dict[str, dict[str, Any]],
    official_cache: dict[str, Any],
    discovered: list[IncomingFile],
    fixture_dir: Path | None,
    token_fixture_dir: Path | None,
) -> Plan:
    plan = Plan()
    prepared: list[PreparedImage] = []
    separator = str(config["duplicate_separator"])
    for incoming in discovered:
        try:
            prepared.append(
                prepare_image(
                    incoming,
                    separator=separator,
                    minimum_width=int(config.get("minimum_width", 300)),
                    minimum_height=int(config.get("minimum_height", 400)),
                    minimum_bytes=int(config.get("minimum_bytes", 10_000)),
                    maximum_bytes=int(config.get("maximum_bytes", 100 * 1024 * 1024)),
                )
            )
        except (OSError, ValueError, wlxlib.WlxError) as exc:
            plan.errors[incoming.path] = str(exc)

    update_groups: dict[tuple[str, str], list[PreparedImage]] = defaultdict(list)
    double_groups: dict[tuple[str, str, str], list[tuple[PreparedImage, dict[str, Any], str]]] = defaultdict(list)
    single_candidates: list[tuple[PreparedImage, dict[str, Any]]] = []
    token_candidates: list[tuple[PreparedImage, str, dict[str, Any]]] = []
    token_prefix = str(config["token_prefix"])

    for image in prepared:
        update_match = UPDATE_RE.fullmatch(image.lookup_name)
        if update_match:
            collector = str(update_match.group("collector"))
            face = str(update_match.group("face") or "").casefold()
            update_groups[(collector, face)].append(image)
            continue
        if image.lookup_name.casefold().startswith(token_prefix.casefold()):
            creator = image.lookup_name[len(token_prefix) :].strip()
            if not creator:
                mark_error(plan, image, f"Token filenames must be {token_prefix}Creating Card Name.jpg")
                continue
            try:
                metadata = token_details(creator, project, token_fixture_dir)
                token_candidates.append((image, creator, metadata))
            except ValueError as exc:
                mark_error(plan, image, str(exc))
            continue
        try:
            details = official_details(
                image.lookup_name, project, official_cache, fixture_dir
            )
        except ValueError as exc:
            mark_error(plan, image, str(exc))
            continue
        layout = str(details.get("layout", ""))
        faces = details.get("faces")
        if layout in wlxlib.DOUBLE_FACED_LAYOUTS:
            if not isinstance(faces, list) or len(faces) != 2:
                mark_error(plan, image, "Official lookup returned malformed double-faced data")
                continue
            side = ""
            for face in faces:
                if (
                    isinstance(face, dict)
                    and str(face.get("official_name", "")).casefold()
                    == image.lookup_name.casefold()
                ):
                    side = str(face.get("side", ""))
                    break
            if side not in {"front", "back"}:
                mark_error(
                    plan,
                    image,
                    "For a double-faced card, name each image after its visible face and "
                    "upload both faces in the same batch.",
                )
                continue
            identity = str(details.get("oracle_id") or details.get("name", "")).casefold()
            double_groups[(image.incoming.player, identity, image.variant.casefold())].append(
                (image, details, side)
            )
        else:
            single_candidates.append((image, details))

    existing_hashes = all_existing_hashes(catalogs)
    claimed_hashes: dict[str, str] = {}

    def claim(image: PreparedImage, description: str, *, current_hash: str = "") -> str:
        if image.sha256 == current_hash:
            return "noop"
        if image.sha256 in existing_hashes:
            return f"This exact artwork is already published as {existing_hashes[image.sha256]}"
        if image.sha256 in claimed_hashes:
            return f"This exact artwork appears twice in the batch ({claimed_hashes[image.sha256]})"
        claimed_hashes[image.sha256] = description
        return ""

    for (collector, face), images in sorted(update_groups.items()):
        if len(images) != 1:
            mark_error(plan, images, f"More than one replacement targets WLX #{collector}{'-' + face if face else ''}")
            continue
        image = images[0]
        try:
            owner, _printing, _record, current_hash = printing_and_hash(
                catalogs, collector, face
            )
            if owner.casefold() != image.incoming.player.casefold():
                raise ValueError(
                    f"WLX #{collector} belongs to {owner}; upload its replacement in "
                    f"imports/incoming/{owner.casefold()}"
                )
            problem = claim(image, f"replacement for WLX #{collector}", current_hash=current_hash)
            if problem == "noop":
                plan.noops.append(image)
            elif problem:
                mark_error(plan, image, problem)
            else:
                plan.updates.append(UpdateArt(image, collector, face))
        except (ValueError, wlxlib.WlxError) as exc:
            mark_error(plan, image, str(exc))

    for image, details in single_candidates:
        problem = claim(image, str(details.get("name", image.lookup_name)))
        if problem:
            mark_error(plan, image, problem)
        else:
            plan.singles.append(AddSingle(image, details))

    for _key, values in sorted(double_groups.items()):
        images = [value[0] for value in values]
        fronts = [value for value in values if value[2] == "front"]
        backs = [value for value in values if value[2] == "back"]
        if len(fronts) != 1 or len(backs) != 1:
            name = str(values[0][1].get("name", "double-faced card"))
            mark_error(
                plan,
                images,
                f"{name} needs exactly one front image and one back image with the same "
                "optional ' __ label' suffix in this batch.",
            )
            continue
        front, details, _side = fronts[0]
        back = backs[0][0]
        problems = [
            problem
            for problem in (
                claim(front, f"front of {details.get('name', '')}"),
                claim(back, f"back of {details.get('name', '')}"),
            )
            if problem
        ]
        if problems:
            mark_error(plan, images, "; ".join(problems))
        else:
            plan.double_faced.append(
                AddDoubleFaced(front.incoming.player, details, front, back)
            )

    available_creators = existing_official_names(catalogs)
    available_creators.update(
        str(item.details.get("name", "")).casefold() for item in plan.singles
    )
    for item in plan.double_faced:
        available_creators.update(
            str(face.get("official_name", "")).casefold()
            for face in item.details.get("faces", [])
            if isinstance(face, dict)
        )
    for image, creator, metadata in token_candidates:
        if creator.casefold() not in available_creators:
            mark_error(
                plan,
                image,
                f"The creating face {creator!r} is not an active WLX card and is not "
                "being added in this batch.",
            )
            continue
        problem = claim(image, f"token for {creator}")
        if problem:
            mark_error(plan, image, problem)
        else:
            plan.tokens.append(AddToken(image, creator, metadata))
    return plan


def image_destination(root: Path, player: str, filename: str) -> Path:
    destination = wlxlib.player_images_path(root, player) / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination


def copy_source(image: PreparedImage, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copy2(image.incoming.path, temporary)
    temporary.replace(destination)


def next_identity(
    project: dict[str, Any], state: dict[str, Any], player: str, card_kind: str
) -> tuple[str, str]:
    collector = f"{int(state['next_collector']):03d}"
    if collector in state["collectors"]:
        raise BulkImportError(f"Collector allocation collision at WLX #{collector}")
    printing_uuid = wlxlib.stable_printing_uuid(
        str(project["package_id"]), str(project["set_code"]), collector
    )
    state["collectors"][collector] = {
        "status": "active",
        "player": player,
        "uuid": printing_uuid,
        "card_kind": card_kind,
    }
    state["next_collector"] = int(state["next_collector"]) + 1
    return collector, printing_uuid


def notes_for(image: PreparedImage, batch_id: str) -> str:
    return f"Imported from {image.incoming.relative_path} in file batch {batch_id}"


def add_single(
    root: Path,
    project: dict[str, Any],
    state: dict[str, Any],
    catalogs: dict[str, dict[str, Any]],
    item: AddSingle,
    batch_id: str,
) -> tuple[str, str]:
    player = item.image.incoming.player
    collector, printing_uuid = next_identity(project, state, player, "official")
    filename = f"WLX-{collector}{item.image.suffix}"
    copy_source(item.image, image_destination(root, player, filename))
    official_name = str(item.details["name"])
    catalogs[player]["printings"].append(
        {
            "collector_number": collector,
            "uuid": printing_uuid,
            "card_kind": "official",
            "official_name": official_name,
            "flavor_name": "",
            "rarity": str(project.get("default_rarity", "special")),
            "image_file": filename,
            "image_sha256": item.image.sha256,
            "notes": notes_for(item.image, batch_id),
        }
    )
    return collector, official_name


def add_double_faced(
    root: Path,
    project: dict[str, Any],
    state: dict[str, Any],
    catalogs: dict[str, dict[str, Any]],
    item: AddDoubleFaced,
    batch_id: str,
) -> tuple[str, str]:
    collector, printing_uuid = next_identity(
        project, state, item.player, "official_double_faced"
    )
    details_faces = item.details.get("faces")
    if not isinstance(details_faces, list) or len(details_faces) != 2:
        raise BulkImportError("Double-faced card details became malformed")
    sources = {"front": item.front, "back": item.back}
    face_records: list[dict[str, Any]] = []
    for details in details_faces:
        side = str(details.get("side", ""))
        source = sources.get(side)
        if source is None:
            raise BulkImportError("Double-faced card sides became malformed")
        filename = f"WLX-{collector}-{side}{source.suffix}"
        copy_source(source, image_destination(root, item.player, filename))
        record = {
            key: str(details.get(key, "")).strip()
            for key in (
                "official_name",
                "side",
                "mana_cost",
                "mana_value",
                "type_line",
                "rules_text",
                "colors",
                "color_identity",
                "power_toughness",
                "loyalty",
                "defense",
            )
        }
        record.update(
            {
                "flavor_name": "",
                "image_file": filename,
                "image_sha256": source.sha256,
            }
        )
        face_records.append(record)
    catalogs[item.player]["printings"].append(
        {
            "collector_number": collector,
            "uuid": printing_uuid,
            "card_kind": "official_double_faced",
            "official_name": str(item.details["name"]),
            "layout": str(item.details["layout"]),
            "faces": face_records,
            "rarity": str(project.get("default_rarity", "special")),
            "notes": f"Imported paired face images in file batch {batch_id}",
        }
    )
    return collector, str(item.details["name"])


def add_token(
    root: Path,
    project: dict[str, Any],
    state: dict[str, Any],
    catalogs: dict[str, dict[str, Any]],
    item: AddToken,
    batch_id: str,
) -> tuple[str, str]:
    player = item.image.incoming.player
    collector, printing_uuid = next_identity(project, state, player, "official_token")
    filename = f"WLX-{collector}{item.image.suffix}"
    copy_source(item.image, image_destination(root, player, filename))
    catalogs[player]["printings"].append(
        {
            "collector_number": collector,
            "uuid": printing_uuid,
            "card_kind": "official_token",
            "creator_card": item.creator_card,
            "token_metadata": item.token_metadata,
            "rarity": str(project.get("default_rarity", "special")),
            "image_file": filename,
            "image_sha256": item.image.sha256,
            "notes": notes_for(item.image, batch_id),
        }
    )
    display = str(
        item.token_metadata.get("display_name")
        or item.token_metadata.get("name", "Token")
    ).rstrip()
    return collector, display


def update_art(
    root: Path,
    catalogs: dict[str, dict[str, Any]],
    item: UpdateArt,
) -> tuple[str, str]:
    player, printing, record, _current_hash = printing_and_hash(
        catalogs, item.collector, item.face
    )
    face_component = f"-{item.face}" if item.face else ""
    filename = f"WLX-{item.collector}{face_component}{item.image.suffix}"
    old_path = wlxlib.player_images_path(root, player) / str(record["image_file"])
    destination = image_destination(root, player, filename)
    copy_source(item.image, destination)
    if old_path != destination and old_path.exists():
        old_path.unlink()
    record["image_file"] = filename
    record["image_sha256"] = item.image.sha256
    if item.face:
        name = str(record.get("official_name", printing.get("official_name", "")))
    else:
        token = printing.get("token_metadata")
        name = str(
            printing.get("official_name")
            or printing.get("flavor_name")
            or (token.get("display_name", "") if isinstance(token, dict) else "")
        )
    return item.collector, name


def attention_destination(
    root: Path,
    config: dict[str, Any],
    incoming: IncomingFile,
    batch_id: str,
) -> Path:
    folder = incoming.player.casefold() if incoming.player else "unknown-player"
    destination_dir = root / str(config["needs_attention_dir"]) / folder / batch_id
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / incoming.path.name
    if destination.exists():
        digest = wlxlib.sha256_file(incoming.path)[:10]
        destination = destination.with_name(
            f"{destination.stem}--{digest}{destination.suffix}"
        )
    return destination


def move_error(
    root: Path,
    config: dict[str, Any],
    incoming_by_path: dict[Path, IncomingFile],
    source: Path,
    message: str,
    batch_id: str,
) -> tuple[str, str]:
    incoming = incoming_by_path[source]
    destination = attention_destination(root, config, incoming, batch_id)
    shutil.move(str(source), str(destination))
    error_path = destination.with_suffix(destination.suffix + ".error.txt")
    error_path.write_text(
        "This image was not published.\n\n"
        + message.strip()
        + "\n\nFix or rename it, then move it back into the matching "
        "imports/incoming/<player> folder.\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination.relative_to(root).as_posix(), error_path.relative_to(root).as_posix()


def write_report(root: Path, config: dict[str, Any], report: dict[str, Any]) -> None:
    wlxlib.write_json(root / str(config["report_json"]), report)
    lines = [
        "# Latest WLX File Import",
        "",
        f"- Batch: `{report['batch_id']}`",
        f"- Finished: `{report['finished_at']}`",
        f"- Images found: **{report['found']}**",
        f"- New printings: **{len(report['added'])}**",
        f"- Artwork replacements: **{len(report['updated'])}**",
        f"- Already-current inputs cleared: **{len(report['already_current'])}**",
        f"- Needs attention: **{len(report['needs_attention'])}**",
    ]
    if report["added"]:
        lines.extend(["", "## Added", ""])
        lines.extend(
            f"- `WLX #{item['collector_number']}` — {item['name']} ({item['player']})"
            for item in report["added"]
        )
    if report["updated"]:
        lines.extend(["", "## Updated", ""])
        lines.extend(
            f"- `WLX #{item['collector_number']}` — {item['name']}"
            for item in report["updated"]
        )
    if report["needs_attention"]:
        lines.extend(["", "## Needs attention", ""])
        lines.extend(
            f"- `{item['original_file']}` — {item['error']}"
            for item in report["needs_attention"]
        )
    (root / str(config["report_markdown"])).write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )


def remove_empty_input_directories(root: Path, config: dict[str, Any]) -> None:
    incoming_root = root / str(config["incoming_dir"])
    protected = {
        incoming_root,
        *(
            incoming_root / str(folder)
            for folder in dict(config["player_folders"])
        ),
    }
    for path in sorted(
        (candidate for candidate in incoming_root.rglob("*") if candidate.is_dir()),
        key=lambda candidate: len(candidate.parts),
        reverse=True,
    ):
        if path not in protected:
            try:
                path.rmdir()
            except OSError:
                pass


def run(
    root: Path,
    config_path: Path = DEFAULT_CONFIG,
    *,
    fixture_dir: Path | None = None,
    token_fixture_dir: Path | None = None,
    batch_id: str = "",
) -> int:
    root = root.resolve()
    config = load_config(root, config_path)
    discovered = discover_inputs(root, config)
    if not discovered:
        print("No WLX card images are waiting in imports/incoming.")
        return 0
    maximum = int(config["max_images_per_batch"])
    if len(discovered) > maximum:
        raise BulkImportError(
            f"Found {len(discovered)} input files. One batch may contain at most {maximum}; "
            "no files were changed."
        )

    project = wlxlib.read_json(wlxlib.source_path(root, wlxlib.PROJECT_RELATIVE))
    state = wlxlib.read_json(wlxlib.source_path(root, wlxlib.STATE_RELATIVE))
    catalogs = wlxlib.load_all_catalogs(root, project)
    official_cache = wlxlib.load_official_cache(root)
    plan = create_plan(
        root,
        config,
        project,
        catalogs,
        official_cache,
        discovered,
        fixture_dir,
        token_fixture_dir,
    )
    batch_id = (
        batch_id.strip()
        or os.environ.get("GITHUB_SHA", "")[:10]
        or dt.datetime.now(dt.timezone.utc).strftime("local-%Y%m%d-%H%M%S")
    )
    incoming_by_path = {item.path: item for item in discovered}
    report: dict[str, Any] = {
        "schema_version": 1,
        "batch_id": batch_id,
        "started_at": utc_now(),
        "finished_at": "",
        "found": len(discovered),
        "version_before": str(project["version"]),
        "version_after": str(project["version"]),
        "added": [],
        "updated": [],
        "already_current": [],
        "needs_attention": [],
    }

    changed_publication = bool(
        plan.singles or plan.double_faced or plan.tokens or plan.updates
    )
    if changed_publication:
        project["version"] = wlxlib.bump_patch(str(project["version"]))
        project["release_created_at"] = utc_now()

    for item in sorted(plan.singles, key=lambda value: value.image.incoming.relative_path.casefold()):
        collector, name = add_single(root, project, state, catalogs, item, batch_id)
        report["added"].append(
            {"collector_number": collector, "name": name, "player": item.image.incoming.player}
        )
    for item in sorted(plan.double_faced, key=lambda value: value.front.incoming.relative_path.casefold()):
        collector, name = add_double_faced(root, project, state, catalogs, item, batch_id)
        report["added"].append(
            {"collector_number": collector, "name": name, "player": item.player}
        )
    for item in sorted(plan.tokens, key=lambda value: value.image.incoming.relative_path.casefold()):
        collector, name = add_token(root, project, state, catalogs, item, batch_id)
        report["added"].append(
            {"collector_number": collector, "name": name, "player": item.image.incoming.player}
        )
    for item in sorted(plan.updates, key=lambda value: (int(value.collector), value.face)):
        collector, name = update_art(root, catalogs, item)
        report["updated"].append(
            {"collector_number": collector, "name": name, "face": item.face}
        )

    if changed_publication:
        wlxlib.persist_catalogs(root, catalogs)
        wlxlib.write_json(wlxlib.source_path(root, wlxlib.STATE_RELATIVE), state)
        wlxlib.write_json(wlxlib.source_path(root, wlxlib.PROJECT_RELATIVE), project)
    wlxlib.write_json(
        wlxlib.source_path(root, wlxlib.OFFICIAL_CACHE_RELATIVE), official_cache
    )
    wlxlib.validate_repository(root)

    successful_images = [item.image for item in plan.singles]
    successful_images.extend(
        image
        for item in plan.double_faced
        for image in (item.front, item.back)
    )
    successful_images.extend(item.image for item in plan.tokens)
    successful_images.extend(item.image for item in plan.updates)
    for image in successful_images:
        image.incoming.path.unlink()
    for image in plan.noops:
        image.incoming.path.unlink()
        report["already_current"].append(image.incoming.relative_path)
    for source, message in sorted(
        plan.errors.items(), key=lambda item: incoming_by_path[item[0]].relative_path.casefold()
    ):
        moved_image, error_file = move_error(
            root, config, incoming_by_path, source, message, batch_id
        )
        report["needs_attention"].append(
            {
                "original_file": incoming_by_path[source].relative_path,
                "moved_image": moved_image,
                "error_file": error_file,
                "error": message,
            }
        )
    remove_empty_input_directories(root, config)
    report["version_after"] = str(project["version"])
    report["finished_at"] = utc_now()
    write_report(root, config, report)
    print(
        f"WLX batch complete: {len(report['added'])} added, "
        f"{len(report['updated'])} updated, "
        f"{len(report['needs_attention'])} need attention."
    )
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    result.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    result.add_argument("--fixture-dir", type=Path, default=None)
    result.add_argument("--token-fixture-dir", type=Path, default=None)
    result.add_argument("--batch-id", default="")
    return result


def main() -> int:
    arguments = parser().parse_args()
    try:
        return run(
            arguments.repository_root,
            arguments.config,
            fixture_dir=arguments.fixture_dir,
            token_fixture_dir=arguments.token_fixture_dir,
            batch_id=arguments.batch_id,
        )
    except (BulkImportError, wlxlib.WlxError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"UNEXPECTED ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
