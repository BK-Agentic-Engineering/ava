# Draft: LifeMate synthetic dataset and ASR benchmark review package

Thắng’s two deliverables are now reviewable together: completed GIPFormer–VALSEA ASR findings on the separate ViMD and VN-SLU official tests, and 1,000 independently authored synthetic WORLD scenarios with local reference replay/verifier evidence.

The synthetic checkpoint is 942 intended train / 58 dev, 108 WORLDs, 31 lineages; 984 acceptable within implementor scope and 16 inspected/pending adjudication. All remain spec_only/non-exportable. Preserve seven mail-family split holds, six Wave 17 independent reviews, B05_L_D and two Wave 11 chore-policy holds. Local semantic alternatives are not official fixed-reference full-score claims; gold is unchanged by packaging.

GIPFormer has lower official-reference WER/CER on ViMD; VALSEA has lower values on VN-SLU. Dataset distributions and uncertainty remain separate. ASR results do not establish LifeMate task correctness or A30 end-to-end compliance. Aggregate findings, pins and scoring code are included; third-party audio/reference/prediction/provider raw text and organizer SDK/catalog are not redistributed. Authorized external SDK is required for local replay.

Review requested:

- Tài: render/load the three v0.1 cases; reconcile Jaz mapping, actual run identity, trace/submission and scorer behavior without exposing private gold or replaying history.
- Tú: review prospective model serialization, end tokens and loss masking; no training export is approved.
- Team: adjudicate 16 holds, diversity and ancestry/split rationale; complete independent review before eligibility promotion.

Validation actually performed is recorded in VALIDATION.md. No new ASR scoring, model/API execution, training, gold changes or organizer sample/environment access is part of this package. Draft review only; do not merge as a training release. No GitHub reviewer identity or assignment has been inferred.

Repository: `BK-Agentic-Engineering/ava`, base `main`. The deliverables are under `workstreams/thang/lifemate-review/`; the root README gains one link. No PR template exists in the inspected base. Workspace AGENTS.md is retained only as a reference document, without automatic instruction scope. Historical validation and destination-copy checks are distinguished in VALIDATION.md.
