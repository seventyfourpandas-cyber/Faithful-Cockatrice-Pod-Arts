# WLX Bulk Card Import

Adding or replacing artwork is file-based. It does not create GitHub Issues.
One upload commit produces one serialized import run, whether it contains one
image or one hundred.

## Add normal official-card art

1. Name each PNG or JPEG exactly after the official English card name:

   ```text
   Sol Ring.jpg
   Eriette of the Charmed Apple.png
   ```

2. Open the correct folder:

   ```text
   imports/incoming/alex/
   imports/incoming/will/
   imports/incoming/miguel/
   imports/incoming/jay/
   ```

3. Upload as many as 100 images and make one commit.
4. Wait for **Actions → Import WLX card art** to turn green.

The importer reads the filenames, verifies exact official identities, assigns
new permanent collector numbers and UUIDs, updates the real per-player source
catalogs, rebuilds the public WLX set, validates it, and removes successful
incoming copies in one publication commit.

To upload a second artwork for the same card in one batch, add an ignored label:

```text
Sol Ring __ second art.jpg
Sol Ring __ third art.jpg
```

Everything after ` __ ` distinguishes the files but is not part of the card's
Cockatrice name.

## Add a double-faced printing

Upload both images in the same player's folder and name each after the visible
face:

```text
Etali, Primal Conqueror.jpg
Etali, Primal Sickness.jpg
```

The importer resolves the shared official card, identifies front and back, and
publishes both faces under one collector number. For a second paired artwork,
give both files the same optional label:

```text
Etali, Primal Conqueror __ storybook.jpg
Etali, Primal Sickness __ storybook.jpg
```

An unpaired face moves to `imports/needs-attention/` and does not consume a
collector number.

## Add official token art

Name the image after the official card face that creates the token:

```text
TOKEN - Awaken the Blood Avatar.jpg
```

The creating face must already be active in WLX or be added in the same batch.
Cockatrice's official token relationship supplies the token identity and stats,
so the same-set creating card selects the WLX token art.

## Replace artwork without changing its printing

Use the existing collector number as the filename and upload it into the
printing owner's folder:

```text
WLX-013.jpg
WLX-007-front.jpg
WLX-007-back.png
```

The collector number and UUID remain unchanged. A replacement may change from
PNG to JPEG or vice versa.

## Results and errors

- `imports/LAST_RUN.md` is the readable result of the latest batch.
- `imports/last-run.json` is the exact machine-readable result.
- A permanently invalid individual input moves to
  `imports/needs-attention/<player>/<batch>/` beside an `.error.txt` explanation.
- A temporary Scryfall, Cockatrice, build, or test failure publishes nothing;
  every incoming image stays available for a safe rerun.
- Successful inputs disappear from `imports/incoming` only after the source
  catalogs validate. The Action then builds and tests the complete public
  release before committing it.

## Limits

- One waiting batch may contain at most 100 uploaded image files.
- GitHub's browser accepts at most 100 files at once and 25 MiB per file.
- Git command-line or GitHub Desktop pushes may use files up to GitHub's normal
  100 MiB Git limit; WLX uses the same per-image ceiling.
- PNG and JPEG are supported. Keep the lossless PNG master locally; a
  high-quality JPEG is usually much smaller for finished card art.
- A completely original rules definition cannot be inferred from an image
  filename. It remains an advanced source-catalog edit, not an Issue request.

Wait for the current import Action to finish before intentionally submitting
another 100-image batch. If another commit does arrive early, its files remain
in the repository-backed queue; the surviving serialized run reads the current
`main` branch and cannot lose them the way cancelled Issue events did.

