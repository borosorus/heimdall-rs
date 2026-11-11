# gas-class audit: exceptional halts are behavior-classified (roadmap lead 5)

The harness now records a deterministic halt class for failed read-calls: a
two-step gas ladder (full cap, half cap via `debug_traceCall`) distinguishes
`determinate` (identical consumption - fixed halt point: invalid/assert) from
`gas-bound` (tighter cap exhausted - loop-style halt). The class is part of the
compared view: equal outcomes must halt alike. Pure decision unit-tested
(`GasClassTest`); unclassifiable mixed cases record None and compare as absent
(back-compat with every recorded verdict).

## Result (this directory = full harness rerun of the sealed modern-errors candidate)

**11/11 feedback + 2/2 withheld under class-aware views.** Per-unit classes:
`ok_errorOutOfGas` and `ok_errorWithInvalidOpcode` are gas-bound on BOTH sides
(the candidate's transplanted gas-burn bodies are class-verified, no longer
parity-only); every payload-reverting unit is determinate on both sides.

The former README caveat ("OOG vs invalid observation-equivalent at this probe
depth") is thereby resolved: the units are distinguishable by consumption
signature, and the recorded candidate matches the reference on the axis - an
assertion replaced by a measurement. Synthesis variant selection is now
class-driven too (`synthesize_error_units.variant_order`): gas-bound -> burn
loop, determinate -> invalid opcode, historical order as fallback.

Suite 205/205 at introduction; audit re-run in the session seal. Reviewer
hardening adopted: `gas-bound` requires BOTH caps exhausted (an expensive
determinate halt at the half cap is unclassified, not mislabeled); the class is
recorded for silent failures only (payload-bearing reverts are already
discriminated by data); the re-sealed run in this directory is from the final
classifier.
