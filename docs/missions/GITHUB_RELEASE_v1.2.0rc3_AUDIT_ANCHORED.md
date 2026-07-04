# NOMOS v1.2.0rc3 — Audit Anchored

## Summary

This technical release candidate closes the audit log tail truncation gap
disclosed in `v1.2.0rc2-security-audited`. The audit log now supports
vault-backed HMAC-SHA256 anchoring.

## Security Improvement

Added HMAC anchoring for audit logs. The anchor protects:

- final chain tip
- total entries count
- log id
- schema version
- anchor metadata

The HMAC key is protected by the local NOMOS vault.

## What this prevents

After anchoring, verification can detect:

- modification
- reordering
- middle deletion
- tail truncation
- chain rewrite attempts without the HMAC key

## Validation

- 520 tests passing
- 17 new audit-anchor tests
- CI green on Linux, macOS and Windows
- 17/17 CI jobs passing
- Wheel build validated
- Post-install smoke validated
- `nomos doutor` validated

## Compatibility

Legacy unanchored logs produce a warning, not a silent success.

## Known Residual Risks

Entries after the latest anchor are only hash-chain protected until re-anchored.
Anyone with the correct vault passphrase can create a new valid anchor.
External append-only anchoring is not included.

## Not Included

- Motor Council
- PyPI publication
- read-write panel
- Obsidian integration
- new product features

## Recommended Use

Preferred technical pre-release for controlled adoption and further security review.
Suggested tag: `v1.2.0rc3-audit-anchored`.
