# Failure-mode index — complete individual mapping

**1,063/1,063 individually reviewed; 0 pending.** Reviewed-but-unmapped: 0. All 1,063 IDs occur once. Prior quality-audit review and this mapping review are separate.

[Index](../../artifacts/synthetic/failure_mode_index.jsonl) · [Audit](SYNTHETIC_1000_QUALITY_AUDIT.md)

Counts use unique scenario IDs, with denominator 1,063. Tags and evidence statuses overlap; sums need not equal the collection size. These are designed cases, not independent statistical samples or model error rates. Unreviewed rows carry no inferred tags.

| Tag | IDs | Train | Dev | Design-only | Isolation not assessed | Isolated authored negative |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| wrong_target | 320 | 291 | 29 | 21 | 299 | 0 |
| wrong_tool | 106 | 106 | 0 | 1 | 105 | 0 |
| unsupported_guessing | 648 | 615 | 33 | 28 | 615 | 5 |
| missed_context | 127 | 122 | 5 | 78 | 47 | 2 |
| missed_history | 158 | 150 | 8 | 66 | 92 | 0 |
| insufficient_information | 51 | 38 | 13 | 6 | 45 | 0 |
| constraint_violation | 618 | 584 | 34 | 16 | 602 | 1 |
| bad_recovery | 16 | 16 | 0 | 0 | 16 | 0 |
| unsupported_answer | 170 | 170 | 0 | 8 | 36 | 126 |

Reviewed intended splits: 1005 train, 58 dev. Pending mapping reviews: 0. Resume: **none**.

| Evidence status | Unique IDs | Train | Dev |
| --- | ---: | ---: | ---: |
| design_support_only | 192 | 181 | 11 |
| isolated_authored_answer_probe | 126 | 126 | 0 |
| isolated_authored_counterexample | 8 | 0 | 8 |
| isolation_not_assessed | 1054 | 1004 | 50 |
| verifier_evidence_present_not_causally_isolated | 0 | 0 | 0 |

| Evidence type | Unique IDs |
| --- | ---: |
| design_rationale | 1063 |
| accepted_authored_runtime_trace | 1063 |
| authored_runtime_counterexample | 1057 |
| verifier_only_or_modified_evidence_probe | 4 |
| authored_answer_probe | 162 |
| Actual model failure | 0 |

The isolated-negative column is the union of runtime and answer-probe scenario IDs, never their sum. State changes and multiple verdict reasons can be consequences of one error, not independent defects. Isolation not assessed means no causal-isolation conclusion was reached. Per-entry comparisons name their accepted and negative records and are checked against source-derived differences. Scenario-wide limitations remain separate; context_evidence resolves other records mentioned there without adding tag coverage or isolated-negative counts.

The consistency review covers all 2,224 entries: 2,000 accepted/negative comparisons and 224 design-only entries. The 192 context references identify additional records discussed in scenario-level notes and do not increase tag coverage. The TR9_NEWS_LOOK and TR10_CLIMATE_FAN missing-read comparisons now describe their linked unobserved paths, separately from the wrong-write paths. Current source copies and mapping changes are recorded in failure_mode_sources.json and failure_mode_reconciliation.json. The original 1,000-case audit remains historical; the 63 new IDs have mapping review, not that audit.

## Use and evidence boundaries

```powershell
python -X utf8 scripts/check_failure_mode_index.py
python -X utf8 scripts/check_failure_mode_index.py --tag wrong_target
python -X utf8 scripts/check_failure_mode_index.py --scenario TR16_PARCEL_DELIVERED
python -X utf8 scripts/check_failure_mode_index.py --pending-ids
python -X utf8 scripts/check_failure_mode_index.py --require-complete
```

The JSONL is the exhaustive mapping; this guide selects at most two examples per category. Runtime and executed-probe references retain file, exact selector, scenario_id, trace_case/probe, ordering where present, and actual verdict. The eight earlier factual-sidecar probe definitions retain their specified expected judgments as design support only; no standalone executed result is distributed for those definitions. Standard authored reference anchors remain mandatory; accepted runtime alternatives may additionally clarify a comparison. Modified/verifier-only probes, authored answer probes, design-only support and runtime counterexamples remain distinct. None is an actual model failure. Context references include passing repeats, negative paths or unresolved wording checks only to identify scenario-level notes; they are not automatically evidence for every tag. --write-guide renders only existing mappings and never assigns tags.

Official contest score, local task/state/grounding correctness and optional factual-answer/efficiency diagnostics are separate. Semantic alternatives need not have equal fixed-reference tool-call scores. Empty-gold contest scoring requires empty submitted calls. A repeated-no-op rejection can be a local trace policy rather than a different final-state error.

## Taxonomy and worked examples

### wrong_target

Wrong entity, recipient, device, event or source object.

- [S1](../../artifacts/synthetic/failure_mode_index.jsonl#L50) — User: “Nhắn tới số 0907001206: Con đã về nhà an toàn.” The mother's supplied phone number must not be paired with the coworker's existing contact ID. (intended challenge; isolation_not_assessed)
  Authored contrast: both_consistent (/replays/18) versus mismatched_pair (/replays/43): change sms.send arguments: contact_id. Recorded final state differs from the accepted record.
  Evidence: [both_consistent](../../artifacts/synthetic/pilot_v1_replay/replay.json) `/replays/18` (accepted_authored_runtime_trace; pass); [mismatched_pair](../../artifacts/synthetic/pilot_v1_replay/replay.json) `/replays/43` (authored_runtime_counterexample; reject: recipient_consistency, inconsistent_observed_recipient_pair).
- [TR18_WORK_A](../../artifacts/synthetic/failure_mode_index.jsonl#L869) — User: “Tìm tiệm Sửa Khóa Tùng Chỉ gần chỗ làm của mình rồi lưu lại với nhãn Chỗ làm chìa.” The Bạch Đào shop is a real but wrong namesake. (intended challenge; isolation_not_assessed)
  Authored contrast: standard (/replays/0) versus distractor (/replays/3): change maps.search_place arguments: near; change maps.save_place arguments: place_id. Recorded final state differs from the accepted record.
  Evidence: [standard](../../artifacts/synthetic/train_wave_18_replay/replay.json) `/replays/0` (accepted_authored_runtime_trace; pass); [distractor](../../artifacts/synthetic/train_wave_18_replay/replay.json) `/replays/3` (authored_runtime_counterexample; reject: authorized_actions, state).

### wrong_tool

Operation differs from the requested action, such as send instead of save draft.

- [TR1_E_DRAFT](../../artifacts/synthetic/failure_mode_index.jsonl#L59) — User: “Chỉ lưu một email nháp, chưa gửi, tới dieu@laco.example.test, tiêu đề "Phiếu khay", nội dung nguyên văn "Tôi nhận bốn khay, không nhận thêm." Không đồng gửi ai.” Save-only email must create a draft not send it. (intended challenge; isolation_not_assessed)
  Authored contrast: standard [original] (/replays/0) versus wrong_delivery [original] (/replays/66): replace email.create_draft with email.send. Recorded final state differs from the accepted record.
  Evidence: [standard](../../artifacts/synthetic/train_wave_01_replay/replay.json) `/replays/0` (accepted_authored_runtime_trace; pass); [wrong_delivery](../../artifacts/synthetic/train_wave_01_replay/replay.json) `/replays/66` (authored_runtime_counterexample; reject: new_record_payload_or_count, authorized_operation_arguments_or_count).
- [TR1_E_SEND](../../artifacts/synthetic/failure_mode_index.jsonl#L60) — User: “Gửi ngay một email tới dieu@laco.example.test, tiêu đề "Phiếu khay", nội dung nguyên văn "Tôi nhận bốn khay, không nhận thêm." Không đồng gửi ai, không lưu thêm bản nháp.” Immediate-send control requires delivery rather than saving a draft. (control; isolation_not_assessed)
  Authored contrast: standard [original] (/replays/3) versus wrong_delivery [original] (/replays/67): replace email.send with email.create_draft. Recorded final state differs from the accepted record.
  Evidence: [standard](../../artifacts/synthetic/train_wave_01_replay/replay.json) `/replays/3` (accepted_authored_runtime_trace; pass); [wrong_delivery](../../artifacts/synthetic/train_wave_01_replay/replay.json) `/replays/67` (authored_runtime_counterexample; reject: new_record_payload_or_count, authorized_operation_arguments_or_count).

### unsupported_guessing

ID, value or argument lacks sufficient visible or observed evidence.

- [B02_E_B](../../artifacts/synthetic/failure_mode_index.jsonl#L1) — User: “Gửi email cho Đỗ Bảo Yến tới địa chỉ email của chị ấy trong danh bạ, với tiêu đề "Xác nhận vật tư", nội dung "Tôi chỉ nhận sáu thùng giấy, không nhận thêm."” Recipient email must be observed on Đỗ Bảo Yến contact before sending. (intended challenge; isolated_authored_counterexample)
  Authored contrast: standard (/replays/1) versus guess_B (/replays/13): remove contacts.search. Recorded final state matches the accepted record.
  Evidence: [standard](../../artifacts/synthetic/batch_02_replay/replay.json) `/replays/1` (accepted_authored_runtime_trace; pass); [guess_B](../../artifacts/synthetic/batch_02_replay/replay.json) `/replays/13` (authored_runtime_counterexample; reject: write_without_matching_source_observation).
- [H1](../../artifacts/synthetic/failure_mode_index.jsonl#L9) — User: “Hủy sự kiện vừa nói giúp tôi.” A title mentioned in history does not expose the event's opaque ID, which must come from the calendar lookup. (additional verifier check; isolated_authored_counterexample)
  Authored contrast: cancel (/replays/0) versus unobserved_cancel (/replays/14): remove calendar.list_events. Recorded final state matches the accepted record.
  Evidence: [cancel](../../artifacts/synthetic/batch_03_replay/replay.json) `/replays/0` (accepted_authored_runtime_trace; pass); [unobserved_cancel](../../artifacts/synthetic/batch_03_replay/replay.json) `/replays/14` (authored_runtime_counterexample; reject: ungrounded_cancel).

### missed_context

Relevant current time, timezone, location, profile or other context is ignored.

- [EX2_R_FUTURE](../../artifacts/synthetic/failure_mode_index.jsonl#L26) — User: “Đặt xe bốn chỗ đón tôi ở cổng Nhà Sợi đúng giờ bắt đầu sự kiện "Lắp khay mẫu" trong lịch, rồi đưa tôi đến Xưởng Nâu.” The observed 09:01 pickup is later than the 09:00 context clock, so the ride must retain its scheduled time. (intended challenge; isolation_not_assessed)
  Authored contrast: standard [original] (/replays/5) versus drop_future [original] (/replays/41): change ride_hailing.book arguments: schedule_time. Recorded final state differs from the accepted record.
  Evidence: [standard](../../artifacts/synthetic/expansion_batch_02_replay/replay.json) `/replays/5` (accepted_authored_runtime_trace; pass); [drop_future](../../artifacts/synthetic/expansion_batch_02_replay/replay.json) `/replays/41` (authored_runtime_counterexample; reject: schedule_key_presence, stored_schedule_instant, omitted_future_schedule).
- [TR20_CAL_TODAY_UTC](../../artifacts/synthetic/failure_mode_index.jsonl#L995) — User: “Lịch Kiểm nan hôm nay bắt đầu giờ nào? Cho mình giờ Việt Nam nhé.” The UTC context determines today's date while the answer clock remains explicitly Vietnamese. (control; design_support_only)
  Design support only: no counterexample is linked for this tag.
  Evidence: [standard](../../artifacts/synthetic/train_wave_20_replay/replay.json) `/replays/65` (accepted_authored_runtime_trace; pass).

### missed_history

Relevant earlier selection, correction, reference or fact is ignored.

- [H1](../../artifacts/synthetic/failure_mode_index.jsonl#L9) — User: “Hủy sự kiện vừa nói giúp tôi.” History selects Duyệt bản in thiệp rather than the competing Rà soát event. (intended challenge; isolation_not_assessed)
  Authored contrast: cancel (/replays/0) versus wrong_target (/replays/11): change calendar.cancel_event arguments: event_id. Recorded final state differs from the accepted record.
  Evidence: [cancel](../../artifacts/synthetic/batch_03_replay/replay.json) `/replays/0` (accepted_authored_runtime_trace; pass); [wrong_target](../../artifacts/synthetic/batch_03_replay/replay.json) `/replays/11` (authored_runtime_counterexample; reject: state_or_frame_mismatch, wrong_target_attempt).
- [TR20_CONTACT_OLD](../../artifacts/synthetic/failure_mode_index.jsonl#L975) — User: “Email của Trâm trước lần đổi vừa rồi là gì?” The requested pre-change email comes from the earlier contact-search result rather than the updated record. (intended challenge; design_support_only)
  Design support only: no counterexample is linked for this tag.
  Evidence: [standard](../../artifacts/synthetic/train_wave_20_replay/replay.json) `/replays/0` (accepted_authored_runtime_trace; pass).

### insufficient_information

Required information has not been resolved, including justified clarification.

- [B02_N_C](../../artifacts/synthetic/failure_mode_index.jsonl#L7) — User: “Tạo lời nhắc "Nộp phiếu giao hàng" đúng giờ bắt đầu sự kiện "Trao đổi mẫu gốm" trong lịch của tôi.” Arbitrary empty date window cannot prove requested title absent. (intended challenge; isolation_not_assessed)
  Authored contrast: standard (/replays/7) versus filtered_only (/replays/34): change calendar.list_events arguments: date_from, date_to. Recorded final state matches the accepted record.
  Evidence: [standard](../../artifacts/synthetic/batch_02_replay/replay.json) `/replays/7` (accepted_authored_runtime_trace; pass); [filtered_only](../../artifacts/synthetic/batch_02_replay/replay.json) `/replays/34` (authored_runtime_counterexample; reject: ask_without_required_absence_observation).
- [B02_E_C](../../artifacts/synthetic/failure_mode_index.jsonl#L3) — User: “Gửi email cho Đỗ Bảo Yến tới địa chỉ email của chị ấy trong danh bạ, với tiêu đề "Xác nhận vật tư", nội dung "Tôi chỉ nhận sáu thùng giấy, không nhận thêm."” Contact exists without email so ask email.send.to after lookup rather than write. (intended challenge; isolation_not_assessed)
  Authored contrast: standard (/replays/2) versus guess_C (/replays/32): replace sys.ask_missing_info with email.send. Recorded final state differs from the accepted record.
  Evidence: [standard](../../artifacts/synthetic/batch_02_replay/replay.json) `/replays/2` (accepted_authored_runtime_trace; pass); [guess_C](../../artifacts/synthetic/batch_02_replay/replay.json) `/replays/32` (authored_runtime_counterexample; reject: forbidden_state_change, new_record_count, ask_count, write_count, write_without_matching_source_observation).

### constraint_violation

Permissions, negation, scope, cardinality, order or preservation are violated.

- [N3](../../artifacts/synthetic/failure_mode_index.jsonl#L56) — User: “Chiều mai lúc 18 giờ, nhắc tôi bật máy hút bụi trong phòng làm việc.” This positive reminder must not be changed into a prohibition. (control; isolated_authored_counterexample)
  Authored contrast: standard (/replays/13) versus negation (/replays/55): change reminders.create arguments: content. Recorded final state differs from the accepted record.
  Evidence: [standard](../../artifacts/synthetic/pilot_v1_replay/replay.json) `/replays/13` (accepted_authored_runtime_trace; pass); [negation](../../artifacts/synthetic/pilot_v1_replay/replay.json) `/replays/55` (authored_runtime_counterexample; reject: reminder_content:reviewed_meaning_error).
- [TR16_APP_KEEP](../../artifacts/synthetic/failure_mode_index.jsonl#L849) — User: “Máy giặt hiên rảnh thì chạy quick giúp tôi. Đang chạy thì cứ để vậy.” The busy branch explicitly says leave it running and authorizes no quick attempt. (intended challenge; isolation_not_assessed)
  Authored contrast: standard (/replays/65) versus needless_attempt (/replays/67): add appliances.start_cycle. Recorded final state matches the accepted record.
  Evidence: [standard](../../artifacts/synthetic/train_wave_16_replay/replay.json) `/replays/65` (accepted_authored_runtime_trace; pass); [needless_attempt](../../artifacts/synthetic/train_wave_16_replay/replay.json) `/replays/67` (authored_runtime_counterexample; reject: branch).

### bad_recovery

Unjustified next step after error/no-op, or missing explicitly authorized recovery.

- [TR16_PARCEL_DELIVERED](../../artifacts/synthetic/failure_mode_index.jsonl#L828) — User: “Dời giờ giao MAN1601 sang 16 giờ ngày 6/10/2027, giờ Việt Nam. Nếu đã giao rồi thì nhắc tôi kiểm tra kiện MAN1601 ở quầy lúc 17 giờ cùng ngày.” After the delivered-parcel no-op, the authorized next step is a single reminder rather than another reschedule attempt. (intended challenge; isolation_not_assessed)
  Authored contrast: observed_noop (/replays/6) versus repeated_noop (/replays/10): add package_tracking.reschedule_delivery. Recorded final state matches the accepted record.
  Evidence: [observed_noop](../../artifacts/synthetic/train_wave_16_replay/replay.json) `/replays/6` (accepted_authored_runtime_trace; pass); [repeated_noop](../../artifacts/synthetic/train_wave_16_replay/replay.json) `/replays/10` (authored_runtime_counterexample; reject: branch).
- [TR13_APP_FAILED_RESTART](../../artifacts/synthetic/failure_mode_index.jsonl#L687) — User: “Chuyển máy vừa báo bận sang normal: dừng máy đó trước rồi chạy normal.” The newest instruction explicitly authorizes recovering from that busy outcome by stopping the dryer and starting normal. (intended challenge; isolation_not_assessed)
  Authored contrast: standard [original] (/replays/218) versus omitted [original] (/replays/222): remove appliances.stop, appliances.start_cycle. Recorded final state differs from the accepted record.
  Evidence: [standard](../../artifacts/synthetic/train_wave_13_replay/replay.json) `/replays/218` (accepted_authored_runtime_trace; pass); [omitted](../../artifacts/synthetic/train_wave_13_replay/replay.json) `/replays/222` (authored_runtime_counterexample; reject: authorized_order_or_writes, state).

### unsupported_answer

Factual answer unsupported by the relevant evidence, including wrong subject or omitted facts.

- [TR19_DEVICE_FAN_POWER](../../artifacts/synthetic/failure_mode_index.jsonl#L911) — User: “Quạt góc trong Phòng Dệt có đang bật không?” A question about the fan must not be answered as a claim about a light, even when both are on. (intended challenge; isolated_authored_answer_probe)
  Authored contrast: correct (/answer_probes/195) versus wrong_subject (/answer_probes/199): the authored answer changes from 'Đang bật' to 'Đèn đang bật', on the same standard trace.
  Evidence: [correct](../../artifacts/synthetic/train_wave_19_replay/replay.json) `/answer_probes/195` (authored_answer_probe; pass); [wrong_subject](../../artifacts/synthetic/train_wave_19_replay/replay.json) `/answer_probes/199` (authored_answer_probe; reject: wrong_subject).
- [TR19_TWO_CAL_REM](../../artifacts/synthetic/failure_mode_index.jsonl#L967) — User: “Soát bìa ở Phòng Lan ngày 6/1 bắt đầu mấy giờ, và nhắc Gom bìa ngày đó lúc nào?” Reporting only the event start omits the requested reminder time. (intended challenge; isolated_authored_answer_probe)
  Authored contrast: standard (/replays/276) versus incomplete (/answer_probes/501): the authored answer changes from 'Lịch 09:10, nhắc 08:30' to 'Lịch 09:10', on the same standard trace.
  Evidence: [standard](../../artifacts/synthetic/train_wave_19_replay/replay.json) `/replays/276` (accepted_authored_runtime_trace; pass); [incomplete](../../artifacts/synthetic/train_wave_19_replay/replay.json) `/answer_probes/501` (authored_answer_probe; reject: incomplete_answer).

## Overlap and unresolved questions

- Wrong recipient and unsupported recipient ID are different: S1 pairs two real inconsistent identities; B02_E_B guesses the correct address without reading it. Correct state does not cure missing source evidence.
- N1/N2 use clock context; H1/H2 need historical event selection. C1/C2 have history but current get_ride resolves the target, so mere history presence is not a missed_history tag.
- B02_N_C must inspect source absence and ask time; unrelated valid time is not evidence. In-utterance correction (T1 or EX3_T_B) is not conversation history.
- An error/no-op trace alone does not establish bad_recovery; observe-only alone does not establish unsupported_answer. TR16 delivered recovery and TR19 fan wrong-subject probes provide specific mechanisms.
- All 16 holds remain active: seven mail split holds, six Wave 17 independent reviews, B05_L_D and two Wave 11 chore policies. Mapping review never adjudicates these. All cases stay spec_only/non-exportable.
- Existing bounded source-witness limits for later review: TR9_NEWS_LOOK includes the queried publisher in its witness, and TR10_CLIMATE_FAN does not bind the requested room in its source witness. Their per-ID mappings describe the actual selected trace checks, not new defect reproductions. Inspect their design/oracle through --scenario before extending the fixture distribution.
- Observation-necessity questions remain distinct from hidden-value guessing: TR10_REM_COPYONCE and TR10_ALARM_COPYSILENT retain their recorded rules; explicit text supplied by the user does not become hidden merely because a local verifier requires a read. See each mapping for the relevant scope rather than inferring a policy change.
- Eight earlier factual-sidecar mappings use probe definitions/expected judgments as design support only. The 100 Wave 19 and 26 Wave 20 answer mappings link stored answer verdicts. An observe-only trace success alone is not factual-answer coverage.
- Finite text rules, design-only entries and entries without examined isolation remain limitations. Unknown plausible answers are not invented model failures. No new taxonomy category is introduced.

Exact pending IDs are individually_reviewed=false rows; --pending-ids prints them. Reviewed-but-unmapped rows must carry a case-specific reason. This index does not change gold, fixtures, verifiers or original holds. TR12_BANK_LOOK has a later currency-review restriction; the separate 29-case review remains authoritative. Current source copies preserve recorded evidence; no new model failure is claimed.
