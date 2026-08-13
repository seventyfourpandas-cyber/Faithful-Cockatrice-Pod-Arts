# Willex's Whimsical Arts

Willex's Whimsical Arts (`WLX`) is a shared, automatically updated Cockatrice
card-art publication for Alex, Will, Miguel, and Jay. This repository contains
both the editable per-player source and the verified public update payload.

## Install for Cockatrice

Download [Willexs_Whimsical_Arts_Cockatrice_Installer.zip](./WLX/published/Willexs_Whimsical_Arts_Cockatrice_Installer.zip),
extract it, close Cockatrice, and run `INSTALL_OR_UPDATE.bat` once.

The installer creates a **Willex's Whimsical Arts** desktop shortcut. Use that
shortcut later: it verifies updates, installs the current WLX XML and artwork
references, and opens Cockatrice. See [PLAYER_GUIDE.md](./WLX/docs/PLAYER_GUIDE.md).

## Add or replace artwork

Artwork intake is repository-file based. It never creates GitHub Issues.

Upload up to 100 appropriately named PNG/JPEG files in one commit to one of:

```text
imports/incoming/alex/
imports/incoming/will/
imports/incoming/miguel/
imports/incoming/jay/
```

The **Import WLX card art** Action verifies the whole persistent batch, updates
the canonical player catalogs, rebuilds and tests WLX, removes successful
incoming copies, and makes one publication commit.

[BULK_IMPORT_GUIDE.md](./WLX/docs/BULK_IMPORT_GUIDE.md) documents normal cards,
automatically paired double-faced cards, linked token art, multiple artworks,
and collector-number artwork replacement.

## View or bulk-edit the collection

Open [`WLX/CARD_MANAGER.csv`](./WLX/CARD_MANAGER.csv) to see one row per
physical printing. Download it, edit only the blank `CHANGE_` columns, and
upload it back to the same location in one commit. The Action can move cards
between player collections, renumber several cards atomically, deliberately
reuse a retired gap, replace single- or double-faced artwork, and change rarity
or printed titles without hand-editing catalog JSON or image paths. Artwork
replacement and renumbering preserve the printing's permanent Cockatrice UUID.

[`CARD_MANAGER_GUIDE.md`](./WLX/docs/CARD_MANAGER_GUIDE.md) gives the exact
spreadsheet workflow. `WLX/published/catalog.resolved.csv` remains a generated,
read-only report; edits there are overwritten by the next build.

## Remove a printing

Removal is the only routine operation that uses **Issues → New issue**. Choose
**Remove a printing**, enter the WLX collector number, and confirm. The number
is retired automatically. A retired number is reused only when an owner
deliberately assigns it through `CARD_MANAGER.csv`.

## Source organization

```text
.github/                 GitHub workflows and the removal form
imports/                 card-art intake, results, and needs-attention queue
imports/replacements/    Card Manager artwork staging folders
WLX/docs/                owner, player, status, and import documentation
WLX/CARD_MANAGER.csv     editable collection-management spreadsheet
WLX/source/              canonical catalogs, automation, tools, and configuration
WLX/published/           public XML, images, manifest, catalogs, and installer
```

Do not manually edit generated files under `WLX/published/`; the builder replaces
them from the canonical data under `WLX/source/`.

## Safety model

- One commit is one batch; the workflow does not create one event per card.
- The committed incoming folder is the queue. A cancelled pending workflow run
  cannot erase an image request.
- New imports never reuse collector numbers; only an explicit manager edit can
  reclaim a retired number.
- Artwork replacement preserves the collector number and UUID.
- Public image URLs are content-addressed, so changed art cannot be hidden by a
  stale Cockatrice cache.
- Publication occurs only after source validation, Cockatrice v4 schema checks,
  the complete unit suite, and an isolated Windows updater integration test.

## Notices

See [THIRD_PARTY_NOTICES.md](./WLX/docs/THIRD_PARTY_NOTICES.md). This fan-created,
non-commercial project is not affiliated with or endorsed by Wizards of the
Coast or the Cockatrice project.
