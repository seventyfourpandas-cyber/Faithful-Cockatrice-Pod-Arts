WILLEX'S WHIMSICAL ARTS — AUTOMATIC CARD IMPORTER
Version 0.1

WHAT THIS DOWNLOAD IS
=====================
This is a drop-in add-on for the existing Faithful-Cockatrice-Pod-Arts GitHub
repository. It does not replace your current catalog, XML, images, manifest, or
installer. It adds an automatic incoming-card folder and a GitHub Action that
processes images after you upload them.

There is no spreadsheet.
There is no Issue form.
There is no second Build button after the upload.

NORMAL USE
==========
1. Name a finished image exactly after the real official card:

       Sol Ring.png
       Angel of Vitality.jpg
       Eriette of the Charmed Apple.png

2. Upload it to one of these folders in the GitHub repository:

       imports/incoming/alex/
       imports/incoming/will/
       imports/incoming/miguel/
       imports/incoming/jay/

   You may also upload directly to imports/incoming/. A root-level image is
   assigned to Alex by default.

3. Click GitHub's normal Commit changes button.

4. GitHub automatically:
   - reads the filename as the card name;
   - requires an exact official-card match from Scryfall;
   - checks that the image is readable;
   - assigns the next WLX collector number;
   - creates a stable printing UUID;
   - copies the image into images/WLX using the established numbered/hash name;
   - adds the printing to catalog.json;
   - adds the printing to customsets/willex_whimsical_arts.xml;
   - updates manifest.json and bumps the patch version;
   - validates that the published image, catalog entry, XML entry, and manifest
     agree;
   - deletes the incoming copy only after that validation succeeds;
   - commits the completed result back into the repository.

A single card and a 60-card batch use the same process.

FIRST-TIME INSTALLATION
=======================
1. Extract this ZIP on your computer.

2. Upload the CONTENTS of the extracted folder to the ROOT of your existing
   GitHub repository. Preserve the folders exactly. For example, the workflow
   must end up at:

       .github/workflows/import-wlx-cards.yml

   Do not put the whole extracted folder inside another outer folder.

3. On GitHub, open:

       Repository Settings > Actions > General

   Under Workflow permissions, allow GitHub Actions to read and write repository
   contents, then save.

4. Open the Actions tab. You should see:

       Import WLX card art

5. The initial install may run once because the empty incoming folders were
   added. That is harmless. It will report that there were no images to process.

WHAT SUCCESS LOOKS LIKE
=======================
After the Action finishes, the uploaded image is gone from imports/incoming and
appears in images/WLX. The repository also receives an automatic commit named:

       Process incoming WLX card art [skip ci]

The new card entry appears in catalog.json, the Cockatrice XML, and manifest.json.
The existing installer ZIP is preserved; it is not rebuilt by this importer.

WHAT FAILURE LOOKS LIKE
=======================
The importer never deletes a card merely because processing started.

A permanent input problem is moved to:

       imports/needs-attention/<player>/

Beside it will be an .error.txt file explaining the reason. Examples:
- the filename did not exactly match an official card;
- the image file was damaged;
- the exact artwork was already published;
- the card is double-faced or otherwise needs special handling;
- the image was placed in an unknown player folder.

The latest complete report is always written to:

       imports/last-run.json

Fix or rename the image, then move it back into an incoming folder.

If Scryfall or the network is temporarily unavailable, the image stays in the
incoming folder so it can be retried. It is not moved or deleted.

CURRENT VERSION LIMITS
======================
This first version intentionally handles only normal, single-faced, official MTG
cards. It does not yet import:
- double-faced cards;
- split, flip, adventure, or reversible cards;
- tokens or emblems;
- fully custom cards that do not exist in Scryfall;
- flavor-name/renamed variants.

Those existing entries already in the repository are preserved. The importer
simply refuses to create new complicated entries until that support is added.

MULTIPLE ARTS FOR THE SAME CARD
===============================
You may import another custom art for a card that is already in WLX. It receives
a new collector number, new UUID, and new image. The visible card name remains
the real official name.

Because two files cannot have the identical filename in one Windows folder,
import two arts for the same card in separate uploads for now. A deliberate
multi-art naming system can be added later without changing visible card names.

LOCAL BACKUP MODE
=================
RUN_IMPORTER_LOCALLY.bat is included as a backup. It runs the same importer on a
local copy of the complete repository. Python and internet access are required.
Normal GitHub use does not require clicking this file.

IMPORTANT SAFETY BEHAVIOR
=========================
The order is always:

    verify input
    -> copy published image
    -> update catalog and XML
    -> update manifest
    -> validate the completed repository
    -> delete incoming copy last

The importer uses repository files and commits. It does not create GitHub Issues,
comments, pull requests, or messages.

CONFIGURATION
=============
The defaults are already filled in for the current project in:

       importer_config.json

They currently target:
- Package: Willex's Whimsical Arts
- Set code: WLX
- XML: customsets/willex_whimsical_arts.xml
- Images: images/WLX
- Repository raw base URL:
  https://raw.githubusercontent.com/seventyfourpandas-cyber/Faithful-Cockatrice-Pod-Arts/main/

Do not change these unless the project name, repository, set code, or paths change.
