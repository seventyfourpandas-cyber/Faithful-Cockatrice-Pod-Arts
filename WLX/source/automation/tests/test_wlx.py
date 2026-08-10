from __future__ import annotations

import base64
import binascii
import hashlib
import http.server
import importlib
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import unittest
import urllib.request
import uuid
import zipfile
import zlib
from pathlib import Path
from unittest import mock


AUTOMATION_DIR = Path(__file__).resolve().parents[1]
SOURCE_ROOT = AUTOMATION_DIR.parent
REPOSITORY_ROOT = SOURCE_ROOT.parents[1]
sys.path.insert(0, str(AUTOMATION_DIR))
import process_issue  # noqa: E402
import wlxlib  # noqa: E402


def png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = binascii.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def test_png_bytes(width: int = 600, height: int = 840, offset: int = 0) -> bytes:
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            rows.extend(
                (
                    (x + offset) % 256,
                    (y * 3 + offset) % 256,
                    (x + y + offset) % 256,
                )
            )
    payload = b"\x89PNG\r\n\x1a\n"
    payload += png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    payload += png_chunk(b"IDAT", zlib.compress(bytes(rows), level=6))
    payload += png_chunk(b"IEND", b"")
    return payload


def extus_details() -> dict[str, object]:
    return {
        "name": "Extus, Oriq Overlord // Awaken the Blood Avatar",
        "oracle_id": "0b299983-9f0f-404a-acd1-8f142572b1f1",
        "scryfall_uri": "https://scryfall.com/card/stx/149/extus-oriq-overlord-awaken-the-blood-avatar",
        "layout": "modal_dfc",
        "verified_at": "2026-08-01",
        "faces": [
            {
                "official_name": "Extus, Oriq Overlord",
                "side": "front",
                "mana_cost": "{1}{W}{B}{B}",
                "mana_value": "4",
                "type_line": "Legendary Creature — Human Warlock",
                "rules_text": "Double strike\nMagecraft — Whenever you cast or copy an instant or sorcery spell, return target nonlegendary creature card from your graveyard to your hand.",
                "colors": "WB",
                "color_identity": "WBR",
                "power_toughness": "2/4",
                "loyalty": "",
                "defense": "",
            },
            {
                "official_name": "Awaken the Blood Avatar",
                "side": "back",
                "mana_cost": "{6}{B}{R}",
                "mana_value": "8",
                "type_line": "Sorcery",
                "rules_text": "As an additional cost to cast this spell, you may sacrifice any number of creatures.",
                "colors": "BR",
                "color_identity": "WBR",
                "power_toughness": "",
                "loyalty": "",
                "defense": "",
            },
        ],
    }


def blood_avatar_token_details() -> dict[str, object]:
    return {
        "name": "Avatar Token  ",
        "display_name": "Avatar Token",
        "rules_text": (
            "Haste\nWhenever this creature attacks, it deals 3 damage to each opponent."
        ),
        "type_line": "Token Creature — Avatar",
        "main_type": "Creature",
        "mana_cost": "",
        "mana_value": "0",
        "colors": "BR",
        "color_identity": "",
        "power_toughness": "3/6",
        "loyalty": "",
        "defense": "",
        "tablerow": "2",
        "reverse_related": [{"name": "Awaken the Blood Avatar"}],
        "verified_at": "2026-08-02",
        "source_url": wlxlib.COCKATRICE_TOKEN_DATABASE_URL,
    }


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *args: object) -> None:
        return


class AttachmentServer:
    def __init__(self, directory: Path) -> None:
        handler = lambda *args, **kwargs: QuietHandler(  # noqa: E731
            *args, directory=str(directory), **kwargs
        )
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_address[1]}/"

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class RepositoryFixture:
    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for player in ("Alex", "Will", "Miguel", "Jay"):
            (self.root / "cards" / player / "images").mkdir(parents=True)
            wlxlib.write_json(
                self.root / "cards" / player / "catalog.json",
                wlxlib.empty_player_catalog(player),
            )
        (self.root / "automation" / "data").mkdir(parents=True)
        shutil.copytree(
            SOURCE_ROOT / "automation" / "installer_source",
            self.root / "automation" / "installer_source",
        )
        self.config = {
            "schema_version": 2,
            "package_id": "unit-test-wlx",
            "display_name": "Unit Test WLX",
            "author": "Tests",
            "version": "2.0.0",
            "release_created_at": "2026-08-01T00:00:00+00:00",
            "public_base_url": "https://example.invalid/wlx/",
            "set_code": "WLX",
            "set_name": "Unit Test WLX",
            "release_date": "2026-08-01",
            "set_priority": 9999,
            "xml_filename": "willex_whimsical_arts.xml",
            "installer_zip_filename": "Willexs_Whimsical_Arts_Cockatrice_Installer.zip",
            "install_folder": "UnitTestWLX",
            "legacy_install_folder": "UnitTestWLXLegacy",
            "players": ["Alex", "Will", "Miguel", "Jay"],
            "default_rarity": "special",
            "uuid_pins": {},
            "scryfall_user_agent": "UnitTests/1.0",
        }
        wlxlib.write_json(self.root / "project.json", self.config)
        self.state = {
            "schema_version": 1,
            "next_collector": 2,
            "collectors": {},
            "processed_issues": {},
        }
        self.cache = {
            "schema_version": 1,
            "cards": {
                "angel of vitality": {
                    "name": "Angel of Vitality",
                    "verified_at": "2026-08-01",
                },
                "sol ring": {
                    "name": "Sol Ring",
                    "verified_at": "2026-08-01",
                },
            },
        }
        wlxlib.write_json(
            self.root / "automation" / "data" / "official_cards_cache.json",
            self.cache,
        )
        self.add_official("Alex", "001", "Angel of Vitality", offset=0)
        wlxlib.write_json(self.root / "automation" / "state.json", self.state)

    def close(self) -> None:
        self.temporary.cleanup()

    def catalog(self, player: str) -> dict[str, object]:
        return wlxlib.read_json(self.root / "cards" / player / "catalog.json")

    def write_catalog(self, player: str, value: dict[str, object]) -> None:
        wlxlib.write_json(self.root / "cards" / player / "catalog.json", value)

    def add_official(self, player: str, collector: str, name: str, *, offset: int) -> None:
        image = self.root / "cards" / player / "images" / f"WLX-{collector}.png"
        image.write_bytes(test_png_bytes(offset=offset))
        printing_uuid = wlxlib.stable_printing_uuid(
            self.config["package_id"], "WLX", collector
        )
        catalog = self.catalog(player)
        catalog["printings"].append(
            {
                "collector_number": collector,
                "uuid": printing_uuid,
                "card_kind": "official",
                "official_name": name,
                "flavor_name": "",
                "rarity": "rare",
                "image_file": image.name,
                "image_sha256": wlxlib.sha256_file(image),
                "notes": "fixture",
            }
        )
        self.write_catalog(player, catalog)
        self.state["collectors"][collector] = {
            "status": "active",
            "player": player,
            "uuid": printing_uuid,
            "card_kind": "official",
        }

    def add_custom(
        self,
        definition_player: str = "Alex",
        printing_player: str = "Will",
        collector: str = "002",
        offset: int = 23,
    ) -> str:
        custom_id = wlxlib.stable_custom_card_id(self.config["package_id"], collector)
        owner = self.catalog(definition_player)
        owner["custom_cards"].append(
            {
                "custom_card_id": custom_id,
                "name": "Lantern Archivist",
                "mana_cost": "{1}{W}{U}",
                "mana_value": "3",
                "type_line": "Legendary Creature — Human Wizard",
                "rules_text": "Flying\nWhenever you draw your second card each turn, create a 1/1 blue Bird creature token with flying.",
                "colors": "WU",
                "color_identity": "WU",
                "power_toughness": "2/4",
                "loyalty": "",
                "defense": "",
                "layout": "normal",
                "side": "front",
                "token": False,
            }
        )
        self.write_catalog(definition_player, owner)
        image = self.root / "cards" / printing_player / "images" / f"WLX-{collector}.png"
        image.write_bytes(test_png_bytes(offset=offset))
        printing_uuid = wlxlib.stable_printing_uuid(
            self.config["package_id"], "WLX", collector
        )
        printing_catalog = self.catalog(printing_player)
        printing_catalog["printings"].append(
            {
                "collector_number": collector,
                "uuid": printing_uuid,
                "card_kind": "custom",
                "custom_card_id": custom_id,
                "flavor_name": "",
                "rarity": "special",
                "image_file": image.name,
                "image_sha256": wlxlib.sha256_file(image),
                "notes": "fixture",
            }
        )
        self.write_catalog(printing_player, printing_catalog)
        self.state["collectors"][collector] = {
            "status": "active",
            "player": printing_player,
            "uuid": printing_uuid,
            "card_kind": "custom",
        }
        self.state["next_collector"] = max(self.state["next_collector"], int(collector) + 1)
        wlxlib.write_json(self.root / "automation" / "state.json", self.state)
        return custom_id


class CorePublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = RepositoryFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_valid_official_printing_has_stable_identity(self) -> None:
        config, _state, printings = wlxlib.validate_repository(self.fixture.root)
        self.assertEqual(len(printings), 1)
        expected = wlxlib.stable_printing_uuid(config["package_id"], "WLX", "001")
        self.assertEqual(printings[0].printing_uuid, expected)
        self.assertEqual(printings[0].card_name, "Angel of Vitality")

    def test_native_token_parser_preserves_cockatrice_identity_and_relation(self) -> None:
        payload = b"""<?xml version='1.0' encoding='UTF-8'?>
<cockatrice_carddatabase version='4'>
  <cards>
    <card>
      <name>Avatar Token  </name>
      <text>Haste\nWhenever this creature attacks, it deals 3 damage to each opponent.</text>
      <prop><colors>BR</colors><type>Token Creature - Avatar</type><maintype>Creature</maintype><cmc>0</cmc><pt>3/6</pt></prop>
      <set>STX</set>
      <reverse-related>Awaken the Blood Avatar</reverse-related>
      <token>1</token><tablerow>2</tablerow>
    </card>
  </cards>
</cockatrice_carddatabase>"""
        token = wlxlib.parse_cockatrice_token_database(
            payload, "Awaken the Blood Avatar"
        )
        self.assertEqual(token["name"], "Avatar Token  ")
        self.assertEqual(token["display_name"], "Avatar Token")
        self.assertEqual(token["power_toughness"], "3/6")
        self.assertEqual(
            token["reverse_related"], [{"name": "Awaken the Blood Avatar"}]
        )

    def test_original_card_generates_complete_cockatrice_metadata(self) -> None:
        self.fixture.add_custom()
        config, _state, printings = wlxlib.validate_repository(self.fixture.root)
        xml = wlxlib.ET.fromstring(wlxlib.xml_bytes(config, printings))
        card = next(
            node for node in xml.findall("./cards/card") if node.findtext("name") == "Lantern Archivist"
        )
        self.assertIn("Whenever you draw", card.findtext("text"))
        self.assertEqual(card.findtext("./prop/type"), "Legendary Creature — Human Wizard")
        self.assertEqual(card.findtext("./prop/maintype"), "Creature")
        self.assertEqual(card.findtext("./prop/manacost"), "{1}{W}{U}")
        self.assertEqual(card.findtext("./prop/coloridentity"), "WU")
        self.assertEqual(card.findtext("./prop/pt"), "2/4")
        self.assertEqual(card.findtext("tablerow"), "2")

    def test_additional_printing_of_original_card_reuses_one_definition(self) -> None:
        custom_id = self.fixture.add_custom()
        image = self.fixture.root / "cards" / "Miguel" / "images" / "WLX-003.png"
        image.write_bytes(test_png_bytes(offset=47))
        catalog = self.fixture.catalog("Miguel")
        printing_uuid = wlxlib.stable_printing_uuid(
            self.fixture.config["package_id"], "WLX", "003"
        )
        catalog["printings"].append(
            {
                "collector_number": "003",
                "uuid": printing_uuid,
                "card_kind": "custom",
                "custom_card_id": custom_id,
                "flavor_name": "Moonlit Archivist",
                "rarity": "special",
                "image_file": image.name,
                "image_sha256": wlxlib.sha256_file(image),
                "notes": "fixture",
            }
        )
        self.fixture.write_catalog("Miguel", catalog)
        self.fixture.state["collectors"]["003"] = {
            "status": "active",
            "player": "Miguel",
            "uuid": printing_uuid,
            "card_kind": "custom",
        }
        self.fixture.state["next_collector"] = 4
        wlxlib.write_json(
            self.fixture.root / "automation" / "state.json", self.fixture.state
        )
        config, _state, printings = wlxlib.validate_repository(self.fixture.root)
        xml = wlxlib.ET.fromstring(wlxlib.xml_bytes(config, printings))
        custom_nodes = [
            node for node in xml.findall("./cards/card") if node.findtext("name") == "Lantern Archivist"
        ]
        self.assertEqual(len(custom_nodes), 1)
        self.assertEqual([node.attrib["num"] for node in custom_nodes[0].findall("set")], ["002", "003"])

    def test_multiple_official_printings_share_one_card_identity(self) -> None:
        self.fixture.add_official("Will", "002", "Angel of Vitality", offset=41)
        self.fixture.state["next_collector"] = 3
        wlxlib.write_json(
            self.fixture.root / "automation" / "state.json", self.fixture.state
        )
        config, _state, printings = wlxlib.validate_repository(self.fixture.root)
        xml = wlxlib.ET.fromstring(wlxlib.xml_bytes(config, printings))
        nodes = [
            node
            for node in xml.findall("./cards/card")
            if node.findtext("name") == "Angel of Vitality"
        ]
        self.assertEqual(len(nodes), 1)
        self.assertEqual(
            [printing.attrib["num"] for printing in nodes[0].findall("set")],
            ["001", "002"],
        )

    def test_player_catalogs_are_separate_but_compile_together(self) -> None:
        self.fixture.add_custom(definition_player="Alex", printing_player="Will")
        _config, _state, printings = wlxlib.validate_repository(self.fixture.root)
        self.assertEqual({item.player for item in printings}, {"Alex", "Will"})
        self.assertEqual(len(self.fixture.catalog("Miguel")["printings"]), 0)

    def test_replacement_art_keeps_uuid_and_changes_content_url(self) -> None:
        before = wlxlib.validate_repository(self.fixture.root)[2][0]
        image = self.fixture.root / "cards" / "Alex" / "images" / "WLX-001.png"
        image.write_bytes(test_png_bytes(offset=88))
        catalog = self.fixture.catalog("Alex")
        catalog["printings"][0]["image_sha256"] = wlxlib.sha256_file(image)
        self.fixture.write_catalog("Alex", catalog)
        after = wlxlib.validate_repository(self.fixture.root)[2][0]
        self.assertEqual(after.printing_uuid, before.printing_uuid)
        self.assertNotEqual(after.published_image_path, before.published_image_path)

    def test_manual_image_change_is_rejected(self) -> None:
        image = self.fixture.root / "cards" / "Alex" / "images" / "WLX-001.png"
        image.write_bytes(test_png_bytes(offset=99))
        with self.assertRaisesRegex(wlxlib.WlxError, "changed outside"):
            wlxlib.validate_repository(self.fixture.root)

    def test_duplicate_collector_across_players_is_rejected(self) -> None:
        alex = self.fixture.catalog("Alex")["printings"][0].copy()
        alex["image_file"] = "duplicate.png"
        image = self.fixture.root / "cards" / "Will" / "images" / "duplicate.png"
        image.write_bytes(test_png_bytes(offset=13))
        alex["image_sha256"] = wlxlib.sha256_file(image)
        will = self.fixture.catalog("Will")
        will["printings"].append(alex)
        self.fixture.write_catalog("Will", will)
        with self.assertRaisesRegex(wlxlib.WlxError, "duplicated"):
            wlxlib.validate_repository(self.fixture.root)

    def test_original_card_may_not_use_official_name(self) -> None:
        catalog = self.fixture.catalog("Alex")
        catalog["custom_cards"].append(
            {
                "custom_card_id": "custom-" + str(uuid.uuid4()),
                "name": "Sol Ring",
                "type_line": "Artifact",
            }
        )
        self.fixture.write_catalog("Alex", catalog)
        with self.assertRaisesRegex(wlxlib.WlxError, "official Magic"):
            wlxlib.validate_repository(self.fixture.root)

    def test_custom_card_rejects_broken_mana_notation(self) -> None:
        self.fixture.add_custom()
        catalog = self.fixture.catalog("Alex")
        catalog["custom_cards"][0]["mana_cost"] = "2WU"
        self.fixture.write_catalog("Alex", catalog)
        with self.assertRaisesRegex(wlxlib.WlxError, "Cockatrice symbols"):
            wlxlib.validate_repository(self.fixture.root)

    def test_custom_creature_requires_power_toughness(self) -> None:
        self.fixture.add_custom()
        catalog = self.fixture.catalog("Alex")
        catalog["custom_cards"][0]["power_toughness"] = ""
        self.fixture.write_catalog("Alex", catalog)
        with self.assertRaisesRegex(wlxlib.WlxError, "power/toughness"):
            wlxlib.validate_repository(self.fixture.root)

    def test_build_manifest_hashes_every_declared_file(self) -> None:
        manifest = wlxlib.build_repository(self.fixture.root)
        self.assertIn("cockatrice_installer", manifest)
        self.assertNotIn("friend_installer", manifest)
        self.assertEqual(
            manifest["cockatrice_installer"]["path"],
            "Willexs_Whimsical_Arts_Cockatrice_Installer.zip",
        )
        for entry in manifest["files"]:
            path = self.fixture.root / entry["path"]
            self.assertTrue(path.is_file())
            self.assertEqual(wlxlib.sha256_file(path), entry["sha256"])

    def test_build_rejects_a_corrupted_shortcut_icon(self) -> None:
        icon = self.fixture.root / "automation" / "installer_source" / "WLX_Shortcut.ico"
        icon.write_bytes(b"not an icon")
        with self.assertRaisesRegex(wlxlib.WlxError, "not a valid Windows icon"):
            wlxlib.build_repository(self.fixture.root)

    def test_cockatrice_installer_contains_verified_bootstrap(self) -> None:
        manifest = wlxlib.build_repository(self.fixture.root)
        archive_path = self.fixture.root / manifest["cockatrice_installer"]["path"]
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            self.assertIn("WLX_Bootstrap.ps1", names)
            self.assertIn("README_FOR_PLAYERS.txt", names)
            self.assertNotIn("README_FOR_FRIENDS.txt", names)
            self.assertIn("installer_config.json", names)
            self.assertNotIn("friend_config.json", names)
            bootstrap = archive.read("WLX_Bootstrap.ps1").decode("utf-8")
            self.assertIn("Get-FileHash -Algorithm SHA256", bootstrap)
            self.assertIn("cockatrice_installer", bootstrap)
            updater = archive.read("WLX_Cockatrice_Updater.ps1").decode("utf-8")
            self.assertIn("Get-ChangedPictureIdentities", updater)
            self.assertIn("picture_url = [string]$identity.picture_url", updater)
            self.assertNotIn("__SHORTCUT_ICON_BASE64__", updater)
            self.assertNotIn("__SHORTCUT_ICON_SHA256__", updater)
            start_marker = "$ShortcutIconBase64 = @'\n"
            start = updater.index(start_marker) + len(start_marker)
            finish = updater.index("\n'@", start)
            embedded_icon = base64.b64decode(updater[start:finish], validate=True)
            source_icon = (
                SOURCE_ROOT / "automation" / "installer_source" / "WLX_Shortcut.ico"
            ).read_bytes()
            self.assertEqual(embedded_icon, source_icon)
            self.assertIn(hashlib.sha256(source_icon).hexdigest(), updater)
            self.assertIn('$shortcut.IconLocation = "$IconPath,0"', updater)
            self.assertIn("Test-Path -LiteralPath $existingShortcut", updater)
            self.assertIn("Select-CockatriceExe", updater)
            self.assertIn("Get-PSDrive -PSProvider FileSystem", updater)
            self.assertIn("Windows\\CurrentVersion\\App Paths\\Cockatrice.exe", updater)
            self.assertIn("cockatrice_exe = $rememberedExe", updater)
            self.assertIn("Hey idiot, where did you move your files?", updater)
            self.assertIn("Initialize-LauncherWindow", updater)
            self.assertIn("Collection ready - opening Cockatrice", updater)
            self.assertIn("Close-LauncherWindow 1500", updater)
            self.assertIn('$shortcut.TargetPath = $powershellPath', updater)
            self.assertIn("-ExecutionPolicy Bypass -STA -WindowStyle Hidden", updater)
            self.assertIn("-WindowStyle Hidden", updater)
            self.assertNotIn('$shortcut.TargetPath = $env:ComSpec', updater)
            launcher_start_marker = "$xaml = @'\n"
            launcher_start = updater.index(launcher_start_marker) + len(launcher_start_marker)
            launcher_finish = updater.index("\n'@", launcher_start)
            launcher_xaml = updater[launcher_start:launcher_finish]
            launcher_root = wlxlib.ET.fromstring(launcher_xaml)
            self.assertTrue(launcher_root.tag.endswith("Window"))
            self.assertEqual(launcher_xaml.count('x:Name="FeedLine'), 3)
            self.assertIn(
                'Data="M 8,44 L 24,4 L 40,44 M 3,17 L 17,33 L 24,23 L 31,33 L 45,17"',
                launcher_xaml,
            )
            self.assertNotIn("wolf", launcher_xaml.lower())
            self.assertNotIn("<Button", launcher_xaml)
            reserved, image_type, image_count = struct.unpack("<HHH", embedded_icon[:6])
            self.assertEqual((reserved, image_type), (0, 1))
            self.assertGreaterEqual(image_count, 7)
            sizes = set()
            for index in range(image_count):
                entry = embedded_icon[6 + index * 16 : 22 + index * 16]
                width = entry[0] or 256
                height = entry[1] or 256
                payload_size, payload_offset = struct.unpack("<II", entry[8:16])
                self.assertEqual(width, height)
                self.assertEqual(embedded_icon[payload_offset : payload_offset + 8], b"\x89PNG\r\n\x1a\n")
                self.assertLessEqual(payload_offset + payload_size, len(embedded_icon))
                sizes.add(width)
            self.assertTrue({16, 24, 32, 48, 64, 128, 256}.issubset(sizes))


class IssueTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = RepositoryFixture()
        self.attachments = Path(tempfile.mkdtemp())
        (self.attachments / "card.png").write_bytes(test_png_bytes(offset=55))
        (self.attachments / "replacement.png").write_bytes(test_png_bytes(offset=77))
        (self.attachments / "front.png").write_bytes(test_png_bytes(offset=101))
        (self.attachments / "back.png").write_bytes(test_png_bytes(offset=131))
        (self.attachments / "front-replacement.png").write_bytes(test_png_bytes(offset=151))
        self.previous_test_setting = os.environ.get("WLX_TEST_ALLOW_LOCAL_ATTACHMENTS")
        os.environ["WLX_TEST_ALLOW_LOCAL_ATTACHMENTS"] = "1"

    def tearDown(self) -> None:
        if self.previous_test_setting is None:
            os.environ.pop("WLX_TEST_ALLOW_LOCAL_ATTACHMENTS", None)
        else:
            os.environ["WLX_TEST_ALLOW_LOCAL_ATTACHMENTS"] = self.previous_test_setting
        shutil.rmtree(self.attachments)
        self.fixture.close()

    def event(self, number: int, title: str, body: str, association: str = "COLLABORATOR") -> Path:
        payload = {
            "issue": {
                "number": number,
                "title": title,
                "body": body,
                "author_association": association,
                "user": {"login": "tester"},
                "created_at": "2026-08-01T12:00:00Z",
                "updated_at": "2026-08-01T12:00:00Z",
            },
            "repository": {"full_name": "owner/repository"},
        }
        path = self.fixture.root / f"event-{number}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def run_event(self, event: Path, result_name: str) -> tuple[int, dict[str, object]]:
        result_dir = self.fixture.root / result_name
        status = process_issue.process(event, self.fixture.root, result_dir)
        result = wlxlib.read_json(result_dir / "result.json")
        return status, result

    def test_official_printing_form_assigns_next_collector_and_player_folder(self) -> None:
        with AttachmentServer(self.attachments) as base:
            body = f"""### Player collection
Will

### Card source
Official Magic card

### Official Magic card name
Sol Ring

### Existing WLX original card name
_No response_

### Alternate printed title
Wedding Sol Ring

### Finished card image
![card.png]({base}card.png)
"""
            status, result = self.run_event(
                self.event(10, "[WLX PRINTING] Wedding Sol Ring", body), "result-10"
            )
        self.assertEqual(status, 0)
        self.assertTrue(result["changed"])
        self.assertEqual(result["collector_number"], "002")
        will = self.fixture.catalog("Will")
        self.assertEqual(will["printings"][0]["official_name"], "Sol Ring")
        self.assertTrue((self.fixture.root / "cards" / "Will" / "images" / "WLX-002.png").is_file())
        self.assertEqual(wlxlib.read_json(self.fixture.root / "project.json")["version"], "2.0.1")

    def test_simple_official_form_needs_only_three_fields(self) -> None:
        with AttachmentServer(self.attachments) as base:
            body = f"""### Player collection
Will

### Official Magic card name
Sol Ring

### Finished card image
![card.png]({base}card.png)
"""
            status, result = self.run_event(
                self.event(21, "[WLX PRINTING] Sol Ring", body), "result-21"
            )
        self.assertEqual(status, 0)
        self.assertEqual(result["collector_number"], "002")
        self.assertEqual(self.fixture.catalog("Will")["printings"][0]["official_name"], "Sol Ring")

    def test_double_faced_form_creates_two_native_linked_faces(self) -> None:
        with AttachmentServer(self.attachments) as base, mock.patch.object(
            process_issue.wlxlib,
            "verify_official_double_faced",
            return_value=extus_details(),
        ):
            body = f"""### Player collection
Will

### Official double-faced Magic card name
Extus, Oriq Overlord

### Front-face alternate printed title
_No response_

### Back-face alternate printed title
_No response_

### Front-face card image
![front.png]({base}front.png)

### Back-face card image
![back.png]({base}back.png)
"""
            status, result = self.run_event(
                self.event(22, "[WLX DOUBLE FACED] Extus", body), "result-22"
            )
        self.assertEqual(status, 0)
        self.assertEqual(result["collector_number"], "002")
        will = self.fixture.catalog("Will")
        self.assertEqual(len(will["printings"]), 1)
        paired = will["printings"][0]
        self.assertEqual(paired["card_kind"], "official_double_faced")
        self.assertEqual([face["side"] for face in paired["faces"]], ["front", "back"])
        self.assertTrue(
            (self.fixture.root / "cards" / "Will" / "images" / "WLX-002-front.png").is_file()
        )
        self.assertTrue(
            (self.fixture.root / "cards" / "Will" / "images" / "WLX-002-back.png").is_file()
        )

        config, _state, printings = wlxlib.validate_repository(self.fixture.root)
        self.assertEqual(len(printings), 3)
        face_printings = [item for item in printings if item.collector_number == "002"]
        self.assertEqual(len(face_printings), 2)
        self.assertEqual(len({item.printing_uuid for item in face_printings}), 1)
        xml = wlxlib.ET.fromstring(wlxlib.xml_bytes(config, printings))
        nodes = {
            node.findtext("name"): node
            for node in xml.findall("./cards/card")
            if node.findtext("name") in {"Extus, Oriq Overlord", "Awaken the Blood Avatar"}
        }
        self.assertEqual(set(nodes), {"Extus, Oriq Overlord", "Awaken the Blood Avatar"})
        front = nodes["Extus, Oriq Overlord"]
        back = nodes["Awaken the Blood Avatar"]
        self.assertEqual(front.findtext("./prop/maintype"), "Creature")
        self.assertEqual(front.findtext("tablerow"), "2")
        self.assertEqual(back.findtext("./prop/maintype"), "Sorcery")
        self.assertEqual(back.findtext("tablerow"), "3")
        self.assertEqual(front.find("related").attrib.get("attach"), "transform")
        self.assertEqual(front.findtext("related"), "Awaken the Blood Avatar")
        self.assertEqual(back.find("related").attrib.get("attach"), "transform")
        self.assertEqual(back.findtext("related"), "Extus, Oriq Overlord")
        self.assertEqual(front.find("set").attrib["uuid"], back.find("set").attrib["uuid"])
        self.assertEqual(front.find("set").attrib["num"], back.find("set").attrib["num"])

        manifest = wlxlib.build_repository(self.fixture.root)
        self.assertEqual(manifest["printings_count"], 2)
        self.assertEqual(manifest["face_entries_count"], 3)

    def test_token_form_links_native_token_art_to_existing_wlx_face(self) -> None:
        with AttachmentServer(self.attachments) as base, mock.patch.object(
            process_issue.wlxlib,
            "verify_official_double_faced",
            return_value=extus_details(),
        ):
            double_faced_body = f"""### Player collection
Will

### Official double-faced Magic card name
Extus, Oriq Overlord

### Front-face card image
![front.png]({base}front.png)

### Back-face card image
![back.png]({base}back.png)
"""
            status, _result = self.run_event(
                self.event(24, "[WLX DOUBLE FACED] Extus", double_faced_body),
                "result-24",
            )
            self.assertEqual(status, 0)

            with mock.patch.object(
                process_issue.wlxlib,
                "verify_official_token_for_creator",
                return_value=blood_avatar_token_details(),
            ):
                token_body = f"""### Player collection
Will

### Creating card face
Awaken the Blood Avatar

### Finished token image
![card.png]({base}card.png)
"""
                status, result = self.run_event(
                    self.event(25, "[WLX TOKEN] Blood Avatar", token_body),
                    "result-25",
                )

        self.assertEqual(status, 0)
        self.assertEqual(result["collector_number"], "003")
        will = self.fixture.catalog("Will")
        token_printing = next(
            printing
            for printing in will["printings"]
            if printing["collector_number"] == "003"
        )
        self.assertEqual(token_printing["card_kind"], "official_token")
        self.assertEqual(token_printing["creator_card"], "Awaken the Blood Avatar")
        self.assertEqual(token_printing["token_metadata"]["name"], "Avatar Token  ")

        config, _state, printings = wlxlib.validate_repository(self.fixture.root)
        xml = wlxlib.ET.fromstring(wlxlib.xml_bytes(config, printings))
        token = next(
            node
            for node in xml.findall("./cards/card")
            if node.findtext("name") == "Avatar Token  "
        )
        self.assertEqual(token.findtext("./prop/type"), "Token Creature — Avatar")
        self.assertEqual(token.findtext("./prop/pt"), "3/6")
        self.assertEqual(token.findtext("reverse-related"), "Awaken the Blood Avatar")
        self.assertEqual(token.findtext("token"), "true")
        self.assertEqual(token.findtext("tablerow"), "2")
        self.assertEqual(token.find("set").text, "WLX")
        self.assertEqual(token.find("set").attrib["num"], "003")

    def test_token_form_requires_the_creating_face_to_exist_in_wlx(self) -> None:
        with AttachmentServer(self.attachments) as base:
            body = f"""### Player collection
Will

### Creating card face
Awaken the Blood Avatar

### Finished token image
![card.png]({base}card.png)
"""
            status, result = self.run_event(
                self.event(26, "[WLX TOKEN] Missing creator", body), "result-26"
            )
        self.assertEqual(status, 1)
        self.assertIn("publish its card printing first", result["error"])
        self.assertEqual(len(self.fixture.catalog("Will")["printings"]), 0)

    def test_ordinary_form_redirects_double_faced_cards_before_publishing(self) -> None:
        with AttachmentServer(self.attachments) as base, mock.patch.object(
            process_issue.wlxlib,
            "verify_official_name",
            return_value="Extus, Oriq Overlord // Awaken the Blood Avatar",
        ), mock.patch.object(
            process_issue.wlxlib,
            "scryfall_exact",
            return_value=extus_details(),
        ):
            body = f"""### Player collection
Will
### Official Magic card name
Extus, Oriq Overlord
### Finished card image
![front.png]({base}front.png)
"""
            status, result = self.run_event(
                self.event(23, "[WLX PRINTING] Extus", body), "result-23"
            )
        self.assertEqual(status, 1)
        self.assertIn("Add a Double-Faced Printing", result["error"])
        self.assertEqual(len(self.fixture.catalog("Will")["printings"]), 0)

    def test_original_card_form_needs_no_official_identity(self) -> None:
        with AttachmentServer(self.attachments) as base, mock.patch.object(
            process_issue.wlxlib, "scryfall_exact", return_value=None
        ):
            body = f"""### Player collection
Miguel

### Original card name
Threadkeeper Adept

### Card category
Regular card

### Mana cost
{{2}}{{U}}

### Mana value
3

### Type line
Creature — Human Wizard

### Rules text
When Threadkeeper Adept enters, draw a card.

### Colors
U

### Color identity
U

### Power/Toughness
2/3

### Loyalty
_No response_

### Defense
_No response_

### Finished card image
[card.png]({base}card.png)
"""
            status, result = self.run_event(
                self.event(11, "[WLX ORIGINAL] Threadkeeper Adept", body), "result-11"
            )
        self.assertEqual(status, 0)
        self.assertEqual(result["collector_number"], "002")
        miguel = self.fixture.catalog("Miguel")
        self.assertEqual(miguel["custom_cards"][0]["name"], "Threadkeeper Adept")
        self.assertEqual(miguel["printings"][0]["card_kind"], "custom")
        config, _state, printings = wlxlib.validate_repository(self.fixture.root)
        xml = wlxlib.ET.fromstring(wlxlib.xml_bytes(config, printings))
        custom = next(
            node for node in xml.findall("./cards/card") if node.findtext("name") == "Threadkeeper Adept"
        )
        self.assertEqual(custom.findtext("./prop/pt"), "2/3")

    def test_replayed_issue_is_idempotent(self) -> None:
        with AttachmentServer(self.attachments) as base:
            body = f"""### Player collection
Will
### Card source
Official Magic card
### Official Magic card name
Sol Ring
### Existing WLX original card name
_No response_
### Alternate printed title
Ring
### Finished card image
[card.png]({base}card.png)
"""
            event = self.event(12, "[WLX PRINTING] Ring", body)
            first, _ = self.run_event(event, "result-12-a")
            second, result = self.run_event(event, "result-12-b")
        self.assertEqual(first, 0)
        self.assertEqual(second, 0)
        self.assertFalse(result["changed"])
        self.assertTrue(result["already_processed"])
        self.assertEqual(len(self.fixture.catalog("Will")["printings"]), 1)

    def test_update_art_preserves_printing_uuid(self) -> None:
        original_uuid = self.fixture.catalog("Alex")["printings"][0]["uuid"]
        with AttachmentServer(self.attachments) as base:
            body = f"""### WLX collector number
001
### New player collection
Keep current
### New alternate printed title
Updated Angel
### New official Magic card name
_No response_
### Replacement card image
[replacement.png]({base}replacement.png)
"""
            status, _result = self.run_event(
                self.event(13, "[WLX UPDATE PRINTING] 001", body), "result-13"
            )
        self.assertEqual(status, 0)
        updated = self.fixture.catalog("Alex")["printings"][0]
        self.assertEqual(updated["uuid"], original_uuid)
        self.assertEqual(updated["flavor_name"], "Updated Angel")
        wlxlib.validate_repository(self.fixture.root)

    def test_update_can_move_printing_between_player_folders(self) -> None:
        body = """### WLX collector number
001
### New player collection
Jay
### New alternate printed title
_No response_
### New official Magic card name
_No response_
### Replacement card image
_No response_
"""
        status, _result = self.run_event(
            self.event(18, "[WLX UPDATE PRINTING] 001", body), "result-18"
        )
        self.assertEqual(status, 0)
        self.assertEqual(len(self.fixture.catalog("Alex")["printings"]), 0)
        self.assertEqual(len(self.fixture.catalog("Jay")["printings"]), 1)
        self.assertFalse(
            (self.fixture.root / "cards" / "Alex" / "images" / "WLX-001.png").exists()
        )
        self.assertTrue(
            (self.fixture.root / "cards" / "Jay" / "images" / "WLX-001.png").is_file()
        )
        wlxlib.validate_repository(self.fixture.root)

    def test_update_original_changes_every_printing_definition(self) -> None:
        self.fixture.add_custom()
        body = """### Existing original card name
Lantern Archivist
### New card name
_No response_
### New card category
Keep current
### New mana cost
_No response_
### New mana value
_No response_
### New type line
_No response_
### New rules text
Whenever you draw your second card each turn, create two 1/1 blue Bird creature tokens with flying.
### New colors
_No response_
### New color identity
_No response_
### New power/toughness
3/4
### New loyalty
_No response_
### New defense
_No response_
"""
        status, _result = self.run_event(
            self.event(19, "[WLX UPDATE ORIGINAL] Lantern Archivist", body),
            "result-19",
        )
        self.assertEqual(status, 0)
        config, _state, printings = wlxlib.validate_repository(self.fixture.root)
        xml = wlxlib.ET.fromstring(wlxlib.xml_bytes(config, printings))
        custom = next(
            node
            for node in xml.findall("./cards/card")
            if node.findtext("name") == "Lantern Archivist"
        )
        self.assertIn("create two", custom.findtext("text"))
        self.assertEqual(custom.findtext("./prop/pt"), "3/4")

    def test_update_original_cannot_clear_required_type_line(self) -> None:
        self.fixture.add_custom()
        body = """### Existing original card name
Lantern Archivist
### New card name
_No response_
### New card category
Keep current
### New mana cost
_No response_
### New mana value
_No response_
### New type line
CLEAR
### New rules text
_No response_
### New colors
_No response_
### New color identity
_No response_
### New power/toughness
_No response_
### New loyalty
_No response_
### New defense
_No response_
"""
        status, result = self.run_event(
            self.event(20, "[WLX UPDATE ORIGINAL] Lantern Archivist", body),
            "result-20",
        )
        self.assertNotEqual(status, 0)
        self.assertIn("cannot be cleared", result["error"])

    def test_remove_retires_collector_without_reuse(self) -> None:
        body = """### WLX collector number
001
"""
        status, _result = self.run_event(
            self.event(14, "[WLX REMOVE] 001", body), "result-14"
        )
        self.assertNotEqual(status, 0, "The repository may not publish an empty set")
        # The failed transaction is never committed by GitHub. This fixture confirms the
        # final validator prevents the last active printing from disappearing accidentally.

    def test_remove_succeeds_with_other_printing_and_cleans_orphan_definition(self) -> None:
        custom_id = self.fixture.add_custom()
        body = """### WLX collector number
002
"""
        status, result = self.run_event(
            self.event(17, "[WLX REMOVE] 002", body), "result-17"
        )
        self.assertEqual(status, 0)
        self.assertEqual(result["collector_number"], "002")
        state = wlxlib.read_json(self.fixture.root / "automation" / "state.json")
        self.assertEqual(state["collectors"]["002"]["status"], "retired")
        self.assertEqual(state["next_collector"], 3)
        self.assertFalse(
            (self.fixture.root / "cards" / "Will" / "images" / "WLX-002.png").exists()
        )
        self.assertFalse(
            any(
                item.get("custom_card_id") == custom_id
                for item in self.fixture.catalog("Alex")["custom_cards"]
            )
        )
        wlxlib.validate_repository(self.fixture.root)

    def test_unauthorized_submission_is_rejected(self) -> None:
        body = "### Player collection\nWill\n"
        status, result = self.run_event(
            self.event(15, "[WLX PRINTING] Unauthorized", body, association="CONTRIBUTOR"),
            "result-15",
        )
        self.assertEqual(status, 1)
        self.assertIn("invited collaborators", result["error"])

    def test_invalid_upload_leaves_result_failed(self) -> None:
        (self.attachments / "bad.png").write_bytes(b"not an image")
        with AttachmentServer(self.attachments) as base:
            body = f"""### Player collection
Will
### Card source
Official Magic card
### Official Magic card name
Sol Ring
### Existing WLX original card name
_No response_
### Alternate printed title
Bad
### Finished card image
[bad.png]({base}bad.png)
"""
            status, result = self.run_event(
                self.event(16, "[WLX PRINTING] Bad", body), "result-16"
            )
        self.assertEqual(status, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(len(self.fixture.catalog("Will")["printings"]), 0)


class ShippedRepositoryTests(unittest.TestCase):
    def test_only_removal_uses_an_issue_form(self) -> None:
        expected = (("01-remove-printing.yml", "name: Remove a printing"),)
        form_dir = REPOSITORY_ROOT / ".github" / "ISSUE_TEMPLATE"
        actual_filenames = tuple(
            path.name for path in sorted(form_dir.glob("[0-9]*.yml"))
        )
        self.assertEqual(actual_filenames, tuple(filename for filename, _name in expected))
        for filename, expected_name in expected:
            first_line = (form_dir / filename).read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(first_line, expected_name, filename)

        forbidden_filenames = (
            "add-printing.yml",
            "add-double-faced-printing.yml",
            "add-original-card.yml",
            "add-printing-advanced.yml",
            "update-printing.yml",
            "update-double-faced-printing.yml",
            "update-original-card.yml",
            "remove-printing.yml",
            "01-add-printing.yml",
            "02-add-double-faced-printing.yml",
            "02b-add-token-printing.yml",
            "03-add-original-card.yml",
            "04-add-printing-advanced.yml",
            "05-update-printing.yml",
            "06-update-double-faced-printing.yml",
            "07-update-original-card.yml",
            "08-remove-printing.yml",
        )
        self.assertFalse(
            any((form_dir / filename).exists() for filename in forbidden_filenames)
        )

    def test_removal_issue_form_has_no_upload_field(self) -> None:
        form_dir = REPOSITORY_ROOT / ".github" / "ISSUE_TEMPLATE"
        forms = tuple(sorted(form_dir.glob("[0-9]*.yml")))
        self.assertEqual(len(forms), 1)
        self.assertNotIn("type: upload", forms[0].read_text(encoding="utf-8"))

    def test_seed_preserves_working_wlx_001(self) -> None:
        config, _state, printings = wlxlib.validate_repository(REPOSITORY_ROOT)
        first = printings[0]
        self.assertEqual(first.collector_number, "001")
        self.assertEqual(first.card_name, "Angel of Vitality")
        self.assertEqual(first.flavor_name, "Alex, Divine Priest")
        self.assertEqual(first.printing_uuid, "f6a9cc3e-beac-5fac-84aa-ca36b34d7d10")
        self.assertEqual(first.image_sha256, "680c22b71393004d0c10d1ade8eead9bc26b9cb26fb3891bde5498fdd8749384")
        self.assertEqual(config["set_code"], "WLX")

    def test_shipped_manifest_and_installer_are_current(self) -> None:
        project = wlxlib.read_json(
            wlxlib.source_path(REPOSITORY_ROOT, wlxlib.PROJECT_RELATIVE)
        )
        publication = wlxlib.published_root(REPOSITORY_ROOT)
        manifest = wlxlib.read_json(publication / "manifest.json")
        self.assertEqual(manifest["version"], project["version"])
        self.assertEqual(manifest["package_id"], project["package_id"])
        self.assertEqual(manifest["publisher_schema_version"], 2)
        self.assertIn("cockatrice_installer", manifest)
        self.assertTrue(
            (
                publication
                / "Willexs_Whimsical_Arts_Cockatrice_Installer.zip"
            ).is_file()
        )

    def test_every_shipped_url_uses_the_published_directory(self) -> None:
        project = wlxlib.read_json(
            wlxlib.source_path(REPOSITORY_ROOT, wlxlib.PROJECT_RELATIVE)
        )
        manifest = wlxlib.read_json(
            wlxlib.published_root(REPOSITORY_ROOT) / "manifest.json"
        )
        expected_base = (
            "https://raw.githubusercontent.com/seventyfourpandas-cyber/"
            "Faithful-Cockatrice-Pod-Arts/main/WLX/published/"
        )
        self.assertEqual(project["public_base_url"], expected_base)
        self.assertEqual(manifest["base_url"], expected_base)
        self.assertTrue(manifest["cockatrice_xml"]["url"].startswith(expected_base))
        self.assertTrue(
            manifest["cockatrice_installer"]["url"].startswith(expected_base)
        )
        for printing in manifest["printings"]:
            self.assertTrue(printing["picture_url"].startswith(expected_base))
        for item in manifest["files"]:
            self.assertTrue(item["url"].startswith(expected_base))

    def test_workflows_run_the_organized_source_tree(self) -> None:
        workflow_dir = REPOSITORY_ROOT / ".github" / "workflows"
        for name in ("import-wlx-cards.yml", "automated-wlx-publisher.yml"):
            payload = (workflow_dir / name).read_text(encoding="utf-8")
            self.assertIn("WLX/source/automation", payload)
            self.assertNotIn("-r automation/", payload)
            self.assertNotIn("python automation/", payload)

    def test_public_payload_is_fetchable_over_http(self) -> None:
        with AttachmentServer(wlxlib.published_root(REPOSITORY_ROOT)) as base:
            with urllib.request.urlopen(base + "manifest.json", timeout=5) as response:
                manifest = json.load(response)
            with urllib.request.urlopen(base + manifest["cockatrice_xml"]["path"], timeout=5) as response:
                xml_payload = response.read()
            self.assertEqual(
                hashlib.sha256(xml_payload).hexdigest(),
                manifest["cockatrice_xml"]["sha256"],
            )

    def test_organized_repository_has_only_intentional_root_entries(self) -> None:
        visible = {
            path.name
            for path in REPOSITORY_ROOT.iterdir()
            if path.name != ".git" and not path.name.startswith("wlx-publish-")
        }
        self.assertEqual(visible, {".github", ".gitignore", "README.md", "WLX", "imports"})
        for obsolete in (
            "automation",
            "cards",
            "catalog.json",
            "manifest.json",
            "customsets",
            "images",
            "cockatrice-installer",
            "STATUS.md",
        ):
            self.assertFalse((REPOSITORY_ROOT / obsolete).exists(), obsolete)


if __name__ == "__main__":
    unittest.main()
