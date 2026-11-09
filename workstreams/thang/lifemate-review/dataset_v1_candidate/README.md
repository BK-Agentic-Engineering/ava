# LifeMate dataset v1 candidate

Model-independent candidate ready for training integration **only for the eligible subset**. Local-only text demonstrations; no training or model/native-harness acceptance is claimed.

## Later review restriction

See the [29-case review](../artifacts/synthetic/manual_rubric_29_review_20261109/README.md): 28 answers pass, TR12_BANK_LOOK remains unresolved on currency grounding. Exclude that case from training consumption until resolved. The counts and eligibility manifest below are the earlier candidate snapshot, not reapproved eligibility after this review. The 16 original holds remain unchanged.

## Contents and counts

- `training.jsonl`: 990 intended-train demonstrations.
- `development.jsonl`: 57 exposed development/reference demonstrations; never train on these.
- `eligibility.jsonl`: all 1063 source IDs exactly once. Derived eligibility: {'ready_for_training_integration': 1047, 'needs_repair': 0, 'held': 16}.
- `private/answer_reviews.jsonl`: 46 bounded author reviews, not model inputs. New wave targets already present in actual replay are separately labeled authored, not model output.
- `tool_schemas.json`: selected exact interface definitions (schema 2.7.0); no SDK modules or organizer records.
- `metadata.json` and `validate.py`: provenance/counts and standard-library validator, trace_grounding.py and grade_final_wave_answers.py for bounded identifier/filter and ten scoped answer checks.

Source designs stay spec_only/non-exportable. Derived integration eligibility authorizes this candidate representation, not a production training release. Canonical source export eligibility remains zero. The original quality audit covers its first 1,000 IDs. The separately refreshed failure-mode index covers all 1,063 source IDs; mapping review does not establish training eligibility. Native/model/template acceptance remains unverified. No audio exists in this package.

## Rendering and supervision

Each JSONL row has a private routing `scenario_id`, original `agent_visible`, tool schema names and `assistant_target`. Resolve only that row's schemas from tool_schemas.json (including implicit sys.ask_missing_info). Render context and history as supplied, followed by the latest request. History has already happened; never execute its writes again. Preserve order, roles, audio_text/text fields, old failures/no-ops and omitted-versus-empty values. Tài owns final Jaz mapping and genuine run IDs.

Latest target calls have unmodified name/arguments/result paired in one object. They are sequential authored reference calls and actual SDK responses. Calls are assistant action targets; results are observations, not assistant prose targets. Final text is an authored target, not hidden reasoning. Null final text is explicit absence, not an invented empty answer; absence_reason explains tool-only, optional-silence or clarification termination. Reference traces are valid examples, not the only valid trajectories and not official full-score guarantees.

Do NOT feed eligibility.jsonl, metadata.json, private reviews, WORLD snapshots, oracle, failure tags or review notes to the model. Do not supervise source IDs, outcome/termination labels or routing metadata as assistant prose. Independent Wave17 readers must see the blind sheet before gold-bearing manifests/reviews; this is not a blind review packet. Tú owns chat template, tokenizer, tool-call encoding, end tokens and actual loss masks. No particular masking implementation is validated here.

## Answers, restrictions and evidence

All 203 required-answer targets are present. 39 manual-rubric examples are canonicalized and three made more explicit; seven previously scoped pilot targets fill additional omissions. The remaining targets reuse accepted scoped canonical evidence. Bounded author review supports targets; independent adjudication is not invented. Ten of the 39 rubric cases now have narrow observation-grounded automatic checks with manual fallback; 29 remain manual. These are not universal Vietnamese graders.

All 16 original holds are excluded. Mail's cross-split group exports dev references only; held train mail descendants stay excluded. All other proposed groups retain their constraints. Never reshuffle descendants into an unseen test. Author/QC exposure is documented, model/prompt exposure is not established. Synthetic failure hypotheses and contrast counts are not observed model errors or representative usage estimates.

Private evidence locators are source-workspace-relative and external to this portable message package. They resolve against the original designs/replays, including post-history state, clock, permissions, final state and oracle. For replay, resolve private_initialization_ref against the source evidence, inject the recorded private_clock_permissions into _meta.tools/current_time, and assert effective permissions plus an empty latest log. Use the post-history snapshot, never the pre-history WORLD or replayed historical writes. The original authorized release v3.2.0 SDK archive is required only to rerun SDK replay; do not redistribute SDK/data with this package. Full replay requires the original workspace too. This export reuses canonical SDK evidence; it does not rerun unaffected sessions.

## Verification and reproduction

After copying/extracting this directory elsewhere, run `python validate.py` (standard library only). This checks structural completeness, counts, routing, answers/review binding, identifier introduction, roles and split/group separation; it is not a fresh semantic judge or SDK replay.

In the original workspace: `python -X utf8 scripts/export_dataset_v1.py --output <fresh-directory>` uses existing PyYAML and authorized `D:/Downloads/train+public_test.zip`. Do not overwrite conflicting candidates. Then `python <fresh-directory>/validate.py --source-root "D:/Project/Zalo AI"` reconciles evidence and visible inputs with originals. Source tests: `python -X utf8 -m unittest discover -s tests -p test_dataset_v1_export.py -v`.

Next review: inspect one required-answer train demonstration and one clarification dev demonstration with the private locators before implementing serialization. No team decision, independent review or model success is implied.
