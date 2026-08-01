#!/usr/bin/env python3
"""Process one authorized WLX GitHub Issue Form submission.

This command edits only the repository checkout used by GitHub Actions. The
workflow validates and builds the complete release before committing anything,
so a failed submission cannot alter the hosted pack.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import wlxlib


ALLOWED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
NO_RESPONSE_VALUES = {"", "_No response_", "No response"}
CLEAR_VALUE = "CLEAR"
# GitHub produces HTTPS attachment links.  HTTP is also recognized here so the
# isolated localhost test server can exercise the same parser; the downloader's
# allow-list still rejects non-GitHub HTTP URLs outside explicit test mode.
URL_RE = re.compile(r"https?://[^\s)>\]]+")


def parse_sections(body: str) -> dict[str, str]:
    """Parse the Markdown headings produced by GitHub Issue Forms."""
    sections: dict[str, str] = {}
    matches = list(re.finditer(r"(?m)^###\s+(.+?)\s*$", body))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[match.group(1).strip()] = body[start:end].strip()
    return sections


def field(sections: dict[str, str], label: str, *, required: bool = False) -> str:
    value = sections.get(label, "").strip()
    if value in NO_RESPONSE_VALUES:
        value = ""
    if required and not value:
        raise wlxlib.WlxError(f"The form field {label!r} is required")
    return value


def exact_player(config: dict[str, Any], requested: str) -> str:
    for player in wlxlib.player_names(config):
        if player.casefold() == requested.casefold():
            return player
    raise wlxlib.WlxError(f"Unknown player collection: {requested!r}")


def normalize_collector(raw: str) -> str:
    value = raw.strip().upper().removeprefix("WLX").lstrip(" #").strip()
    if not value.isdigit():
        raise wlxlib.WlxError("Collector number must look like 002 or WLX #002")
    return f"{int(value):03d}"


def attachment_url(raw: str, *, required: bool) -> str:
    if raw in NO_RESPONSE_VALUES:
        raw = ""
    urls = URL_RE.findall(raw)
    if not urls:
        if required:
            raise wlxlib.WlxError("Attach exactly one finished PNG or JPEG card image")
        return ""
    if len(urls) != 1:
        raise wlxlib.WlxError("Attach exactly one image file, not multiple files or links")
    return urls[0].rstrip(".,")


def _allowed_attachment_url(url: str, *, redirected: bool = False) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        if os.environ.get("WLX_TEST_ALLOW_LOCAL_ATTACHMENTS") == "1":
            return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
        return False
    host = (parsed.hostname or "").lower()
    if host == "github.com":
        return parsed.path.startswith("/user-attachments/")
    if host.endswith(".githubusercontent.com"):
        return True
    if redirected and re.fullmatch(r"github-production-user-asset-[a-z0-9-]+\.s3\.amazonaws\.com", host):
        return True
    return False


class SafeAttachmentRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        if not _allowed_attachment_url(newurl, redirected=True):
            raise wlxlib.WlxError("The image attachment redirected outside GitHub's file service")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_attachment(url: str) -> tuple[bytes, str]:
    if not _allowed_attachment_url(url):
        raise wlxlib.WlxError("The image must be uploaded through the GitHub form")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "image/png,image/jpeg,application/octet-stream",
            "User-Agent": "WillexWhimsicalArtsPublisher/2.0",
        },
    )
    opener = urllib.request.build_opener(SafeAttachmentRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > 10 * 1024 * 1024:
                raise wlxlib.WlxError("The uploaded image exceeds 10 MiB")
            payload = response.read(10 * 1024 * 1024 + 1)
    except wlxlib.WlxError:
        raise
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise wlxlib.WlxError(f"Could not download the attached image: {exc}") from exc
    if len(payload) > 10 * 1024 * 1024:
        raise wlxlib.WlxError("The uploaded image exceeds 10 MiB")
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        suffix = ".png"
    elif payload.startswith(b"\xff\xd8"):
        suffix = ".jpg"
    else:
        raise wlxlib.WlxError("The uploaded file is not a real PNG or JPEG image")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / ("image" + suffix)
        path.write_bytes(payload)
        if path.stat().st_size < 10_000:
            raise wlxlib.WlxError("The uploaded image is suspiciously small")
        width, height = wlxlib.image_dimensions(path)
        if width < 300 or height < 400:
            raise wlxlib.WlxError(
                f"The uploaded image is {width}x{height}; use at least 300x400"
            )
    return payload, suffix


def write_image(root: Path, player: str, collector: str, payload: bytes, suffix: str) -> tuple[str, str]:
    directory = wlxlib.player_images_path(root, player)
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"WLX-{collector}{suffix}"
    destination = directory / filename
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(destination)
    return filename, wlxlib.sha256_bytes(payload)


def allocate_printing(
    root: Path,
    config: dict[str, Any],
    state: dict[str, Any],
    catalogs: dict[str, dict[str, Any]],
    *,
    player: str,
    card_kind: str,
    official_name: str = "",
    custom_card_id: str = "",
    flavor_name: str = "",
    image_payload: bytes,
    image_suffix: str,
    actor: str,
    issue_number: int,
) -> tuple[str, dict[str, Any]]:
    collector = f"{int(state['next_collector']):03d}"
    if collector in state["collectors"]:
        raise wlxlib.WlxError(f"Internal collector allocation collision at WLX #{collector}")
    printing_uuid = wlxlib.stable_printing_uuid(
        str(config["package_id"]), str(config["set_code"]), collector
    )
    image_file, image_hash = write_image(
        root, player, collector, image_payload, image_suffix
    )
    printing: dict[str, Any] = {
        "collector_number": collector,
        "uuid": printing_uuid,
        "card_kind": card_kind,
        "flavor_name": flavor_name,
        "rarity": str(config.get("default_rarity", "special")),
        "image_file": image_file,
        "image_sha256": image_hash,
        "notes": f"Submitted by @{actor} through issue #{issue_number}",
    }
    if card_kind == "official":
        printing["official_name"] = official_name
    else:
        printing["custom_card_id"] = custom_card_id
    catalogs[player]["printings"].append(printing)
    state["collectors"][collector] = {
        "status": "active",
        "player": player,
        "uuid": printing_uuid,
        "card_kind": card_kind,
    }
    state["next_collector"] = int(state["next_collector"]) + 1
    return collector, printing


def add_printing(
    root: Path,
    config: dict[str, Any],
    state: dict[str, Any],
    catalogs: dict[str, dict[str, Any]],
    sections: dict[str, str],
    actor: str,
    issue_number: int,
) -> tuple[str, str]:
    player = exact_player(config, field(sections, "Player collection", required=True))
    source = field(sections, "Card source", required=True)
    official_requested = field(sections, "Official Magic card name")
    custom_requested = field(sections, "Existing WLX original card name")
    flavor_name = field(sections, "Alternate printed title")
    image = attachment_url(field(sections, "Finished card image"), required=True)
    payload, suffix = download_attachment(image)
    if source == "Official Magic card":
        if not official_requested or custom_requested:
            raise wlxlib.WlxError(
                "For an official printing, fill only Official Magic card name"
            )
        official_name = wlxlib.verify_official_name(root, official_requested, config)
        collector, _ = allocate_printing(
            root,
            config,
            state,
            catalogs,
            player=player,
            card_kind="official",
            official_name=official_name,
            flavor_name=flavor_name,
            image_payload=payload,
            image_suffix=suffix,
            actor=actor,
            issue_number=issue_number,
        )
        return collector, flavor_name or official_name
    if source == "Existing WLX original card":
        if not custom_requested or official_requested:
            raise wlxlib.WlxError(
                "For an existing WLX original card, fill only its WLX card name"
            )
        _owner, _catalog, _index, definition = wlxlib.find_custom_definition(
            catalogs, custom_requested
        )
        collector, _ = allocate_printing(
            root,
            config,
            state,
            catalogs,
            player=player,
            card_kind="custom",
            custom_card_id=str(definition["custom_card_id"]),
            flavor_name=flavor_name,
            image_payload=payload,
            image_suffix=suffix,
            actor=actor,
            issue_number=issue_number,
        )
        return collector, flavor_name or str(definition["name"])
    raise wlxlib.WlxError(f"Unsupported card source: {source!r}")


def add_original_card(
    root: Path,
    config: dict[str, Any],
    state: dict[str, Any],
    catalogs: dict[str, dict[str, Any]],
    sections: dict[str, str],
    actor: str,
    issue_number: int,
) -> tuple[str, str]:
    player = exact_player(config, field(sections, "Player collection", required=True))
    name = field(sections, "Original card name", required=True)
    type_line = field(sections, "Type line", required=True)
    if name.casefold() in wlxlib.all_custom_names(catalogs):
        raise wlxlib.WlxError(f"An original WLX card named {name!r} already exists")
    cache = wlxlib.load_official_cache(root)
    if name.casefold() in cache["cards"]:
        raise wlxlib.WlxError(
            f"{name!r} is an official Magic card; use Add a Printing instead"
        )
    official_match = wlxlib.scryfall_exact(name, config)
    if official_match is not None:
        raise wlxlib.WlxError(
            f"{official_match['name']!r} is an official Magic card; use Add a Printing instead"
        )

    image = attachment_url(field(sections, "Finished card image"), required=True)
    payload, suffix = download_attachment(image)
    collector_preview = f"{int(state['next_collector']):03d}"
    custom_card_id = wlxlib.stable_custom_card_id(
        str(config["package_id"]), collector_preview
    )
    token_choice = field(sections, "Card category") or "Regular card"
    definition = {
        "custom_card_id": custom_card_id,
        "name": name,
        "mana_cost": field(sections, "Mana cost"),
        "mana_value": field(sections, "Mana value"),
        "type_line": type_line,
        "rules_text": field(sections, "Rules text"),
        "colors": field(sections, "Colors"),
        "color_identity": field(sections, "Color identity"),
        "power_toughness": field(sections, "Power/Toughness"),
        "loyalty": field(sections, "Loyalty"),
        "defense": field(sections, "Defense"),
        "layout": "normal",
        "side": "front",
        "token": token_choice == "Token",
        "created_by": actor,
        "created_from_issue": issue_number,
    }
    wlxlib.custom_definition_from_raw(player, definition)
    catalogs[player]["custom_cards"].append(definition)
    collector, _ = allocate_printing(
        root,
        config,
        state,
        catalogs,
        player=player,
        card_kind="custom",
        custom_card_id=custom_card_id,
        image_payload=payload,
        image_suffix=suffix,
        actor=actor,
        issue_number=issue_number,
    )
    return collector, name


def _clearable(current: str, submitted: str, *, allow_clear: bool = True) -> str:
    if not submitted:
        return current
    if submitted.strip().upper() == CLEAR_VALUE:
        if allow_clear:
            return ""
        raise wlxlib.WlxError("This required field cannot be cleared")
    return submitted.strip()


def update_printing(
    root: Path,
    config: dict[str, Any],
    state: dict[str, Any],
    catalogs: dict[str, dict[str, Any]],
    sections: dict[str, str],
) -> tuple[str, str]:
    collector = normalize_collector(field(sections, "WLX collector number", required=True))
    old_player, source_catalog, index, printing = wlxlib.find_printing(catalogs, collector)
    destination_choice = field(sections, "New player collection")
    new_player = old_player
    if destination_choice and destination_choice != "Keep current":
        new_player = exact_player(config, destination_choice)

    new_official = field(sections, "New official Magic card name")
    if new_official:
        if printing.get("card_kind") != "official":
            raise wlxlib.WlxError(
                "An original custom card cannot be changed into an official printing"
            )
        printing["official_name"] = wlxlib.verify_official_name(root, new_official, config)
    alternate = field(sections, "New alternate printed title")
    printing["flavor_name"] = _clearable(
        str(printing.get("flavor_name", "")), alternate
    )

    raw_attachment = field(sections, "Replacement card image")
    url = attachment_url(raw_attachment, required=False)
    old_path = wlxlib.player_images_path(root, old_player) / str(printing["image_file"])
    if url:
        payload, suffix = download_attachment(url)
        new_filename, new_hash = write_image(
            root, new_player, collector, payload, suffix
        )
        new_path = wlxlib.player_images_path(root, new_player) / new_filename
        printing["image_file"] = new_filename
        printing["image_sha256"] = new_hash
        if old_path != new_path and old_path.exists():
            old_path.unlink()
    elif new_player != old_player:
        destination = wlxlib.player_images_path(root, new_player) / old_path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_path), str(destination))

    if new_player != old_player:
        moved = source_catalog["printings"].pop(index)
        catalogs[new_player]["printings"].append(moved)
        state["collectors"][collector]["player"] = new_player
    card_name = str(
        printing.get("official_name")
        or printing.get("flavor_name")
        or printing.get("custom_card_id")
    )
    return collector, card_name


def update_original_card(
    root: Path,
    config: dict[str, Any],
    catalogs: dict[str, dict[str, Any]],
    sections: dict[str, str],
) -> tuple[str, str]:
    requested = field(sections, "Existing original card name", required=True)
    player, _catalog, _index, definition = wlxlib.find_custom_definition(catalogs, requested)
    new_name = field(sections, "New card name")
    if new_name:
        if new_name.strip().upper() == CLEAR_VALUE:
            raise wlxlib.WlxError("An original card name cannot be cleared")
        if new_name.casefold() != str(definition["name"]).casefold():
            other_names = wlxlib.all_custom_names(catalogs) - {str(definition["name"]).casefold()}
            if new_name.casefold() in other_names:
                raise wlxlib.WlxError(f"An original WLX card named {new_name!r} already exists")
            cache = wlxlib.load_official_cache(root)
            if new_name.casefold() in cache["cards"] or wlxlib.scryfall_exact(new_name, config) is not None:
                raise wlxlib.WlxError(
                    f"{new_name!r} is an official Magic card name and cannot identify an original card"
                )
            definition["name"] = new_name

    mappings = {
        "New mana cost": "mana_cost",
        "New mana value": "mana_value",
        "New type line": "type_line",
        "New rules text": "rules_text",
        "New colors": "colors",
        "New color identity": "color_identity",
        "New power/toughness": "power_toughness",
        "New loyalty": "loyalty",
        "New defense": "defense",
    }
    for label, key in mappings.items():
        submitted = field(sections, label)
        if submitted:
            allow_clear = key not in {"type_line"}
            definition[key] = _clearable(
                str(definition.get(key, "")), submitted, allow_clear=allow_clear
            )
    category = field(sections, "New card category")
    if category and category != "Keep current":
        definition["token"] = category == "Token"
    checked = wlxlib.custom_definition_from_raw(player, definition)
    return "custom", checked.name


def remove_printing(
    root: Path,
    state: dict[str, Any],
    catalogs: dict[str, dict[str, Any]],
    sections: dict[str, str],
    event_time: str,
) -> tuple[str, str]:
    collector = normalize_collector(field(sections, "WLX collector number", required=True))
    player, catalog, index, printing = wlxlib.find_printing(catalogs, collector)
    custom_card_id = str(printing.get("custom_card_id", ""))
    if custom_card_id:
        _owner, _definition_catalog, _definition_index, definition = wlxlib.find_custom_definition_by_id(
            catalogs, custom_card_id
        )
        name = str(definition["name"])
    else:
        name = str(printing.get("flavor_name") or printing.get("official_name"))
    image_path = wlxlib.player_images_path(root, player) / str(printing["image_file"])
    catalog["printings"].pop(index)
    if image_path.exists():
        image_path.unlink()
    entry = state["collectors"].get(collector)
    if not isinstance(entry, dict):
        raise wlxlib.WlxError(f"WLX #{collector} is missing from automation state")
    entry["status"] = "retired"
    entry["retired_at"] = event_time

    # An original definition is shared by all of its printings.  Once its final
    # printing is removed, remove the now-unused definition as well so each
    # player's source list stays clean.
    if custom_card_id:
        still_used = any(
            str(candidate.get("custom_card_id", "")) == custom_card_id
            for candidate_catalog in catalogs.values()
            for candidate in candidate_catalog["printings"]
        )
        if not still_used:
            _owner, definition_catalog, definition_index, _definition = wlxlib.find_custom_definition_by_id(
                catalogs, custom_card_id
            )
            definition_catalog["custom_cards"].pop(definition_index)
    return collector, name


def release_time(issue: dict[str, Any]) -> str:
    raw = str(issue.get("updated_at") or issue.get("created_at") or "").strip()
    if raw:
        return raw.replace("Z", "+00:00")
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_result(result_dir: Path, payload: dict[str, Any], message: str) -> None:
    result_dir.mkdir(parents=True, exist_ok=True)
    wlxlib.write_json(result_dir / "result.json", payload)
    filename = "success.md" if payload.get("ok") else "failure.md"
    (result_dir / filename).write_text(message.rstrip() + "\n", encoding="utf-8", newline="\n")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write(f"changed={'true' if payload.get('changed') else 'false'}\n")


def process(event_path: Path, root: Path, result_dir: Path) -> int:
    try:
        event = json.loads(event_path.read_text(encoding="utf-8"))
        issue = event.get("issue")
        repository = event.get("repository")
        if not isinstance(issue, dict) or not isinstance(repository, dict):
            raise wlxlib.WlxError("The GitHub event does not contain an issue and repository")
        association = str(issue.get("author_association", "")).upper()
        if association not in ALLOWED_ASSOCIATIONS:
            raise wlxlib.WlxError(
                "Only the repository owner and invited collaborators may publish WLX changes"
            )
        actor = str(issue.get("user", {}).get("login", "unknown"))
        issue_number = int(issue["number"])
        full_name = str(repository.get("full_name", "repository"))
        issue_key = f"{full_name}#{issue_number}"

        config = wlxlib.read_json(root / wlxlib.PROJECT_RELATIVE)
        state = wlxlib.read_json(root / wlxlib.STATE_RELATIVE)
        catalogs = wlxlib.load_all_catalogs(root, config)
        processed = state.setdefault("processed_issues", {})
        if issue_key in processed:
            previous = processed[issue_key]
            message = (
                "This request was already published successfully.\n\n"
                f"- Version: `{previous.get('version', config['version'])}`\n"
                f"- Result: {previous.get('result', 'completed')}\n"
            )
            write_result(
                result_dir,
                {"ok": True, "changed": False, "already_processed": True},
                message,
            )
            return 0

        title = str(issue.get("title", ""))
        sections = parse_sections(str(issue.get("body", "")))
        if title.startswith("[WLX PRINTING]"):
            action = "add_printing"
            collector, result_name = add_printing(
                root, config, state, catalogs, sections, actor, issue_number
            )
            action_text = f"Added **{result_name}** as `WLX #{collector}`"
        elif title.startswith("[WLX ORIGINAL]"):
            action = "add_original"
            collector, result_name = add_original_card(
                root, config, state, catalogs, sections, actor, issue_number
            )
            action_text = f"Added original card **{result_name}** as `WLX #{collector}`"
        elif title.startswith("[WLX UPDATE PRINTING]"):
            action = "update_printing"
            collector, result_name = update_printing(
                root, config, state, catalogs, sections
            )
            action_text = f"Updated `WLX #{collector}`"
        elif title.startswith("[WLX UPDATE ORIGINAL]"):
            action = "update_original"
            collector, result_name = update_original_card(
                root, config, catalogs, sections
            )
            action_text = f"Updated original card **{result_name}**"
        elif title.startswith("[WLX REMOVE]"):
            action = "remove_printing"
            collector, result_name = remove_printing(
                root, state, catalogs, sections, release_time(issue)
            )
            action_text = f"Removed `WLX #{collector}` from the active catalog"
        else:
            raise wlxlib.WlxError("This issue was not created from a recognized WLX request form")

        config["version"] = wlxlib.bump_patch(str(config["version"]))
        config["release_created_at"] = release_time(issue)
        processed[issue_key] = {
            "action": action,
            "version": config["version"],
            "result": action_text.replace("**", "").replace("`", ""),
            "actor": actor,
        }
        wlxlib.persist_catalogs(root, catalogs)
        wlxlib.write_json(root / wlxlib.STATE_RELATIVE, state)
        wlxlib.write_json(root / wlxlib.PROJECT_RELATIVE, config)
        wlxlib.validate_repository(root)
        message = (
            "The automated publisher completed this request successfully.\n\n"
            f"- {action_text}\n"
            f"- Published version: `{config['version']}`\n"
            "- Existing player shortcuts will receive the change the next time they update and launch Cockatrice.\n"
        )
        write_result(
            result_dir,
            {
                "ok": True,
                "changed": True,
                "action": action,
                "collector_number": collector,
                "name": result_name,
                "version": config["version"],
            },
            message,
        )
        return 0
    except (wlxlib.WlxError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        message = (
            "This request was not published. The current live WLX release was left unchanged.\n\n"
            f"**Reason:** {exc}\n\n"
            "Correct the form and edit or reopen this issue to try again."
        )
        write_result(result_dir, {"ok": False, "changed": False, "error": str(exc)}, message)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Process a WLX GitHub Issue Form submission")
    result.add_argument("--event", type=Path, required=True)
    result.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    result.add_argument("--result-dir", type=Path, required=True)
    return result


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(
        process(arguments.event, arguments.repository_root.resolve(), arguments.result_dir.resolve())
    )
