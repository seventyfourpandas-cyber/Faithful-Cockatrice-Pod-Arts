# WLX no-Command-Prompt fix — v2.0.5

This patch changes only the launcher entry point. The desktop shortcut now uses Windows' console-free script host, so the polished WLX launcher appears without a Command Prompt opening, flashing, or minimizing first.

It does not contain or replace any card catalog, card image, collector number, UUID, manifest, or generated Cockatrice XML.

## Upload once

1. Open the GitHub repository's **Code** tab.
2. Choose **Add file → Upload files**.
3. Open this package's `UPLOAD_TO_GITHUB` folder.
4. Drag **everything inside** `UPLOAD_TO_GITHUB` onto GitHub.
5. Confirm GitHub previews exactly these four paths:
   - `automation/installer_source/WLX_Cockatrice_Updater.ps1`
   - `automation/installer_source/README_FOR_PLAYERS.txt`
   - `automation/tests/test_wlx.py`
   - `project.json`
6. Commit directly to `main`.
7. Wait for **Actions → Automated WLX Publisher → repository-build** to finish with a green checkmark.
8. Confirm `STATUS.md` says `2.0.5`.
9. Click the existing black **Willex's Whimsical Arts** desktop shortcut once.

The old shortcut may show the Command Prompt **one final time on that v2.0.4 → v2.0.5 transition click**. That click rewrites the shortcut. Every click afterward starts only the polished WLX launcher, with no console flash.

No installer download or reinstall is required.

## Verification

- All 29 publisher and transaction tests passed.
- Cockatrice v4 XML schema validation passed.
- The PowerShell source parsed without new syntax errors.
- The embedded VBScript launcher parsed successfully.
- The generated shortcut targets `wscript.exe`, not PowerShell or Command Prompt.
