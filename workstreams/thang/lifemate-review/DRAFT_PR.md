# Draft: LifeMate synthetic dataset and ASR benchmark review package

Thắng’s two deliverables are now reviewable together: completed GIPFormer–VALSEA–QUAN ASR findings on the separate ViMD and VN-SLU official tests, and a model-independent dataset v1 candidate (1,063 source IDs; 990 training candidates / 57 exposed development references / 16 held). The earlier 1,000-scenario snapshot and its complete failure-mode index remain available with unchanged evidence selectors.

The historical synthetic checkpoint is 942 intended train / 58 dev, 108 WORLDs, 31 lineages; 984 acceptable within implementor scope and 16 inspected/pending adjudication. All remain spec_only/non-exportable. Preserve seven mail-family split holds, six Wave 17 independent reviews, B05_L_D and two Wave 11 chore-policy holds. Local semantic alternatives are not official fixed-reference full-score claims; gold is unchanged by packaging.

GIPFormer has the lowest official-reference WER/CER on ViMD, including all three regions, and beats QUAN on both datasets. Its verified single-T4 path and locally pinnable deployment support recommending it as the primary LifeMate ASR baseline, pending team agreement. VALSEA leads VN-SLU and remains a comparison candidate; no routing policy is approved. QUAN uses FP32 weights/FP16 autocast with FP32 attention repair; upstream equivalence and ViMD train/test overlap remain unverified. Dataset distributions and uncertainty remain separate. ASR results do not establish LifeMate task correctness or A30 end-to-end compliance. Historical scoring code and frozen pins are included. QUAN’s contribution to this package consists of aggregate reports and metrics; its integration scorer and required original inputs remain in the source workspace, so this portable package cannot independently reproduce full QUAN scoring. As before, third-party audio/reference/prediction/provider raw text and organizer runtime and full catalog are not redistributed; the candidate includes selected tool interface definitions. Authorized external SDK is required for local replay.

Review requested:

- Tài: render/load the three v0.1 cases; reconcile Jaz mapping, actual run identity, trace/submission and scorer behavior without exposing private gold or replaying history.
- Tú: review prospective model serialization, end tokens and loss masking; no training export is approved.
- Team: adjudicate 16 holds, diversity and ancestry/split rationale; complete independent review before eligibility promotion.

Validation actually performed is recorded in VALIDATION.md. No new ASR scoring, model/API execution, training, gold changes or organizer sample/environment access is part of this package. Draft review only; do not merge as a training release. No GitHub reviewer identity or assignment has been inferred.

Repository: `BK-Agentic-Engineering/ava`, base `main`. The deliverables are under `workstreams/thang/lifemate-review/`; the root README gains one link. No PR template exists in the inspected base. Workspace AGENTS.md is retained only as a reference document, without automatic instruction scope. Historical validation and destination-copy checks are distinguished in VALIDATION.md.

Current update: adds the portable candidate with complete-ID grounding and unit-aware numeric answer checks. All 203 required-answer targets are present; 29 of the 39 rubric cases remain manually graded. Candidate source references require the current original workspace; bundled historical artifacts are not substitutes. No native/model run or training acceptance is claimed. See DATASET_V1_FINALIZATION.md and VALIDATION.md for checks performed.

Latest approved review: 29 canonical rubric answers individually inspected by AI; 28 pass and TR12_BANK_LOOK unresolved because “đồng” is not grounded in its rendered input/schema/response. Do not consume that case for training until resolved. This restriction is additional to the 16 historical holds; stored eligibility and gold are unchanged, so the earlier ready count is not freshly certified. Review ledger and report are included. No human-independent or universal automatic grading claim.
