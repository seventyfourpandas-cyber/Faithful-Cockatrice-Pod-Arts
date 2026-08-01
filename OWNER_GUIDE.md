# WLX Owner and Contributor Guide

## Routine publishing

Use **Issues → New issue** in this repository. Choose the form that matches the change, complete it, and submit it.

The automation performs the repository work. Do not edit the generated XML, manifest, public image directory, or installer ZIP directly.

### Add artwork for an official Magic card

Choose **Add a card printing**:

1. Select the player collection that should own the source image.
2. Select **Official Magic card**.
3. Enter the exact English card name.
4. Optionally enter the alternate title printed on the submitted image.
5. Upload one finished PNG or JPEG.

The official name remains the Cockatrice card identity. The alternate title is stored as `flavorName`. This permits any number of WLX artwork printings for the same official card without renaming the underlying card.

### Add a completely original card

Choose **Add an original card** and enter the card's own:

- name;
- regular-card or token category;
- mana cost and mana value, when applicable;
- type line;
- rules text;
- colors and color identity;
- power/toughness, loyalty, or defense, when applicable;
- finished image.

The publisher rejects a custom name that belongs to an official Magic card or another WLX original card. An accepted card is written to Cockatrice with its own complete identity and does not inherit official rules or card information.

To add another artwork printing later, choose **Add a card printing**, select **Existing WLX original card**, and enter that original card's WLX name.

### Update a printing

Choose **Update a printing or its artwork** and identify the existing collector number. You may:

- replace its image;
- change or clear its alternate printed title;
- correct the official card identity of an official printing;
- move its editable source between Alex, Will, Miguel, and Jay.

The collector number and UUID remain unchanged. A replacement image receives a new content-addressed public URL, and installed clients refresh only the matching Cockatrice picture-cache entry.

### Update an original card

Choose **Update an original card definition**. Changes to the name or rules metadata apply to every active printing of that original card. Artwork is changed separately through **Update a printing or its artwork**.

Blank fields keep their current values. Where the form permits it, enter `CLEAR` to remove an existing optional value.

### Remove a printing

Choose **Remove a printing** and enter its collector number. The number becomes a permanent tombstone and will not be assigned again. If it was the last printing of an original card, the unused original definition is also removed from the player catalog.

Do not remove a printing that an important saved deck still depends on unless that loss of exact-printing resolution is intended.

## Reading the result

- **Success:** the issue receives the assigned collector number and published version, then closes automatically.
- **Rejected:** the issue remains open and states the reason. Correct the form and edit or reopen it to retry.
- **Actions failure:** open the linked workflow run. The live release remains at the last successful commit.

The repository serializes publication requests, so two submissions cannot allocate the same collector number.

## Player folders

Each source catalog is independent:

- `cards/Alex/catalog.json`
- `cards/Will/catalog.json`
- `cards/Miguel/catalog.json`
- `cards/Jay/catalog.json`

Each adjacent `images/` directory contains only that player's editable source images. The generated `images/WLX/` directory combines all active public images and should not be edited manually.

An original card definition lives in the catalog of the player who created it. Additional printings may belong to any player and reference that one definition.

## Contributor access

Only the repository owner and invited collaborators are authorized by the publisher. Add Will as a repository collaborator if he should submit forms directly. Miguel and Jay need collaborator access only if they will publish their own requests.

The repository is public because Cockatrice clients must retrieve the manifest, XML, installer, and card images without GitHub credentials. Treat every submitted image and issue field as public material.

## Manual source editing

Direct source editing is supported as an advanced recovery path, not the routine workflow. If used, update the appropriate player's `catalog.json` and source image together, preserve existing collector numbers and UUIDs, then run:

```text
python automation/build.py --repository-root .
python -m unittest discover -s automation/tests -v
python automation/tests/schema_validation.py --require-lxml
python automation/tests/powershell_integration.py --require-pwsh
```

Never manually edit the generated publication and then expect the next automated build to preserve that edit.
