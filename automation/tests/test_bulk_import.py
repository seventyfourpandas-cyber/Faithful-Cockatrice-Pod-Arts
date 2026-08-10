from __future__ import annotations

import binascii
import hashlib
import importlib.util
import json
import shutil
import struct
import sys
import tempfile
import unittest
import uuid
import zlib
from pathlib import Path


AUTOMATION_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = AUTOMATION_DIR.parent
sys.path.insert(0, str(AUTOMATION_DIR))
import wlxlib  # noqa: E402

IMPORTER_PATH = REPOSITORY_ROOT / "tools" / "wlx_bulk_import.py"
SPEC = importlib.util.spec_from_file_location("wlx_bulk_import", IMPORTER_PATH)
assert SPEC and SPEC.loader
bulk = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bulk
SPEC.loader.exec_module(bulk)


def png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = binascii.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def test_png_bytes(width: int = 300, height: int = 400, offset: int = 0) -> bytes:
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            rows.extend(
                (
                    (x * 7 + offset) % 256,
                    (y * 11 + offset) % 256,
                    (x + y * 3 + offset) % 256,
                )
            )
    payload = b"\x89PNG\r\n\x1a\n"
    payload += png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    payload += png_chunk(b"IDAT", zlib.compress(bytes(rows), level=6))
    payload += png_chunk(b"IEND", b"")
    return payload


def normal_details(name: str) -> dict[str, object]:
    return {
        "name": name,
        "oracle_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "test-card|" + name)),
        "scryfall_uri": "https://example.invalid/" + name.replace(" ", "-"),
        "layout": "normal",
        "faces": [],
        "verified_at": "2026-08-10",
    }


def extus_details() -> dict[str, object]:
    return {
        "name": "Extus, Oriq Overlord // Awaken the Blood Avatar",
        "oracle_id": "0b299983-9f0f-404a-acd1-8f142572b1f1",
        "scryfall_uri": "https://example.invalid/extus",
        "layout": "modal_dfc",
        "verified_at": "2026-08-10",
        "faces": [
            {
                "official_name": "Extus, Oriq Overlord",
                "side": "front",
                "mana_cost": "{1}{W}{B}{B}",
                "mana_value": "4",
                "type_line": "Legendary Creature — Human Warlock",
                "rules_text": "Double strike",
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
                "rules_text": "Create a 3/6 black and red Avatar creature token.",
                "colors": "BR",
                "color_identity": "WBR",
                "power_toughness": "",
                "loyalty": "",
                "defense": "",
            },
        ],
    }


def token_details() -> dict[str, object]:
    return {
        "name": "Avatar Token  ",
        "display_name": "Avatar Token",
        "rules_text": "Haste",
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
        "verified_at": "2026-08-10",
        "source_url": wlxlib.COCKATRICE_TOKEN_DATABASE_URL,
    }


class Fixture:
    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for player in ("Alex", "Will", "Miguel", "Jay"):
            (self.root / "cards" / player / "images").mkdir(parents=True)
            wlxlib.write_json(
                self.root / "cards" / player / "catalog.json",
                wlxlib.empty_player_catalog(player),
            )
            (self.root / "imports" / "incoming" / player.casefold()).mkdir(
                parents=True
            )
        (self.root / "imports" / "needs-attention").mkdir(parents=True)
        (self.root / "automation" / "data").mkdir(parents=True)
        shutil.copy2(REPOSITORY_ROOT / "bulk_import_config.json", self.root)
        self.project = {
            "schema_version": 2,
            "package_id": "bulk-test-wlx",
            "display_name": "Bulk Test WLX",
            "author": "Tests",
            "version": "3.0.0",
            "release_created_at": "2026-08-10T00:00:00+00:00",
            "public_base_url": "https://example.invalid/wlx/",
            "set_code": "WLX",
            "set_name": "Bulk Test WLX",
            "release_date": "2026-08-10",
            "set_priority": 9999,
            "xml_filename": "willex_whimsical_arts.xml",
            "installer_zip_filename": "Willexs_Whimsical_Arts_Cockatrice_Installer.zip",
            "install_folder": "BulkTestWLX",
            "legacy_install_folder": "BulkTestLegacy",
            "players": ["Alex", "Will", "Miguel", "Jay"],
            "default_rarity": "special",
            "uuid_pins": {},
            "scryfall_user_agent": "BulkImporterTests/1.0",
        }
        self.state = {
            "schema_version": 1,
            "next_collector": 2,
            "collectors": {},
            "processed_issues": {},
        }
        self.cache = {
            "schema_version": 1,
            "cards": {"angel of vitality": normal_details("Angel of Vitality")},
        }
        wlxlib.write_json(self.root / "project.json", self.project)
        wlxlib.write_json(self.root / "automation" / "state.json", self.state)
        wlxlib.write_json(
            self.root / "automation" / "data" / "official_cards_cache.json",
            self.cache,
        )
        self.add_existing()
        self.fixtures = self.root / "fixtures"
        self.token_fixtures = self.root / "token-fixtures"
        self.fixtures.mkdir()
        self.token_fixtures.mkdir()

    def close(self) -> None:
        self.temporary.cleanup()

    def add_existing(self) -> None:
        image = self.root / "cards" / "Alex" / "images" / "WLX-001.png"
        image.write_bytes(test_png_bytes(offset=1))
        printing_uuid = wlxlib.stable_printing_uuid(
            self.project["package_id"], "WLX", "001"
        )
        catalog = wlxlib.load_player_catalog(self.root, "Alex")
        catalog["printings"].append(
            {
                "collector_number": "001",
                "uuid": printing_uuid,
                "card_kind": "official",
                "official_name": "Angel of Vitality",
                "flavor_name": "",
                "rarity": "special",
                "image_file": image.name,
                "image_sha256": wlxlib.sha256_file(image),
                "notes": "fixture",
            }
        )
        wlxlib.write_json(self.root / "cards" / "Alex" / "catalog.json", catalog)
        self.state["collectors"]["001"] = {
            "status": "active",
            "player": "Alex",
            "uuid": printing_uuid,
            "card_kind": "official",
        }
        wlxlib.write_json(self.root / "automation" / "state.json", self.state)

    def incoming(self, player: str, filename: str, payload: bytes) -> Path:
        path = self.root / "imports" / "incoming" / player.casefold() / filename
        path.write_bytes(payload)
        return path

    def card_fixture(self, requested: str, details: dict[str, object]) -> None:
        digest = hashlib.sha256(requested.encode("utf-8")).hexdigest()
        wlxlib.write_json(self.fixtures / f"{digest}.json", details)

    def token_fixture(self, creator: str, details: dict[str, object]) -> None:
        digest = hashlib.sha256(creator.encode("utf-8")).hexdigest()
        wlxlib.write_json(self.token_fixtures / f"token-{digest}.json", details)

    def run(self, batch: str = "unit-batch") -> int:
        return bulk.run(
            self.root,
            fixture_dir=self.fixtures,
            token_fixture_dir=self.token_fixtures,
            batch_id=batch,
        )


class BulkImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_one_batch_imports_one_hundred_images_and_bumps_once(self) -> None:
        for number in range(1, 101):
            name = f"Test Card {number:03d}"
            self.fixture.card_fixture(name, normal_details(name))
            self.fixture.incoming(
                "Will", f"{name}.png", test_png_bytes(offset=number + 2)
            )
        self.assertEqual(self.fixture.run(), 0)
        will = wlxlib.load_player_catalog(self.fixture.root, "Will")
        self.assertEqual(len(will["printings"]), 100)
        state = wlxlib.read_json(self.fixture.root / "automation" / "state.json")
        project = wlxlib.read_json(self.fixture.root / "project.json")
        self.assertEqual(state["next_collector"], 102)
        self.assertEqual(project["version"], "3.0.1")
        self.assertFalse(
            any(
                path.suffix.casefold() in {".png", ".jpg", ".jpeg"}
                for path in (self.fixture.root / "imports" / "incoming").rglob("*")
            )
        )
        wlxlib.validate_repository(self.fixture.root)

    def test_more_than_one_hundred_inputs_changes_nothing(self) -> None:
        for number in range(101):
            self.fixture.incoming("Will", f"Too Many {number:03d}.jpg", b"x")
        with self.assertRaises(bulk.BulkImportError):
            self.fixture.run()
        self.assertEqual(
            len(list((self.fixture.root / "imports" / "incoming" / "will").glob("*.jpg"))),
            101,
        )
        self.assertEqual(
            wlxlib.read_json(self.fixture.root / "project.json")["version"], "3.0.0"
        )

    def test_double_faced_images_become_one_linked_printing(self) -> None:
        details = extus_details()
        for face in ("Extus, Oriq Overlord", "Awaken the Blood Avatar"):
            self.fixture.card_fixture(face, details)
        self.fixture.incoming(
            "Will", "Extus, Oriq Overlord.jpg", test_png_bytes(offset=20)
        )
        self.fixture.incoming(
            "Will", "Awaken the Blood Avatar.jpg", test_png_bytes(offset=21)
        )
        self.fixture.run()
        printing = wlxlib.load_player_catalog(self.fixture.root, "Will")["printings"][0]
        self.assertEqual(printing["card_kind"], "official_double_faced")
        self.assertEqual(printing["collector_number"], "002")
        self.assertEqual([face["side"] for face in printing["faces"]], ["front", "back"])
        wlxlib.validate_repository(self.fixture.root)

    def test_token_can_follow_its_creating_face_in_the_same_batch(self) -> None:
        details = extus_details()
        for face in ("Extus, Oriq Overlord", "Awaken the Blood Avatar"):
            self.fixture.card_fixture(face, details)
        self.fixture.token_fixture("Awaken the Blood Avatar", token_details())
        self.fixture.incoming(
            "Will", "Extus, Oriq Overlord.png", test_png_bytes(offset=30)
        )
        self.fixture.incoming(
            "Will", "Awaken the Blood Avatar.png", test_png_bytes(offset=31)
        )
        self.fixture.incoming(
            "Will", "TOKEN - Awaken the Blood Avatar.png", test_png_bytes(offset=32)
        )
        self.fixture.run()
        printings = wlxlib.load_player_catalog(self.fixture.root, "Will")["printings"]
        self.assertEqual(
            [printing["card_kind"] for printing in printings],
            ["official_double_faced", "official_token"],
        )
        self.assertEqual(printings[1]["creator_card"], "Awaken the Blood Avatar")
        wlxlib.validate_repository(self.fixture.root)

    def test_collector_filename_replaces_art_without_changing_identity(self) -> None:
        before = wlxlib.load_player_catalog(self.fixture.root, "Alex")["printings"][0]
        original_uuid = before["uuid"]
        original_hash = before["image_sha256"]
        self.fixture.incoming("Alex", "WLX-001.jpg", test_png_bytes(offset=70))
        self.fixture.run()
        after = wlxlib.load_player_catalog(self.fixture.root, "Alex")["printings"][0]
        self.assertEqual(after["collector_number"], "001")
        self.assertEqual(after["uuid"], original_uuid)
        self.assertNotEqual(after["image_sha256"], original_hash)
        self.assertEqual(after["image_file"], "WLX-001.png")
        wlxlib.validate_repository(self.fixture.root)

    def test_valid_items_publish_while_permanent_name_error_moves_aside(self) -> None:
        self.fixture.card_fixture("Sol Ring", normal_details("Sol Ring"))
        self.fixture.incoming("Miguel", "Sol Ring.png", test_png_bytes(offset=80))
        self.fixture.incoming(
            "Miguel", "Definitely Not A Real Card.png", test_png_bytes(offset=81)
        )
        self.fixture.run()
        self.assertEqual(
            len(wlxlib.load_player_catalog(self.fixture.root, "Miguel")["printings"]), 1
        )
        report = wlxlib.read_json(self.fixture.root / "imports" / "last-run.json")
        self.assertEqual(len(report["added"]), 1)
        self.assertEqual(len(report["needs_attention"]), 1)
        moved = self.fixture.root / report["needs_attention"][0]["moved_image"]
        self.assertTrue(moved.exists())
        self.assertTrue(Path(str(moved) + ".error.txt").exists())

    def test_exact_duplicate_art_is_not_republished(self) -> None:
        existing = self.fixture.root / "cards" / "Alex" / "images" / "WLX-001.png"
        self.fixture.card_fixture("Sol Ring", normal_details("Sol Ring"))
        self.fixture.incoming("Will", "Sol Ring.png", existing.read_bytes())
        self.fixture.run()
        self.assertEqual(
            len(wlxlib.load_player_catalog(self.fixture.root, "Will")["printings"]), 0
        )
        report = wlxlib.read_json(self.fixture.root / "imports" / "last-run.json")
        self.assertIn("already published", report["needs_attention"][0]["error"])


if __name__ == "__main__":
    unittest.main()
