# Dataset v1 candidate finalization — 2026-11-09

The [candidate](../../dataset_v1_candidate/README.md) contains 990 training demonstrations and 57 exposed development references. Its manifest retains all 1,063 source IDs, including 16 excluded historical holds. No new hold or demonstration repair was needed in this final verifier pass.

## Repairs and impact

- Identifier introduction now requires complete boundaries: supplying GOM9080 cannot justify querying GOM908. The SDK-supported whitespace/case normalization is confined to tracking codes; other identifiers/channels do not inherit whitespace removal. Previous successful, permitted observations can supply values; a call cannot justify itself through its own response. This remains a bounded check, not a proof of source identity or arbitrary semantic grounding.
- Numeric answer parsing follows the unit. Percentages 0.050% and 0,050% remain 0.05%, so both fail against an observed 50%. Vietnamese money grouping such as 150.000 đồng remains supported. Ambiguous/unrecognized forms remain unresolved, including 150,000 đồng and 0.030 phút. Unknown wording requires manual review.

Both repaired checks were applied through a fresh candidate build. All 1,047 demonstrations, the complete eligibility manifest and existing final-answer targets remained byte-identical. Only the two bundled verifier helper files changed. The 16 holds remain unchanged. No source case was downgraded merely because a verifier vulnerability existed.

## Checks performed

- 11 final-wave regression tests and seven candidate export tests passed in the source workspace, including complete source reconciliation, clean-directory execution/import and deterministic rebuild.
- Wave 23 ran again in fresh SDK sessions: six standards, 57 runtime paths (30 pass / 27 reject). Its complete artifact matched the canonical file after excluding only created_utc and replay_wall_seconds.
- Fresh candidate validation with the original source workspace passed: 1,063 IDs, 990 train / 57 dev, 16 held, zero needs_repair, 203 required answers.
- Portable verifier regressions and package/index checks are recorded in the package validation log. Invented regression probes are not model observations.

## Scope and evidence access

The older 1,000-case designs/replays and failure-mode index elsewhere in this package are a preserved historical snapshot. Candidate private locators refer to the current original source workspace, not those older files. Full current replay requires that workspace and the authorized v3.2.0 SDK; no organizer dataset or runtime is distributed here. The candidate includes selected tool interface definitions for rendering.

All 203 required-answer demonstrations contain text. Of the 39 rubric cases, ten have scoped automatic checks; 29 remain manual. Canonical source status stays spec_only/non-exportable; derived candidate eligibility means ready for training integration, not tested model serialization, loss masking, native harness execution or a production training release. Keep all group restrictions and exposed-development labels. No untouched test set or measured generalization claim is introduced.

No model/API inference, new benchmark scoring, training or additional scenarios were performed.
