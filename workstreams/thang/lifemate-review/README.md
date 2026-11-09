# LifeMate: Thắng’s team review handoff

Thắng benchmarked three ASR systems on the full released test splits and prepared a 1,063-scenario source collection, with 1,047 demonstrations eligible for training integration. The earlier 1,000-scenario review snapshot is retained separately. GIPFormer 1.5 is recommended as LifeMate’s primary ASR baseline, pending team agreement. Agent performance on these WORLDs is still unmeasured.

- **Tài:** use the [three integration cases](integration/three_cases/README.md) to check what Jaz renders, which tools it exposes and what it records after a call. These cases exercise the interface.
- **Tú:** inspect the [clarification input](integration/three_cases/B02_N_C.input.json) alongside its [reference output](integration/three_cases/B02_N_C.output.json) to review message serialization and loss masking. Use the model-independent candidate below for adapter work; model-specific serialization and loss masks still require validation.
- **Team:** review the [16 pending decisions](#decisions-still-pending). For the independent Vietnamese reading, send the blind sheet before the reader opens any gold-bearing files.

## Answer review follow-up — 2026-11-09

The [29-case semantic review](artifacts/synthetic/manual_rubric_29_review_20261109/README.md) records **28 pass / 1 unresolved** for the exact canonical answers. This was AI review with access to gold, not blind human adjudication or a general automatic grader.

**Do not use TR12_BANK_LOOK for training until the currency question is resolved.** Its balance and beneficiary facts match, but the added unit “đồng” lacks an explicit source in the rendered input/schema/response. This is a new review restriction, separate from the 16 historical holds. The existing eligibility manifest and targets remain unchanged: its 1,047 ready count predates this restriction and must not be treated as a fresh unconditional approval. No new eligibility count is certified by this documentation update.

## 1. Completed GIPFormer–VALSEA–QUAN ASR benchmark

| Official test distribution | Records | GIPFormer WER / CER | VALSEA WER / CER | QUAN WER / CER |
| --- | ---: | ---: | ---: | ---: |
| ViMD | 2,026 | 6.992% / 5.431% | 13.130% / 10.379% | 9.875% / 7.319% |
| VN-SLU author-released test | 2,401 | 20.296% / 17.775% | 17.499% / 12.508% | 25.808% / 21.587% |

GIPFormer has the lowest official-reference WER/CER on ViMD, including all three regions, and beats QUAN on both datasets. Its verified single-T4 path and locally pinnable deployment support the primary-baseline recommendation; this is not a ratified team decision. VALSEA has the lowest WER/CER on VN-SLU and remains a comparison candidate, without an automatic fallback/routing policy. QUAN has not shown an advantage sufficient to replace GIPFormer here. Keep the datasets separate: no pooled score, universal winner, semantic-slot accuracy or LifeMate task-success claim follows. ViMD has paired speaker-cluster intervals; VN-SLU lacks speaker/region metadata, so those intervals are unavailable. Its released count of 2,401 differs from the paper’s 2,454.

Start with the [canonical three-model closeout](docs/implementation/ASR_BENCHMARK_CLOSEOUT.md) and current [ViMD report](artifacts/scoring/quan_vs_baselines_20261107/vimd/report.md) / [VN-SLU report](artifacts/scoring/quan_vs_baselines_20261107/vnslu/report.md); metrics.json sits alongside each report. These contain additive totals, regional/intent results, uncertainty, configurations, provenance and scoring rules. The older [GIPFormer–VALSEA ViMD report](artifacts/scoring/valsea_vs_gipformer_vimd_20261101/report.md) and [VN-SLU report](artifacts/scoring/valsea_vs_gipformer_vnslu_20261102/report.md) are **historical two-model comparisons**.

Precision policies differ: GIPFormer uses FP16 weights with mixed computation; QUAN uses FP32 weights, FP16 autocast and the FP32 attention repair. QUAN/upstream equivalence is unverified. ViMD appears among QUAN’s training sources, with test-split overlap unverified; other models’ training exposure is not fully known. VALSEA lacks an immutable exposed revision. The closeout preserves exact settings, provider/retry limits and qualifications; no comparable latency/cost/memory advantage or A30 end-to-end compliance is established. All samples/flags remain included, including QUAN’s two empty VN-SLU texts with full deletion errors.

Full benchmark reference/prediction text, provider raw responses and audio remain local. Redistribution rights remain unresolved for the recorded ViMD license, VN-SLU release and provider outputs. Aggregates do not replace the authorized original inputs needed for rescoring. Completed requests do not establish usage rights or exactly-once remote processing.

The next proposed validation compares matched LifeMate tasks using gold transcripts versus GIPFormer-transcribed audio, measuring downstream target/value/time/tool and task/state errors. WER/CER and selected English/name wins do not establish those outcomes; strict number-form differences and reference uncertainty remain limitations. No fine-tuning requirement, cost/latency/memory advantage or end-to-end deployment compliance is established.

## 2. Dataset v1 candidate and historical evidence

Start with [dataset v1 candidate](dataset_v1_candidate/README.md): **990 training candidates / 57 exposed development references**, with all **16 held cases excluded**. Its eligibility manifest retains all **1,063 source IDs**. Source designs remain spec_only/non-exportable; candidate eligibility concerns training integration only, not validated training or native harness acceptance.

Run `python dataset_v1_candidate/validate.py` without the SDK. For source reconciliation, add `--source-root` pointing to the original source workspace. The manifest's private source references refer to that workspace, **not the older snapshot below**. Full replay needs those current source files and the authorized external SDK. Do not resolve a candidate reference against an older same-named artifact.

All 203 required-answer targets are present. Of the 39 rubric cases, ten have scoped automatic checks and 29 remain manual. The [finalization note](docs/implementation/DATASET_V1_FINALIZATION.md) records the two verifier repairs, coverage and limits. Group restrictions remain conservative; development references are exposed, not an unseen test.

### Historical 1,000-scenario review snapshot

The following designs, replay artifacts, audit and failure-mode index retain their earlier versions and exact evidence selectors. They are reference material, not the source of the current candidate.


| Checkpoint | Status |
| --- | --- |
| Scenarios | **1,000**: 942 intended train, 58 dev, zero test |
| WORLDs / named lineages / ancestry components | 108 / 31 / 15 (train: 5; dev: 10) |
| Outcomes | 715 execute, 239 observe-only, 31 ask_missing, 15 out_of_scope |
| Implementor inspection | 984 acceptable within scope; 16 inspected and awaiting adjudication; zero awaiting inspection |
| Eligibility | All **spec_only and non-exportable**; training-export eligibility is **zero** |

Entry points: [designs](data/synthetic/design/), [canonical authored replay](artifacts/synthetic/), [failure taxonomy and coverage](docs/implementation/WORLD_LOCAL_COVERAGE.md), [individual ledger](artifacts/synthetic/quality_audit_1000/per_sample_review.jsonl) and [completed implementor audit](docs/implementation/SYNTHETIC_1000_QUALITY_AUDIT.md).

Independently authored Vietnamese requests, fixtures and controls test permissions, entity/source selection, missing information, context/history, preservation, conditions, recovery and factual answers. Gold traces were authored and executed locally; they are not model-generated results or the only valid solutions. Designed failure cases remain **hypotheses until tested on a model**. Controls, rephrasings and negative traces are not additional independent mechanisms. Train/dev ancestry is preserved; exact request-repeat checks do not prove semantic independence. All 1,000 cases are text-only, with no generated scenario audio or established voice/ASR coverage.

### Decisions still pending

- **Seven mail-family holds:** connected-family split/overlap adjudication. Exact IDs and evidence are in the audit and ledger.
- **Six Wave 17 independent reviews:** responses remain pending. Give independent readers **only the [blind sheet](review/blind/reviewer_sheet_vi.md) before they see this gold-bearing package**. Keep the [private key](review/private/PRIVATE_comparison_key_vi.md) separate. Proposed administration changes remain unimplemented: one item at a time, explicit-duration control last; distinguish incomplete answers from reasoned ambiguity.
- **B05_L_D:** gold remains empty log / unchanged state. The open classification/policy question is whether an unavailable write permits a harmless condition read. That semantic alternative is not officially accepted or guaranteed full score.
- **TR11_CHORE_PAIR / TR11_CHORE_EXPLICIT:** gold still requires the authored assignments. Whether observation of an already-satisfied assignment permits no-op or partial writes remains open; PAIR still needs its genuinely changed assignment. No policy or gold change is made here.

## Evaluation and integration boundaries

Keep three concepts separate: **official contest score**, **local task/state/grounding correctness**, and **optional factual-answer/trace-efficiency diagnostics**. A semantically valid alternative may receive a different tool-call score against a fixed reference. Empty-gold contest scoring requires an empty submitted call list. Local acceptance, redundant-read notes and proposed no-op alternatives do not certify official full-score behavior. Older observe-only verifiers often do not grade final text; unfamiliar plausible language remains reviewable.

For example, in `TR16_PARCEL_DELIVERED`, the local verifier accepts two routes to the requested reminder. Tracking can confirm delivery, or a reschedule attempt can return an already-delivered no-op. Both supply evidence before the reminder is created. Creating the reminder first and checking delivery afterward fails the authorization check. The [Wave 16 replay](artifacts/synthetic/train_wave_16_replay/replay.json) records the calls, responses and verdicts for each route.

The [v0.1 harness proposal](docs/implementation/WORLD_HARNESS_CONTRACT_PROPOSAL.md) and [three-case integration README](integration/three_cases/README.md) provide TR15_PLANNING_TOMORROW, B02_N_C and TR16_APP_KEEP: visible inputs, private post-history WORLD, clock, permissions, reference calls/results/final state, oracle and verifier dependencies. Render **only agent_visible**. Never expose private state/gold or execute historical actions again. Prepared run IDs are examples, not actual model-run identities.

## Reproduction

Run from the package root with Python 3.10+ and PyYAML; Python 3.12+ is recommended for current tooling. Windows may need tzdata. These CPU tools are separate from the frozen ASR inference environment; no dependency upgrade is required by this documentation task.

Package-only checks:

```powershell
python -X utf8 scripts/check_team_review.py
python -X utf8 scripts/check_synthetic_quality_audit.py
python -X utf8 -m unittest discover -s tests -p "test_benchmark.py"
python -X utf8 -m unittest discover -s tests -p "test_compare_*.py"
```

SDK replay requires your **authorized release v3.2.0 archive, schema 2.7.0**:

```powershell
$env:LIFEMATE_SDK_ARCHIVE = 'X:/authorized/train+public_test.zip'
python -X utf8 integration/three_cases/verify.py --archive "$env:LIFEMATE_SDK_ARCHIVE"
```

The command temporarily materializes allowlisted SDK modules and nine exact schemas; none is distributed. No organizer sample/environment member is read. The [integration README](integration/three_cases/README.md) describes reference verification. The [validation record](VALIDATION.md) retains previously executed regression/replay checks; they are not newly executed results of this prose revision.

The canonical closeout records the source-workspace QUAN reproduction command; its integration script and required inputs are not bundled. Complete ASR rescoring needs the withheld authorized manifests, predictions, configurations, ledgers and baseline scores at the paths documented in the saved reports. In particular, test_score_vnslu_test.py needs the completed run bundle. Do not invoke bundled inference/transport entry points; their source is present for frozen scoring validation. No model call or ASR scoring rerun is part of this task.

## Constraints and publication status

The [supplied contest description](docs/project/description.md) and [team assignment](docs/project/README.md) were checked locally on 2026-11-06, not reverified against a live organizer page. Their offline, model/context, hardware/time, deterministic decoding, precision and organizer-data restrictions remain applicable. [Validation qualifications](VALIDATION.md) separate recorded ASR/local replay evidence from **unverified full-system compliance**, licensing and training/deployment work outside this handoff. ASR-only T4 measurements establish no A30 end-to-end compliance.

[FILE_SELECTION.json](FILE_SELECTION.json) is the publication allowlist. Organizer SDK/data, transcript bundles, audio, weights, credentials, caches and delivery ZIPs are excluded from the extracted publication set. Retained plans and old setup instructions are historical. See [Draft PR text](DRAFT_PR.md) and [Vietnamese handoff note](HANDOFF_VI.md).

Team review is open in [Draft PR #5](https://github.com/BK-Agentic-Engineering/ava/pull/5).

## Failure-mode navigation

Use the [failure-mode guide](docs/implementation/FAILURE_MODE_INDEX.md) to find intended challenges, controls and exact authored runtime/answer evidence. The [JSONL index](artifacts/synthetic/failure_mode_index.jsonl) contains all **1,000 individually reviewed mappings**, including the 16 holds. Counts overlap and describe design/verifier coverage, not model error rates. The earlier quality audit, official contest scoring and local semantic checks remain separate. All scenarios stay spec_only and non-exportable. This index covers the original 1,000 IDs only; later additions are not indexed here.

From this package directory, run `python -X utf8 scripts/check_failure_mode_index.py --require-complete`. Add `--tag wrong_target` to list matching IDs or `--scenario TR16_PARCEL_DELIVERED` to inspect a mapping and its evidence selectors.
