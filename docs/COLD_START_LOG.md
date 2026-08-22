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
