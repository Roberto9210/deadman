# Cold-start run — deadman-kit certificate verifier

Run 2026-08-22, 00:03:44Z → 00:07:22Z. Directory outside the repo, fresh venv, PyPI only.
Nothing was fixed during the run. Failures are recorded as they happened.

---

## Environment honesty check (before anything else)

```
$ python -m pip show deadman-kit
Name: deadman-kit
Version: 0.2.0
Location: ...\coldstart\.venv\Lib\site-packages

$ python -c "import deadman; print(deadman.__file__)"
...\coldstart\.venv\Lib\site-packages\deadman\__init__.py
```

`site-packages` — yes. Repo path — no. `sys.path[0]` is `''` (the cold-start dir, which holds no
`deadman/`). **The environment is not lying; the run counts.**

---

## The run, in order

| T+ | step |
|---|---|
| 0:00 | directory created outside the repo |
| 0:35 | `python -m venv .venv`; Python 3.14.2 |
| 1:05 | `pip install deadman-kit` → `Successfully installed deadman-kit-0.2.0` |
| 1:20 | environment honesty check (above) |
| 1:35 | read the PyPI project page — **friction 1, 2, 3** |
| 2:05 | read the GitHub README — **friction 4** |
| 2:20 | downloaded `certificate.json` + `ledger.jsonl` from GitHub raw |
| **2:26** | **`python -m deadman.verify_certificate certificate.json ledger.jsonl` → `VERIFIED at L1`, exit 0** |
| 2:50 | ran it with only the certificate — **friction 5** |
| 3:10 | ran the tampered example → `CLAIM_MISMATCH`, exit 1 |
| 3:25 | `--help` — **friction 6** |
| 3:38 | searched the published page for an explanation of `L1` — **friction 7** |

### The command that worked, verbatim

```
$ python -m deadman.verify_certificate certificate.json ledger.jsonl
deadman-kit - verifiable session certificate
==============================================================
ledger dialect  : guardian-core-v1  (16 entries read)
declared range  : seq 1..16

  chain         OK
  certHash      matches
  claims        6 recomputed from events
  anchors       0 checked
  signature     ABSENT

  DECLARED      L1
  REACHED       L1

COULD NOT VERIFY - true even when everything above passes:
  - NO_EXTERNAL_ANCHOR: ...
  - OTHER_VENUES: ...
  - PRE_START_BYPASS: ...
  - TRADES_OBSERVED: ...

RESULT: VERIFIED at L1 (exit 0).
EXIT=0
```

The tampered example, verbatim:

```
CONTRADICTIONS - the certificate does not survive its own evidence:
  - CLAIM_MISMATCH: `changeAttemptsWhileSealed`: certificate says 0, the events say 2
RESULT: CONTRADICTED (exit 1).
```

---

## Friction points

### 1. The published page tells you to clone because "it is not on PyPI yet" — ABANDONMENT POINT

The PyPI page for **0.2.0**, which is the page you land on after `pip install deadman-kit`, says:

```bash
git clone https://github.com/Roberto9210/deadman.git && cd deadman   # not on PyPI yet: 0.1.0 predates it
python -m deadman.verify_certificate certificate.json ledger.jsonl
```

You have just installed 0.2.0 from PyPI. The page for that very release tells you the tool is not
on PyPI. **This is the one that makes a reasonable reader quit**, and not because of the wasted
clone — because it is the first thing they read from us and it is *visibly false against evidence
already on their screen*. Everything after it is discounted. A verifier's entire pitch is "check us
rather than trust us", and the first checkable claim fails.

Cause: the README is frozen into the release artefact at build time. The clone note was removed
from `main` *after* 0.2.0 was cut, so GitHub is right and PyPI is stale — and PyPI is where the
`pip install` path leads.

### 2. The published page points at a worked example that is not in the package

> A worked example ships in [`examples/certificate/`](examples/certificate/)

The installed package contains sixteen `.py` files and nothing else. `examples/` is not in the
wheel. The word "ships" is doing damage here — a reader reasonably looks inside site-packages.

### 3. The links to the fuller documentation are relative, and do not reach it from PyPI

Both the guide and the examples are linked as `docs/verify-certificate.md` and
`examples/certificate/` — relative paths. Fetching them under `pypi.org/project/deadman-kit/`
returns something that is **not** the guide (PyPI served a bot-challenge page to a scripted
request, so what a browser gets is unconfirmed; what is confirmed is that the document is not
there). On GitHub the same links work.

### 4. The two published sources disagree

GitHub's README says `pip install deadman-kit  # 0.2.0 or newer`. PyPI's says clone. Same
document, two renderings, opposite instructions. A reader who sees both cannot tell which is
current, and has no way to date them.

### 5. A certificate on its own cannot be checked, and nothing says where to get the other half

The realistic case — someone hands you a certificate — fails:

```
$ python -m deadman.verify_certificate certificate.json
COULD NOT EVALUATE - no ledger given; the certificate cannot judge itself
EXIT=2
```

Accurate and well-phrased, but it stops one sentence early. It does not say *ask whoever gave you
the certificate for the ledger it covers* — which is the only possible next action, and not
obvious to someone who has never heard of the ledger.

**Mitigating, and worth keeping:** the certificate is self-documenting. Opening it shows

```json
"verifyInstructions": {"install": "pip install deadman-kit",
                       "command": "python -m deadman.verify_certificate certificate.json ledger.jsonl"}
```

A stranger who opens the file they were handed gets the right instructions without any of our
pages. That is the strongest thing in this run.

### 6. `--help` leaks internal identifiers

```
--series CERT [CERT ...]   additional certificates: check the links between days (C12/C13)
```

`C12/C13` are guarantee numbers from a specification the reader has not seen and cannot reach from
here. Also `--anchors ... - reaches L2` and `--pubkey ... - reaches L3` name levels the help never
defines.

### 7. The headline of the output is a term the published page never defines

`REACHED L1` is the result line. **`L1` appears zero times in the published PyPI README.** The
trust-layer table that explains L1/L2/L3 — and says plainly that L1 alone does not survive an
attacker with disk access — lives in `docs/verify-certificate.md`, which is on GitHub only, behind
the relative links of friction 3.

So the tool tells you it verified something at a level, and the page you installed from never says
what a level is. The four `COULD NOT VERIFY` lines are self-explanatory prose and do most of the
work — which is what saves this from being an abandonment point on its own.

---

## The number

**2 minutes 26 seconds** from empty directory to `RESULT: VERIFIED at L1 (exit 0)` — *if the
reader arrives via GitHub*.

**Understanding the result takes one more hop**, to `docs/verify-certificate.md`, and that hop is
only reachable from GitHub. Via PyPI, which is where `pip install` sends you, the run does not
start at all: friction 1 stops it before the first command.

Two paths, two very different numbers:

| arrival | to a verified certificate | to understanding it |
|---|---|---|
| GitHub README | ~2.5 min | ~4 min, one extra click |
| PyPI page | does not complete — instructions are false and self-contradictory | — |

---

## What worked, unprompted

- The install is one line and correct, with zero dependencies pulled.
- The tool ran on the first try with no configuration, no account, no key, no network.
- Exit codes behaved exactly as documented: 0, 1, and 2 for the three cases tried.
- `COULD NOT VERIFY` is printed on success, and reads as plain English.
- The failure message on the tampered certificate names the field, the claim and the true count
  in one line: `changeAttemptsWhileSealed: certificate says 0, the events say 2`.
- The certificate carries its own verification instructions.
