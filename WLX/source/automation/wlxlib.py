#!/usr/bin/env python3
"""Core validation and publishing logic for Willex's Whimsical Arts.

The repository is the editable source of truth. Four player catalogs are
validated and compiled into one Cockatrice v4 custom-set database plus the
hosted updater payload. The implementation intentionally uses only Python's
standard library so it can run on GitHub's hosted runners and ordinary local
Python installations without a dependency installation step.
"""

from __future__ import annotations

import base64
import csv
import dataclasses
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import shutil
import struct
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


SOURCE_RELATIVE = Path("WLX") / "source"
PUBLISHED_RELATIVE = Path("WLX") / "published"
DOCS_RELATIVE = Path("WLX") / "docs"
PLAYER_CATALOG_RELATIVE = Path("cards")
STATE_RELATIVE = Path("automation") / "state.json"
OFFICIAL_CACHE_RELATIVE = Path("automation") / "data" / "official_cards_cache.json"
INSTALLER_SOURCE_RELATIVE = Path("automation") / "installer_source"
PROJECT_RELATIVE = Path("project.json")
STATUS_RELATIVE = Path("STATUS.md")
COCKATRICE_TOKEN_DATABASE_URL = (
    "https://raw.githubusercontent.com/Cockatrice/Magic-Token/master/tokens.xml"
)

COLLECTOR_RE = re.compile(r"^[0-9]{3,}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
COLOR_RE = re.compile(r"^[WUBRG]*$")
MANA_COST_RE = re.compile(r"(?:\{[^{}\s]+\})+")
ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
MAX_SOURCE_IMAGE_BYTES = 100 * 1024 * 1024
ALLOWED_RARITIES = {"common", "uncommon", "rare", "mythic", "special", "bonus"}
DOUBLE_FACED_LAYOUTS = {
    "double_faced_token",
    "flip",
    "modal_dfc",
    "reversible_card",
    "transform",
}
PRIMARY_TYPES = (
    "Land",
    "Creature",
    "Artifact",
    "Enchantment",
    "Planeswalker",
    "Instant",
    "Sorcery",
    "Battle",
    "Plane",
    "Phenomenon",
    "Scheme",
    "Vanguard",
    "Conspiracy",
    "Dungeon",
    "Emblem",
    "Token",
)


class WlxError(RuntimeError):
    """A user-facing validation or publishing failure."""


@dataclasses.dataclass(frozen=True)
class CustomDefinition:
    custom_card_id: str
    player: str
    name: str
    text: str
    type_line: str
    mana_cost: str
    mana_value: str
    colors: str
    color_identity: str
    power_toughness: str
    loyalty: str
    defense: str
    layout: str
    side: str
    token: bool


@dataclasses.dataclass(frozen=True)
class ResolvedPrinting:
    player: str
    card_kind: str
    card_key: str
    card_name: str
    custom_definition: CustomDefinition | None
    flavor_name: str
    collector_number: str
    printing_uuid: str
    rarity: str
    image_file: str
    image_path: Path
    image_sha256: str
    image_width: int
    image_height: int
    published_image_path: str
    picture_url: str
    notes: str
    face_metadata: dict[str, str] | None = None
    transform_into: str = ""
    token_metadata: dict[str, Any] | None = None


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WlxError(f"Required file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WlxError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise WlxError(f"Expected a JSON object in {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def image_dimensions(path: Path) -> tuple[int, int]:
    """Read PNG/JPEG dimensions without external libraries."""
    with path.open("rb") as handle:
        signature = handle.read(24)
        if signature.startswith(b"\x89PNG\r\n\x1a\n") and len(signature) >= 24:
            return struct.unpack(">II", signature[16:24])
        if signature[:2] != b"\xff\xd8":
            raise WlxError(f"{path.name} is not a valid PNG or JPEG image")
        handle.seek(2)
        while True:
            marker_start = handle.read(1)
            if not marker_start:
                break
            if marker_start != b"\xff":
                continue
            marker = handle.read(1)
            while marker == b"\xff":
                marker = handle.read(1)
            if not marker:
                break
            code = marker[0]
            if code in {0xD8, 0xD9}:
                continue
            raw_length = handle.read(2)
            if len(raw_length) != 2:
                break
            segment_length = struct.unpack(">H", raw_length)[0]
            if segment_length < 2:
                break
            if code in {
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            }:
                payload = handle.read(5)
                if len(payload) != 5:
                    break
                height, width = struct.unpack(">HH", payload[1:5])
                return width, height
            handle.seek(segment_length - 2, os.SEEK_CUR)
    raise WlxError(f"Could not read image dimensions from {path.name}")


def normalize_base_url(value: str) -> str:
    value = value.strip()
    if not value.endswith("/"):
        value += "/"
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WlxError("project.json public_base_url must be a complete HTTP(S) URL")
    return value


def url_for(base_url: str, relative_path: str) -> str:
    quoted = "/".join(urllib.parse.quote(part) for part in relative_path.split("/"))
    return urllib.parse.urljoin(base_url, quoted)


def stable_printing_uuid(package_id: str, set_code: str, collector_number: str) -> str:
    seed = f"{package_id}|printing|{set_code}|{collector_number}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def stable_custom_card_id(package_id: str, collector_number: str) -> str:
    seed = f"{package_id}|custom-card|{collector_number}"
    return "custom-" + str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def bump_patch(version: str) -> str:
    match = SEMVER_RE.fullmatch(version)
    if not match:
        raise WlxError(f"Invalid release version: {version!r}")
    major, minor, patch = (int(group) for group in match.groups())
    return f"{major}.{minor}.{patch + 1}"


def player_names(config: dict[str, Any]) -> list[str]:
    players = config.get("players")
    if not isinstance(players, list) or not players:
        raise WlxError("project.json players must be a non-empty array")
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in players:
        player = str(raw).strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]*", player):
            raise WlxError(f"Invalid player folder name: {player!r}")
        if player.casefold() in seen:
            raise WlxError(f"Duplicate player name: {player}")
        seen.add(player.casefold())
        normalized.append(player)
    return normalized


def source_root(root: Path) -> Path:
    """Return the canonical source root for either the v3 or legacy layout."""
    root = root.resolve()
    organized = root / SOURCE_RELATIVE
    if organized.is_dir():
        return organized
    return root


def published_root(root: Path) -> Path:
    """Return the public payload root while retaining isolated legacy fixtures."""
    root = root.resolve()
    if source_root(root) != root:
        return root / PUBLISHED_RELATIVE
    return root


def docs_root(root: Path) -> Path:
    """Return the documentation root while retaining isolated legacy fixtures."""
    root = root.resolve()
    if source_root(root) != root:
        return root / DOCS_RELATIVE
    return root


def source_path(root: Path, relative: Path) -> Path:
    return source_root(root) / relative


def player_catalog_path(root: Path, player: str) -> Path:
    return source_path(root, PLAYER_CATALOG_RELATIVE) / player / "catalog.json"


def player_images_path(root: Path, player: str) -> Path:
    return source_path(root, PLAYER_CATALOG_RELATIVE) / player / "images"


def empty_player_catalog(player: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "player": player,
        "custom_cards": [],
        "printings": [],
    }


def load_player_catalog(root: Path, player: str) -> dict[str, Any]:
    path = player_catalog_path(root, player)
    catalog = read_json(path)
    if catalog.get("schema_version") != 1:
        raise WlxError(f"Unsupported schema_version in {path}")
    if str(catalog.get("player", "")) != player:
        raise WlxError(f"{path} must identify player {player!r}")
    for key in ("custom_cards", "printings"):
        if not isinstance(catalog.get(key), list):
            raise WlxError(f"{path} field {key!r} must be an array")
    return catalog


def load_all_catalogs(root: Path, config: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    config = config or read_json(source_path(root, PROJECT_RELATIVE))
    return {player: load_player_catalog(root, player) for player in player_names(config)}


def normalize_colors(raw: str) -> str:
    raw = raw.upper().replace(" ", "").replace(",", "")
    if not COLOR_RE.fullmatch(raw):
        raise WlxError("Colors and color identity may contain only W, U, B, R, and G")
    return "".join(symbol for symbol in "WUBRG" if symbol in raw)


def main_type_from_type_line(type_line: str) -> str:
    normalized = type_line.replace("—", "-")
    words = {word.casefold() for word in re.findall(r"[A-Za-z]+", normalized)}
    for candidate in PRIMARY_TYPES:
        if candidate.casefold() in words:
            return candidate
    return ""


def table_row_for(main_type: str) -> int:
    if main_type == "Land":
        return 0
    if main_type == "Creature":
        return 2
    if main_type in {"Instant", "Sorcery"}:
        return 3
    return 1


def custom_definition_from_raw(player: str, raw: dict[str, Any]) -> CustomDefinition:
    custom_card_id = str(raw.get("custom_card_id", "")).strip()
    if not custom_card_id.startswith("custom-"):
        raise WlxError(f"Invalid custom_card_id in {player}'s catalog")
    name = str(raw.get("name", "")).strip()
    type_line = str(raw.get("type_line", "")).strip()
    if not name:
        raise WlxError(f"A custom card in {player}'s catalog has no name")
    if not type_line:
        raise WlxError(f"Custom card {name!r} has no type line")
    layout = str(raw.get("layout", "normal")).strip() or "normal"
    side = str(raw.get("side", "front")).strip() or "front"
    if side not in {"front", "back"}:
        raise WlxError(f"Custom card {name!r} side must be front or back")
    mana_value = str(raw.get("mana_value", "")).strip()
    if mana_value:
        try:
            numeric_mana_value = float(mana_value)
            if not math.isfinite(numeric_mana_value) or numeric_mana_value < 0:
                raise ValueError
        except ValueError as exc:
            raise WlxError(f"Custom card {name!r} has an invalid mana value") from exc
    colors = normalize_colors(str(raw.get("colors", "")))
    color_identity = normalize_colors(str(raw.get("color_identity", "")))
    mana_cost = str(raw.get("mana_cost", "")).strip()
    if mana_cost and not MANA_COST_RE.fullmatch(mana_cost):
        raise WlxError(
            f"Custom card {name!r} mana cost must use Cockatrice symbols such as {{2}}{{W}}{{U}}"
        )
    type_words = {
        word.casefold()
        for word in re.findall(r"[A-Za-z]+", type_line.replace("—", "-"))
    }
    power_toughness = str(raw.get("power_toughness", "")).strip()
    loyalty = str(raw.get("loyalty", "")).strip()
    defense = str(raw.get("defense", "")).strip()
    if "creature" in type_words and not power_toughness:
        raise WlxError(f"Custom creature {name!r} must include power/toughness")
    if "planeswalker" in type_words and not loyalty:
        raise WlxError(f"Custom planeswalker {name!r} must include starting loyalty")
    if "battle" in type_words and not defense:
        raise WlxError(f"Custom battle {name!r} must include starting defense")
    return CustomDefinition(
        custom_card_id=custom_card_id,
        player=player,
        name=name,
        text=str(raw.get("rules_text", "")).strip(),
        type_line=type_line,
        mana_cost=mana_cost,
        mana_value=mana_value,
        colors=colors,
        color_identity=color_identity,
        power_toughness=power_toughness,
        loyalty=loyalty,
        defense=defense,
        layout=layout,
        side=side,
        token=bool(raw.get("token", False)),
    )


def load_official_cache(root: Path) -> dict[str, Any]:
    cache = read_json(source_path(root, OFFICIAL_CACHE_RELATIVE))
    if cache.get("schema_version") != 1 or not isinstance(cache.get("cards"), dict):
        raise WlxError("Official-card cache is malformed")
    return cache


def cached_official_name(cache: dict[str, Any], requested: str) -> str:
    entry = cache["cards"].get(requested.casefold())
    if not isinstance(entry, dict) or not str(entry.get("name", "")).strip():
        raise WlxError(
            f"Official card {requested!r} has not been verified. Submit it through the GitHub form."
        )
    return str(entry["name"])


def scryfall_exact(name: str, config: dict[str, Any]) -> dict[str, Any] | None:
    query = urllib.parse.urlencode({"exact": name})
    request = urllib.request.Request(
        f"https://api.scryfall.com/cards/named?{query}",
        headers={
            "Accept": "application/json",
            "User-Agent": str(config.get("scryfall_user_agent", "WillexWhimsicalArts/2.0")),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise WlxError(f"Scryfall returned HTTP {exc.code}; try the submission again later") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise WlxError(f"Could not verify the card name with Scryfall: {exc}") from exc
    if not isinstance(payload, dict) or not payload.get("name"):
        raise WlxError("Scryfall returned an unexpected response")
    faces: list[dict[str, str]] = []
    raw_faces = payload.get("card_faces", [])
    if isinstance(raw_faces, list):
        for index, raw_face in enumerate(raw_faces):
            if not isinstance(raw_face, dict):
                continue
            power = str(raw_face.get("power", "") or "").strip()
            toughness = str(raw_face.get("toughness", "") or "").strip()
            power_toughness = ""
            if power or toughness:
                power_toughness = f"{power}/{toughness}"
            raw_colors = raw_face.get("colors", [])
            colors = "".join(str(value) for value in raw_colors) if isinstance(raw_colors, list) else ""
            raw_identity = payload.get("color_identity", [])
            color_identity = (
                "".join(str(value) for value in raw_identity)
                if isinstance(raw_identity, list)
                else ""
            )
            faces.append(
                {
                    "official_name": str(raw_face.get("name", "")).strip(),
                    "side": "front" if index == 0 else "back",
                    "mana_cost": str(raw_face.get("mana_cost", "") or "").strip(),
                    "mana_value": str(raw_face.get("cmc", "") or "").strip(),
                    "type_line": str(raw_face.get("type_line", "") or "").strip(),
                    "rules_text": str(raw_face.get("oracle_text", "") or "").strip(),
                    "colors": normalize_colors(colors),
                    "color_identity": normalize_colors(color_identity),
                    "power_toughness": power_toughness,
                    "loyalty": str(raw_face.get("loyalty", "") or "").strip(),
                    "defense": str(raw_face.get("defense", "") or "").strip(),
                }
            )
    return {
        "name": str(payload["name"]),
        "oracle_id": str(payload.get("oracle_id", "")),
        "scryfall_uri": str(payload.get("scryfall_uri", "")),
        "layout": str(payload.get("layout", "")),
        "faces": faces,
        "verified_at": dt.date.today().isoformat(),
    }


def parse_cockatrice_token_database(payload: bytes, creator_name: str) -> dict[str, Any]:
    """Find the one native Cockatrice token related to a creating card face."""
    try:
        database = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise WlxError("Cockatrice returned a malformed token database") from exc
    requested = creator_name.strip().casefold()
    matches: list[tuple[ET.Element, list[dict[str, str]]]] = []
    allowed_relation_attributes = {
        "count",
        "exclude",
        "attach",
        "persistent",
        "facedown",
    }
    for card in database.findall("./cards/card"):
        related: list[dict[str, str]] = []
        for relation in card.findall("reverse-related"):
            related_name = (relation.text or "").strip()
            if related_name.casefold() != requested:
                continue
            entry = {"name": related_name}
            for key, value in relation.attrib.items():
                if key in allowed_relation_attributes:
                    entry[key] = value
            related.append(entry)
        if related:
            matches.append((card, related))

    if not matches:
        raise WlxError(
            f"Cockatrice has no official token linked to {creator_name!r}"
        )
    if len(matches) > 1:
        token_names = sorted(
            {
                ((card.findtext("name") or "").rstrip() or "unnamed token")
                for card, _related in matches
            }
        )
        raise WlxError(
            f"{creator_name!r} creates more than one official token ({', '.join(token_names)}); "
            "this three-field form needs a card face that identifies one token"
        )

    card, related = matches[0]
    # Cockatrice deliberately uses trailing spaces to distinguish a few tokens
    # with the same visible name. Preserve those spaces as part of the identity.
    name = card.findtext("name") or ""
    if not name.strip():
        raise WlxError("Cockatrice returned a token without a name")
    prop = card.find("prop")
    properties = {
        child.tag: (child.text or "").strip()
        for child in ([] if prop is None else list(prop))
    }
    type_line = properties.get("type", "")
    if not type_line:
        raise WlxError(f"Cockatrice token {name.rstrip()!r} has no type line")
    tablerow = (card.findtext("tablerow") or "").strip()
    if tablerow:
        try:
            int(tablerow)
        except ValueError as exc:
            raise WlxError(
                f"Cockatrice token {name.rstrip()!r} has an invalid table row"
            ) from exc
    return {
        "name": name,
        "display_name": name.rstrip(),
        "rules_text": (card.findtext("text") or "").strip(),
        "type_line": type_line,
        "main_type": properties.get("maintype", "") or main_type_from_type_line(type_line),
        "mana_cost": properties.get("manacost", ""),
        "mana_value": properties.get("cmc", ""),
        "colors": normalize_colors(properties.get("colors", "")),
        "color_identity": normalize_colors(properties.get("coloridentity", "")),
        "power_toughness": properties.get("pt", ""),
        "loyalty": properties.get("loyalty", ""),
        "defense": properties.get("defense", ""),
        "tablerow": tablerow,
        "reverse_related": related,
        "verified_at": dt.date.today().isoformat(),
        "source_url": COCKATRICE_TOKEN_DATABASE_URL,
    }


def verify_official_token_for_creator(
    creator_name: str, config: dict[str, Any]
) -> dict[str, Any]:
    """Download Cockatrice's native token data and resolve one creator relation."""
    request = urllib.request.Request(
        COCKATRICE_TOKEN_DATABASE_URL,
        headers={
            "Accept": "application/xml,text/xml",
            "User-Agent": str(config.get("scryfall_user_agent", "WillexWhimsicalArts/2.0")),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read(8 * 1024 * 1024 + 1)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise WlxError(
            f"Could not read Cockatrice's official token database: {exc}"
        ) from exc
    if len(payload) > 8 * 1024 * 1024:
        raise WlxError("Cockatrice's official token database was unexpectedly large")
    return parse_cockatrice_token_database(payload, creator_name)


def verify_official_name(root: Path, requested: str, config: dict[str, Any]) -> str:
    cache_path = source_path(root, OFFICIAL_CACHE_RELATIVE)
    cache = load_official_cache(root)
    cached = cache["cards"].get(requested.casefold())
    if isinstance(cached, dict) and cached.get("name"):
        return str(cached["name"])
    result = scryfall_exact(requested, config)
    if result is None:
        raise WlxError(f"Scryfall did not find an official Magic card named {requested!r}")
    canonical = str(result["name"])
    cache["cards"][canonical.casefold()] = result
    if canonical.casefold() != requested.casefold():
        cache["cards"][requested.casefold()] = result
    write_json(cache_path, cache)
    return canonical


def verify_official_double_faced(
    root: Path, requested: str, config: dict[str, Any]
) -> dict[str, Any]:
    """Resolve one official two-faced physical card and cache both face names."""
    cache_path = source_path(root, OFFICIAL_CACHE_RELATIVE)
    cache = load_official_cache(root)
    cached = cache["cards"].get(requested.casefold())
    if (
        isinstance(cached, dict)
        and cached.get("name")
        and cached.get("layout") in DOUBLE_FACED_LAYOUTS
        and isinstance(cached.get("faces"), list)
        and len(cached["faces"]) == 2
    ):
        return cached

    result = scryfall_exact(requested, config)
    if result is None:
        raise WlxError(f"Scryfall did not find an official Magic card named {requested!r}")
    layout = str(result.get("layout", ""))
    faces = result.get("faces")
    if layout not in DOUBLE_FACED_LAYOUTS or not isinstance(faces, list) or len(faces) != 2:
        raise WlxError(
            f"{result['name']!r} is not a two-faced Magic card. Use Add a Card Printing instead."
        )
    face_names = [str(face.get("official_name", "")).strip() for face in faces if isinstance(face, dict)]
    if len(face_names) != 2 or not all(face_names) or face_names[0].casefold() == face_names[1].casefold():
        raise WlxError("Scryfall returned malformed double-faced card data")

    canonical = str(result["name"])
    aliases = {canonical.casefold(), requested.casefold(), *(name.casefold() for name in face_names)}
    for alias in aliases:
        cache["cards"][alias] = result
    write_json(cache_path, cache)
    return result


def validate_repository(root: Path) -> tuple[dict[str, Any], dict[str, Any], list[ResolvedPrinting]]:
    root = root.resolve()
    config = read_json(source_path(root, PROJECT_RELATIVE))
    state = read_json(source_path(root, STATE_RELATIVE))
    catalogs = load_all_catalogs(root, config)
    official_cache = load_official_cache(root)

    required = (
        "package_id",
        "display_name",
        "version",
        "public_base_url",
        "set_code",
        "set_name",
        "install_folder",
    )
    for key in required:
        if not str(config.get(key, "")).strip():
            raise WlxError(f"project.json is missing {key!r}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(config["package_id"])):
        raise WlxError("package_id must contain lowercase letters, numbers, and hyphens")
    if not SEMVER_RE.fullmatch(str(config["version"])):
        raise WlxError("project.json version must use three-part semantic versioning")
    set_code = str(config["set_code"])
    if not re.fullmatch(r"[A-Z0-9]{2,8}", set_code):
        raise WlxError("set_code must be 2-8 uppercase letters or numbers")
    base_url = normalize_base_url(str(config["public_base_url"]))
    xml_filename = str(config.get("xml_filename", "willex_whimsical_arts.xml"))
    installer_zip = str(
        config.get(
            "installer_zip_filename",
            "Willexs_Whimsical_Arts_Cockatrice_Installer.zip",
        )
    )
    if not SAFE_FILENAME_RE.fullmatch(xml_filename) or not xml_filename.lower().endswith(".xml"):
        raise WlxError("xml_filename must be a safe filename ending in .xml")
    if not SAFE_FILENAME_RE.fullmatch(installer_zip) or not installer_zip.lower().endswith(".zip"):
        raise WlxError("installer_zip_filename must be a safe filename ending in .zip")
    install_folder = str(config["install_folder"])
    legacy_install_folder = str(config.get("legacy_install_folder", ""))
    if not SAFE_FILENAME_RE.fullmatch(install_folder):
        raise WlxError("install_folder must be one safe Windows folder name")
    if legacy_install_folder and not SAFE_FILENAME_RE.fullmatch(legacy_install_folder):
        raise WlxError("legacy_install_folder must be one safe Windows folder name")
    if state.get("schema_version") != 1:
        raise WlxError("automation/state.json has an unsupported schema_version")
    collectors_state = state.get("collectors")
    if not isinstance(collectors_state, dict):
        raise WlxError("automation/state.json collectors must be an object")

    custom_by_id: dict[str, CustomDefinition] = {}
    custom_names: dict[str, str] = {}
    for player, catalog in catalogs.items():
        for raw in catalog["custom_cards"]:
            if not isinstance(raw, dict):
                raise WlxError(f"{player}'s custom_cards list contains a non-object value")
            definition = custom_definition_from_raw(player, raw)
            if definition.custom_card_id in custom_by_id:
                raise WlxError(f"Duplicate custom card ID: {definition.custom_card_id}")
            name_key = definition.name.casefold()
            if name_key in custom_names:
                raise WlxError(f"Duplicate original custom card name: {definition.name}")
            if name_key in official_cache["cards"]:
                raise WlxError(
                    f"Original custom card {definition.name!r} matches an official Magic card name"
                )
            custom_by_id[definition.custom_card_id] = definition
            custom_names[name_key] = definition.custom_card_id

    pins = config.get("uuid_pins", {})
    if not isinstance(pins, dict):
        raise WlxError("project.json uuid_pins must be an object")
    resolved: list[ResolvedPrinting] = []
    seen_collectors: set[str] = set()
    seen_uuids: set[str] = set()
    seen_images: set[Path] = set()

    def resolve_image(
        player: str,
        collector: str,
        raw_image: dict[str, Any],
        *,
        published_label: str,
    ) -> tuple[str, Path, str, int, int, str, str]:
        image_file = str(raw_image.get("image_file", "")).strip()
        image_relative = Path(image_file)
        if (
            not image_file
            or image_relative.is_absolute()
            or len(image_relative.parts) != 1
            or ".." in image_relative.parts
            or image_relative.suffix.lower() not in ALLOWED_IMAGE_SUFFIXES
        ):
            raise WlxError(f"WLX #{collector} has an unsafe image filename")
        image_path = player_images_path(root, player) / image_file
        if not image_path.is_file():
            raise WlxError(f"WLX #{collector} image is missing: {image_path.relative_to(root)}")
        if image_path in seen_images:
            raise WlxError(f"Source image is reused by more than one printing: {image_path}")
        seen_images.add(image_path)
        size = image_path.stat().st_size
        if size < 10_000:
            raise WlxError(f"WLX #{collector} image is suspiciously small")
        if size > MAX_SOURCE_IMAGE_BYTES:
            raise WlxError(
                f"WLX #{collector} image exceeds the {MAX_SOURCE_IMAGE_BYTES // (1024 * 1024)} MiB source limit"
            )
        width, height = image_dimensions(image_path)
        if width < 300 or height < 400:
            raise WlxError(f"WLX #{collector} image is only {width}x{height}; minimum is 300x400")
        image_hash = sha256_file(image_path)
        stored_hash = str(raw_image.get("image_sha256", "")).lower().strip()
        if stored_hash and stored_hash != image_hash:
            raise WlxError(
                f"WLX #{collector} image changed outside the update workflow; submit an Update Printing request"
            )
        suffix = ".jpg" if image_path.suffix.lower() in {".jpg", ".jpeg"} else ".png"
        published = f"images/{set_code}/{published_label}-{image_hash[:12]}{suffix}"
        return (
            image_file,
            image_path,
            image_hash,
            width,
            height,
            published,
            url_for(base_url, published),
        )

    for player, catalog in catalogs.items():
        for raw in catalog["printings"]:
            if not isinstance(raw, dict):
                raise WlxError(f"{player}'s printings list contains a non-object value")
            collector = str(raw.get("collector_number", "")).strip()
            if not COLLECTOR_RE.fullmatch(collector):
                raise WlxError(f"Invalid WLX collector number in {player}'s catalog: {collector!r}")
            if collector in seen_collectors:
                raise WlxError(f"WLX collector number {collector} is duplicated")
            seen_collectors.add(collector)

            raw_uuid = str(raw.get("uuid", "")).strip()
            try:
                printing_uuid = str(uuid.UUID(raw_uuid))
            except ValueError as exc:
                raise WlxError(f"WLX #{collector} has an invalid UUID") from exc
            expected_uuid = str(pins.get(collector) or stable_printing_uuid(str(config["package_id"]), set_code, collector))
            if printing_uuid != expected_uuid:
                raise WlxError(f"WLX #{collector} UUID does not match its permanent printing identity")
            if printing_uuid in seen_uuids:
                raise WlxError(f"Printing UUID {printing_uuid} is duplicated")
            seen_uuids.add(printing_uuid)

            state_entry = collectors_state.get(collector)
            if not isinstance(state_entry, dict) or state_entry.get("status") != "active":
                raise WlxError(f"WLX #{collector} is not active in automation/state.json")
            if str(state_entry.get("uuid", "")) != printing_uuid:
                raise WlxError(f"WLX #{collector} state UUID does not match its catalog")
            if str(state_entry.get("player", "")) != player:
                raise WlxError(f"WLX #{collector} state owner does not match {player}'s catalog")

            card_kind = str(raw.get("card_kind", "")).strip()
            state_kind = str(state_entry.get("card_kind", "")).strip()
            if state_kind and state_kind != card_kind:
                raise WlxError(f"WLX #{collector} state card kind does not match its catalog")
            rarity = str(raw.get("rarity", config.get("default_rarity", "special"))).lower().strip()
            if rarity not in ALLOWED_RARITIES:
                raise WlxError(f"WLX #{collector} has unsupported rarity {rarity!r}")

            if card_kind == "official_double_faced":
                combined_name = str(raw.get("official_name", "")).strip()
                layout = str(raw.get("layout", "")).strip()
                raw_faces = raw.get("faces")
                if not combined_name:
                    raise WlxError(f"WLX #{collector} has no official double-faced card name")
                if layout not in DOUBLE_FACED_LAYOUTS:
                    raise WlxError(f"WLX #{collector} has unsupported double-faced layout {layout!r}")
                if not isinstance(raw_faces, list) or len(raw_faces) != 2:
                    raise WlxError(f"WLX #{collector} must contain exactly two card faces")

                normalized_faces: list[dict[str, Any]] = []
                for expected_side, raw_face in zip(("front", "back"), raw_faces):
                    if not isinstance(raw_face, dict):
                        raise WlxError(f"WLX #{collector} contains malformed face data")
                    side = str(raw_face.get("side", "")).strip()
                    face_name = str(raw_face.get("official_name", "")).strip()
                    type_line = str(raw_face.get("type_line", "")).strip()
                    if side != expected_side:
                        raise WlxError(
                            f"WLX #{collector} faces must be ordered front, then back"
                        )
                    if not face_name or not type_line:
                        raise WlxError(f"WLX #{collector} {side} face is missing its name or type line")
                    normalize_colors(str(raw_face.get("colors", "")))
                    normalize_colors(str(raw_face.get("color_identity", "")))
                    normalized_faces.append(raw_face)
                if (
                    str(normalized_faces[0]["official_name"]).casefold()
                    == str(normalized_faces[1]["official_name"]).casefold()
                ):
                    raise WlxError(f"WLX #{collector} card faces must have different names")

                for index, face in enumerate(normalized_faces):
                    side = str(face["side"])
                    other_name = str(normalized_faces[1 - index]["official_name"])
                    (
                        image_file,
                        image_path,
                        image_hash,
                        width,
                        height,
                        published,
                        picture_url,
                    ) = resolve_image(
                        player,
                        collector,
                        face,
                        published_label=f"{collector}-{side}",
                    )
                    face_metadata = {
                        "layout": layout,
                        "side": side,
                        "type_line": str(face.get("type_line", "")).strip(),
                        "rules_text": str(face.get("rules_text", "")).strip(),
                        "mana_cost": str(face.get("mana_cost", "")).strip(),
                        "mana_value": str(face.get("mana_value", "")).strip(),
                        "colors": normalize_colors(str(face.get("colors", ""))),
                        "color_identity": normalize_colors(str(face.get("color_identity", ""))),
                        "power_toughness": str(face.get("power_toughness", "")).strip(),
                        "loyalty": str(face.get("loyalty", "")).strip(),
                        "defense": str(face.get("defense", "")).strip(),
                    }
                    face_name = str(face["official_name"])
                    resolved.append(
                        ResolvedPrinting(
                            player=player,
                            card_kind=card_kind,
                            card_key="official:" + face_name.casefold(),
                            card_name=face_name,
                            custom_definition=None,
                            flavor_name=str(face.get("flavor_name", "")).strip(),
                            collector_number=collector,
                            printing_uuid=printing_uuid,
                            rarity=rarity,
                            image_file=image_file,
                            image_path=image_path,
                            image_sha256=image_hash,
                            image_width=width,
                            image_height=height,
                            published_image_path=published,
                            picture_url=picture_url,
                            notes=str(raw.get("notes", "")).strip(),
                            face_metadata=face_metadata,
                            transform_into=other_name,
                        )
                    )
                continue

            if card_kind == "official_token":
                creator_card = str(raw.get("creator_card", "")).strip()
                token = raw.get("token_metadata")
                if not creator_card or not isinstance(token, dict):
                    raise WlxError(f"WLX #{collector} has malformed official token data")
                token_name = str(token.get("name", ""))
                type_line = str(token.get("type_line", "")).strip()
                if not token_name.strip() or not type_line:
                    raise WlxError(f"WLX #{collector} token is missing its name or type line")
                normalize_colors(str(token.get("colors", "")))
                normalize_colors(str(token.get("color_identity", "")))
                reverse_related = token.get("reverse_related")
                if not isinstance(reverse_related, list) or not reverse_related:
                    raise WlxError(f"WLX #{collector} token has no creating-card relation")
                if not any(
                    isinstance(relation, dict)
                    and str(relation.get("name", "")).casefold() == creator_card.casefold()
                    for relation in reverse_related
                ):
                    raise WlxError(
                        f"WLX #{collector} token is not linked back to {creator_card!r}"
                    )
                tablerow = str(token.get("tablerow", "")).strip()
                if tablerow:
                    try:
                        int(tablerow)
                    except ValueError as exc:
                        raise WlxError(f"WLX #{collector} token has an invalid table row") from exc
                (
                    image_file,
                    image_path,
                    image_hash,
                    width,
                    height,
                    published,
                    picture_url,
                ) = resolve_image(player, collector, raw, published_label=collector)
                resolved.append(
                    ResolvedPrinting(
                        player=player,
                        card_kind=card_kind,
                        card_key="official-token:" + token_name.casefold(),
                        card_name=token_name,
                        custom_definition=None,
                        flavor_name="",
                        collector_number=collector,
                        printing_uuid=printing_uuid,
                        rarity=rarity,
                        image_file=image_file,
                        image_path=image_path,
                        image_sha256=image_hash,
                        image_width=width,
                        image_height=height,
                        published_image_path=published,
                        picture_url=picture_url,
                        notes=str(raw.get("notes", "")).strip(),
                        token_metadata=token,
                    )
                )
                continue

            custom_definition: CustomDefinition | None = None
            if card_kind == "official":
                requested = str(raw.get("official_name", "")).strip()
                if not requested:
                    raise WlxError(f"WLX #{collector} has no official card name")
                card_name = cached_official_name(official_cache, requested)
                card_key = "official:" + card_name.casefold()
            elif card_kind == "custom":
                custom_id = str(raw.get("custom_card_id", "")).strip()
                custom_definition = custom_by_id.get(custom_id)
                if custom_definition is None:
                    raise WlxError(f"WLX #{collector} references missing custom card {custom_id!r}")
                card_name = custom_definition.name
                card_key = custom_id
            else:
                raise WlxError(
                    f"WLX #{collector} card_kind must be official, official_token, or custom"
                )
            (
                image_file,
                image_path,
                image_hash,
                width,
                height,
                published,
                picture_url,
            ) = resolve_image(player, collector, raw, published_label=collector)
            resolved.append(
                ResolvedPrinting(
                    player=player,
                    card_kind=card_kind,
                    card_key=card_key,
                    card_name=card_name,
                    custom_definition=custom_definition,
                    flavor_name=str(raw.get("flavor_name", "")).strip(),
                    collector_number=collector,
                    printing_uuid=printing_uuid,
                    rarity=rarity,
                    image_file=image_file,
                    image_path=image_path,
                    image_sha256=image_hash,
                    image_width=width,
                    image_height=height,
                    published_image_path=published,
                    picture_url=picture_url,
                    notes=str(raw.get("notes", "")).strip(),
                )
            )

    creator_names = {
        item.card_name.casefold()
        for item in resolved
        if item.card_kind != "official_token"
    }
    for item in resolved:
        if item.token_metadata is None:
            continue
        relations = item.token_metadata.get("reverse_related", [])
        linked_names = {
            str(relation.get("name", "")).casefold()
            for relation in relations
            if isinstance(relation, dict)
        }
        if not linked_names.intersection(creator_names):
            raise WlxError(
                f"WLX #{item.collector_number} token has no active creating card face in WLX"
            )

    if not resolved:
        raise WlxError("No active WLX printings were found")
    active_state = {
        key for key, value in collectors_state.items() if isinstance(value, dict) and value.get("status") == "active"
    }
    if active_state != seen_collectors:
        missing = sorted(active_state - seen_collectors)
        extra = sorted(seen_collectors - active_state)
        raise WlxError(f"Catalog/state mismatch; missing={missing}, unexpected={extra}")
    next_collector = state.get("next_collector")
    if not isinstance(next_collector, int) or next_collector <= max(int(value) for value in collectors_state):
        raise WlxError("automation/state.json next_collector must be greater than every used collector")

    return config, state, sorted(resolved, key=lambda item: int(item.collector_number))


def custom_prop_values(definition: CustomDefinition) -> list[tuple[str, str]]:
    main_type = main_type_from_type_line(definition.type_line)
    result = [
        ("layout", definition.layout),
        ("side", definition.side),
        ("type", definition.type_line),
        ("maintype", main_type),
        ("manacost", definition.mana_cost),
        ("cmc", definition.mana_value),
        ("colors", definition.colors),
        ("coloridentity", definition.color_identity),
        ("pt", definition.power_toughness),
        ("loyalty", definition.loyalty),
        ("defense", definition.defense),
    ]
    return [(key, value) for key, value in result if value != ""]


def face_prop_values(metadata: dict[str, str]) -> list[tuple[str, str]]:
    type_line = metadata.get("type_line", "")
    result = [
        ("layout", metadata.get("layout", "")),
        ("side", metadata.get("side", "")),
        ("type", type_line),
        ("maintype", main_type_from_type_line(type_line)),
        ("manacost", metadata.get("mana_cost", "")),
        ("cmc", metadata.get("mana_value", "")),
        ("colors", metadata.get("colors", "")),
        ("coloridentity", metadata.get("color_identity", "")),
        ("pt", metadata.get("power_toughness", "")),
        ("loyalty", metadata.get("loyalty", "")),
        ("defense", metadata.get("defense", "")),
    ]
    return [(key, value) for key, value in result if value != ""]


def token_prop_values(metadata: dict[str, Any]) -> list[tuple[str, str]]:
    type_line = str(metadata.get("type_line", ""))
    result = [
        ("type", type_line),
        (
            "maintype",
            str(metadata.get("main_type", "")) or main_type_from_type_line(type_line),
        ),
        ("manacost", str(metadata.get("mana_cost", ""))),
        ("cmc", str(metadata.get("mana_value", ""))),
        ("colors", str(metadata.get("colors", ""))),
        ("coloridentity", str(metadata.get("color_identity", ""))),
        ("pt", str(metadata.get("power_toughness", ""))),
        ("loyalty", str(metadata.get("loyalty", ""))),
        ("defense", str(metadata.get("defense", ""))),
    ]
    return [(key, value) for key, value in result if value != ""]


def xml_bytes(config: dict[str, Any], printings: Iterable[ResolvedPrinting]) -> bytes:
    printings = list(printings)
    base_url = normalize_base_url(str(config["public_base_url"]))
    root = ET.Element("cockatrice_carddatabase", {"version": "4"})
    info = ET.SubElement(root, "info")
    ET.SubElement(info, "author").text = str(config.get("author", "Alex"))
    ET.SubElement(info, "createdAt").text = str(config["release_created_at"])
    ET.SubElement(info, "sourceUrl").text = url_for(base_url, "manifest.json")
    ET.SubElement(info, "sourceVersion").text = str(config["version"])

    sets = ET.SubElement(root, "sets")
    set_node = ET.SubElement(sets, "set")
    ET.SubElement(set_node, "name").text = str(config["set_code"])
    ET.SubElement(set_node, "longname").text = str(config["set_name"])
    ET.SubElement(set_node, "settype").text = "Custom"
    ET.SubElement(set_node, "releasedate").text = str(config["release_date"])
    ET.SubElement(set_node, "priority").text = str(config.get("set_priority", 9999))

    grouped: dict[str, list[ResolvedPrinting]] = defaultdict(list)
    for printing in printings:
        grouped[printing.card_key].append(printing)
    cards_node = ET.SubElement(root, "cards")
    ordered_groups = sorted(grouped.values(), key=lambda group: group[0].card_name.casefold())
    for group in ordered_groups:
        first = group[0]
        card_node = ET.SubElement(cards_node, "card")
        ET.SubElement(card_node, "name").text = first.card_name
        if first.card_kind == "custom":
            assert first.custom_definition is not None
            definition = first.custom_definition
            if definition.text:
                ET.SubElement(card_node, "text").text = definition.text
            prop_node = ET.SubElement(card_node, "prop")
            for key, value in custom_prop_values(definition):
                ET.SubElement(prop_node, key).text = value
        elif first.face_metadata is not None:
            if first.face_metadata.get("rules_text"):
                ET.SubElement(card_node, "text").text = first.face_metadata["rules_text"]
            prop_node = ET.SubElement(card_node, "prop")
            for key, value in face_prop_values(first.face_metadata):
                ET.SubElement(prop_node, key).text = value
        elif first.token_metadata is not None:
            if str(first.token_metadata.get("rules_text", "")):
                ET.SubElement(card_node, "text").text = str(
                    first.token_metadata["rules_text"]
                )
            prop_node = ET.SubElement(card_node, "prop")
            for key, value in token_prop_values(first.token_metadata):
                ET.SubElement(prop_node, key).text = value
        for printing in sorted(group, key=lambda item: int(item.collector_number)):
            attributes = {
                "uuid": printing.printing_uuid,
                "picurl": printing.picture_url,
                "num": printing.collector_number,
                "rarity": printing.rarity,
            }
            if printing.flavor_name:
                attributes["flavorName"] = printing.flavor_name
            set_printing = ET.SubElement(card_node, "set", attributes)
            set_printing.text = str(config["set_code"])
        if first.transform_into:
            related = ET.SubElement(card_node, "related", {"attach": "transform"})
            related.text = first.transform_into
        if first.token_metadata is not None:
            seen_relations: set[tuple[tuple[str, str], ...]] = set()
            for printing in group:
                metadata = printing.token_metadata or {}
                raw_relations = metadata.get("reverse_related", [])
                if not isinstance(raw_relations, list):
                    continue
                for raw_relation in raw_relations:
                    if not isinstance(raw_relation, dict):
                        continue
                    name = str(raw_relation.get("name", "")).strip()
                    if not name:
                        continue
                    attributes = {
                        key: str(raw_relation[key])
                        for key in (
                            "count",
                            "exclude",
                            "attach",
                            "persistent",
                            "facedown",
                        )
                        if str(raw_relation.get(key, ""))
                    }
                    relation_key = tuple(sorted({"name": name, **attributes}.items()))
                    if relation_key in seen_relations:
                        continue
                    seen_relations.add(relation_key)
                    reverse_related = ET.SubElement(
                        card_node, "reverse-related", attributes
                    )
                    reverse_related.text = name
        if first.card_kind == "custom":
            assert first.custom_definition is not None
            definition = first.custom_definition
            if definition.token:
                ET.SubElement(card_node, "token").text = "true"
            main_type = main_type_from_type_line(definition.type_line)
            ET.SubElement(card_node, "tablerow").text = str(table_row_for(main_type))
        elif first.token_metadata is not None:
            ET.SubElement(card_node, "token").text = "true"
            token_row = str(first.token_metadata.get("tablerow", "")).strip()
            if not token_row:
                token_row = str(
                    table_row_for(
                        str(first.token_metadata.get("main_type", ""))
                        or main_type_from_type_line(
                            str(first.token_metadata.get("type_line", ""))
                        )
                    )
                )
            ET.SubElement(card_node, "tablerow").text = token_row
        elif first.face_metadata is not None:
            main_type = main_type_from_type_line(first.face_metadata.get("type_line", ""))
            ET.SubElement(card_node, "tablerow").text = str(table_row_for(main_type))

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def render_template(source: Path, destination: Path, tokens: dict[str, str]) -> None:
    payload = source.read_text(encoding="utf-8")
    for marker, value in tokens.items():
        payload = payload.replace(marker, value)
    newline = "\r\n" if destination.suffix.lower() == ".bat" else "\n"
    destination.write_text(payload, encoding="utf-8", newline=newline)


def deterministic_zip(source_dir: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in source_dir.iterdir() if item.is_file()):
            info = zipfile.ZipInfo(path.name, date_time=(2026, 8, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())


def write_resolved_csv(path: Path, printings: Iterable[ResolvedPrinting]) -> None:
    fields = [
        "player",
        "card_kind",
        "card_name",
        "flavor_name",
        "set_code",
        "collector_number",
        "uuid",
        "rarity",
        "published_image",
        "picture_url",
        "sha256",
        "dimensions",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for printing in printings:
            writer.writerow(
                {
                    "player": printing.player,
                    "card_kind": printing.card_kind,
                    "card_name": printing.card_name,
                    "flavor_name": printing.flavor_name,
                    "set_code": "WLX",
                    "collector_number": printing.collector_number,
                    "uuid": printing.printing_uuid,
                    "rarity": printing.rarity,
                    "published_image": printing.published_image_path,
                    "picture_url": printing.picture_url,
                    "sha256": printing.image_sha256,
                    "dimensions": f"{printing.image_width}x{printing.image_height}",
                }
            )


def _replace_directory(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.replace(destination)


def _replace_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.replace(destination)


def build_repository(root: Path) -> dict[str, Any]:
    """Validate and atomically replace every generated public file."""
    root = root.resolve()
    config, _state, printings = validate_repository(root)
    base_url = normalize_base_url(str(config["public_base_url"]))
    set_code = str(config["set_code"])
    xml_filename = str(config["xml_filename"])
    installer_zip_name = str(config["installer_zip_filename"])
    staging = Path(tempfile.mkdtemp(prefix="wlx-publish-", dir=root))
    try:
        customsets_dir = staging / "customsets"
        images_dir = staging / "images" / set_code
        installer_dir = staging / "cockatrice-installer"
        customsets_dir.mkdir(parents=True)
        images_dir.mkdir(parents=True)
        installer_dir.mkdir(parents=True)

        xml_path = customsets_dir / xml_filename
        xml_path.write_bytes(xml_bytes(config, printings))
        parsed = ET.parse(xml_path)
        if parsed.getroot().tag != "cockatrice_carddatabase" or parsed.getroot().attrib.get("version") != "4":
            raise WlxError("Generated XML failed its Cockatrice v4 structural check")

        for printing in printings:
            target = staging / printing.published_image_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(printing.image_path, target)
            if sha256_file(target) != printing.image_sha256:
                raise WlxError(f"Published image hash mismatch for WLX #{printing.collector_number}")

        catalog_payload = {
            "schema_version": 2,
            "package_id": config["package_id"],
            "display_name": config["display_name"],
            "version": config["version"],
            "set_code": set_code,
            "cards": [
                {
                    "player": printing.player,
                    "card_kind": printing.card_kind,
                    "card_name": printing.card_name,
                    "flavor_name": printing.flavor_name,
                    "set_code": set_code,
                    "set_name": config["set_name"],
                    "collector_number": printing.collector_number,
                    "uuid": printing.printing_uuid,
                    "rarity": printing.rarity,
                    "image": printing.published_image_path,
                    "picture_url": printing.picture_url,
                    "sha256": printing.image_sha256,
                    "dimensions": [printing.image_width, printing.image_height],
                }
                for printing in printings
            ],
        }
        write_json(staging / "catalog.json", catalog_payload)
        write_resolved_csv(staging / "catalog.resolved.csv", printings)

        manifest_url = url_for(base_url, "manifest.json")
        source_dir = source_path(root, INSTALLER_SOURCE_RELATIVE)
        shortcut_icon_path = source_dir / "WLX_Shortcut.ico"
        try:
            shortcut_icon = shortcut_icon_path.read_bytes()
        except FileNotFoundError as exc:
            raise WlxError(f"Required shortcut icon is missing: {shortcut_icon_path.relative_to(root)}") from exc
        if len(shortcut_icon) < 22 or shortcut_icon[:4] != b"\x00\x00\x01\x00":
            raise WlxError("WLX_Shortcut.ico is not a valid Windows icon container")
        icon_count = int.from_bytes(shortcut_icon[4:6], "little")
        if icon_count < 1 or len(shortcut_icon) < 6 + (16 * icon_count):
            raise WlxError("WLX_Shortcut.ico has an invalid image directory")
        tokens = {
            "__MANIFEST_URL__": manifest_url,
            "__PACKAGE_VERSION__": str(config["version"]),
            "__DISPLAY_NAME__": str(config["display_name"]),
            "__PACKAGE_ID__": str(config["package_id"]),
            "__INSTALL_FOLDER__": str(config["install_folder"]),
            "__LEGACY_INSTALL_FOLDER__": str(config.get("legacy_install_folder", "")),
            "__SHORTCUT_ICON_BASE64__": base64.b64encode(shortcut_icon).decode("ascii"),
            "__SHORTCUT_ICON_SHA256__": hashlib.sha256(shortcut_icon).hexdigest(),
        }
        installer_files = (
            "INSTALL_OR_UPDATE.bat",
            "UPDATE_AND_LAUNCH.bat",
            "REPAIR_ART.bat",
            "UNINSTALL.bat",
            "WLX_Bootstrap.ps1",
            "WLX_Cockatrice_Updater.ps1",
            "README_FOR_PLAYERS.txt",
        )
        for filename in installer_files:
            render_template(source_dir / filename, installer_dir / filename, tokens)
        installer_config = {
            "schema_version": 1,
            "package_id": config["package_id"],
            "display_name": config["display_name"],
            "version": config["version"],
            "manifest_url": manifest_url,
            "install_folder": config["install_folder"],
        }
        write_json(installer_dir / "installer_config.json", installer_config)
        installer_zip = staging / installer_zip_name
        deterministic_zip(installer_dir, installer_zip)

        manifest_candidates = [xml_path, staging / "catalog.json", installer_zip]
        manifest_candidates.extend(staging / item.published_image_path for item in printings)
        files: list[dict[str, Any]] = []
        for path in manifest_candidates:
            relative = path.relative_to(staging).as_posix()
            files.append(
                {
                    "path": relative,
                    "url": url_for(base_url, relative),
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
            )
        xml_relative = xml_path.relative_to(staging).as_posix()
        physical_printing_ids = {item.printing_uuid for item in printings}
        manifest = {
            "schema_version": 1,
            "publisher_schema_version": 2,
            "package_id": config["package_id"],
            "display_name": config["display_name"],
            "version": config["version"],
            "published_at": config["release_created_at"],
            "release_ready": True,
            "base_url": base_url,
            "cockatrice_xml": {
                "path": xml_relative,
                "url": url_for(base_url, xml_relative),
                "install_filename": xml_filename,
                "sha256": sha256_file(xml_path),
                "size_bytes": xml_path.stat().st_size,
                "database_version": 4,
            },
            "cockatrice_installer": {
                "path": installer_zip_name,
                "url": url_for(base_url, installer_zip_name),
                "sha256": sha256_file(installer_zip),
                "size_bytes": installer_zip.stat().st_size,
            },
            "cards": len({item.card_key for item in printings}),
            "printings_count": len(physical_printing_ids),
            "face_entries_count": len(printings),
            "sets": 1,
            "players": {
                player: len(
                    {item.printing_uuid for item in printings if item.player == player}
                )
                for player in player_names(config)
            },
            "printings": [
                {
                    "collector_number": item.collector_number,
                    "uuid": item.printing_uuid,
                    "card_name": item.card_name,
                    "player": item.player,
                    "image_sha256": item.image_sha256,
                    "picture_url": item.picture_url,
                }
                for item in printings
            ],
            "files": sorted(files, key=lambda entry: entry["path"]),
        }
        write_json(staging / "manifest.json", manifest)

        status_lines = [
            f"# {config['display_name']} — Published Status",
            "",
            f"- Version: `{config['version']}`",
            f"- Set: `{set_code}` — {config['set_name']}",
            f"- Active card identities: **{manifest['cards']}**",
            f"- Active printings: **{manifest['printings_count']}**",
            "",
            "| Player | Active printings |",
            "| --- | ---: |",
        ]
        for player, count in manifest["players"].items():
            status_lines.append(f"| {player} | {count} |")
        status_lines.extend(
            [
                "",
                "This file is generated automatically. Add or replace art through imports/incoming; use Issues only to remove a printing.",
            ]
        )
        (staging / "STATUS.md").write_text(
            "\n".join(status_lines) + "\n", encoding="utf-8", newline="\n"
        )

        publication = published_root(root)
        documentation = docs_root(root)
        _replace_directory(staging / "customsets", publication / "customsets")
        _replace_directory(
            staging / "images" / set_code, publication / "images" / set_code
        )
        _replace_directory(
            staging / "cockatrice-installer", publication / "cockatrice-installer"
        )
        for filename in (
            "catalog.json",
            "catalog.resolved.csv",
            "manifest.json",
            installer_zip_name,
        ):
            _replace_file(staging / filename, publication / filename)
        _replace_file(staging / "STATUS.md", documentation / STATUS_RELATIVE)
        for cleanup_root in {root, publication}:
            for obsolete in cleanup_root.glob(
                "Willexs_Whimsical_Arts_Friend_Installer_v*.zip"
            ):
                obsolete.unlink()
            obsolete_stable = (
                cleanup_root / "Willexs_Whimsical_Arts_Friend_Installer.zip"
            )
            if obsolete_stable.exists():
                obsolete_stable.unlink()
            obsolete_directory = cleanup_root / "friend-installer"
            if obsolete_directory.exists():
                shutil.rmtree(obsolete_directory)
        old_readme = root / "README.txt"
        if old_readme.exists():
            old_readme.unlink()
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def find_printing(
    catalogs: dict[str, dict[str, Any]], collector_number: str
) -> tuple[str, dict[str, Any], int, dict[str, Any]]:
    matches: list[tuple[str, dict[str, Any], int, dict[str, Any]]] = []
    for player, catalog in catalogs.items():
        for index, printing in enumerate(catalog["printings"]):
            if str(printing.get("collector_number", "")) == collector_number:
                matches.append((player, catalog, index, printing))
    if not matches:
        raise WlxError(f"WLX #{collector_number} does not exist")
    if len(matches) > 1:
        raise WlxError(f"WLX #{collector_number} is duplicated across player catalogs")
    return matches[0]


def find_custom_definition(
    catalogs: dict[str, dict[str, Any]], requested_name: str
) -> tuple[str, dict[str, Any], int, dict[str, Any]]:
    matches: list[tuple[str, dict[str, Any], int, dict[str, Any]]] = []
    for player, catalog in catalogs.items():
        for index, definition in enumerate(catalog["custom_cards"]):
            if str(definition.get("name", "")).casefold() == requested_name.casefold():
                matches.append((player, catalog, index, definition))
    if not matches:
        raise WlxError(f"No WLX original card named {requested_name!r} exists")
    if len(matches) > 1:
        raise WlxError(f"More than one WLX original card is named {requested_name!r}")
    return matches[0]


def find_custom_definition_by_id(
    catalogs: dict[str, dict[str, Any]], custom_card_id: str
) -> tuple[str, dict[str, Any], int, dict[str, Any]]:
    matches: list[tuple[str, dict[str, Any], int, dict[str, Any]]] = []
    for player, catalog in catalogs.items():
        for index, definition in enumerate(catalog["custom_cards"]):
            if str(definition.get("custom_card_id", "")) == custom_card_id:
                matches.append((player, catalog, index, definition))
    if not matches:
        raise WlxError(f"No WLX original card definition with ID {custom_card_id!r} exists")
    if len(matches) > 1:
        raise WlxError(f"More than one WLX original card uses ID {custom_card_id!r}")
    return matches[0]


def all_custom_names(catalogs: dict[str, dict[str, Any]]) -> set[str]:
    return {
        str(item.get("name", "")).casefold()
        for catalog in catalogs.values()
        for item in catalog["custom_cards"]
    }


def persist_catalogs(root: Path, catalogs: dict[str, dict[str, Any]]) -> None:
    for player, catalog in catalogs.items():
        catalog["printings"] = sorted(
            catalog["printings"], key=lambda item: int(str(item["collector_number"]))
        )
        catalog["custom_cards"] = sorted(
            catalog["custom_cards"], key=lambda item: str(item.get("name", "")).casefold()
        )
        write_json(player_catalog_path(root, player), catalog)
