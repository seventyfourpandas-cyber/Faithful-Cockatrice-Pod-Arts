#!/usr/bin/env python3
"""Automatic filename-driven importer for Willex's Whimsical Arts.

Drop single-faced official MTG card images into imports/incoming (or a player
subfolder). The script verifies the filename as an exact Scryfall card name,
adds a new WLX printing, updates the catalog/XML/manifest, and removes the
incoming image only after validation succeeds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import xml.etree.ElementTree as ET

from PIL import Image, UnidentifiedImageError

SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
UNSUPPORTED_MULTIFACE_LAYOUTS = {
    "transform",
    "modal_dfc",
    "double_faced_token",
    "reversible_card",
    "split",
    "flip",
    "adventure",
    "art_series",
}


class ImporterFailure(RuntimeError):
    """A repository/configuration failure that should stop the whole run."""


class TemporaryLookupFailure(RuntimeError):
    """A temporary Scryfall/network failure; input should remain in incoming."""


@dataclass
class Candidate:
    source_path: Path
    player: str
    requested_name: str
    card_name: str
    sha256: str
    width: int
    height: int
    extension: str
    scryfall_id: str
    layout: str
    collector_number: str = ""
    printing_uuid: str = ""
    published_relpath: str = ""
    picture_url: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_base_url(value: str) -> str:
    value = value.strip()
    return value if value.endswith("/") else value + "/"


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ImporterFailure(f"Required file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ImporterFailure(f"Invalid JSON in {path}: {exc}") from exc


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(data)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_xml(path: Path, tree: ET.ElementTree) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temp_name = handle.name
    tree.write(temp_name, encoding="utf-8", xml_declaration=True)
    os.replace(temp_name, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_dimensions(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            return int(image.width), int(image.height)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError(f"The file is not a readable image: {exc}") from exc


def increment_version(version: str, mode: str) -> str:
    parts = version.strip().split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ImporterFailure(
            f"Version must use major.minor.patch numbers; found {version!r}."
        )
    major, minor, patch = map(int, parts)
    if mode == "major":
        return f"{major + 1}.0.0"
    if mode == "minor":
        return f"{major}.{minor + 1}.0"
    if mode == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ImporterFailure(f"Unsupported version_bump value: {mode!r}")


def exact_card_lookup(name: str, user_agent: str, fixture_dir: Path | None) -> dict[str, Any]:
    if fixture_dir is not None:
        fixture = fixture_dir / (hashlib.sha256(name.encode("utf-8")).hexdigest() + ".json")
        if not fixture.exists():
            raise LookupError(f"No exact official card named {name!r} was found.")
        return load_json(fixture)

    query = urllib.parse.urlencode({"exact": name})
    url = f"https://api.scryfall.com/cards/named?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        time.sleep(0.1)
        return payload
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            suggestion = fuzzy_suggestion(name, user_agent)
            message = f"No exact official card named {name!r} was found."
            if suggestion and suggestion.casefold() != name.casefold():
                message += f" Possible match: {suggestion!r}."
            raise LookupError(message) from exc
        if exc.code == 429 or 500 <= exc.code <= 599:
            raise TemporaryLookupFailure(
                f"Scryfall temporarily returned HTTP {exc.code}; the image was left in incoming."
            ) from exc
        raise TemporaryLookupFailure(
            f"Scryfall request failed with HTTP {exc.code}; the image was left in incoming."
        ) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise TemporaryLookupFailure(
            f"Could not contact Scryfall ({exc}); the image was left in incoming."
        ) from exc


def fuzzy_suggestion(name: str, user_agent: str) -> str | None:
    query = urllib.parse.urlencode({"fuzzy": name})
    url = f"https://api.scryfall.com/cards/named?{query}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": user_agent, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        time.sleep(0.1)
        return payload.get("name")
    except Exception:
        return None


def discover_images(incoming_root: Path, players: dict[str, str], default_player: str) -> list[tuple[Path, str]]:
    discovered: list[tuple[Path, str]] = []
    if not incoming_root.exists():
        incoming_root.mkdir(parents=True, exist_ok=True)
        return discovered

    for path in sorted(incoming_root.rglob("*"), key=lambda p: str(p).casefold()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
            continue
        relative = path.relative_to(incoming_root)
        if len(relative.parts) == 1:
            player = default_player
        else:
            folder = relative.parts[0].casefold()
            if folder not in players:
                player = ""
            else:
                player = players[folder]
        discovered.append((path, player))
    return discovered


def safe_attention_destination(attention_root: Path, source: Path, player: str, digest: str) -> Path:
    folder = attention_root / (player.casefold() if player else "unknown-player")
    folder.mkdir(parents=True, exist_ok=True)
    base = f"{source.stem}--{digest[:8]}{source.suffix.lower()}"
    destination = folder / base
    index = 2
    while destination.exists():
        destination = folder / f"{source.stem}--{digest[:8]}-{index}{source.suffix.lower()}"
        index += 1
    return destination


def move_to_attention(attention_root: Path, source: Path, player: str, message: str) -> tuple[str, str]:
    try:
        digest = sha256_file(source)
    except OSError:
        digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()
    destination = safe_attention_destination(attention_root, source, player, digest)
    shutil.move(str(source), str(destination))
    error_path = destination.with_suffix(destination.suffix + ".error.txt")
    error_path.write_text(
        "This card was not imported.\n\n"
        + message.strip()
        + "\n\nRename/fix the image, then move it back into imports/incoming.\n",
        encoding="utf-8",
    )
    return destination.as_posix(), error_path.as_posix()


def next_collector_number(catalog_cards: Iterable[dict[str, Any]]) -> int:
    numeric: list[int] = []
    for card in catalog_cards:
        value = str(card.get("collector_number", ""))
        if value.isdigit():
            numeric.append(int(value))
    return (max(numeric) if numeric else 0) + 1


def deterministic_uuid(package_id: str, set_code: str, collector: str, card_name: str, digest: str) -> str:
    seed = f"{package_id}|{set_code}|{collector}|{card_name}|{digest}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def parse_xml(path: Path) -> ET.ElementTree:
    try:
        return ET.parse(path)
    except FileNotFoundError as exc:
        raise ImporterFailure(f"Cockatrice XML is missing: {path}") from exc
    except ET.ParseError as exc:
        raise ImporterFailure(f"Cockatrice XML is invalid: {path}: {exc}") from exc


def ensure_xml_printing(
    tree: ET.ElementTree,
    card_name: str,
    set_code: str,
    collector_number: str,
    printing_uuid: str,
    picture_url: str,
    rarity: str,
) -> None:
    root = tree.getroot()
    cards_node = root.find("cards")
    if cards_node is None:
        cards_node = ET.SubElement(root, "cards")

    matching_card: ET.Element | None = None
    for card in cards_node.findall("card"):
        name_node = card.find("name")
        if name_node is not None and (name_node.text or "") == card_name:
            matching_card = card
            break

    if matching_card is None:
        matching_card = ET.Element("card")
        name_node = ET.SubElement(matching_card, "name")
        name_node.text = card_name
        cards_node.append(matching_card)

    for set_node in matching_card.findall("set"):
        if set_node.get("uuid") == printing_uuid or (
            (set_node.text or "") == set_code and set_node.get("num") == collector_number
        ):
            raise ImporterFailure(
                f"XML already contains printing {set_code} {collector_number} / {printing_uuid}."
            )

    set_node = ET.Element(
        "set",
        {
            "uuid": printing_uuid,
            "picurl": picture_url,
            "num": collector_number,
            "rarity": rarity,
        },
    )
    set_node.text = set_code

    children = list(matching_card)
    insert_at = 1
    for index, child in enumerate(children):
        if child.tag == "set":
            insert_at = index + 1
        elif child.tag in {"related", "tablerow"}:
            insert_at = min(insert_at, index)
            break
        else:
            insert_at = index + 1
    matching_card.insert(insert_at, set_node)

    card_nodes = list(cards_node.findall("card"))
    for card in card_nodes:
        cards_node.remove(card)
    card_nodes.sort(
        key=lambda card: ((card.findtext("name") or "").casefold(), card.findtext("name") or "")
    )
    for card in card_nodes:
        cards_node.append(card)


def update_xml_info(tree: ET.ElementTree, version: str, base_url: str, manifest_path: str, now: str) -> None:
    root = tree.getroot()
    info = root.find("info")
    if info is None:
        info = ET.Element("info")
        root.insert(0, info)

    def set_text(tag: str, value: str) -> None:
        node = info.find(tag)
        if node is None:
            node = ET.SubElement(info, tag)
        node.text = value

    set_text("createdAt", now)
    set_text("sourceUrl", base_url + manifest_path.replace("\\", "/"))
    set_text("sourceVersion", version)


def make_file_record(repo_root: Path, relative_path: str, base_url: str) -> dict[str, Any]:
    path = repo_root / relative_path
    if not path.is_file():
        raise ImporterFailure(f"Manifest expects a file that is missing: {relative_path}")
    return {
        "path": relative_path.replace("\\", "/"),
        "url": base_url + relative_path.replace("\\", "/"),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def rebuild_manifest(
    repo_root: Path,
    manifest: dict[str, Any],
    catalog: dict[str, Any],
    config: dict[str, Any],
    version: str,
    now: str,
) -> dict[str, Any]:
    base_url = normalize_base_url(config["public_base_url"])
    catalog_path = config["catalog_path"].replace("\\", "/")
    xml_path = config["cockatrice_xml_path"].replace("\\", "/")
    cards = catalog.get("cards", [])

    manifest["schema_version"] = manifest.get("schema_version", 1)
    manifest["package_id"] = config["package_id"]
    manifest["display_name"] = config["display_name"]
    manifest["version"] = version
    manifest["published_at"] = now
    manifest["release_ready"] = True
    manifest["base_url"] = base_url
    manifest["cards"] = len(cards)
    manifest["face_entries_count"] = len(cards)
    manifest["printings_count"] = len({str(card.get("uuid", "")) for card in cards if card.get("uuid")})
    manifest["sets"] = len({str(card.get("set_code", "")) for card in cards if card.get("set_code")})

    player_uuids: dict[str, set[str]] = {
        display_name: set() for display_name in config.get("players", {}).values()
    }
    for card in cards:
        player = str(card.get("player", ""))
        printing = str(card.get("uuid", ""))
        if player:
            player_uuids.setdefault(player, set())
            if printing:
                player_uuids[player].add(printing)
    manifest["players"] = {name: len(ids) for name, ids in player_uuids.items()}

    printings: list[dict[str, Any]] = []
    for card in cards:
        printings.append(
            {
                "collector_number": str(card.get("collector_number", "")),
                "uuid": str(card.get("uuid", "")),
                "card_name": str(card.get("card_name", "")),
                "player": str(card.get("player", "")),
                "image_sha256": str(card.get("sha256", "")),
                "picture_url": str(card.get("picture_url", "")),
            }
        )
    printings.sort(key=lambda item: (int(item["collector_number"]) if item["collector_number"].isdigit() else 10**9, item["card_name"].casefold()))
    manifest["printings"] = printings

    xml_record = make_file_record(repo_root, xml_path, base_url)
    cockatrice_xml = manifest.setdefault("cockatrice_xml", {})
    cockatrice_xml.update(
        {
            "path": xml_path,
            "url": xml_record["url"],
            "install_filename": cockatrice_xml.get("install_filename", Path(xml_path).name),
            "sha256": xml_record["sha256"],
            "size_bytes": xml_record["size_bytes"],
            "database_version": 4,
        }
    )

    managed_paths: set[str] = {catalog_path, xml_path}
    for card in cards:
        image_path = str(card.get("image", "")).replace("\\", "/")
        if image_path:
            managed_paths.add(image_path)

    for installer_key in ("cockatrice_installer", "friend_installer"):
        installer = manifest.get(installer_key)
        if isinstance(installer, dict) and installer.get("path"):
            managed_paths.add(str(installer["path"]).replace("\\", "/"))

    for old_record in manifest.get("files", []):
        if isinstance(old_record, dict) and old_record.get("path"):
            old_path = str(old_record["path"]).replace("\\", "/")
            if (repo_root / old_path).is_file() and not old_path.startswith(("imports/", "tools/", ".github/")):
                managed_paths.add(old_path)

    files = [make_file_record(repo_root, path, base_url) for path in sorted(managed_paths, key=str.casefold)]
    manifest["files"] = files

    for installer_key in ("cockatrice_installer", "friend_installer"):
        installer = manifest.get(installer_key)
        if isinstance(installer, dict) and installer.get("path"):
            path = str(installer["path"]).replace("\\", "/")
            if (repo_root / path).is_file():
                record = make_file_record(repo_root, path, base_url)
                installer.update(record)

    return manifest


def validate_repository(
    repo_root: Path,
    catalog: dict[str, Any],
    xml_tree: ET.ElementTree,
    new_candidates: list[Candidate],
) -> None:
    cards = catalog.get("cards")
    if not isinstance(cards, list):
        raise ImporterFailure("catalog.json must contain a cards array.")

    catalog_by_uuid = {str(card.get("uuid")): card for card in cards}
    for candidate in new_candidates:
        catalog_card = catalog_by_uuid.get(candidate.printing_uuid)
        if not catalog_card:
            raise ImporterFailure(f"Validation failed: {candidate.card_name} is missing from catalog.json.")
        image_path = repo_root / candidate.published_relpath
        if not image_path.is_file():
            raise ImporterFailure(f"Validation failed: published image is missing: {candidate.published_relpath}")
        if sha256_file(image_path) != candidate.sha256:
            raise ImporterFailure(f"Validation failed: image hash changed for {candidate.card_name}.")

        found_xml = False
        for card_node in xml_tree.getroot().findall("./cards/card"):
            if card_node.findtext("name") != candidate.card_name:
                continue
            for set_node in card_node.findall("set"):
                if set_node.get("uuid") == candidate.printing_uuid and set_node.get("picurl") == candidate.picture_url:
                    found_xml = True
                    break
        if not found_xml:
            raise ImporterFailure(f"Validation failed: {candidate.card_name} is missing from Cockatrice XML.")


def build_candidate(
    source_path: Path,
    player: str,
    user_agent: str,
    fixture_dir: Path | None,
) -> Candidate:
    requested_name = source_path.stem.strip()
    if not requested_name:
        raise ValueError("The image filename does not contain a card name.")
    if not player:
        raise ValueError(
            "The image is inside an unknown player folder. Use incoming/alex, will, miguel, or jay."
        )

    digest = sha256_file(source_path)
    width, height = get_dimensions(source_path)
    card = exact_card_lookup(requested_name, user_agent, fixture_dir)
    card_name = str(card.get("name", "")).strip()
    if not card_name:
        raise ValueError("Scryfall returned a card without a name.")
    layout = str(card.get("layout", "normal"))
    if card.get("card_faces") or layout in UNSUPPORTED_MULTIFACE_LAYOUTS:
        raise ValueError(
            f"{card_name!r} uses the {layout!r} multi-face/special layout. "
            "This first importer version handles single-faced official cards only."
        )
    if str(card.get("set_type", "")) in {"token", "memorabilia"}:
        raise ValueError(f"{card_name!r} is a token/memorabilia entry, not a normal official card.")

    extension = source_path.suffix.lower()
    if extension == ".jpeg":
        extension = ".jpg"
    return Candidate(
        source_path=source_path,
        player=player,
        requested_name=requested_name,
        card_name=card_name,
        sha256=digest,
        width=width,
        height=height,
        extension=extension,
        scryfall_id=str(card.get("id", "")),
        layout=layout,
    )


def run(repo_root: Path, config_path: Path, fixture_dir: Path | None = None) -> int:
    config = load_json(config_path)
    required_config = [
        "package_id",
        "display_name",
        "set_code",
        "set_name",
        "default_player",
        "players",
        "default_rarity",
        "public_base_url",
        "catalog_path",
        "manifest_path",
        "cockatrice_xml_path",
        "published_images_dir",
        "incoming_dir",
        "needs_attention_dir",
        "last_run_report",
        "version_bump",
        "scryfall_user_agent",
    ]
    missing = [key for key in required_config if key not in config]
    if missing:
        raise ImporterFailure(f"importer_config.json is missing: {', '.join(missing)}")

    base_url = normalize_base_url(config["public_base_url"])
    catalog_path = repo_root / config["catalog_path"]
    manifest_path = repo_root / config["manifest_path"]
    xml_path = repo_root / config["cockatrice_xml_path"]
    published_dir = repo_root / config["published_images_dir"]
    incoming_root = repo_root / config["incoming_dir"]
    attention_root = repo_root / config["needs_attention_dir"]
    report_path = repo_root / config["last_run_report"]

    catalog = load_json(catalog_path)
    manifest = load_json(manifest_path)
    xml_tree = parse_xml(xml_path)
    catalog_cards = catalog.get("cards")
    if not isinstance(catalog_cards, list):
        raise ImporterFailure("catalog.json must contain a cards array.")

    discovered = discover_images(
        incoming_root,
        {str(k).casefold(): str(v) for k, v in config["players"].items()},
        str(config["default_player"]),
    )
    report: dict[str, Any] = {
        "started_at": utc_now(),
        "finished_at": None,
        "found": len(discovered),
        "imported": [],
        "needs_attention": [],
        "temporary_errors": [],
        "version_before": str(catalog.get("version", manifest.get("version", "0.0.0"))),
        "version_after": str(catalog.get("version", manifest.get("version", "0.0.0"))),
    }

    if not discovered:
        report["finished_at"] = utc_now()
        report["message"] = "No card images were waiting in imports/incoming."
        atomic_write_json(report_path, report)
        print("No card images found in imports/incoming.")
        return 0

    existing_hashes: dict[str, dict[str, Any]] = {
        str(card.get("sha256", "")): card for card in catalog_cards if card.get("sha256")
    }
    candidates: list[Candidate] = []

    for source_path, player in discovered:
        try:
            candidate = build_candidate(
                source_path,
                player,
                str(config["scryfall_user_agent"]),
                fixture_dir,
            )
            duplicate = existing_hashes.get(candidate.sha256)
            if duplicate:
                raise ValueError(
                    "This exact artwork is already published as "
                    f"{duplicate.get('card_name')} ({duplicate.get('set_code')} {duplicate.get('collector_number')})."
                )
            existing_hashes[candidate.sha256] = {"card_name": candidate.card_name}
            candidates.append(candidate)
            print(f"VERIFIED: {candidate.card_name} ({player})")
        except TemporaryLookupFailure as exc:
            report["temporary_errors"].append(
                {"file": source_path.as_posix(), "error": str(exc)}
            )
            print(f"TEMPORARY ERROR: {source_path.name}: {exc}", file=sys.stderr)
        except (LookupError, ValueError, OSError) as exc:
            moved_image, error_file = move_to_attention(
                attention_root, source_path, player, str(exc)
            )
            report["needs_attention"].append(
                {
                    "original_file": source_path.as_posix(),
                    "moved_image": moved_image,
                    "error_file": error_file,
                    "error": str(exc),
                }
            )
            print(f"NEEDS ATTENTION: {source_path.name}: {exc}", file=sys.stderr)

    if candidates:
        start_number = next_collector_number(catalog_cards)
        current_version = str(catalog.get("version", manifest.get("version", "0.0.0")))
        new_version = increment_version(current_version, str(config["version_bump"]))
        now = utc_now()

        original_catalog_bytes = catalog_path.read_bytes()
        original_xml_bytes = xml_path.read_bytes()
        original_manifest_bytes = manifest_path.read_bytes()
        created_destinations: list[Path] = []

        try:
            published_dir.mkdir(parents=True, exist_ok=True)
            for offset, candidate in enumerate(candidates):
                collector = f"{start_number + offset:03d}"
                printing_uuid = deterministic_uuid(
                    str(config["package_id"]),
                    str(config["set_code"]),
                    collector,
                    candidate.card_name,
                    candidate.sha256,
                )
                filename = f"{collector}-{candidate.sha256[:12]}{candidate.extension}"
                relpath = (Path(config["published_images_dir"]) / filename).as_posix()
                destination = repo_root / relpath
                if destination.exists():
                    raise ImporterFailure(f"Refusing to overwrite existing published file: {relpath}")
                shutil.copy2(candidate.source_path, destination)
                created_destinations.append(destination)

                candidate.collector_number = collector
                candidate.printing_uuid = printing_uuid
                candidate.published_relpath = relpath
                candidate.picture_url = base_url + relpath

                entry = {
                    "player": candidate.player,
                    "card_kind": "official",
                    "card_name": candidate.card_name,
                    "flavor_name": "",
                    "set_code": str(config["set_code"]),
                    "set_name": str(config["set_name"]),
                    "collector_number": collector,
                    "uuid": printing_uuid,
                    "rarity": str(config["default_rarity"]),
                    "image": relpath,
                    "picture_url": candidate.picture_url,
                    "sha256": candidate.sha256,
                    "dimensions": [candidate.width, candidate.height],
                }
                catalog_cards.append(entry)
                ensure_xml_printing(
                    xml_tree,
                    candidate.card_name,
                    str(config["set_code"]),
                    collector,
                    printing_uuid,
                    candidate.picture_url,
                    str(config["default_rarity"]),
                )

            catalog_cards.sort(
                key=lambda card: (
                    int(str(card.get("collector_number", "")))
                    if str(card.get("collector_number", "")).isdigit()
                    else 10**9,
                    str(card.get("card_name", "")).casefold(),
                )
            )
            catalog["schema_version"] = catalog.get("schema_version", 2)
            catalog["package_id"] = str(config["package_id"])
            catalog["display_name"] = str(config["display_name"])
            catalog["version"] = new_version
            catalog["set_code"] = str(config["set_code"])
            catalog["cards"] = catalog_cards

            update_xml_info(
                xml_tree,
                new_version,
                base_url,
                str(config["manifest_path"]),
                now,
            )

            atomic_write_json(catalog_path, catalog)
            atomic_write_xml(xml_path, xml_tree)
            manifest = rebuild_manifest(
                repo_root, manifest, catalog, config, new_version, now
            )
            atomic_write_json(manifest_path, manifest)

            # Re-read what was actually written, then validate before deleting inputs.
            written_catalog = load_json(catalog_path)
            written_xml = parse_xml(xml_path)
            validate_repository(repo_root, written_catalog, written_xml, candidates)

            for candidate in candidates:
                candidate.source_path.unlink()
                report["imported"].append(
                    {
                        "card_name": candidate.card_name,
                        "player": candidate.player,
                        "collector_number": candidate.collector_number,
                        "uuid": candidate.printing_uuid,
                        "published_image": candidate.published_relpath,
                        "picture_url": candidate.picture_url,
                    }
                )
                print(
                    f"IMPORTED: {candidate.card_name} -> {config['set_code']} {candidate.collector_number}"
                )

            report["version_after"] = new_version
        except Exception:
            # Restore the three generated metadata files and remove any newly copied
            # published images. Incoming source images have not been deleted unless
            # every validation step already succeeded.
            atomic_write_bytes(catalog_path, original_catalog_bytes)
            atomic_write_bytes(xml_path, original_xml_bytes)
            atomic_write_bytes(manifest_path, original_manifest_bytes)
            for destination in created_destinations:
                try:
                    destination.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

    report["finished_at"] = utc_now()
    report["success_count"] = len(report["imported"])
    report["attention_count"] = len(report["needs_attention"])
    report["temporary_error_count"] = len(report["temporary_errors"])
    atomic_write_json(report_path, report)

    if report["needs_attention"] or report["temporary_errors"]:
        return 2
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (default: current directory).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("importer_config.json"),
        help="Importer config path, relative to the repository root unless absolute.",
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=None,
        help="Offline Scryfall fixture directory for tests.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    config_path = args.config
    if not config_path.is_absolute():
        config_path = repo_root / config_path
    fixture_dir = args.fixture_dir.resolve() if args.fixture_dir else None
    try:
        return run(repo_root, config_path, fixture_dir)
    except ImporterFailure as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"UNEXPECTED FATAL ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
