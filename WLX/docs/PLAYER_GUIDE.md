# WLX Cockatrice Player Guide

## First installation

1. Open `WLX/published/` in the repository and download `Willexs_Whimsical_Arts_Cockatrice_Installer.zip`.
2. Extract the ZIP to a normal folder.
3. Close Cockatrice.
4. Double-click `INSTALL_OR_UPDATE.bat`.
5. Wait for the success message.
6. Open Cockatrice and confirm **Willex's Whimsical Arts (WLX)** is enabled under **Card Database → Manage Sets**.

Windows may show a warning because the small batch and PowerShell utilities are not signed with a commercial code-signing certificate. The complete source is included in the installer, and every downloaded release file is verified by SHA-256 before installation.

## Later use

Launch Cockatrice through the **Willex's Whimsical Arts** desktop shortcut. It checks for the current verified WLX release, updates one canonical XML, and then opens Cockatrice.

You do not need to:

- download the installer again for ordinary card updates;
- import an XML file;
- edit GitHub files;
- change Cockatrice's card-picture sources;
- select artwork manually for another player.

Do not use Cockatrice's **Add custom sets/cards** button for WLX. That importer creates numbered copies instead of updating the canonical WLX file.

## Troubleshooting pictures

Keep **Download card pictures on the fly** enabled. If the exact WLX printing remains blank or shows outdated art:

1. Close Cockatrice.
2. Run `REPAIR_ART.bat` from the extracted installer or the installed folder.
3. Reopen Cockatrice and select the exact WLX printing.

Repair is recoverable. It quarantines matching filesystem art and Cockatrice's network image cache; it does not remove unrelated custom-set XML files.

## Portable or unusual Cockatrice installations

Edit this file after the first installer run:

`%LOCALAPPDATA%\WillexsWhimsicalArts\installer_settings.json`

Set the needed custom paths for `cockatrice_data_dir`, `cockatrice_pics_dir`, `cockatrice_network_cache_dir`, or `cockatrice_exe`, then run the installer again.

## Uninstall

Run `UNINSTALL.bat`. The WLX XML is moved into a recoverable folder, while decks, settings, the main Cockatrice card database, and unrelated custom sets are left alone.
