#!/usr/bin/env python3
"""End-to-end test for the generated WLX bootstrap and PowerShell updater.

The test uses a localhost publication and an isolated Cockatrice profile.  It
never reads or changes the operator's real Cockatrice files.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path


AUTOMATION_DIR = Path(__file__).resolve().parents[1]
SOURCE_REPOSITORY = AUTOMATION_DIR.parents[2]
sys.path.insert(0, str(AUTOMATION_DIR))
import wlxlib  # noqa: E402


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *args: object) -> None:
        return


class PublicationServer:
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


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def run_pwsh(
    pwsh: str,
    script: Path,
    environment: dict[str, str],
    *,
    expect_success: bool,
    no_launch: bool = True,
) -> str:
    command = [
        pwsh,
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
    ]
    if no_launch:
        command.append("-NoLaunch")
    result = subprocess.run(
        command,
        cwd=script.parent,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=90,
        check=False,
    )
    if expect_success and result.returncode != 0:
        raise AssertionError(f"PowerShell integration failed ({result.returncode}):\n{result.stdout}")
    if not expect_success and result.returncode == 0:
        raise AssertionError("A deliberately corrupted publication was accepted")
    return result.stdout


def main(*, require_pwsh: bool) -> int:
    pwsh = shutil.which("pwsh")
    if not pwsh:
        if require_pwsh:
            raise SystemExit("pwsh is required for the PowerShell integration test")
        print("SKIP: pwsh is not installed")
        return 0

    with tempfile.TemporaryDirectory(prefix="wlx-powershell-integration-") as temporary:
        test_root = Path(temporary)
        repository = test_root / "repository"
        shutil.copytree(
            SOURCE_REPOSITORY,
            repository,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".wlx-result"),
        )
        local_app_data = test_root / "local-app-data"
        temp_dir = test_root / "windows-temp"
        shim_dir = test_root / "bin"
        xdg_cache = test_root / "xdg-cache"
        xdg_config = test_root / "xdg-config"
        xdg_data = test_root / "xdg-data"
        local_app_data.mkdir()
        temp_dir.mkdir()
        shim_dir.mkdir()
        xdg_cache.mkdir()
        xdg_config.mkdir()
        xdg_data.mkdir()
        (shim_dir / "powershell.exe").symlink_to(Path(pwsh))
        launch_marker = test_root / "cockatrice-launched.txt"
        fake_cockatrice = shim_dir / "Cockatrice.exe"
        fake_cockatrice.write_text(
            f"#!/bin/sh\nprintf launched > '{launch_marker}'\n", encoding="utf-8"
        )
        fake_cockatrice.chmod(0o755)

        environment = os.environ.copy()
        environment.update(
            {
                "LOCALAPPDATA": str(local_app_data),
                "TEMP": str(temp_dir),
                "XDG_CACHE_HOME": str(xdg_cache),
                "XDG_CONFIG_HOME": str(xdg_config),
                "XDG_DATA_HOME": str(xdg_data),
                "PATH": str(shim_dir) + os.pathsep + environment.get("PATH", ""),
            }
        )

        with PublicationServer(repository) as repository_url:
            base_url = repository_url + "WLX/published/"
            project_path = wlxlib.source_path(repository, wlxlib.PROJECT_RELATIVE)
            project = wlxlib.read_json(project_path)
            project["public_base_url"] = base_url
            wlxlib.write_json(project_path, project)
            wlxlib.build_repository(repository)

            installer_zip = (
                wlxlib.published_root(repository)
                / str(project["installer_zip_filename"])
            )
            launch_dir = test_root / "installer-launch"
            with zipfile.ZipFile(installer_zip) as archive:
                archive.extractall(launch_dir)
            bootstrap = launch_dir / "WLX_Bootstrap.ps1"

            legacy_root = local_app_data / str(project["legacy_install_folder"])
            legacy_root.mkdir()
            (legacy_root / "migration-marker.txt").write_text(
                "recoverable legacy updater data", encoding="utf-8"
            )
            (legacy_root / "installer_settings.json").write_text(
                json.dumps(
                    {
                        "manifest_url": repository_url + "manifest.json",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            first_output = run_pwsh(pwsh, bootstrap, environment, expect_success=True)
            install_root = local_app_data / str(project["install_folder"])
            state_path = install_root / "installed_state.json"
            if not state_path.is_file():
                raise AssertionError(f"Updater did not create installed state:\n{first_output}")
            installed_icon = install_root / "WLX_Shortcut.ico"
            source_icon = (
                wlxlib.source_root(repository)
                / "automation"
                / "installer_source"
                / "WLX_Shortcut.ico"
            )
            if not installed_icon.is_file():
                raise AssertionError("Updater did not install the embedded black shortcut icon")
            if wlxlib.sha256_file(installed_icon) != wlxlib.sha256_file(source_icon):
                raise AssertionError("Installed shortcut icon does not match the verified source icon")
            settings = read_json(install_root / "installer_settings.json")
            if settings["manifest_url"] != base_url + "manifest.json":
                raise AssertionError(
                    "Installer retained the obsolete root-level manifest URL"
                )
            if Path(str(settings["cockatrice_exe"])) != fake_cockatrice.resolve():
                raise AssertionError("Updater did not remember the resolved Cockatrice executable")
            first_state = read_json(state_path)
            installed_xml = Path(str(first_state["installed_xml"]))
            if not installed_xml.is_file():
                raise AssertionError("Updater did not install the canonical XML")
            if legacy_root.exists():
                raise AssertionError("The previous updater folder was not migrated")
            migrated_markers = list(
                (install_root / "migration-backup").rglob("migration-marker.txt")
            )
            if len(migrated_markers) != 1:
                raise AssertionError("The previous updater folder was not recoverably archived")
            original_xml_hash = wlxlib.sha256_file(installed_xml)
            first_printing = first_state["printings"][0]
            if first_printing["uuid"] != "f6a9cc3e-beac-5fac-84aa-ca36b34d7d10":
                raise AssertionError("The preserved WLX #001 UUID changed during installation")

            # Simulate a Cockatrice filesystem cache entry for the current UUID.
            data_dir = installed_xml.parent.parent
            cache_file = (
                data_dir
                / "pics"
                / "downloadedPics"
                / "WLX"
                / f"Angel of Vitality_{first_printing['uuid']}.png"
            )
            cache_file.parent.mkdir(parents=True)
            cache_file.write_bytes(b"old cached picture")

            # Publish replacement artwork while retaining the permanent UUID.
            source_image = wlxlib.player_images_path(repository, "Alex") / "WLX-001.png"
            source_image.write_bytes(source_image.read_bytes() + b"\nWLX integration replacement\n")
            alex_catalog_path = wlxlib.player_catalog_path(repository, "Alex")
            alex_catalog = wlxlib.read_json(alex_catalog_path)
            alex_catalog["printings"][0]["image_sha256"] = wlxlib.sha256_file(source_image)
            wlxlib.write_json(alex_catalog_path, alex_catalog)
            project = wlxlib.read_json(project_path)
            project["version"] = "2.0.1"
            project["release_created_at"] = "2026-08-01T12:00:00-04:00"
            wlxlib.write_json(project_path, project)
            wlxlib.build_repository(repository)

            second_output = run_pwsh(pwsh, bootstrap, environment, expect_success=True)
            second_state = read_json(state_path)
            second_printing = second_state["printings"][0]
            if second_printing["uuid"] != first_printing["uuid"]:
                raise AssertionError("Artwork replacement changed the printing UUID")
            if second_printing["picture_url"] == first_printing["picture_url"]:
                raise AssertionError("Artwork replacement did not change its content-addressed URL")
            if cache_file.exists():
                raise AssertionError(f"Targeted old artwork cache was not quarantined:\n{second_output}")
            quarantined = list((install_root / "quarantine").rglob(cache_file.name))
            if not quarantined:
                raise AssertionError("Targeted old artwork cache was not recoverably preserved")

            # The normal shortcut path must use the remembered executable and
            # actually launch Cockatrice after the verified update completes.
            launch_output = run_pwsh(
                pwsh,
                bootstrap,
                environment,
                expect_success=True,
                no_launch=False,
            )
            for _ in range(50):
                if launch_marker.is_file():
                    break
                time.sleep(0.1)
            if not launch_marker.is_file():
                raise AssertionError(f"Updater did not launch Cockatrice:\n{launch_output}")
            if "Launching Cockatrice" not in launch_output:
                raise AssertionError("Updater launched Cockatrice without reporting the launch step")

            # A bad hosted hash must fail without replacing the working XML.
            safe_xml_hash = wlxlib.sha256_file(installed_xml)
            manifest_path = wlxlib.published_root(repository) / "manifest.json"
            manifest = wlxlib.read_json(manifest_path)
            manifest["cockatrice_xml"]["sha256"] = "0" * 64
            wlxlib.write_json(manifest_path, manifest)
            failure_output = run_pwsh(pwsh, bootstrap, environment, expect_success=False)
            if wlxlib.sha256_file(installed_xml) != safe_xml_hash:
                raise AssertionError("Failed verification altered the working Cockatrice XML")
            if "failed SHA-256 verification" not in failure_output:
                raise AssertionError("Corrupted publication failed for an unexpected reason")
            if original_xml_hash == safe_xml_hash:
                raise AssertionError("The valid replacement XML was never installed")

    print("PASS: bootstrap, verified install, stable-UUID art refresh, cache quarantine, rollback safety")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-pwsh", action="store_true")
    args = parser.parse_args()
    raise SystemExit(main(require_pwsh=args.require_pwsh))
