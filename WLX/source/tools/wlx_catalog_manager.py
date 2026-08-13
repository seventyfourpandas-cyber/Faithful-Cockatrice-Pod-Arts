#!/usr/bin/env python3
"""Apply reviewed bulk metadata edits from WLX/CARD_MANAGER.csv."""

from __future__ import annotations

import argparse
import copy
import csv
import dataclasses
import datetime as dt
import json
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any


SOURCE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SOURCE_ROOT.parents[1]
AUTOMATION_DIR = SOURCE_ROOT / "automation"
sys.path.insert(0, str(AUTOMATION_DIR))
import wlxlib  # noqa: E402


CHANGE_FIELDS = (
    "CHANGE_owner_to",
    "CHANGE_collector_to",
    "CHANGE_rarity_to",
    "CHANGE_front_title_to",
    "CHANGE_back_title_to",
)
LOCKED_FIELDS = tuple(
    field for field in wlxlib.CARD_MANAGER_FIELDS if field not in CHANGE_FIELDS
)
CLEAR_VALUE = "CLEAR"


class CatalogManagerError(RuntimeError):
    """A safe, user-facing manager rejection."""


@dataclasses.dataclass
class PlannedPrinting:
    printing: dict[str, Any]
    original_owner: str
    original_collector: str
    target_owner: str
    target_collector: str
    target_uuid: str
    target_rarity: str
    target_front_title: str
    target_back_title: str
    requested: bool

    @property
    def changed(self) -> bool:
        current_front, current_back = printing_titles(self.printing)
        return any(
            (
                self.target_owner != self.original_owner,
                self.target_collector != self.original_collector,
                self.target_uuid != str(self.printing.get("uuid", "")),
                self.target_rarity != str(self.printing.get("rarity", "")),
                self.target_front_title != current_front,
                self.target_back_title != current_back,
            )
        )


@dataclasses.dataclass(frozen=True)
class ImageMove:
    source: Path
    destination: Path
    record: dict[str, Any]
    new_filename: str


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def normalize_collector(raw: str) -> str:
    value = str(raw).strip().upper()
    value = re.sub(r"^WLX[\s#_-]*", "", value)
    if re.fullmatch(r"[0-9]+\.0+", value):
        value = value.split(".", 1)[0]
    if not value.isdigit() or int(value) < 1:
        raise CatalogManagerError(
            f"Collector number {raw!r} must look like 3, 003, or WLX-003"
        )
    return f"{int(value):03d}"


def exact_player(config: dict[str, Any], requested: str) -> str:
    for player in wlxlib.player_names(config):
        if player.casefold() == requested.strip().casefold():
            return player
    raise CatalogManagerError(
        f"Unknown owner {requested!r}; use Alex, Will, Miguel, or Jay"
    )


def read_manager_rows(root: Path) -> list[dict[str, str]]:
    path = wlxlib.card_manager_path(root)
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except FileNotFoundError as exc:
        raise CatalogManagerError(f"Missing editable manager: {path}") from exc
    with handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != wlxlib.CARD_MANAGER_FIELDS:
            raise CatalogManagerError(
                "CARD_MANAGER.csv columns were renamed, removed, or reordered. "
                "Restore the current file and edit only cells under CHANGE_."
            )
        rows = []
        for raw in reader:
            row = {field: str(raw.get(field) or "") for field in reader.fieldnames}
            if any(value.strip() for value in row.values()):
                rows.append(row)
    return rows


def custom_names(catalogs: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {
        str(definition.get("custom_card_id", "")): str(definition.get("name", ""))
        for catalog in catalogs.values()
        for definition in catalog["custom_cards"]
        if isinstance(definition, dict)
    }


def printing_name(
    printing: dict[str, Any], definitions: dict[str, str]
) -> str:
    kind = str(printing.get("card_kind", ""))
    if kind == "official_double_faced":
        faces = printing.get("faces", [])
        if not isinstance(faces, list):
            return ""
        return " // ".join(
            str(face.get("official_name", ""))
            for face in faces
            if isinstance(face, dict)
        )
    if kind == "official_token":
        token = printing.get("token_metadata", {})
        if isinstance(token, dict):
            return str(token.get("display_name") or token.get("name", "")).rstrip()
        return ""
    if kind == "custom":
        return definitions.get(str(printing.get("custom_card_id", "")), "")
    return str(printing.get("official_name", ""))


def printing_titles(printing: dict[str, Any]) -> tuple[str, str]:
    if printing.get("card_kind") == "official_double_faced":
        faces = printing.get("faces")
        if isinstance(faces, list) and len(faces) == 2:
            return (
                str(faces[0].get("flavor_name", "")),
                str(faces[1].get("flavor_name", "")),
            )
    return str(printing.get("flavor_name", "")), ""


def printing_image_records(printing: dict[str, Any]) -> list[dict[str, Any]]:
    if printing.get("card_kind") == "official_double_faced":
        faces = printing.get("faces")
        if not isinstance(faces, list) or len(faces) != 2:
            raise CatalogManagerError("A double-faced printing has malformed face data")
        if not all(isinstance(face, dict) for face in faces):
            raise CatalogManagerError("A double-faced printing has malformed face data")
        return faces
    return [printing]


def source_snapshot(
    catalogs: dict[str, dict[str, Any]]
) -> tuple[dict[str, dict[str, str]], dict[str, tuple[str, dict[str, Any]]]]:
    definitions = custom_names(catalogs)
    rows: dict[str, dict[str, str]] = {}
    records: dict[str, tuple[str, dict[str, Any]]] = {}
    for owner, catalog in catalogs.items():
        for printing in catalog["printings"]:
            if not isinstance(printing, dict):
                raise CatalogManagerError(f"{owner}'s catalog contains malformed data")
            printing_uuid = str(printing.get("uuid", ""))
            collector = str(printing.get("collector_number", ""))
            if not printing_uuid or printing_uuid in records:
                raise CatalogManagerError("Printing UUIDs are missing or duplicated")
            front_title, back_title = printing_titles(printing)
            image_files = " | ".join(
                str(record.get("image_file", ""))
                for record in printing_image_records(printing)
            )
            row = {
                "current_collector": f"WLX-{collector}",
                "card_name": printing_name(printing, definitions),
                "current_owner": owner,
                "CHANGE_owner_to": "",
                "CHANGE_collector_to": "",
                "current_rarity": str(printing.get("rarity", "")),
                "CHANGE_rarity_to": "",
                "current_front_title": front_title,
                "CHANGE_front_title_to": "",
                "current_back_title": back_title,
                "CHANGE_back_title_to": "",
                "card_kind": str(printing.get("card_kind", "")),
                "printing_uuid": printing_uuid,
                "source_images": image_files,
                "notes": str(printing.get("notes", "")),
            }
            rows[printing_uuid] = row
            records[printing_uuid] = (owner, printing)
    return rows, records


def validate_rows(
    rows: list[dict[str, str]], expected: dict[str, dict[str, str]]
) -> None:
    actual_ids = [row["printing_uuid"].strip() for row in rows]
    if len(actual_ids) != len(set(actual_ids)):
        raise CatalogManagerError("CARD_MANAGER.csv contains duplicate printing rows")
    actual_set = set(actual_ids)
    expected_set = set(expected)
    if actual_set != expected_set:
        missing = sorted(expected_set - actual_set)
        extra = sorted(actual_set - expected_set)
        raise CatalogManagerError(
            "CARD_MANAGER.csv is stale or incomplete; "
            f"missing printing UUIDs={missing}, unexpected UUIDs={extra}. "
            "Download the current manager and re-enter the CHANGE_ cells."
        )
    for row in rows:
        printing_uuid = row["printing_uuid"].strip()
        current = expected[printing_uuid]
        for field in LOCKED_FIELDS:
            submitted = row[field]
            wanted = current[field]
            if field == "current_collector":
                try:
                    matches = normalize_collector(submitted) == normalize_collector(wanted)
                except CatalogManagerError:
                    matches = False
            else:
                matches = submitted == wanted
            if not matches:
                raise CatalogManagerError(
                    f"{field} is view-only for {current['current_collector']} "
                    f"({current['card_name']}). Restore {wanted!r} and use a CHANGE_ column."
                )


def changed_text(raw: str, current: str) -> str:
    value = raw.strip()
    if not value:
        return current
    if value.casefold() == CLEAR_VALUE.casefold():
        return ""
    return value


def prepare_plan(
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]], list[PlannedPrinting]]:
    config = wlxlib.read_json(wlxlib.source_path(root, wlxlib.PROJECT_RELATIVE))
    state = wlxlib.read_json(wlxlib.source_path(root, wlxlib.STATE_RELATIVE))
    catalogs = wlxlib.load_all_catalogs(root, config)
    rows = read_manager_rows(root)
    expected, records = source_snapshot(catalogs)
    validate_rows(rows, expected)
    pins = config.get("uuid_pins", {})
    if not isinstance(pins, dict):
        raise CatalogManagerError("project.json uuid_pins must be an object")

    plan: list[PlannedPrinting] = []
    for row in rows:
        printing_uuid = row["printing_uuid"].strip()
        owner, printing = records[printing_uuid]
        original_collector = str(printing["collector_number"])
        owner_request = row["CHANGE_owner_to"].strip()
        collector_request = row["CHANGE_collector_to"].strip()
        rarity_request = row["CHANGE_rarity_to"].strip()
        front_request = row["CHANGE_front_title_to"].strip()
        back_request = row["CHANGE_back_title_to"].strip()
        target_owner = exact_player(config, owner_request) if owner_request else owner
        target_collector = (
            normalize_collector(collector_request)
            if collector_request
            else original_collector
        )
        target_rarity = (
            rarity_request.casefold()
            if rarity_request
            else str(printing.get("rarity", ""))
        )
        if target_rarity not in wlxlib.ALLOWED_RARITIES:
            raise CatalogManagerError(
                f"Unsupported rarity {rarity_request!r} for {row['current_collector']}"
            )
        current_front, current_back = printing_titles(printing)
        kind = str(printing.get("card_kind", ""))
        if kind == "official_token" and (front_request or back_request):
            raise CatalogManagerError("Official token printed titles cannot be changed here")
        if kind != "official_double_faced" and back_request:
            raise CatalogManagerError(
                f"{row['current_collector']} has no back-face title to change"
            )
        target_front = changed_text(front_request, current_front)
        target_back = changed_text(back_request, current_back)
        # A manager edit changes where an existing printing lives, not which
        # printing it is. Preserve its Cockatrice UUID across renumbering.
        target_uuid = str(printing.get("uuid", ""))
        plan.append(
            PlannedPrinting(
                printing=printing,
                original_owner=owner,
                original_collector=original_collector,
                target_owner=target_owner,
                target_collector=target_collector,
                target_uuid=target_uuid,
                target_rarity=target_rarity,
                target_front_title=target_front,
                target_back_title=target_back,
                requested=any(row[field].strip() for field in CHANGE_FIELDS),
            )
        )

    by_target: dict[str, list[PlannedPrinting]] = defaultdict(list)
    for item in plan:
        by_target[item.target_collector].append(item)
    duplicates = {
        collector: items for collector, items in by_target.items() if len(items) > 1
    }
    if duplicates:
        details = "; ".join(
            f"WLX-{collector}: "
            + ", ".join(printing_name(item.printing, custom_names(catalogs)) for item in items)
            for collector, items in sorted(duplicates.items())
        )
        raise CatalogManagerError(f"Two active cards cannot share a collector number: {details}")
    if len({item.target_uuid for item in plan}) != len(plan):
        raise CatalogManagerError("The requested collector numbers create duplicate UUIDs")
    return config, state, catalogs, plan


def requested_status(root: Path) -> str:
    _config, _state, _catalogs, plan = prepare_plan(root)
    return "pending" if any(item.requested for item in plan) else "clean"


def desired_image_filename(
    printing: dict[str, Any], record: dict[str, Any], collector: str
) -> str:
    current = Path(str(record.get("image_file", "")))
    suffix = current.suffix.casefold()
    if suffix == ".jpeg":
        suffix = ".jpg"
    if suffix not in wlxlib.ALLOWED_IMAGE_SUFFIXES:
        raise CatalogManagerError(f"Unsupported source image suffix: {current.name}")
    if printing.get("card_kind") == "official_double_faced":
        side = str(record.get("side", ""))
        if side not in {"front", "back"}:
            raise CatalogManagerError("A double-faced printing has an invalid side")
        return f"WLX-{collector}-{side}{suffix}"
    return f"WLX-{collector}{suffix}"


def plan_image_moves(root: Path, plan: list[PlannedPrinting]) -> list[ImageMove]:
    moves: list[ImageMove] = []
    all_sources: set[Path] = set()
    all_destinations: set[Path] = set()
    for item in plan:
        for record in printing_image_records(item.printing):
            source = (
                wlxlib.player_images_path(root, item.original_owner)
                / str(record.get("image_file", ""))
            )
            if not source.is_file():
                raise CatalogManagerError(f"Source image is missing: {source.relative_to(root)}")
            filename = desired_image_filename(
                item.printing, record, item.target_collector
            )
            destination = wlxlib.player_images_path(root, item.target_owner) / filename
            if source in all_sources:
                raise CatalogManagerError(f"Source image is reused: {source.relative_to(root)}")
            if destination in all_destinations:
                raise CatalogManagerError(
                    f"Two images would use {destination.relative_to(root)}"
                )
            all_sources.add(source)
            all_destinations.add(destination)
            moves.append(
                ImageMove(
                    source=source,
                    destination=destination,
                    record=record,
                    new_filename=filename,
                )
            )
    for move in moves:
        if move.destination.exists() and move.destination not in all_sources:
            raise CatalogManagerError(
                f"Destination already contains an unrelated file: {move.destination.relative_to(root)}"
            )
    return moves


def execute_image_moves(moves: list[ImageMove]) -> None:
    changed = [move for move in moves if move.source != move.destination]
    with tempfile.TemporaryDirectory(prefix="wlx-card-manager-") as directory:
        staging = Path(directory)
        staged: list[tuple[ImageMove, Path]] = []
        for index, move in enumerate(changed):
            temporary = staging / f"{index:04d}{move.source.suffix.casefold()}"
            shutil.copy2(move.source, temporary)
            staged.append((move, temporary))
        for source in {move.source for move in changed}:
            source.unlink()
        for move, temporary in staged:
            move.destination.parent.mkdir(parents=True, exist_ok=True)
            pending = move.destination.with_suffix(move.destination.suffix + ".tmp")
            shutil.copy2(temporary, pending)
            pending.replace(move.destination)
    for move in moves:
        move.record["image_file"] = move.new_filename


def archive_state(
    state: dict[str, Any], collector: str, entry: dict[str, Any], timestamp: str, reason: str
) -> None:
    history = state.setdefault("collector_history", [])
    if not isinstance(history, list):
        raise CatalogManagerError("automation/state.json collector_history must be an array")
    snapshot = {"collector_number": collector, **copy.deepcopy(entry)}
    snapshot["archived_at"] = timestamp
    snapshot["archive_reason"] = reason
    history.append(snapshot)


def update_state(
    state: dict[str, Any], plan: list[PlannedPrinting], timestamp: str
) -> None:
    collectors = state.get("collectors")
    if not isinstance(collectors, dict):
        raise CatalogManagerError("automation/state.json collectors must be an object")
    current_by_collector = {item.original_collector: item for item in plan}
    final_by_collector = {item.target_collector: item for item in plan}
    for collector in sorted(
        set(current_by_collector) | set(final_by_collector), key=int
    ):
        previous = collectors.get(collector)
        target = final_by_collector.get(collector)
        if target is None:
            if not isinstance(previous, dict):
                raise CatalogManagerError(f"Missing state for WLX-{collector}")
            desired = copy.deepcopy(previous)
            desired["status"] = "retired"
            desired["retired_at"] = timestamp
            desired["retired_reason"] = "Renumbered through CARD_MANAGER.csv"
        else:
            desired = {
                "status": "active",
                "player": target.target_owner,
                "uuid": target.target_uuid,
                "card_kind": str(target.printing.get("card_kind", "")),
            }
        if previous != desired:
            if isinstance(previous, dict):
                archive_state(
                    state,
                    collector,
                    previous,
                    timestamp,
                    "Reassigned through CARD_MANAGER.csv",
                )
            collectors[collector] = desired
    highest = max((int(value) for value in collectors), default=0)
    state["next_collector"] = max(int(state.get("next_collector", 1)), highest + 1)


def move_single_owner_custom_definitions(
    catalogs: dict[str, dict[str, Any]], plan: list[PlannedPrinting]
) -> None:
    targets: dict[str, set[str]] = defaultdict(set)
    for item in plan:
        if item.printing.get("card_kind") == "custom":
            targets[str(item.printing.get("custom_card_id", ""))].add(item.target_owner)
    locations: dict[str, tuple[str, dict[str, Any]]] = {}
    for owner, catalog in catalogs.items():
        for definition in catalog["custom_cards"]:
            if isinstance(definition, dict):
                locations[str(definition.get("custom_card_id", ""))] = (owner, definition)
    for custom_id, owners in targets.items():
        if len(owners) != 1 or custom_id not in locations:
            continue
        target_owner = next(iter(owners))
        current_owner, definition = locations[custom_id]
        if current_owner == target_owner:
            continue
        catalogs[current_owner]["custom_cards"].remove(definition)
        catalogs[target_owner]["custom_cards"].append(definition)


def rebuild_uuid_pins(config: dict[str, Any], plan: list[PlannedPrinting]) -> None:
    """Pin only identities whose preserved UUID differs from their new number."""
    pins: dict[str, str] = {}
    for item in plan:
        expected = wlxlib.stable_printing_uuid(
            str(config["package_id"]),
            str(config["set_code"]),
            item.target_collector,
        )
        if item.target_uuid != expected:
            pins[item.target_collector] = item.target_uuid
    config["uuid_pins"] = {
        collector: pins[collector] for collector in sorted(pins, key=int)
    }


def apply_plan(root: Path) -> dict[str, Any]:
    wlxlib.validate_repository(root)
    config, state, catalogs, plan = prepare_plan(root)
    requested = [item for item in plan if item.requested]
    changed = [item for item in plan if item.changed]
    if not requested:
        return {"changed": False, "requested": 0, "updated": 0}
    if not changed:
        print("The requested values already match the current collection.")
        current = wlxlib.validate_repository(root)[2]
        wlxlib.write_card_manager_csv(wlxlib.card_manager_path(root), current)
        return {"changed": False, "requested": len(requested), "updated": 0}

    moves = plan_image_moves(root, plan)
    owner_moves = sum(item.target_owner != item.original_owner for item in changed)
    renumbered = sum(
        item.target_collector != item.original_collector for item in changed
    )
    metadata_edits = sum(
        (
            item.target_rarity != str(item.printing.get("rarity", ""))
            or (item.target_front_title, item.target_back_title)
            != printing_titles(item.printing)
        )
        for item in changed
    )
    timestamp = utc_now()
    execute_image_moves(moves)

    for item in plan:
        item.printing["collector_number"] = item.target_collector
        item.printing["uuid"] = item.target_uuid
        item.printing["rarity"] = item.target_rarity
        if item.printing.get("card_kind") == "official_double_faced":
            faces = printing_image_records(item.printing)
            faces[0]["flavor_name"] = item.target_front_title
            faces[1]["flavor_name"] = item.target_back_title
        elif item.printing.get("card_kind") != "official_token":
            item.printing["flavor_name"] = item.target_front_title

    for catalog in catalogs.values():
        catalog["printings"] = []
    for item in plan:
        catalogs[item.target_owner]["printings"].append(item.printing)
    move_single_owner_custom_definitions(catalogs, plan)
    update_state(state, plan, timestamp)
    rebuild_uuid_pins(config, plan)
    config["version"] = wlxlib.bump_patch(str(config["version"]))
    config["release_created_at"] = timestamp

    wlxlib.persist_catalogs(root, catalogs)
    wlxlib.write_json(wlxlib.source_path(root, wlxlib.STATE_RELATIVE), state)
    wlxlib.write_json(wlxlib.source_path(root, wlxlib.PROJECT_RELATIVE), config)
    _checked_config, _checked_state, resolved = wlxlib.validate_repository(root)
    wlxlib.write_card_manager_csv(wlxlib.card_manager_path(root), resolved)
    return {
        "changed": True,
        "requested": len(requested),
        "updated": len(changed),
        "version": config["version"],
        "owner_moves": owner_moves,
        "renumbered": renumbered,
        "metadata_edits": metadata_edits,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    mode = result.add_mutually_exclusive_group(required=True)
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--apply", action="store_true")
    return result


def main() -> int:
    arguments = parser().parse_args()
    root = arguments.repository_root.resolve()
    try:
        if arguments.status:
            print(requested_status(root))
        else:
            result = apply_plan(root)
            print(json.dumps(result, indent=2))
        return 0
    except (CatalogManagerError, wlxlib.WlxError, OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
