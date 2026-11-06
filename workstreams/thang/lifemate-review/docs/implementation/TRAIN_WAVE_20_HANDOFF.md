# Train Wave 20 checkpoint

## Quality-audit correction — 2026-11-06

The [ongoing 1,000-case audit](SYNTHETIC_1000_QUALITY_AUDIT.md) repaired context-local event-day conversion and complete date retrieval for the seven relative-day cases. Their standards now use unfiltered calendar reads; alternatives use a day±2 raw-date envelope before timezone-aware filtering. Selection follows context timezone, while explicitly requested answer clocks remain Vietnamese. Current contact facts also accept permitted `contacts.get` evidence. Four reviewed note-content variants were added; other unrecognized nonempty note prose requires review rather than automatic string-based rejection, with full state preservation still checked.

Current evidence has **84 runtime paths: 58 accepts / 26 intended failures**, including 26 standards and six equivalent-note paths. The 68 historical calls and 130 existing authored-answer/evidence probes are unchanged. Against the preserved `replay.pre_audit.json`, 59 earlier rows are unchanged and 21 change only calendar calls/results; all earlier final states and verdicts match. Four note-format paths are new checks, not new scenarios. Fourteen focused Wave 20 tests pass; complete fresh-process evidence reproduces excluding only the two declared timing fields. Later sections describe the original 80-row authoring checkpoint. No status/export promotion or completion of the full semantic audit is implied.

## Family choice before authoring

| Family | Gap and parents | Rule, shortcut and contrast |
| --- | --- | --- |
| Historical contact versus current record | Wave 13 distinguishes overwritten values and Wave 19 answers current facts. Inherit TR13_CONTACT_INSPECT and TR13_CONTACT_CURRENT_CHECK. | Requested historical moment supplies old contact facts. A fresh read supplies explicitly requested current facts. Mixed questions require both. Blindly choosing the last returned email fails the historical control. Changed historical or current values must affect only the appropriate answer or authorized note. |
| Transfer receipt versus current ledger | Wave 13 repeats a successful transfer and Wave 19 answers balances. Inherit financial-history and bank-answer ancestry. | A historical successful receipt establishes its own amount and post-transfer balance. A second completed transfer changes current balance. Questions about the first payment, latest payment, total debits and present funds require different evidence. Do not equate current funds with the first receipt. |
| Relative calendar scope after historical writes | Wave 15 copies a historical clock into a new event. Wave 19 asks absolute-date calendar questions. Inherit date-context and executed-history planning ancestry. | Today/tomorrow scope comes from current_time and timezone, while the already created event timestamps remain absolute. A timezone/context-only contrast changes which records answer the same question. Current calendar lookup is required for current schedule facts. Notes must preserve the source event and earlier records. |

The wave will use 26 new IDs only if each has a named decision, source contrast or ordinary component control. Final-answer probes remain separate from SDK evidence. All train ancestry and non-exportable status will be retained.

## Scope and worked contrasts

The baseline audit confirmed 974 scenarios, 105 WORLDs, 31 named lineages and 15 connected ancestry components. There were 219 observe-only cases and seven held mail-family cases. Wave 20 adds exactly 26 new IDs in three inherited train WORLDs. It upgrades zero earlier cases. The count is supported by distinct requested source/value/effect decisions and matched controls. These are three inherited families, not 26 independent mechanisms.

| Family | Cases | Observe-only | Execute | Main controls |
| --- | ---: | ---: | ---: | --- |
| Contact snapshot versus current | 10 | 7 | 3 | Old/current email, old/current phone, both moments, changed old source, changed update, notes from one/both moments. |
| Transfer receipt versus ledger | 8 | 6 | 2 | First/last transfer, receipt balance/current balance, total debits, mixed comparison and notes. |
| Calendar date after history | 8 | 7 | 1 | Before/after midnight, timezone-only contrast, tomorrow absence, end/location, note and historical absolute start. |
| **Total** | **26** | **20** | **6** | Three WORLDs and no new named roots. |

**Contact.** The historical search actually returns tram.cu@lat.example.test before the SDK updates the same record to tram.moi@lat.example.test. OLD asks for the earlier value and needs no latest read. CURRENT explicitly asks to look again and needs a latest contact search. BOTH requires the old result and the new read. OLD_CHANGED alters only the pre-history email, preserves the latest request and post-history state, and changes the answer. CURRENT_CHANGED changes the authorized historical update text and email argument. Its observed update and post-history email also change, so it is not a fixed-state history-only pair. The phone cases are ordinary controls for another requested field, not a new independent mechanism. Notes preserve the contact and existing note.

**Bank.** Actual history reads Quỹ Lá at 900000 đồng and makes two authorized transfers of 120000 and 50000 đồng. The first receipt says 780000 remains, the second 730000. RECEIPT_BALANCE answers 780000 from the first response. CURRENT_BALANCE must read the current account and answers 730000. BALANCE_COMPARE requires both. The ledger sum is -170000 in the API's signed debit convention, rendered as 170000 đồng already deducted. The named funding account is resolved from a visible balance observation before joining transaction account_id. No private account ID can replace that observation. Whole-ledger and observed-account-filtered reads are valid alternatives. Two note cases accept equivalent 120.000/170.000 đồng formatting while preserving all other records.

**Calendar.** Historical SDK calls create Kiểm nan at 09:00 on February 11 in Phòng Tằm and at 20:00 on February 10 in Phòng Sậy. The calls intentionally return IDs in creation order, not timestamp order. TODAY_EVENING and TODAY_MORNING share the same request, history and post-history WORLD. Only current_time changes from February 10 at 23:50 to February 11 at 00:10 in Vietnam. The answer changes from 20:00 to 09:00. TODAY_UTC keeps the latter current_time string but changes only timezone to UTC, where the current day is still February 10. It answers 20:00 in the explicitly requested Vietnamese clock. Historical event timestamps are not reinterpreted as relative dates. TOMORROW observes the full relevant day before answering zero named events. A returned unrelated event on that date does not count. HISTORICAL reads the first actual creation result and preserves its absolute day/time.

## Local implementation and evidence

The runner reuses Wave 13 history execution, Wave 19 entity/field/scoped aggregation, the existing finite answer normalizer/rules, and collection integrity/ancestry checks. The Wave 20 wrapper adds historical-position source selection, an observed named-account join, current date/timezone derivation, and authorized note-effect checks. Shared helpers and earlier artifacts were preserved. The catalog/schema is 2.7.0 and runtime release v3.2.0. Only selected train SDK source and the catalog are read from the organizer archive.

Each scenario executes its own authorized historical calls in a fresh local SDK session at the declared history_time. Actual paired results become visible history, and the latest session starts from that resulting WORLD with its own clock and empty call log. Every historical and latest tool call and result is preserved. There are 68 historical calls, separately from 80 latest-turn runtime traces. The 80 paths comprise 26 standards, 26 sufficient alternatives, two equivalent note formats and 26 successful-but-wrong note creations. Task failure is decided by the oracle, not by SDK success. For an observe-only question, creating the unrelated note is unauthorized. For an execute case, writing the wrong note fails requested fields/state preservation.

Evidence-dependent facts must precede the consuming write. A fresh read is required when the request asks for the current record. A correct old value in a returned historical result remains usable without an unnecessary read. Relative-day entity selection uses title and the day derived from visible current_time/timezone; it does not use the requested room or clock as its own selector. Answer content is checked against values resolved from that run. Changed source values route to unresolved rather than being replaced with canonical facts.

Final texts are authored probes. There are 104 answer probes, two accepted, one wrong and one manual-review formulation per case. They produce 52 pass, 26 fail and 26 unresolved judgments. The further 26 remove-observations probes alter in-memory visible history and latest evidence and fail with unresolved answer content. Two extra unit-test mutations check ambiguous calendar identity and changed observed location. None is an SDK result or a model-generated answer. The canonical replays keep these source types distinct. The status probe_verdicts combines the 104 answer probes and 26 explicitly labeled evidence ablations, so its 52 overall failures are not a count of wrong-answer texts alone.

## Validation and repairs

All 26 standards and all 80 runtime paths passed their expected checks in fresh sessions. The nine Wave 20 tests passed, along with 17 Wave 19 and 13 factual pilot/adapter tests, 39 relevant tests total. The complete parsed result reproduced in a fresh process after excluding only created_utc and replay_wall_seconds. The canonical replay took 8.13 seconds and the first independent replay 6.49 seconds. A final rerun after contrast-reference validation also matched. Language examples ending in a period initially missed the existing normalizer's punctuation stripping. The authored whole-answer patterns were corrected before canonical recording. Ledger identity handling was explicitly grounded in visible account-name observations before accepting a sum.

Cross-file uniqueness, references, lineage consistency, split ancestry and variants passed the existing collection checks. New exact request strings do not match earlier records. This is only an exact-text check. The nearest semantic overlaps are declared train parents and are recorded above. Ordinary field/effect controls are not claimed as independent diversity. The changed-old-email and two calendar context comparisons are checked in regression tests, including identical post-history state where claimed. The new fixtures make no unsupported claims about nearest places, real banking services or calendar availability outside the response scope.

## Verified checkpoint

| Intended split | Scenarios | WORLDs | Named lineages | Connected ancestry components |
| --- | ---: | ---: | ---: | ---: |
| Train | 942 | 90 | 19 | 5 |
| Dev | 58 | 18 | 12 | 10 |
| Test | 0 | 0 | 0 | 0 |
| **Total** | **1,000** | **108** | **31** | **15** |

Collection outcomes are 715 execute, 239 observe-only, 31 ask_missing and 15 out_of_scope. The seven mail-family holds remain in intended train. The prospective pool excluding them is 935, with actual eligibility still zero. Every new case remains spec_only and non-exportable. Reaching 1,000 is an inventory checkpoint. Independent semantic/gold review, Jaz acceptance and approved training serialization are outstanding.

## Next iteration full-collection audit checklist

- [ ] Review Vietnamese request/history/context together with factual or effect gold. Check ambiguous references, implicit assumptions, negation, subject/value/unit errors and whether the answer obligation is explicit. Preserve original reader responses and distinguish incompleteness from a reasoned ambiguity judgment.
- [ ] Validate every fixture/oracle against the pinned SDK. Reconcile pre/post-history state and clocks, real response fields, unique selectors, queried values separate from identity, complete-scope evidence, no-op/error meaning, grounding and collateral preservation.
- [ ] Check valid alternative traces and equivalent text/time/number representations. Inspect false rejections as well as false accepts. Separate reproducibility repeats, actual SDK negatives, authored text and modified-response probes.
- [ ] Assess diversity by underlying decision family, ordinary controls, hard contrasts and language constructions. Do not treat count, names, field substitutions or app breadth as independent mechanism coverage.
- [ ] Review exact and semantic duplicates, shared templates, ancestry components and split boundaries. Adjudicate the seven TRAIN_MAIL_DISPOSITION_01 holds. Do not obtain a test split by resampling existing descendants.
- [ ] Record per-sample eligibility with concrete reason and evidence. Check independently adjudicated gold, replay correctness, unresolved policies, provenance, harness rendering and serialization readiness before any status/export change.

Outstanding items are the pending Wave 17 independent responses and proposed administration order, the seven mail-family split holds, finite Vietnamese answer rules and 26 new unresolved language probes, the absence of new held-out evaluation, Tài's three-case Jaz feedback, and Tú's target format/loss masking. Earlier conditional/mixed-capability and clarification-policy limits remain part of the audit. This iteration performs no status promotion or audit adjudication.

## Reproduction

Run from the workspace root:

```powershell
python -X utf8 scripts/replay_train_wave_20.py
python -X utf8 scripts/replay_train_wave_20.py --output artifacts/synthetic/train_wave_20_replay/recheck.json
python -m unittest discover -s tests -p test_replay_train_wave_20.py
python -m unittest discover -s tests -p test_replay_train_wave_19.py
python -m unittest discover -s tests -p 'test_factual*.py'
python -X utf8 scripts/audit_synthetic_coverage.py
```

[Design](../../data/synthetic/design/train_wave_20.yaml) · [Runner/verifier](../../scripts/replay_train_wave_20.py) · [Evidence](../../artifacts/synthetic/train_wave_20_replay/replay.json) · [Tests](../../tests/test_replay_train_wave_20.py)

## Resumed 1,000-case audit

Resumed audit repair: missing/malformed events can no longer prove zero; explicit complete events:[] still can. Relative-day bounds now derive from local midnight/next midnight and legal ISO offsets under the SDK raw-prefix date filter. February9–11 inclusive is sufficient for February10 UTC; a truncated9–10 range is not. Seven calendar IDs share this path; HISTORICAL does not. Sixteen focused tests pass, including actual SDK opposite-offset boundary fixtures and separately labeled modified-response probes. All84 canonical paths and existing answer probes reproduce unchanged after only declared timing exclusions. See SYNTHETIC_1000_QUALITY_AUDIT.md for completed per-ID inspection and policy holds.
