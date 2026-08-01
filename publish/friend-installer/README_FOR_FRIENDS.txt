Alex's Cockatrice Alternate Art — Friend Installer v1.0.0
========================================================

FIRST TIME
1. Extract this ZIP to a normal folder.
2. Double-click INSTALL_OR_UPDATE.bat.
3. Let the window finish. It creates an update-and-launch shortcut on your Desktop.
4. In Cockatrice, use Card Database > Manage Sets and make sure Alex's custom set(s) are enabled.

EVERY LATER TIME
Use the Desktop shortcut. It checks Alex's hosted manifest, verifies the XML with SHA-256,
installs an update only when needed, and opens Cockatrice.

WHAT IT CHANGES
- Installs one XML file in Cockatrice's customsets folder.
- Keeps updater files in %LOCALAPPDATA%\AlexCockatriceAltArt.
- Does not replace cards.xml, decks, settings, or anyone else's custom sets.
- Card images download from Alex's public source when Cockatrice needs them.

IF COCKATRICE IS PORTABLE OR INSTALLED SOMEWHERE UNUSUAL
Open %LOCALAPPDATA%\AlexCockatriceAltArt\friend_settings.json in Notepad and fill in:
- cockatrice_data_dir: the folder containing Cockatrice's cards.xml/customsets folder
- cockatrice_exe: the full path to Cockatrice.exe

IF ART DOES NOT APPEAR
1. Close and reopen Cockatrice after updating.
2. Confirm the custom set is enabled under Card Database > Manage Sets.
3. Confirm your deck uses the exact custom printing in the Printing Selector.
4. Ask Alex whether your updater reports the newest version.

UNINSTALL
Double-click UNINSTALL.bat. It moves this pack's XML into a recoverable folder and leaves
other custom sets alone.
