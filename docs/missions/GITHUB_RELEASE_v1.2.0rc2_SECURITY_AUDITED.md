# NOMOS v1.2.0rc2 — Security Audited

## Summary

This is a technical release candidate for controlled adoption and security review.

It includes the delivery-ready NOMOS v1.2.0rc1 work plus a post-audit security fix for skill manifest path safety.

## Security Fix

Fixed a skill manifest path safety issue where an unsafe absolute `entry` path could point outside the installed skill directory and outside the checksummed file set.

### Mitigation

- Absolute paths are rejected.
- `..` traversal is rejected.
- Windows drive paths are rejected.
- `entry` must be present in `files`.
- `entry` must be covered by checksum.
- Runtime execution includes defense-in-depth path validation.

## Validation

- 503 tests passing.
- CI green on Linux, macOS and Windows.
- 17/17 CI jobs passing.
- Wheel build validated.
- Post-install smoke validated.
- `nomos doutor` validated.
- `python -m nomos doutor` validated.
- Official agents included in wheel and validated.

## Known Gaps

### Audit log tail truncation

The current unkeyed hash-chain detects modification, reordering and removal from the middle of the log, but it does not detect truncation of the last entries.

Future mitigation should use HMAC anchored in the vault, signed checkpoints, or another keyed integrity anchor.

## Not Included

This release does not include:

- Motor Council
- PyPI publication
- read-write panel
- Obsidian integration
- new features beyond the audited fix and release documentation

## Recommended Use

Use as a technical pre-release for security review and controlled adoption.

Do not treat this as the final stable release.
