# Cold-start runs — deadman-kit certificate verifier

Two runs, one before and one after the fixes. A stranger's path each time: a directory outside
the repository, a fresh virtualenv, PyPI only, published pages only. **Nothing was fixed during
either run** — the run is the artefact, and the failures below are recorded as they happened.

| | run 1 — 0.2.0 | run 2 — 0.2.1 |
|---|---|---|
| first useful command | *(did not exist)* | **35 s** — `--example`, run before reading anything |
| arriving via GitHub | 2 min 26 s | **~1 min 40 s** |
| arriving via PyPI | **did not complete** | **35 s** — the two paths converged |
| abandonment points | 1 | 0 |

---

# Run 1 — 2026-08-22, 00:03:44Z → 00:07:22Z (deadman-kit 0.2.0)

## Environment honesty check

```
$ python -m pip show deadman-kit      →  Version: 0.2.0, Location: ...\.venv\Lib\site-packages
$ python -c "import deadman; print(deadman.__file__)"
                                      →  ...\.venv\Lib\site-packages\deadman\__init__.py
```

site-packages yes, repo no. The run counts.

## Sequence

| T+ | step |
|---|---|
| 0:00 | directory created outside the repo |
| 1:05 | `pip install deadman-kit` → 0.2.0 |
| 1:35 | read the PyPI project page — **friction 1, 2, 3** |
| 2:05 | read the GitHub README — **friction 4** |
| 2:20 | downloaded `certificate.json` + `ledger.jsonl` from GitHub raw |
| **2:26** | **`... verify_certificate certificate.json ledger.jsonl` → `VERIFIED at L1`, exit 0** |
| 2:50 | ran it with only the certificate — **friction 5** |
| 3:25 | `--help` — **friction 6** |
| 3:38 | searched the published page for an explanation of `L1` — **friction 7** |

## Friction points

### 1. The published page told you to clone because it was "not on PyPI yet" — ABANDONMENT POINT

The page for **0.2.0**, which is where `pip install deadman-kit` sends you, said:

```bash
git clone https://github.com/Roberto9210/deadman.git && cd deadman   # not on PyPI yet: 0.1.0 predates it
```

You have just installed 0.2.0 from PyPI. **This is where a reasonable reader quits** — not over
the wasted clone, but because it is the first thing they read from us and it is visibly false
against evidence already on their screen. Everything after it is discounted, and the entire pitch
of a verifier is "check us rather than trust us".

Cause: the long description is frozen into the release artefact at build time. The clone note was
removed from `main` after 0.2.0 was cut, so GitHub was right and PyPI was stale — and PyPI is
where the install path leads. **A PyPI description cannot be edited; only a new release replaces
it.**

### 2. The page pointed at a worked example that was not in the package

> A worked example ships in `examples/certificate/`

The installed package contained sixteen `.py` files and nothing else.

### 3. The links to the fuller documentation were relative

`docs/verify-certificate.md`, `examples/certificate/` — relative paths, which do not resolve from
pypi.org. Confirmed the fetched content was not the guide; what a browser is served was not
confirmed, because PyPI answered a scripted request with a bot-challenge page.

### 4. The two published sources disagreed

GitHub said `pip install deadman-kit`. PyPI said clone. Same document, two renderings, opposite
instructions, no dates.

### 5. A certificate on its own could not be checked, and nothing said where to get the other half

```
COULD NOT EVALUATE - no ledger given; the certificate cannot judge itself
```

Accurate, and one sentence short: it never said *ask whoever gave you the certificate for the
ledger*, which is the only possible next action.

### 6. `--help` cited internal identifiers

`--series ... (C12/C13)` — guarantee numbers from a specification the reader has not seen.

### 7. The headline of the output was a term the published page never defined

`REACHED L1` is the result line. **`L1` appeared zero times in the published README.**

## What worked, unprompted

One-line install, zero dependencies, ran first try with no configuration or network, exit codes
exactly as documented, `COULD NOT VERIFY` printed on success in plain English, and the tampered
example named field, claim and true count in one line. **And the certificate carried its own
verification instructions**, which is the one thing that routed around friction 1 entirely.

---

# Run 2 — 2026-08-22, 01:12:13Z → 01:13:52Z (deadman-kit 0.2.1)

Same rules. Nothing fixed during the run.

## A false start, recorded because it nearly invalidated the run

The first attempt installed **0.2.0** although 0.2.1 was already published, so `--example` did not
exist and the first command failed. That was **this machine's pip HTTP cache serving a stale index
page**, not a project defect: `pip index versions` immediately afterwards reported 0.2.1 as the
latest, and a stranger on a fresh machine has no such cache.

It is written down rather than quietly retried, because it is the same failure the honesty check
exists for: *the environment lied, so the run did not count*. Re-run with `--no-cache-dir`, which
is what a fresh machine does anyway.

A second self-inflicted note: the first honesty assertion failed on `'Desktop' not in path` —
wrongly, because the temporary directory is named after the project slug
`C--Users-home-Desktop-ALAYA`. The assertion was measuring the wrong thing, and was corrected to
test whether the import resolves inside the checkout, which is the actual question.

## Environment honesty check

```
import location  : ...\coldstart3\.venv\Lib\site-packages\deadman\__init__.py
in site-packages : True
inside the repo  : False
version          : 0.2.1
```

## The first command, before reading any documentation

```
$ python -m deadman.verify_certificate --example
Verifying the example certificate that ships with this package.
Nothing is downloaded; this runs entirely offline.
...
RESULT: VERIFIED at L1 (exit 0).

That certificate is honest, so it passes. Three more ship beside it - one with a
falsified claim, one that lies by declaring a shorter range, and one whose issuer
fields are omitted because the emitter could not determine them:
    https://github.com/Roberto9210/deadman/tree/main/deadman/examples/certificate

To check a real certificate you need two files: the certificate, and the ledger it
says it covers. Then:  python -m deadman.verify_certificate certificate.json ledger.jsonl
EXIT=0
```

**35 seconds from an empty directory**, with no documentation read, no file downloaded and no
network used by the command itself. It wrote nothing into the working directory.

## The published 0.2.1 description, audited

| check | result |
|---|---|
| says "not on PyPI yet" | no |
| says "predates it" | no |
| presents `git clone` as the way to get the tool | no |
| mentions `L1` | **5 times** (0 in 0.2.0) |
| explains `--example` | yes |
| relative markdown links | **0** (37 in 0.2.0) |
| absolute GitHub links | 39 |

## Do the absolute links reach the right document?

A 200 proves nothing — GitHub answers 200 for repository pages and soft-404s alike — so each link
was paired with a phrase that must appear in what comes back:

```
  OK     docs/verify-certificate.md    -> contains 'How to contradict a deadman session certificate'
  OK     docs/SPEC.md                  -> contains 'SPEC'
  OK     CHANGELOG.md                  -> contains '0.2.1'
  OK     LICENSE                       -> contains 'MIT License'
  OK     deadman/examples/certificate  -> contains 'certificate.json'
  OK     tests/test_g11_ledger.py      -> contains 'def test_'
  OK     examples/freqtrade            -> contains 'freqtrade'

checked 7: 7 returned the right document, 0 wrong, 0 unreachable
```

## The rest of the run

```
$ python -m deadman.verify_certificate certificate.json ledger.jsonl     (downloaded from raw)
RESULT: VERIFIED at L1 (exit 0).

$ python -m deadman.verify_certificate certificate.json
WHAT TO DO: ask whoever gave you the certificate for the ledger file it covers
(usually ledger.jsonl). A certificate handed over without its ledger cannot be
verified by anyone, including us.
EXIT=2
```

## Remaining friction

**No abandonment point.** Two things worth naming anyway:

1. **This file is linked from the CHANGELOG but not from the README.** The evidence that the
   project publishes its own failures is reachable only by someone already reading the changelog.
2. **The 39 absolute links point at `/blob/main/`.** A description frozen in 0.2.1 that points at
   a moving branch will, in six months, describe things `main` has changed: the same drift defect
   in different clothes. Deliberately not fixed in this release — if the tag were missing or named
   differently every link would 404, which is worse and immediate, whereas pointing at `main`
   fails slowly and mildly. Pinning to the tag belongs in the next release, gated on verifying the
   tag exists before anything is rewritten.

## What the release gate now refuses

`scripts/check_published_description.py` reads the built wheel's own metadata. Against the
description **actually published as 0.2.0** it reports **40 offences**, the first being
`'not on pypi yet'` — it would have blocked that release. It runs from `release.yml` and not from
the test suite, because `main` may be mid-repair while a published page cannot be.

Its own first draft passed while reading **zero characters**: METADATA uses CRLF and the script
split on a bare blank line. A gate that passes because it measured nothing is worse than no gate,
since it also hands out confidence. It now parses METADATA as the RFC 822 document it is and
refuses to run at all below 500 characters.

---

# Run 3 - 2026-08-22 (deadman-kit 0.2.2)

Purpose: 0.2.2 exists only to stop the project promising a trust layer nobody has reached. A cold
start is the only way to check that, because every claim it fixes lives on a page a stranger reads
before installing.

## A discarded first attempt, and a NEW failure mode

The first attempt is void. `pip install --no-cache-dir deadman-kit` resolved **0.2.1**, minutes
after 0.2.2 was live on the simple index.

**This is not the Run 2 defect.** Run 2 was pip's local HTTP cache, and `--no-cache-dir` is the fix
for that. Here `--no-cache-dir` was passed and it still happened: the index view pip fetched was
stale, and a flag that clears a *local* cache cannot clear that. Minutes later `pip index versions`
reported `LATEST: 0.2.2` and resolved it without complaint.

The lesson is one line, and it generalises past pip: **no flag makes a remote answer fresh. The
only reliable check is to assert the version AFTER installing, and discard the run when it is
wrong.** A flag that is believed to guarantee freshness is worse than no flag, because the run
proceeds with confidence it has not earned - the same defect this release was cut to fix, met while
verifying the fix.

## Confirming publication - two paths, never the bare `/json`

| path | reports |
|---|---|
| `pypi.org/simple/deadman-kit/` (what pip resolves) | `0.1.0, 0.2.0, 0.2.1, 0.2.2`, both wheel and sdist |
| `pypi.org/pypi/deadman-kit/0.2.2/json` (per version) | `0.2.2`, with the corrected Summary |
| ~~`pypi.org/pypi/deadman-kit/json`~~ (cached) | still said **0.2.1**, with the OLD Summary |

The bare `/json` endpoint was wrong again, and was again not consulted for the verdict.

## Environment honesty check

    installed version      : 0.2.2
    package resolves to    : ...\coldstart3\v\Lib\site-packages\deadman\__init__.py
    inside this fresh venv : True
    NOT from the repo tree : True
    repo absent from path  : True

Install: **3 seconds**, zero dependencies.

## What 0.2.2 was cut to fix, checked on the published artefacts

**1. The Summary no longer states an optional capability as present.**

    Execution-safety primitives ... hash-chained ledger anchorable to a third party
    by a publisher you supply. Zero runtime dependencies.

`"externally anchored" in summary: False`. Read aloud with anchoring off, the new sentence is still
true and still says something - it names who has to supply the missing piece.

**2. A reader who installs and runs `--example` learns L2 exists and what reaches it.** Against a
whole run of 0.2.1, which contained the strings `L2`, `L3` and `--anchors` exactly zero times:

    - NO_EXTERNAL_ANCHOR: ... a full rewrite with recomputed hashes passes L1. TO REACH L2, ask
      whoever holds this ledger for anchors kept by a third party and pass them with --anchors

    RESULT: VERIFIED at L1, THE FLOOR LAYER (exit 0).

Both the layer and the flag are **inside the finding**, not in a footer the reader has already
scrolled past. The headline can no longer be quoted as a grade.

**3. The missing sentence is on the page, above the snippet.** *"Without a publisher there is no
anchor, and everything stays at L1"* appears twice in the published description, at lines 33 and
136, and the `Ledger(...)` a reader copies is at line 113 - so the first occurrence is read before
anything is built. The snippet itself now shows both constructions with the consequence beside
each.

## Friction

One, and it is the discarded attempt above. Nothing was fixed during the run.

---

# Run 4 - 2026-09-03 (deadman-kit 0.3.0, BEFORE publishing)

**This run is a different instrument from runs 1-3, and the difference is the whole point.** Those
installed from PyPI to find out what a stranger already gets. This one installs the LOCAL wheel, as
a gate: it runs before the upload so that a bad artefact is never published rather than audited
afterwards. Everything runs from a temporary directory with the repository off `sys.path`, because
this machine holds the source and a check that runs inside the tree can pass by importing the very
thing it was meant to test.

The stale-index trap that voided the first attempt of run 3 does not apply here - there is no index
- so the version is asserted against the artefact instead. That asymmetry is worth naming: a
pre-publication run cannot catch the failures runs 1-3 exist to catch, and a post-publication run
cannot stop anything. **They are not substitutes, and this one does not retire the others.** A run
from PyPI is still owed once 0.3.0 is live.

## What was checked, and all of it held

**Environment honesty** - installed version `0.3.0`; package resolving inside the cold venv, not
the repository; repository absent from the path; **zero non-stdlib modules loaded**; zero
dependencies pulled.

**The thing this release exists to fix.** `CERT_SPEC.md` is inside the installed package, and it
is byte-identical to the repository's copy (sha256 `daa01bf0…`). `--spec` exits 0, prints a path
that exists on disk, points **inside the venv rather than at any repository**, and the document
found there declares the version the code claims. That chain is the whole answer to the defect: a
reader who installs from PyPI and follows a citation in the source now arrives somewhere.

**The verifier on the certificates it ships.** The honest one passes at exit 0 and names the layer
it reached; the tampered and the truncated one are both **CONTRADICTED at exit 1**; a certificate
handed over **without its ledger is UNEVALUABLE at exit 2, not a pass**.

**The two contract changes, observed from outside the repository**, which is the only place they
matter:

- `--json` on a verified run parses, carries `spec`, and reports `chainOk` and `certHashOk` as
  `true` - the checks that actually ran.
- A certificate with `ledgerDialect` removed is **exit 1, not exit 2**: a mandatory field that is
  absent is a defect of the document, and asking for a better copy will not produce one.
- That same stopped run **omits `chainOk` entirely** instead of publishing `false` for a check it
  never performed, and **still reports `certHashOk`**, because that computation was moved ahead of
  every early return. It reports `false`, which is correct and is the point: the document was
  modified after sealing, and the cheapest check in the tool caught it on a path where it used to
  never run at all.

## Friction

None. Nothing was fixed during the run.

---

# Run 5 - 2026-09-03 (deadman-kit 0.3.0, AFTER publishing) - and what it found

The debt run 4 wrote down, paid the same day: the published wheel was downloaded from the simple
index and the 22 checks were run **against it**. All 22 held, including the four that this release
exists for - `CERT_SPEC.md` inside the package, `--spec` resolving inside the venv, a certificate
missing `ledgerDialect` exiting **1**, and `chainOk` **omitted** on a run that never reached it.
Publication confirmed by the two paths `RELEASING.md` allows and never by the bare `/json`.

## The finding: the local wheel and the published one are not the same bytes

**13 members differ.** That is the sentence that mattered, and the cause is not what it sounds
like. Measured before being named:

| | |
|---|---|
| members differing | 13 |
| of those, differing ONLY in line endings | **12** |
| the 13th | `RECORD`, which stores the hashes of the other members |
| every published module equals | the git **blob** |
| every local module equals | the working-copy **disk** |

**Nothing transforms anything.** CI builds from a fresh checkout, which materialises the blobs;
this machine builds from a working copy whose endings drifted from those blobs on 17 files under
`core.autocrlf`. Same content, different bytes, and `METADATA` follows because it embeds a
description read from a file in the same state.

**The conclusion survives the benign cause, and it is why the default changed.** A cold check on a
locally built wheel compares a copy against the repository that produced it - two views of one
source, agreeing with themselves. It *cannot fail* for the only cause that matters: a difference
between what we built and what anyone installs. It never could, and every previous "verified"
before an upload had that hole in it.

So `scripts/coldstart_check.py` now **downloads the published wheel by default** and verifies that.
`--local` remains, because before a release there is nothing published and stopping a bad artefact
is worth doing - but it is a **pre-flight, not a verification**, it must be asked for by name, and
it prints a banner saying so rather than trusting the reader to remember which mode they ran. A
bare path is refused for the same reason.

It also compares the two wheels, **split by cause**: a CONTENT difference fails loudly, an
endings-only difference is a NOTE with its explanation. Collapsing the two would make the check
permanently red on this machine, and a check that is always red is a check that gets turned off.

## Friction

None, and nothing was fixed during the run. The finding above was measured, not repaired: the 17
files are untouched by decision.
