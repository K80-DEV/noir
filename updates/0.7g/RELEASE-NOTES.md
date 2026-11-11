# NOIR 0.7g — second external audit release (AUDIT2) + cross-lineage compatibility

Payload: `cairn.py` — 1,625,068 bytes — sha256 `e2598ae94b8770258b5f7e945611373bcf6d3c221f92462c37dbfd5a67bdd093`
Manifest: `manifest-0.7g-unsigned.json` (nonce 24) — **not publishable until the master key signs it**
Build basis: audited tree `68602b8` + the auditor's fix band + the compat band below.

**Per-finding descriptions are withheld on purpose until this release is signed and installable.** The
audited versions (0.7e and 0.7f) are still what most installs run, and a line-by-line description of what
this build repairs is a map of what is still open in the build people are actually standing on. The
descriptions are in the audit record and in the release ledger; they move into these notes when the fix is
the newest thing users can take, not before.

## What it carries

- **The auditor's accepted band**: B1–B17 and F1–F19 as filed, except **F2, which is deliberately not
  changed** — the fork handler's own docstring documents the quota doubling as an intended trade, so
  "fixing" it would rewrite shipped intent rather than repair a defect. Sixteen of the findings are
  machine-checked by the auditor's own `unit_tests.py` / `proc_tests.py`.
- **G9 is a behaviour change** you may notice: `/v1/chat/completions` no longer supplies the owner's full
  system prompt to a third-party app that sends none; it sends a short minimal prompt. The `/v1` token is
  routinely pasted into phone apps, and it should cost model spend if it leaks, not identity. Operators who
  want the previous behaviour opt in explicitly, at root scope, and then treat the token accordingly:

      Environment=NOIR_V1_IDENTITY=full      # service drop-in, then restart

- **Cross-lineage compat** — the part that decides whether an install updated itself or sat where it was:
  - `CAIRN_*` and `NOIR_*` environment names are both honoured for every setting; `NOIR_*` wins when both
    are set and a disagreement is reported on stderr at boot. A `CAIRN_`→`NOIR_` shim already existed;
    the mirror now runs both ways so a `NOIR_*`-only reading of the file cannot silently move a data home.
  - The raw-import, restore, restore-identity and import-secrets doors accept **both** `X-Cairn-*` and
    `X-Noir-*`. Before this, an external poster still sending `X-Cairn-Raw` fell into the JSON door and died
    on the body cap instead of streaming.
  - Export answers carry both spellings of the skipped-count headers, because a browser can be holding
    pre-rename JavaScript.
  - `SERVICE_UNIT` comes from `NOIR_UNIT`/`CAIRN_UNIT` when set and only then from the filename, so printed
    restart and rollback text names a unit that exists.
- **`VERSION` 0.7g, nonce 24.** 0.7f was staged and signed on 2026-11-06 and never published; 0.7g/24 avoids
  colliding with it, and installs accept either order.
- **Five fixes that existed only on the maintainer's running lineage** and would have been silently lost by
  shipping the audited tree as-is: the mid-turn context guard, no-thinking short calls, the empty-title
  fallback, the dash-is-not-bash shell guidance, and elapsed-timer resync against the server's own clock.

## Taking it

**Existing install, any spelling of the environment:** nothing to change. Settings → Updates → Check →
Download → Install. Auto-update stays owner-confirmed; publishing a manifest only makes an update available.

**Still on 0.6x:** run `cairn-migrate.py --dry-run` first, then for real, then update.

**Renaming your install to `noir.py`:** the updater will not do it, and that is deliberate — it writes new
bytes into whichever file is running and never creates a new one, so a half-done rename leaves systemd
starting the old file while the state file reports the new version. Once you are on 0.7g the rename is a
short root step: stop, `mv cairn.py noir.py`, set `Environment=NOIR_UNIT=<your-unit>` if the unit is not
named after the file, `daemon-reload`, start. 0.7g accepts a `noir.py` payload in a signed manifest, so a
future release can ship under the new name once the field has moved.

## Verification

`mara_compat_tests.py` ships next to this file. Run it with absolute paths (its scratch handling deletes its
own source if you hand it a relative one):

    python3 mara_compat_tests.py /absolute/path/to/cairn.py /absolute/path/to/scratch

On the build this release was cut from: auditor `unit_tests.py` **16/16** (the audited base scores 0/16),
`proc_tests.py` B12 PASS with a clean SIGTERM shutdown and B13 3/3, `mara_compat_tests.py` **16/16**, and the
manifest gate 16/17 where the single failure is the absent signature. The compat probe covers what the
auditor's suite cannot: booting with a `CAIRN_*`-only unit environment, which is what most existing installs
actually export, and proving the data home lands where that environment says.

## Not covered by any of this

TLS serving modes, Caddy routing, systemd units, the connectors, MCP, media generation, OCR, a full backup
round trip, and any real Anthropic wire (the two Anthropic items are wire-shape only). The embedded
front-end was reviewed by pattern, not line by line.

## Ship scrub (why this sha differs from the working copy)

The publish candidate is the gated build with eight comment lines genericised (personal name -> role, two infra names -> neutral wording), per the standing rule that shipped artifacts carry zero personal info. No code token changed and the line count is identical; the scrub is reproducible with build/make_ship_07g.py and every gate above was run on these exact bytes.
