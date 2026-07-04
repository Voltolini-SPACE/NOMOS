# NOMOS v1.2.0rc2 — Security Audited

## Summary

This release candidate includes the delivery-ready NOMOS v1.2.0rc1 work plus a
post-audit security fix for skill manifest path safety.

## Security Fix

Fixed skill manifest path traversal / unsafe absolute entry path issue. A skill
manifest could declare an absolute or traversal `entry` (e.g. `/tmp/evil`) that,
at execution time, escaped the skill directory and pointed to an external file
outside the checksum-verified file set. The installer now rejects absolute
paths, `..`, and Windows drive paths, requires `entry` to be listed in `files`
(so it is checksum-covered), and adds a defense-in-depth check at execution.

## Validation

- 503 tests passing
- CI green on Linux, macOS and Windows
- Wheel build validated
- Post-install smoke validated
- `nomos doutor` validated
- official agents included in wheel and validated

## Known Gaps

Audit log tail truncation remains a known limitation of the current unkeyed
hash-chain design. The chain detects modification, reordering, and middle
removal, but not removal of the final lines. Future mitigation should use HMAC
anchored in the vault.

## Not Included

- Motor Council
- PyPI publication
- read-write panel
- Obsidian integration
- new features

## Recommended Use

Technical release candidate for security review and controlled adoption.
Suggested tag: `v1.2.0rc2-security-audited`.
