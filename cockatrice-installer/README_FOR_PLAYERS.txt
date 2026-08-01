Willex's Whimsical Arts — WLX Cockatrice Installer v2.0.8
===============================================================

FIRST TIME
1. Extract this ZIP to a normal folder.
2. Double-click INSTALL_OR_UPDATE.bat.
3. Let the window finish. It creates an update-and-launch shortcut on your Desktop.
4. In Cockatrice, use Card Database > Manage Sets and make sure Willex's Whimsical Arts (WLX) is enabled.

EVERY LATER TIME
Use the Desktop shortcut. It checks the hosted WLX manifest, refreshes the verified updater when
needed, verifies the XML with SHA-256, replaces one canonical XML, quarantines matching numbered
or duplicate copies, and opens Cockatrice. On its first use, it asks you to choose Cockatrice.exe
and remembers that exact location on any drive. It asks again only if Cockatrice.exe is moved.

The shortcut opens a compact WLX launcher instead of a raw Command Prompt. Its three-line activity
feed reports each real update stage, and the red flame line fills as the work completes. When the
collection is ready, the launcher pauses briefly, opens Cockatrice, and closes itself automatically.
There is no OK button or press-any-key screen. A troubleshooting log remains at
%LOCALAPPDATA%\WillexsWhimsicalArts\launcher.log.

IMPORTANT
Do not use Cockatrice's "Add custom sets/cards" button for this pack. That button makes a new
numbered XML copy each time instead of updating the old one. Always use INSTALL_OR_UPDATE.bat
or the Desktop update shortcut.

WHAT IT CHANGES
- Installs exactly one canonical XML in Cockatrice's customsets folder.
- Moves matching ghost XMLs into a dated, recoverable quarantine folder.
- Keeps updater files in %LOCALAPPDATA%\WillexsWhimsicalArts.
- Does not replace cards.xml, decks, settings, or anyone else's custom sets.
- WLX card images download from the public source when Cockatrice needs them.

IF THE WRONG ART OR A BLANK CARD PERSISTS
1. Close Cockatrice.
2. Double-click REPAIR_ART.bat.
3. Keep "Download card pictures on the fly" enabled.
4. Reopen Cockatrice and select the exact custom printing again.

Repair moves matching filesystem art and Cockatrice's opaque network image cache into:
%LOCALAPPDATA%\WillexsWhimsicalArts\quarantine
Nothing is permanently deleted; unrelated XML files are not touched.

IF COCKATRICE IS PORTABLE OR INSTALLED SOMEWHERE UNUSUAL
Open %LOCALAPPDATA%\WillexsWhimsicalArts\installer_settings.json in Notepad and fill in:
- cockatrice_data_dir: the folder containing Cockatrice's cards.xml/customsets folder
- cockatrice_pics_dir: optional override for the pictures folder
- cockatrice_network_cache_dir: optional override ending in a folder named downloaded
- cockatrice_exe: the full path to Cockatrice.exe

UNINSTALL
Double-click UNINSTALL.bat. It moves this pack's canonical XML into a recoverable folder and
leaves other custom sets alone.
