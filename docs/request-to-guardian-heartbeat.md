# Request to the guardian: a heartbeat that survives every state

**From:** `deadman` (the verifier).
**To:** `deadman-guardian` (the emitter).
**Status:** a request, not a change. Nothing here is implemented on either side, and the
continuity block already shipped without it — this would improve one figure, not enable the
feature.

---

## What is being asked

One event, emitted on a fixed interval, **in every state including `DISARMED` and `LOCKED`**.

An existing event would do; `PNL_CHECKPOINT` is nearly it already. What matters is only that the
ledger contains a regular mark of "the process was alive at this time", whatever the guardian
happens to be doing.

## Why

The verifier now derives seal-continuity coverage from the ledger, to make the gap in
[SPEC §17.2](https://github.com/Roberto9210/deadman-guardian) visible in a published certificate:
across a process restart the seal is measured against the wall clock, which the trader can move.
That cannot be closed without a time source off the machine, and v1 opens no sockets. It can be
made **noisy**, because a legitimate restart lasts seconds and a long gap is the shape the attack
needs.

Gap durations come from `GUARDIAN_STOPPED` → `GUARDIAN_STARTED` intervals. `Stop()` is what writes
`GUARDIAN_STOPPED`, and `Stop()` does not run on a crash, a kill, or a power cut. So an ungraceful
exit leaves a gap with **no measurable start** — and an ungraceful exit is precisely what someone
avoiding the measurement would produce.

The obvious fallback does not work, and this is the part worth reading before proposing one:

> **Gap length cannot be inferred from silence in the ledger.** `Tick()` returns before reaching
> the checkpoint while `DISARMED` (`Guardian.cs:368`) and while `LOCKED` (`Guardian.cs:372-377`).
> A four-hour lockout with the guardian running perfectly therefore produces **no events at all**.
> Inferring a gap from that silence would report four hours "with no guardian running", which is
> false — and false in the direction that accuses an innocent trader who simply hit their limit
> early in the session.

With a state-independent heartbeat at interval *N*, the last mark before an unexplained
`GUARDIAN_STARTED` bounds the gap to within *N*. That is all this needs; it does not have to be
precise, only bounded.

## What it is worth, stated honestly

**It is not required.** The verifier already handles the ungraceful case without it, by reporting
`uncleanShutdowns` and omitting the durations **with the reason attached** rather than leaving a
hole in the output. No path is silent today:

| how the session ended | what the certificate says |
|---|---|
| clean shutdown | the gap's duration, measured |
| ungraceful exit | no duration, and *"the previous session ended without a clean shutdown"* |

What the heartbeat would buy is the duration in the second row — turning "we cannot say how long"
into "at most *N* more than this". Useful, and strictly an improvement to a figure that is already
honest without it.

## What must not change

`GUARDIAN_STOPPED`, `GUARDIAN_STARTED` and the `basis` field of `SEAL_EXPIRED` are now the
derivation source for everything in that block. They were already in the vocabulary and nothing
new is asked of them, but they have become load-bearing: dropping one from a rotated segment, or
making it conditional, would silently reduce a published figure without anything failing. That is
worth a line in SPEC §11/§12 saying so.

## Not asked for

No new field in the certificate. No computation in the emitter. The whole point of deriving these
in the verifier is that a computed quantity is **verified** and a published one is only
**asserted** — the same distinction as an external anchor versus a hash chain. The emitter's only
obligation here is not to lose the events.
