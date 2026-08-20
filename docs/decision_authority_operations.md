# Decision authority operations

The managed routes are `BTCUSDT:1h`, `BTCUSDT:4h`, and `ETHUSDT:4h`.
Ownership is stored only in Valkey under `signal:authority:{route}`. The
remaining configured Strategy routes are unrelated and continue to use their
existing admission path.

## Required order

Run the foreground authority controller's `prepare` operation before starting
an authoritative Decision topology. An unseeded topology fails closed: neither
Strategy nor Decision repairs or creates authority records automatically.

For the initial handoff, quiesce and stop Strategy, read and confirm stable
legacy feature boundaries, drain Risk, seed Decision effect progress, and then
run `cutover-to-decision`. Start Decision only after the atomic transfer has
completed.

For cutback, stop Decision first, read stable effect progress, drain Risk, run
the controller's legacy feature-group `SETID` fast-forward, then run
`cutback-to-strategy` and restart Strategy. For re-cutover, stop Strategy,
read stable legacy boundaries, drain Risk, run `recutover-to-decision`, and
start Decision.

Inspect the current records with the controller's `status` operation. Do not
blindly restart the default topology during a handoff: the authority records,
effect-progress rows, consumer-group positions, and Risk quiescence must be
prepared in the stated order. Execution remains paper-only in this phase.

When Decision owns a managed route, Strategy admission blocks that route and
does not consume or publish its feature stream. Missing, malformed, or
unavailable authority blocks only that managed route; unrelated routes remain
available.
