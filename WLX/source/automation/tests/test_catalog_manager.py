from __future__ import annotations

import csv
import sys
import unittest
from pathlib import Path


AUTOMATION_DIR = Path(__file__).resolve().parents[1]
SOURCE_ROOT = AUTOMATION_DIR.parent
TOOLS_DIR = SOURCE_ROOT / "tools"
TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(AUTOMATION_DIR))
sys.path.insert(0, str(TOOLS_DIR))
sys.path.insert(0, str(TESTS_DIR))

import process_issue  # noqa: E402
import wlx_catalog_manager as manager  # noqa: E402
import wlxlib  # noqa: E402
from test_wlx import RepositoryFixture, extus_details, test_png_bytes  # noqa: E402


def write_manager_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=wlxlib.CARD_MANAGER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def read_manager_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class CatalogManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = RepositoryFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def persist_state(self) -> None:
        wlxlib.write_json(
            self.fixture.root / "automation" / "state.json", self.fixture.state
        )

    def build_manager(self) -> Path:
        wlxlib.build_repository(self.fixture.root)
        return wlxlib.card_manager_path(self.fixture.root)

    def test_build_creates_one_clean_row_per_physical_printing(self) -> None:
        catalogs = wlxlib.load_all_catalogs(self.fixture.root, self.fixture.config)
        process_issue.allocate_official_double_faced_printing(
            self.fixture.root,
            self.fixture.config,
            self.fixture.state,
            catalogs,
            player="Will",
            card_details=extus_details(),
            front_payload=test_png_bytes(offset=41),
            front_suffix=".png",
            back_payload=test_png_bytes(offset=53),
            back_suffix=".png",
            front_flavor_name="",
            back_flavor_name="Blood Moon",
            actor="tester",
            issue_number=2,
        )
        wlxlib.persist_catalogs(self.fixture.root, catalogs)
        self.persist_state()

        path = self.build_manager()
        rows = read_manager_rows(path)
        self.assertEqual(len(rows), 2)
        double = next(row for row in rows if row["card_kind"] == "official_double_faced")
        self.assertEqual(
            double["card_name"],
            "Extus, Oriq Overlord // Awaken the Blood Avatar",
        )
        self.assertEqual(double["current_back_title"], "Blood Moon")
        self.assertEqual(double["source_images"], "WLX-002-front.png | WLX-002-back.png")
        self.assertTrue(all(not row[field] for row in rows for field in manager.CHANGE_FIELDS))
        self.assertEqual(manager.requested_status(self.fixture.root), "clean")

    def test_owner_move_and_retired_number_reuse_updates_every_source(self) -> None:
        self.fixture.add_official("Will", "002", "Sol Ring", offset=71)
        self.fixture.state["collectors"]["003"] = {
            "status": "retired",
            "player": "Will",
            "uuid": wlxlib.stable_printing_uuid(
                self.fixture.config["package_id"], "WLX", "003"
            ),
            "card_kind": "official",
            "retired_at": "2026-08-01T00:00:00+00:00",
        }
        self.fixture.state["next_collector"] = 4
        self.persist_state()
        path = self.build_manager()
        rows = read_manager_rows(path)
        sol_ring = next(row for row in rows if row["card_name"] == "Sol Ring")
        original_uuid = sol_ring["printing_uuid"]
        sol_ring["CHANGE_owner_to"] = "Alex"
        sol_ring["CHANGE_collector_to"] = "3"
        write_manager_rows(path, rows)

        result = manager.apply_plan(self.fixture.root)
        self.assertTrue(result["changed"])
        self.assertEqual(result["owner_moves"], 1)
        self.assertEqual(result["renumbered"], 1)
        _config, state, resolved = wlxlib.validate_repository(self.fixture.root)
        moved = next(item for item in resolved if item.card_name == "Sol Ring")
        self.assertEqual((moved.player, moved.collector_number), ("Alex", "003"))
        self.assertEqual(
            moved.printing_uuid,
            original_uuid,
        )
        self.assertEqual(
            wlxlib.read_json(self.fixture.root / "project.json")["uuid_pins"]["003"],
            original_uuid,
        )
        self.assertTrue(
            (self.fixture.root / "cards" / "Alex" / "images" / "WLX-003.png").is_file()
        )
        self.assertFalse(
            (self.fixture.root / "cards" / "Will" / "images" / "WLX-002.png").exists()
        )
        self.assertEqual(state["collectors"]["002"]["status"], "retired")
        self.assertEqual(state["collectors"]["003"]["status"], "active")
        self.assertEqual(state["collectors"]["003"]["player"], "Alex")
        self.assertTrue(
            any(
                entry["collector_number"] == "003"
                and entry["status"] == "retired"
                for entry in state["collector_history"]
            )
        )
        self.assertEqual(
            wlxlib.read_json(self.fixture.root / "project.json")["version"],
            "2.0.1",
        )
        refreshed = read_manager_rows(path)
        refreshed_sol = next(row for row in refreshed if row["card_name"] == "Sol Ring")
        self.assertEqual(refreshed_sol["current_collector"], "WLX-003")
        self.assertEqual(refreshed_sol["current_owner"], "Alex")
        self.assertTrue(all(not refreshed_sol[field] for field in manager.CHANGE_FIELDS))

    def test_two_cards_can_swap_numbers_atomically_in_one_folder(self) -> None:
        self.fixture.add_official("Alex", "002", "Sol Ring", offset=97)
        self.fixture.state["next_collector"] = 3
        self.persist_state()
        path = self.build_manager()
        rows = read_manager_rows(path)
        next(row for row in rows if row["card_name"] == "Angel of Vitality")[
            "CHANGE_collector_to"
        ] = "2"
        next(row for row in rows if row["card_name"] == "Sol Ring")[
            "CHANGE_collector_to"
        ] = "1"
        write_manager_rows(path, rows)

        manager.apply_plan(self.fixture.root)
        _config, _state, resolved = wlxlib.validate_repository(self.fixture.root)
        by_name = {item.card_name: item for item in resolved}
        self.assertEqual(by_name["Angel of Vitality"].collector_number, "002")
        self.assertEqual(by_name["Sol Ring"].collector_number, "001")
        self.assertTrue(
            (self.fixture.root / "cards" / "Alex" / "images" / "WLX-001.png").is_file()
        )
        self.assertTrue(
            (self.fixture.root / "cards" / "Alex" / "images" / "WLX-002.png").is_file()
        )

    def test_three_retired_gaps_can_be_reclaimed_in_one_bulk_edit(self) -> None:
        for collector, owner, offset in (
            ("002", "Will", 121),
            ("005", "Miguel", 133),
            ("006", "Jay", 145),
        ):
            self.fixture.add_official(owner, collector, "Sol Ring", offset=offset)
        for collector in ("003", "004", "012"):
            self.fixture.state["collectors"][collector] = {
                "status": "retired",
                "player": "Will",
                "uuid": wlxlib.stable_printing_uuid(
                    self.fixture.config["package_id"], "WLX", collector
                ),
                "card_kind": "official",
                "retired_at": "2026-08-01T00:00:00+00:00",
            }
        self.fixture.state["next_collector"] = 13
        self.persist_state()
        path = self.build_manager()
        rows = read_manager_rows(path)
        target_by_current = {"WLX-002": "3", "WLX-005": "004", "WLX-006": "WLX-012"}
        for row in rows:
            if row["current_collector"] in target_by_current:
                row["CHANGE_collector_to"] = target_by_current[row["current_collector"]]
        write_manager_rows(path, rows)

        result = manager.apply_plan(self.fixture.root)
        self.assertEqual(result["renumbered"], 3)
        _config, state, resolved = wlxlib.validate_repository(self.fixture.root)
        self.assertEqual(
            {item.collector_number for item in resolved},
            {"001", "003", "004", "012"},
        )
        self.assertTrue(
            all(state["collectors"][collector]["status"] == "active" for collector in ("003", "004", "012"))
        )

    def test_duplicate_final_collector_is_rejected_before_sources_change(self) -> None:
        self.fixture.add_official("Will", "002", "Sol Ring", offset=109)
        self.fixture.state["next_collector"] = 3
        self.persist_state()
        path = self.build_manager()
        rows = read_manager_rows(path)
        next(row for row in rows if row["card_name"] == "Sol Ring")[
            "CHANGE_collector_to"
        ] = "001"
        write_manager_rows(path, rows)
        alex_before = (self.fixture.root / "cards" / "Alex" / "catalog.json").read_bytes()
        will_before = (self.fixture.root / "cards" / "Will" / "catalog.json").read_bytes()

        with self.assertRaisesRegex(manager.CatalogManagerError, "cannot share"):
            manager.apply_plan(self.fixture.root)
        self.assertEqual(
            (self.fixture.root / "cards" / "Alex" / "catalog.json").read_bytes(),
            alex_before,
        )
        self.assertEqual(
            (self.fixture.root / "cards" / "Will" / "catalog.json").read_bytes(),
            will_before,
        )

    def test_view_only_edit_is_rejected_with_change_column_instruction(self) -> None:
        path = self.build_manager()
        rows = read_manager_rows(path)
        rows[0]["current_owner"] = "Will"
        write_manager_rows(path, rows)
        with self.assertRaisesRegex(manager.CatalogManagerError, "view-only"):
            manager.requested_status(self.fixture.root)

    def test_rarity_and_titles_can_change_or_clear(self) -> None:
        path = self.build_manager()
        rows = read_manager_rows(path)
        rows[0]["CHANGE_rarity_to"] = "mythic"
        rows[0]["CHANGE_front_title_to"] = "Radiant Alex"
        write_manager_rows(path, rows)
        manager.apply_plan(self.fixture.root)
        printing = self.fixture.catalog("Alex")["printings"][0]
        self.assertEqual(printing["rarity"], "mythic")
        self.assertEqual(printing["flavor_name"], "Radiant Alex")

        rows = read_manager_rows(path)
        rows[0]["CHANGE_front_title_to"] = "CLEAR"
        write_manager_rows(path, rows)
        manager.apply_plan(self.fixture.root)
        self.assertEqual(self.fixture.catalog("Alex")["printings"][0]["flavor_name"], "")


if __name__ == "__main__":
    unittest.main()
