# Willex's Whimsical Arts

Willex's Whimsical Arts (`WLX`) is a shared Cockatrice card publication. This repository is both the editable source and the public update endpoint.

The current release includes `WLX #001`, an alternate printing of **Angel of Vitality** titled **Alex, Divine Priest**.

## Install for Cockatrice

Download [Willexs_Whimsical_Arts_Cockatrice_Installer.zip](./Willexs_Whimsical_Arts_Cockatrice_Installer.zip), extract it, close Cockatrice, and run `INSTALL_OR_UPDATE.bat` once.

The installer creates a **Willex's Whimsical Arts** desktop shortcut. Use that shortcut for later sessions: it checks for a verified update, installs it, and opens Cockatrice. Players do not need to import XML files or download a new installer for each card release.

See [PLAYER_GUIDE.md](./PLAYER_GUIDE.md) for the complete player instructions.

## Publish a change

Repository owners and invited collaborators publish through the [WLX request forms](https://github.com/seventyfourpandas-cyber/Faithful-Cockatrice-Pod-Arts/issues/new/choose):

| Request | Use it for |
| --- | --- |
| Add a card printing | New artwork for an official Magic card, or another printing of an existing WLX original card |
| Add an original card | A completely original card whose name, rules, and card metadata do not come from an official card |
| Update a printing or its artwork | Replace art, change an alternate title, correct an official identity, or move the source to another player |
| Update an original card definition | Change the shared rules metadata used by every printing of an original WLX card |
| Remove a printing | Remove one printing and permanently retire its collector number |

Each accepted request automatically assigns or preserves the collector number and UUID, validates the source, builds the Cockatrice v4 XML, hashes every public file, tests the installer, commits the finished release, and closes the request. A rejected request leaves the currently published release unchanged and reports the reason on the issue.

See [OWNER_GUIDE.md](./OWNER_GUIDE.md) for the publishing workflow.

## Supported card models

| Model | Cockatrice identity | Information stored by WLX |
| --- | --- | --- |
| Printing of an official card | Exact official English card name | WLX set, collector number, permanent UUID, image, rarity, and optional alternate printed title |
| Completely original card | Its own WLX card name | Rules text, mana cost/value, type line, colors, color identity, power/toughness, loyalty, defense, token status, printing data, and image |

Official-card printings inherit the underlying card identity from Cockatrice's normal card database. Original cards are emitted as complete card definitions and do not reference or inherit an official card name, rules text, or metadata.

Both models support multiple artwork printings. Each printing receives a globally unique WLX collector number and permanent UUID.

## Source organization

The editable source is separated by player while every active printing compiles into one `WLX` set:

```text
cards/
  Alex/
    catalog.json
    images/
  Will/
    catalog.json
    images/
  Miguel/
    catalog.json
    images/
  Jay/
    catalog.json
    images/
```

The request forms maintain these files automatically. Generated files such as `manifest.json`, `customsets/`, `images/WLX/`, `catalog.json`, and the installer ZIP are publication output and should not be edited by hand.

## Safety and continuity

- Only the repository owner and invited collaborators can publish through the forms.
- Collector numbers are never reused after removal.
- Artwork replacement keeps the existing printing UUID so saved decks retain their exact printing.
- Public image filenames include the image hash, forcing a new URL when artwork changes.
- The updater verifies SHA-256 before replacing the installed XML or its own support files.
- Matching duplicate XML and picture-cache files are moved to recoverable quarantine; unrelated custom sets are ignored.
- The automated transaction runs unit tests, the official Cockatrice v4 schema validation, and an isolated PowerShell installer test before publication.

## Project files

- `cards/` — editable player catalogs and source images
- `.github/ISSUE_TEMPLATE/` — guided add, update, and remove forms
- `.github/workflows/` — transactional GitHub publisher
- `automation/` — source validation, XML generation, tests, and installer templates
- `customsets/`, `images/WLX/`, `manifest.json` — generated public update payload
- `cockatrice-installer/` and the installer ZIP — generated player installation package
- `catalog.resolved.csv` — readable generated index of every active printing

## Notices

See [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md). This is a fan-created, non-commercial Cockatrice card publication and is not affiliated with or endorsed by Wizards of the Coast or the Cockatrice project.
