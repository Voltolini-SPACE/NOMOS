# NOMOS v1.2.0rc3 — Audit Anchored

## Status

STATUS_FINAL=RC3_AUDIT_ANCHORED_READY

## Summary

This release candidate builds on `v1.2.0rc2-security-audited` and closes the
previously disclosed audit log tail truncation gap. The audit log now supports
HMAC-SHA256 anchoring using a key protected by the NOMOS vault.

## What changed

- Added HMAC-SHA256 audit anchors.
- Anchor protects chain tip, entries count, log id, schema and timestamp/checkpoint metadata.
- HMAC key is stored/protected via the local vault.
- `nomos logs verify` now reports anchored states.
- `nomos logs anchor` creates a vault-backed anchor.
- Legacy unanchored logs are reported as WARN, not silent PASS.
- Tail truncation is now detected after anchoring.
- Rewritten chains without the HMAC key are rejected.

## Validation

- 520 tests passing.
- 17 new audit-anchor tests.
- CI green on Linux, macOS and Windows.
- 17/17 CI jobs passing.
- Wheel build validated.
- Post-install smoke validated.
- `nomos doutor` validated.
- `python -m nomos doutor` validated.
- Official agents validated.

## Security model

The audit log still uses a hash-chain for line-by-line integrity.
The new HMAC anchor adds keyed integrity over the chain state.
This detects:

- entry modification
- entry reordering
- middle removal
- tail truncation
- chain rewriting without the vault-protected HMAC key

## Compatibility

Legacy logs without an HMAC anchor are not silently considered fully protected.
They report:

```text
LOG_LEGACY_UNANCHORED
```

(a WARN status), not a silent PASS.

## Residual risks

- Entries written after the latest anchor are protected by the normal hash-chain
  until the next anchor.
- A user or attacker with the correct vault passphrase can create a new valid anchor.
- External append-only storage is not implemented.
- Remote attestation is not implemented.

## Not included

This release does not include:

- Motor Council
- PyPI publication
- read-write panel
- Obsidian integration
- new features outside audit-log hardening

## Recommendation

Use this as the preferred technical pre-release over `v1.2.0rc2-security-audited`.
