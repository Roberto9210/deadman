# Releasing deadman-kit

The one thing to hold in mind before anything else:

> **A PyPI description is frozen at publication and cannot be edited.** Correcting the README and
> pushing to `main` leaves the published page exactly as wrong as it was. Only a new release
> replaces it. That is not a detail of the process — in 0.2.0 it was the defect a cold-start run
> found, and the page said the tool was "not on PyPI yet" to every reader who installed it.

Automated gates already cover the mechanical part: the tag must match `project.version`, the full
suite runs on nine OS/Python combinations, the wheel is installed into a clean virtualenv with
`--no-deps` from a neutral working directory, and
[`scripts/check_published_description.py`](https://github.com/Roberto9210/deadman/blob/main/scripts/check_published_description.py)
refuses to publish a description containing stale claims, relative markdown links, or a
present-tense claim about a capability that is off by default. It checks **both** frozen
strings - the one-line Summary and the long description - because 0.2.1 shipped
"externally anchored ledger" in the Summary through a gate that ran and passed while
reading only the description. What follows is the part a person still has to do.

---

## After publishing

- [ ] Confirm the version by **two** paths and never by the bare `/json` endpoint, which has now
      served a stale answer on three separate releases: `pypi.org/simple/deadman-kit/` (what pip
      actually resolves against) and `pypi.org/pypi/deadman-kit/<version>/json`.
- [ ] In the cold-start venv, **assert the installed version after installing**. `--no-cache-dir`
      clears a *local* cache and does nothing about a stale index response: run 3 passed the flag
      and still got the previous version, minutes after the new one was live. No flag makes a
      remote answer fresh, so the check has to be on the result. If it is wrong, discard the run
      rather than reinstalling into it.

## Before tagging

- [ ] `pyproject.toml` version and `deadman/__init__.py` `__version__` agree.
- [ ] CHANGELOG entry written, and it describes what a reader gets, not what was refactored.
- [ ] Every count quoted in the README was **produced by running something**, not estimated.
- [ ] Build locally and run the description gate against the artefact that will ship:

      python -m build
      python scripts/check_published_description.py dist/deadman_kit-<version>-py3-none-any.whl

  The gate reads the wheel's own metadata, so it sees what PyPI will render — not the working
  tree. It exits non-zero on stale claims, relative links, and optional capabilities stated
  as present, and refuses to run at all if it extracts fewer than 500 characters or finds no
  Summary, because a gate that passes on nothing also hands out confidence.

- [ ] Read the Summary out loud with the feature **off**. If the sentence is still true, it
      is not describing anything. That is the whole test behind `OPTIONAL_AS_PRESENT`, and
      the blacklist only catches the phrases we already got wrong once.

## After publishing — verifying it landed

**Do not use `https://pypi.org/pypi/<name>/json` to confirm freshness.** That aggregate endpoint
is cached and served a stale `latest` twice during the 0.2.x releases, once for several minutes
after a confirmed upload. Concluding from it that a release had failed would have been wrong both
times. Use either of these instead, which update ahead of it:

```bash
# the simple index - lists every file, updates promptly
python -c "import urllib.request,re; print(sorted(set(re.findall(r'deadman_kit-([0-9.]+)-py3-none-any\.whl', urllib.request.urlopen('https://pypi.org/simple/deadman-kit/').read().decode()))))"

# the version-specific endpoint - 404s if that version is not really there
python -c "import json,urllib.request; print(json.load(urllib.request.urlopen('https://pypi.org/pypi/deadman-kit/<version>/json'))['info']['version'])"
```

And confirm from the workflow log that the upload actually happened, rather than from the index
alone:

```bash
gh run view <run-id> --log | grep -i "Uploading deadman_kit-<version>"
```

## After publishing — verifying it works

- [ ] **Install with `--no-cache-dir`.** pip keeps an HTTP cache of the simple index, and a
      machine that installed the previous version minutes earlier will happily install it again.
      That happened during the 0.2.1 cold-start run: the first attempt got 0.2.0 although 0.2.1
      was live, which invalidated the run and had to be discarded rather than patched.

      python -m venv .venv && .venv/bin/pip install --no-cache-dir deadman-kit

- [ ] **Verify the environment is not lying before drawing any conclusion.** The import must
      resolve inside `site-packages` and **not** inside the checkout. Test that precisely — an
      earlier attempt asserted `'Desktop' not in path`, which fails for a temp directory merely
      *named* after the project, and was measuring the wrong thing.

      python -c "import deadman,pathlib; p=pathlib.Path(deadman.__file__); print(p, deadman.__version__)"

- [ ] **Run the first command a stranger would run**, from a directory outside the repository,
      before reading anything:

      python -m deadman.verify_certificate --example

- [ ] **Read the *published* page, not the local files.** They can be ahead. The published
      description is available as `info.description` from the version-specific JSON endpoint.

- [ ] **Check links by content, not by status code.** GitHub answers `200` for repository pages
      and soft-404s alike, so a reachable link is not a correct one. Pair each sampled link with a
      phrase that must appear in the response.

## Step N — pin the README's links to the tag

**This is a step of a release, not a standalone commit.** Done at the wrong moment it is worse
than not doing it: the links must point at a tag that already exists, and a tag only exists once
the release is under way.

The problem it solves is drift wearing different clothes. The description is frozen at
publication; its links point at `/blob/main/`, a branch that keeps moving. In six months that
frozen page will describe files `main` has since changed — exactly the failure the cold-start run
found, one level up.

The order matters and the safety condition is not optional:

1. Tag the release and **push the tag first**.
2. **Verify the tag exists on the remote before rewriting a single link.** Get this wrong and all
   39 links 404 simultaneously, which is worse and more immediate than pointing at `main`, which
   fails slowly and mildly:

       git ls-remote --tags origin "refs/tags/v<version>"    # must print a line

3. Only then rewrite `/blob/main/` → `/blob/v<version>/` and `/tree/main/` → `/tree/v<version>/`
   in `README.md`.
4. Rebuild and re-run the description gate; **check a sample of the rewritten links by content**,
   not by status code, exactly as after any release.
5. Once this is in place, add `/blob/main/` and `/tree/main/` to the gate's refusals, so a
   published description can never again aim at a moving branch.

Until step 5 is done the gate does **not** catch this, and that is the honest state: the defect is
known, written down here, and deliberately not fixed in a rush.

## Known, deliberately unfixed

- The README's absolute links still point at `/blob/main/`. See the step above; it is scheduled,
  not forgotten.

## The rule underneath all of this

Verify the fix by **being the stranger**, not by reading the repository. Reading the repository to
confirm a published page is fixed trusts the same mechanism that failed: the repository was right
the whole time; the artefact was the thing that was wrong. Both cold-start runs are published at
[`docs/COLD_START_LOG.md`](https://github.com/Roberto9210/deadman/blob/main/docs/COLD_START_LOG.md).
