# WLX Card Manager

`WLX/CARD_MANAGER.csv` is the editable control sheet for cards that are already
published. It contains one row per physical printing. A double-faced card uses
one row, not one row per face.

`WLX/published/catalog.resolved.csv` is different: it is a generated report for
viewing and auditing. Never edit the resolved catalog, the combined JSON, XML,
manifest, source catalogs, state file, or image filenames by hand.

## Make a bulk edit

1. Wait for every current WLX Action to finish.
2. Download the current `WLX/CARD_MANAGER.csv` from `main`.
3. Open it in Excel, Google Sheets, LibreOffice, or a text editor.
4. Sort and filter freely, but keep every row and every column.
5. Enter requests only under columns whose names begin with `CHANGE_`.
6. Save/export as CSV without renaming the file.
7. Replace `WLX/CARD_MANAGER.csv` in one GitHub commit.
8. Wait for **Actions → Import WLX card art** to turn green.
9. Fetch and pull the Action's follow-up commit before making another edit.

The Action validates the whole requested final layout before publishing any of
it. A red run leaves the catalogs, artwork and public WLX release unchanged.
Correct the spreadsheet and commit it again.

## Editable columns

| Column | What to enter |
| --- | --- |
| `CHANGE_owner_to` | `Alex`, `Will`, `Miguel`, or `Jay` |
| `CHANGE_collector_to` | `3`, `003`, or `WLX-003` |
| `CHANGE_rarity_to` | `common`, `uncommon`, `rare`, `mythic`, `special`, or `bonus` |
| `CHANGE_front_title_to` | A new alternate printed title, or `CLEAR` to remove one |
| `CHANGE_back_title_to` | A double-faced card's new back title, or `CLEAR` |

Blank `CHANGE_` cells mean “keep the current value.” Every other column is
view-only identity/context and must remain unchanged. Rows may be reordered;
the permanent `printing_uuid` identifies each row safely.

## Examples

Move one card from Will to Alex:

```text
CHANGE_owner_to = Alex
```

Move it and reclaim retired collector 003 at the same time:

```text
CHANGE_owner_to = Alex
CHANGE_collector_to = 3
```

Assign three cards to the retired gaps 003, 004, and 012: enter those three
targets on the three chosen rows and upload the sheet once. Retired targets are
accepted because typing one in a `CHANGE_` cell is an explicit instruction.
Their earlier tombstone data is archived in automation history before reuse.

Swap two active collector numbers atomically:

```text
first card:  CHANGE_collector_to = 21
second card: CHANGE_collector_to = 20
```

Both sides of a swap must be present in the same CSV commit. Pointing one card
at another active card's number without moving the other card is rejected as a
duplicate.

## What the Action changes

For a successful request, the manager updates all dependent pieces together:

- the printing's player source catalog;
- its source-art folder and `WLX-###` filename;
- collector state and archived history;
- the permanent Cockatrice UUID pin, so renumbering does not replace the
  printing's identity;
- the project version and release timestamp;
- generated XML, public images, catalogs, manifest, status and installer;
- `CARD_MANAGER.csv` itself, regenerated with current values and blank request
  cells.

New imports continue allocating above `next_collector`; they never fill gaps
automatically. Only an explicit manager request can reclaim a retired number.

## Safety rejections

The manager rejects the entire request when:

- a row or permanent UUID is missing, duplicated, or stale;
- a view-only cell was changed;
- two active cards would finish on one collector number;
- an owner or rarity is invalid;
- a back-face title is requested for a single-faced card;
- an unrelated file already occupies a requested source-image destination;
- the underlying collection fails ordinary WLX validation.

If the sheet is stale because another publication happened after you downloaded
it, download the newly generated manager and copy only your `CHANGE_` requests
into it.
