# Offline factual-answer pilot

This pilot adds answer checks to eight existing intended-train cases. No scenarios, split assignments or benchmark gold changed. The collection remains 862 scenarios across 96 WORLDs, with 804 intended train and 58 dev. All remain spec_only and non-exportable. There are 119 existing observe-only cases, eight sidecar specifications, and eight cases with validated scoped automatic checks. Seven require a factual answer. One permits silence after the condition check. No case is exclusively manual, but all eight route unsupported formulations to human review.

| Canonical case | Required answer and visible source |
| --- | --- |
| TR8_TV_ONLYGUIDE | Vệt 2 for Vườn Mưa at 20:00 on the requested day. Latest filtered guide proves the matching airing. An exhaustive claim about other airings is unsupported. |
| TR9_BANK_LOOK | Current balance of 600,000 đồng for Quỹ Khuôn Đồng. Latest balance read also returns Quỹ Đường Vải with 900,000 as a distractor. |
| TR10_APPL_LOOK | Máy Giặt Khe Sợi is running eco. The latest appliance list distinguishes running from scheduled and exposes the cycle. |
| TR10_FUEL_LOOK | RON95 is 22,999 VND per litre from the latest price response. Both amount and denominator matter. |
| TR10_ALARM_LOOK | The 06:15 weekend Phơi Khung alarm is off. The latest list has a separate enabled weekday record. |
| TR12_SHOP_LOOK | Three dây cói lines with quantities 2, 5 and 2, any order. The unfiltered list exposes all lines including an unrelated nẹp tre row. A total of nine loses the requested per-line information. |
| TR13_CONTACT_INSPECT | Repeat the old email thu.cu@daymoc.example.test from the earlier search. The later update shows thu.moi@daymoc.example.test. The latest standard log is empty. |
| TR16_APP_KEEP | This is a conditional action. The latest appliance list shows the washer is already running eco. The correct branch leaves it alone. Silence or a supported status or acknowledgment is acceptable under the proposed pilot rule. |

The sidecar identifies canonical call/result positions, entity fields, facts and tolerable omissions. It distinguishes latest observations from historical ones. For example, “Đang giặt chế độ ECO” and “Đang chạy eco” both satisfy the washer question. “Đang chạy” omits the cycle and fails. “Máy ở eco rồi” leaves the running versus scheduled distinction unclear and goes to review. The old-email case rejects the current email even though it genuinely appears in history. A correct channel followed by “Không có suất nào khác” fails the unsupported-exhaustiveness probe. A missing field, filtered empty list, and confirmed absence carry different evidence. This pilot does not infer broader absence from either of the first two.

All 65 answers are authored evaluation probes. There are 17 passes, 40 concrete fails and eight unresolved probes. The local adapter checks canonical evidence before applying whole-answer rules with scoped normalization. The rules are intentionally narrow. A plausible but unrecognized paraphrase, qualifier or extra claim remains unresolved. Reviewers should compare it to the case rubric, confirm the entity and all required facts, and reject material contradictions or unsupported assertions. The adapter cannot grade arbitrary Vietnamese text or establish model performance. It uses the canonical passing tool path for the probes. The combined verdict checks separately demonstrate that a tool/state failure survives a correct answer, and that a factually wrong answer fails despite a valid tool trace.

Wave 16's ordinary parcel attempt after a conclusive read is accepted for task correctness and carries a redundancy note. The attempt-bound control still requires the actual no-op response. All 99 original runtime rows reconciled, with one reclassified verdict and three surviving rejections whose redundancy reason moved to the efficiency field. Calls, validation results, states and sequences were preserved. Wave 16 reconciliation (excluded local source: `TRAIN_WAVE_16_HANDOFF.md#redundant-attempt-policy-clarification`; see FILE_SELECTION.json)

## Reproduction

```powershell
python -X utf8 scripts/evaluate_factual_answer_pilot.py
python -m unittest discover -s tests -p test_factual_answer_pilot.py
python -m unittest discover -s tests -p test_replay_train_wave_16.py
```

Two fresh processes produced identical factual output. Five factual checks and seven Wave 16 checks passed. No separate probe output file is required. Tài needs to confirm final-text capture and trace association before the sidecar can score live harness output. Tú's target serialization and masking remain pending. [Sidecar](../../data/synthetic/factual_answer_pilot.yaml) · [Evaluator](../../scripts/evaluate_factual_answer_pilot.py) · [Harness proposal](WORLD_HARNESS_CONTRACT_PROPOSAL.md)

## Three-case trace-binding integration

The local adapter takes one object per run. The tests build these examples directly from canonical artifacts and pair them with authored final text. No model generated the text. The previous eight-case probe CLI continues to evaluate its fixed canonical fixtures.

| Field | Local contract |
| --- | --- |
| scenario_id, run_id | One supported scenario and a nonempty run identity. |
| source_ref | scenario_id, run_id, design version and fixture_variant. A mismatch is incompatible. The design resolves the canonical replay and pinned local configuration. |
| visible | The rendered request, context, permissions and history. The adapter checks the rendering against the scenario. It inspects actual historical result payloads, including missing payloads. |
| initial_state, final_state | Private complete app snapshots. Initial state must match the selected fixture or post-history state. Wave 16 additionally requires state_after on each call and checks the last snapshot against final_state. |
| calls | Ordered latest calls, each with name, arguments and actual result. Historical calls remain in visible history. |
| final_text, termination | final_text is present as a field. Null means absent, and an empty string is preserved separately. Supported termination values are completed, runner_error and incomplete. |

The adapter returns input_status and either an incompatibility reason or separate trace_verdict, trace_reasons, evidence_status, answer_verdict, answer_reason, termination, text_status and overall. It reruns the existing Wave 10, 13 or 16 verifier and ignores caller verdicts. Reject and fail map to fail. Unknown verdicts map to unresolved. The corresponding scenario and run IDs identify a compatible result. Runner error fails the overall task. Incomplete execution cannot pass. An independent trace or answer failure fails the overall task even when the other component passes.

| Canonical input reference | Authored final text | Expected outcome |
| --- | --- | --- |
| TR10_APPL_LOOK, standard | Đang chạy eco. | Fresh read supplies target identity, running status and cycle. Trace and answer pass. |
| TR13_CONTACT_INSPECT, standard, original order | thu.cu@daymoc.example.test | Actual rendered historical search supplies the old email. Empty latest log passes. |
| TR16_APP_KEEP, standard | null | Fresh observation establishes the no-write branch and silence is permitted. |

Entity rows resolve by stable ID and name. Reordered appliance and historical contact arrays pass. For historical evidence, the adapter aligns calls with results by position within the turn. It projects only contact-search row order for Wave 13's exact-payload comparison and represents a missing paired result as unsuccessful for that verifier. Canonical historical events define the expected provenance and never supply a missing observed fact. Missing, empty and unrelated fresh reads fail the required trace even if the text guesses correctly. A changed value for the right entity gives source_mismatch and unresolved answer grading. Scoped Vietnamese rules are unchanged.

This local check verifies consistency and provenance within a recorded envelope. It does not authenticate external response payloads or prove the text came from the claimed run. The exact current fixture and rendering contract are deliberate pilot restrictions. Tài must confirm run-ID ownership, how capture ties the response to the same turn, snapshot and result formats, and the mapping for interruptions and runner errors. Tú needs to preserve absent versus empty text and consume only separately approved targets if export is later authorized.

### Integration reproduction

```powershell
python -m unittest discover -s tests -p 'test_factual*.py'
python -m unittest discover -s tests -p 'test_replay_train_wave_1[36].py'
```

Eight adapter tests cover saved local runtime traces, two new local Session reads with empty and unrelated results, and in-memory metadata, response and termination probes. The test names and comments distinguish these sources. Thirteen factual tests and 18 existing Wave 13/16 verifier tests passed. No canonical replay, verifier, sidecar or scenario was changed. Inventory remains 862 scenarios across 96 WORLDs with 804 intended train and 58 dev. [Adapter](../../scripts/factual_trace_adapter.py) · [Contract examples and tests](../../tests/test_factual_trace_adapter.py)
