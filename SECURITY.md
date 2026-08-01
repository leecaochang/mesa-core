# Security Policy

mesa-core is a safety enforcement component: it decides whether an AI agent's action against a smart-home entity is permitted. A bug that causes it to allow something it should block is a security issue, not just a defect. This policy describes what to report and how.

## Supported versions

| Version | Supported |
|---|---|
| 1.3.x   | Yes       |
| 1.2.x   | Yes       |
| < 1.2   | No        |

Security fixes are released as patch versions and noted in the changelog.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability.

Report it privately by either:

- GitHub's "Report a vulnerability" button under the repository's Security tab (a private advisory), or
- email to sfox38@gmail.com with "mesa-core security" in the subject.

Include the affected version, the impact, and a minimal profile plus service call that reproduces it. mesa-core has zero runtime dependencies, so a reproduction is usually a small self-contained Python snippet.

This is a solo-maintained project. Expect an acknowledgement within five business days and an assessment of severity and fix timeline shortly after. Please allow a reasonable window for a fix before any public disclosure.

## What is in scope

The bug that matters most here is a fail-open: an outcome that should be denied but is allowed. For example:

- A `control_mode: prohibited` or `read_only` entity that is nonetheless actionable in enforced mode.
- An active `declared_limit`, `temporal_constraint`, or privacy classification that fails to apply when it should.
- Conflict resolution (Rules A-E) loosening a value that should only tighten, for example an inherited `prohibited` being downgraded.
- The confirmation protocol (Section 6.6) accepting a token that does not bind to the exact entity, service, and parameters challenged, or honouring a reused single-use token.
- An evaluation error that opens access rather than failing closed.

Reports framed against a specific spec section are the most actionable.

## What is out of scope

These are documented design boundaries, not vulnerabilities. They are described in spec Section 3 (Security Considerations) and the project's design notes:

- Deliberately deceptive agents. MESA's threat model assumes cooperative agents. A malicious agent that ignores boundaries is out of scope at the metadata layer; Home Assistant's native access control is the required backstop. Enforced mode and native HA permissions are meant to be used together, and neither alone is sufficient.
- Global state invariants across calls. mesa-core evaluates one call at a time. It does not solve cross-entity transition invariants (for example "never leave the door unlocked while the alarm is disarmed"); that is an automation-layer concern.
- Non-canonical inputs. mesa-core matches service names, entity IDs, and state values exactly against their canonical Home Assistant forms. Canonicalising incoming calls before evaluation is the host's responsibility (spec Section 6); a non-canonical call that slips past a boundary is a host integration bug, not a mesa-core vulnerability.
- Over-restriction via erroneous or poisoned profiles. A profile that wrongly over-restricts is handled by the removal path in spec Section 3, not as a security report.

If you are unsure whether something is in scope, report it privately anyway and we will sort it out.

