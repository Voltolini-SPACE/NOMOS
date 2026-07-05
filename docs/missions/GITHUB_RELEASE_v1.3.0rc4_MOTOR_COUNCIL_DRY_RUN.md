# GitHub Release Draft — NOMOS v1.3.0rc4 Motor Council Dry-run

## Release type

Pre-release candidate.

## Important

This file originated as a draft only in MC10 (no tag or GitHub Release
existed yet at that point). The tag was created in MC11-RC4
(`v1.3.0rc4-motor-council-dry-run`), and the release it automatically
triggered was corrected and published with this file's content as its body
in MC12-RC4 — see
`https://github.com/Voltolini-SPACE/NOMOS/releases/tag/v1.3.0rc4-motor-council-dry-run`
(`prerelease=true`, not "latest"). This file is kept as the source-of-truth
draft that the live release body was built from; it is not automatically
kept in sync with the live release if either is edited later.

## Summary

NOMOS v1.3.0rc4 prepares the Motor Council dry-run stack: a multi-engine
review-and-arbitration pipeline that runs entirely in memory, entirely
local, and entirely without executing a real model, before any future real
integration.

## Included

- Data models.
- Offline simulator.
- Local provider contract.
- Local adapter dry-run.
- Real execution harness locked with hardcoded false flag
  (`REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False`, no activation API).
- Policy gate dry-run (A0–A6).
- Private audit envelope dry-run (metadata-only).
- Orchestrator dry-run (composes all of the above into one deterministic,
  fail-closed pipeline).
- CLI/chat UX specification (`nomos conselho` / `/conselho` — spec only, not
  implemented).
- Technical index consolidating MC0–MC9.

## Security posture

```text
REAL_ENGINE_EXECUTION=false
REAL_POLICY=false
REAL_AUDIT=false
REAL_VAULT=false
REAL_APPROVAL=false
CLOUD=false
NETWORK=false
SUBPROCESS=false
PERSISTENCE=false
CLI_IMPLEMENTED=false
CHAT_IMPLEMENTED=false
```

Every module in `nomos.council` is proven, by AST-based test (not
convention), to import no network, subprocess, threading/asyncio, cloud SDK,
real local-engine runtime, or real kernel policy/vault/audit/approval module.

## Validation

- Test suite expected: 778.
- CI expected: 17/17 (12 test jobs across 3 OS × 4 Python versions, plus
  informational coverage, informational mypy, and post-install wheel smoke
  tests on 3 OS).
- Package builds cleanly as a wheel (verified in CI runners on all 3
  operating systems; a sandbox-mount-only quirk in the authoring environment
  does not affect the published package).

## Not included

- No real engine execution.
- No real CLI (`nomos conselho` is specified, not implemented).
- No real chat command (`/conselho` is specified, not implemented).
- No PyPI publication.
- No production release.
- No tag created by this draft.

## Next step

If approved: **MC11 — RC4 Tag Preparation/Validation**, validating CI status
and commit ancestry before creating the `v1.3.0rc4` tag, still without
automatically publishing a GitHub Release.
