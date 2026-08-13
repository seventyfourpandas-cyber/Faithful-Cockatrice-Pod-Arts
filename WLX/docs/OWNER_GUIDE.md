# WLX Owner and Contributor Guide

## Routine publishing

Add and replace artwork by uploading files to the correct player's folder under
`imports/incoming/`. Do not create Issues for additions or updates.

The complete filename rules and examples are in
[BULK_IMPORT_GUIDE.md](./BULK_IMPORT_GUIDE.md). The normal flow is:

1. Put 1–100 images in Alex, Will, Miguel, or Jay's incoming folder.
2. Commit them together once.
3. Wait for **Actions → Import WLX card art** to finish.
4. Read `imports/LAST_RUN.md` if anything needs attention.
5. Have players open their normal WLX Cockatrice shortcut.

The importer writes only canonical source files under `WLX/source/cards/<Player>/`, then
the existing builder generates the XML, public images, manifest, readable
catalog, installer, and status under `WLX/published/`. Never edit generated
publication files by hand.

## View, transfer, or renumber existing cards

Use `WLX/CARD_MANAGER.csv`. It lists one row per physical printing, including
one combined row for a double-faced card. Edit only columns whose names begin
with `CHANGE_`, then replace the file in one commit. The same serialized Action
updates the real player catalogs, state, UUIDs, source-image folders and names,
public XML, manifest, installer, and readable catalogs together.

See [CARD_MANAGER_GUIDE.md](./CARD_MANAGER_GUIDE.md) for examples, retired-gap
reuse, swaps, title clearing, and the failure rules. Do not edit
`WLX/published/catalog.resolved.csv`; it is regenerated from the canonical
sources.

## Add and update conventions

- `Sol Ring.jpg` adds a new official printing.
- `Sol Ring __ second art.jpg` permits another same-name file in the batch.
- Two official face-name files add one linked double-faced printing.
- `TOKEN - Awaken the Blood Avatar.jpg` adds the official related token.
- `WLX-013.jpg` replaces a single-face/token image without changing identity.
- `WLX-007-back.jpg` replaces one face of a double-faced printing.

Original rules definitions require manual canonical source editing because an
image filename cannot provide mana cost, type line, rules text, colors, and
stats. The dormant backend remains available for recovery, but there is no
routine Issue form for it.

## Remove a printing

Use **Issues → New issue → Remove a printing**. Enter its collector number and
confirm. The number becomes a retired tombstone unless an owner later reclaims
that exact gap deliberately through `CARD_MANAGER.csv`. If it was the final
printing of an original definition, the unused definition is removed as well.

## Reading a result

- Green import Action: every publishable item was committed; individual
  permanent problems, if any, are listed in `imports/LAST_RUN.md`.
- Red import Action: nothing from that runner was pushed. Incoming files on
  `main` remain the source of truth and can be rerun safely.
- Removal success: the Issue receives the published version and closes.
- Removal rejection: the live release remains unchanged and the Issue explains
  the problem.

## Persistent queue and concurrency

The workflow intentionally serializes import runs. GitHub may replace an older
pending run when several pushes arrive quickly, but that no longer loses work:
the images themselves remain committed under `imports/incoming/`, and the
surviving run checks out current `main` and processes the persistent queue.

Still, wait for green before uploading the next planned batch. It makes the
result report and collector-number sequence easiest to read.

## Source layout

- `WLX/source/cards/Alex/catalog.json` and `WLX/source/cards/Alex/images/`
- `WLX/source/cards/Will/catalog.json` and `WLX/source/cards/Will/images/`
- `WLX/source/cards/Miguel/catalog.json` and `WLX/source/cards/Miguel/images/`
- `WLX/source/cards/Jay/catalog.json` and `WLX/source/cards/Jay/images/`

Generated `WLX/published/images/WLX/` combines every active public printing. The repository
is public because Cockatrice clients retrieve the manifest, XML, and artwork
without credentials; treat every uploaded image as public material.

## Advanced manual validation

After an intentional source edit, run:

```text
python WLX/source/automation/build.py --repository-root .
python -m unittest discover -s WLX/source/automation/tests -v
python WLX/source/automation/tests/schema_validation.py --require-lxml
python WLX/source/automation/tests/powershell_integration.py --require-pwsh
```

Never edit only a generated file and expect a later build to preserve it.
