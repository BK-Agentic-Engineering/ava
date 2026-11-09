# First 1,000 scenarios: completed implementor inspection

All **1,000 unique IDs now have individual implementor judgments** in [per_sample_review.jsonl](../../artifacts/synthetic/quality_audit_1000/per_sample_review.jsonl). This completes direct inspection, not independent Vietnamese adjudication, harness acceptance or training approval.

The resumed starting checkpoint reconciled to **133 inspected/acceptable + 13 inspected/pending + 854 awaiting direct inspection = 1,000**. The original judgments were retained. The remaining 854 were reviewed individually, reading visible request/context/rendered history/permissions before comparing fixture, observations, reference effect or answer, and verifier. Read-only helpers assembled materials; they did not assign judgments. Completed families were saved to the ledger before continuing. Repeated requests have individual notes explaining source, context, target or effect contrasts. No uninspected records remain.

| Dimension | Final checkpoint |
| --- | --- |
| Direct implementor inspection | 1,000 completed; **0 awaiting inspection** |
| Content acceptable within documented scope | **984** |
| Inspected, awaiting semantic/policy/split adjudication | **16** |
| Content disposition needs repair | 0 currently assigned; this is not a proof of complete oracles |
| Oracle/fixture status | 23 IDs have documented repairs; 3 have explicit pending policy; 974 retain finite-fixture/equivalence limitations |
| Independent human adjudication | Not established by this audit; six Wave 17 responses remain pending |
| Team harness acceptance | Not established for any of the 1,000 by local replay |
| Design/export | All 1,000 **spec_only**, non-exportable; actual eligibility **0** |

The three new adjudication holds are **B05_L_D**, **TR11_CHORE_PAIR**, and **TR11_CHORE_EXPLICIT**. The first needs a decision on forbidding even a harmless conditional read when the write capability is unavailable. The latter two need a decision on a read-confirmed already-satisfied assignment: may the agent preserve it, or must it repeat the assignment write? PAIR contains one real reassignment plus one already-correct assignment. Their requests, gold and evidence were not silently changed. These are additional holds, not reversals of the original 146 judgments.

## Findings and repairs

### 1. Context-local calendar dates and complete retrieval

Affected IDs: TR20_CAL_TODAY_EVENING, TR20_CAL_TODAY_MORNING, TR20_CAL_TODAY_UTC, TR20_CAL_TOMORROW, TR20_CAL_TODAY_END, TR20_CAL_TODAY_ROOM, TR20_CAL_NOTE_TODAY. TR20_CAL_HISTORICAL asks an absolute historical creation result and does not use this selection path.

The old verifier derived today in the context timezone but compared the event's raw timestamp prefix. An altered-response count probe at `2028-02-11T01:00:00+07:00` returned zero for February 10 UTC although that event belongs to that day. The repaired selector converts each aware start timestamp to `context.timezone` before comparing dates. A naive or unreadable timestamp cannot establish the requested day. The requested answer display remains Vietnam time in the start/end questions; selection timezone and display timezone have different roles.

Actual pinned SDK execution with an independently authored temporary boundary fixture confirmed the separate retrieval problem: `calendar.list_events(date_from="2028-02-10", date_to="2028-02-10")` omits that event because the SDK ranges use raw date prefixes. The same unfiltered read returns it. The seven standards now list without date limits; their existing alternatives use an inclusive day±2 raw-date envelope and then filter by context-local date. The resumed repair accepts tighter provably sufficient bounds too: compute the requested local midnight and next midnight in UTC, then the raw-date envelope reachable with legal Python ISO offsets strictly between −24 and +24 hours. For February 10 UTC this is **February 9–11 inclusive**, rather than requiring day±2. The SDK does not perform timezone conversion for the caller. A range ending February 10 can omit a valid +07 boundary event and is rejected. Requests, contexts, fixture states and expected answers were preserved.

Source: pinned release v3.2.0, catalog/schema 2.7.0, allowlisted `zaic_tools/apps/calendar.py` and the existing base/runtime helpers. The actual SDK boundary session is a regression diagnostic, **not a new dataset scenario**. Altered-response tests are separately labeled and are not SDK observations.

### 2. A valid current-contact lookup was rejected

Affected IDs: TR20_CONTACT_CURRENT, TR20_CONTACT_BOTH, TR20_CONTACT_CURRENT_PHONE, TR20_CONTACT_CURRENT_CHANGED, TR20_CONTACT_NOTE_CURRENT, TR20_CONTACT_NOTE_BOTH.

Their permissions include `contacts.get`, and their rendered history supplies the target contact ID. The old search-only fact path returned `missing` for a successful current get. Actual SDK execution confirms `contacts.get(contact_id="w20_tram")` returns the same `contacts` collection shape, containing the requested named record and current email. The Wave 20 wrapper now recognizes that read as equivalent evidence, retaining name-based unique-ID selection and successful-response checks. Raw recorded call names/results are not rewritten. Historical old-value obligations still use their historical source and are not satisfied by a current get.

### 3. Meaning-preserving note formatting was too strict

Affected IDs: TR20_CONTACT_NOTE_OLD, TR20_CONTACT_NOTE_CURRENT, TR20_CONTACT_NOTE_BOTH, TR20_BANK_NOTE_RECEIPT, TR20_BANK_NOTE_LEDGER, TR20_CAL_NOTE_TODAY.

An altered-response/state probe for NOTE_OLD copied its valid trace and changed only content from `tram.cu@lat.example.test` to `Email cũ: tram.cu@lat.example.test`. The old verifier rejected it as `authorized_write` and `state`, although the request did not require a literal bare-email template. Four explicitly reviewed formats now have actual SDK alternative paths: a labeled old email, labeled current email, reversed correctly labeled old/current lines, and a labeled room. The two existing dotted-money formats remain valid.

Other nonempty, unrecognized note prose with the correct destination/title is now **unresolved**, requiring content review. It is not automatically accepted or rejected as factually wrong from string inequality. Required observations still precede the write; the full state frame is checked using the actual submitted content. Empty content, wrong destination/title, extra writes and damage to existing state are still failures. This is a small Wave 20 rule, not a general Vietnamese parser. Reviewed formats do not exhaust all valid prose.

## Earlier checkpoint reconciliation and validation

Pre-repair canonical evidence was preserved once at replay.pre_audit.json (excluded local source: `../../artifacts/synthetic/train_wave_20_replay/replay.pre_audit.json`; see FILE_SELECTION.json). The structured reconciliation is [repair_reconciliation.json](../../artifacts/synthetic/quality_audit_1000/repair_reconciliation.json).

- 80 prior runtime rows: 59 unchanged; 21 differ only in `calls` (calendar lookup arguments and returned scope).
- Every prior final state, observed-fact verdict and answer verdict is unchanged.
- Four new `equivalent_note` runtime paths make 84 rows: 58 accepted and 26 intended failures. All 26 standards pass; historical execution remains 68 calls.
- Existing 104 authored-answer probes and 26 evidence-ablation probes remain unchanged: 52 overall pass, 52 fail, 26 unresolved. These are not model outputs.
- Full parsed fresh-process output matches the updated canonical evidence after excluding only the declared `created_utc` and `replay_wall_seconds`. Inventory/provenance/visible inputs/post-history states/answer probes are unchanged; the status count reflects the four added paths.
- At that earlier checkpoint, fourteen focused Wave 20 tests passed, including actual-SDK raw-date omission/current get, altered-response local-day conversion, unchanged display timestamp, ambiguity, reviewed note variants, unfamiliar prose review and collateral-state rejection.
- At that earlier checkpoint, all **194 replay regression tests** passed in 113.485 seconds; all **13 factual-answer/trace-adapter tests** also passed (207 applicable tests total). The earlier replay-suite run passed 193 tests before the final unfamiliar-note-prose regression was added; the complete suite was rerun after that change. These are local regression results, not 1,000 semantic approvals.

Reproduce locally from the workspace:

```powershell
python -X utf8 scripts/check_synthetic_quality_audit.py
python -X utf8 -m unittest discover -s tests -p "test_replay_*.py"
python -X utf8 -m unittest discover -s tests -p "test_factual*.py"
python -X utf8 scripts/replay_train_wave_20.py --output "$env:TEMP/lifemate_wave20_audit_replay.json"
```

The replay command uses only the existing pinned SDK/catalog source in `D:/Downloads/train+public_test.zip`, fresh local sessions and synthetic fixtures. The table checker validates IDs, references and status consistency; it **does not perform or assign semantic review**. Do not use it to promote pending rows.

## Coverage and split assessment

Collection integrity checks confirm 1,000 IDs, 108 WORLDs, 31 named lineages, valid references/fixture variants and split ancestry. Intended splits remain train942/dev58/test0; WORLDs train90/dev18. The graph has five connected train ancestry components and ten dev components, rather than 1,000 independent source families. Every design remains `spec_only` and non-exportable.

Outcomes remain execute715, observe-only239, ask_missing31, out_of_scope15. Current standard evidence has nonempty history in 230 cases; 120 contain rendered tool results. The coverage script finds 137 normalized-request repeat groups covering 343 records, with no exact normalized-request group crossing train/dev. Those are mechanical counts: source-value, context and target controls can intentionally share wording. They neither prove 343 accidental duplicates nor rule out cross-split semantic overlap. The inspected Wave 19/20 field/count/target controls are documented individually; a second queried field or app is not automatically an independent decision mechanism.

The reviewed Wave 19 parcel contrast separates target-carrier status from distractor status. Shopping cases distinguish rows from quantity totals; finance cases rely on the SDK's default unpaid-bill scope, with a type-filtered read valid for electricity count but insufficient for all bill types. Two-fact questions may be supported by one complete response. Their same-run evidence and fixed-state requirements are defensible within those fixtures. Answer rules are finite whole-answer patterns, not a validated Vietnamese semantic evaluator; unfamiliar plausible responses remain reviewable. Technical labels such as `cool`/`normal`, clipped alarm wording and numeric verbalizations still need broader language assessment.

**Mail disposition recommendation:** retain the existing seven-case quarantine from prospective train export, without relabeling historical splits or deleting evidence. Direct inspection confirms B02_E_A and TR1_E_SEND share the supplied-address/subject/body direct-send structure and a near-template negated quantity body. Extra preservation fixtures do not make that an independent split decision. DRAFT, DRAFT_CC, SEND_CC and TWO_DRAFTS are linked disposition/recipient/cardinality controls. REPLY and REPLY_OTHER add real observed-thread linkage and are not individually proven direct-send duplicates. Keep the connected family together for adjudication instead of clearing selected controls based on tool success. No external WORLD currently declares this mail WORLD/lineage or one of its scenarios as a parent; that is a metadata finding, not proof of all semantic independence. Preserve all seven holds until the team resolves disposition.

**Wave 17:** all six cases were inspected against their own calendar response and trace. The duration-preserving shift is coherent, and REPHRASE explicitly requires it, but the independent reader checkpoint remains pending. Keep sheet/key/judgments unchanged, present items individually with explicit-duration control last as proposed, and distinguish an incomplete answer from a reasoned ambiguity interpretation. Implementor inspection cannot fill that independent evidence gap.

## Practical readiness and remaining decisions

| Use | What this checkpoint supports | Remaining gate |
| --- | --- | --- |
| Local debugging | Pinned synthetic replay and explicit negative/answer probes; repaired Wave 20 boundaries and alternatives. | Broader equivalent traces/text, independent judgments and the three explicit policy decisions; reference traces do not exhaust valid behavior. Passing a reference trace is not completeness of an oracle. |
| Training preparation | Auditable provenance, fixed intended ancestry, per-ID review progress. | Seven mail holds, independent language/policy adjudication, Tài's harness feedback and approved serialization. Actual export eligibility remains zero. |
| Evaluation | Designed controls can diagnose specific mechanisms. | No independent test split, representativeness, calibrated evaluator or model experiments established. Do not randomly reshuffle existing descendants into test. |

No IDs await direct inspection. The next decisions are the 16 explicit holds, independent review and team integration, followed by per-sample release eligibility. A clear request and correct reference effect do not prove that a finite verifier accepts every legitimate answer or trace.

No new scenarios, held-out records, independent reviewer answers, model/API calls, audio, organizer sample/environment access, training export or status promotion occurred. Authoring/audit wall time was not measured as a complete interval; test/replay durations are diagnostic runtimes only.

## Resumed repairs and evidence

| Impact | Affected IDs | Reproduction, repair and limits |
| --- | --- | --- |
| False zero from absent evidence | TR20_CAL_TOMORROW; shared calendar path also used by TR20_CAL_TODAY_EVENING, TR20_CAL_TODAY_MORNING, TR20_CAL_TODAY_UTC, TR20_CAL_TODAY_END, TR20_CAL_TODAY_ROOM, TR20_CAL_NOTE_TODAY | Before repair `ok:true` without `events` supported zero. Require an actual list of event objects; missing/null/dict/string/malformed members cannot establish zero. A successful complete `events:[]` can. Paired modified-response regressions distinguish them. Request judgments are unchanged. |
| False rejection of sufficient retrieval | Same seven IDs, specifically TR20_CAL_TODAY_UTC | Before repair February9–11 was rejected despite being sufficient for February10 UTC. Derive bounds from local day/timezone and raw-prefix filtering as above. Actual SDK synthetic fixture contains February11 01:00+07 and February9 23:30−01, both belonging to February10 UTC; inclusive9–11 retrieves both, truncated9–10 omits the late boundary. Modified-response probes are separately labeled. Broad standard stays valid. |
| Missing collection falsely proves no matching event | B02_N_C | Reproduced on copied saved standard. Batch02 now rejects missing/malformed events; explicit empty list remains sufficient. Read all eight siblings and calendar verifier callers; no fixture, request or canonical replay changed. |
| Equivalent observed default rejected | TR10_ROBOT_INHERIT, TR10_ROBOT_RESTARTALL | Copied saved traces with explicit mode=mop were rejected only as authorized_actions despite observed stored mop and unchanged effect. Local Wave10 wrapper accepts that explicit observed default before start. Wrong vacuum and unobserved mop still reject. Wave02 parent already supports explicit defaults; no shared global normalization change. These are modified-call probes, not new SDK paths. |
| Future-dated logged security alerts | All 12 TR12_ALERT_* IDs | Existing alerts June12 08:00–08:10 were ahead of June10 09:00 context. Changed only these clocks to June12 09:00+07. Alert records, requests, gold and all399 runtime rows unchanged. Regression checks every alert timestamp against its case clock. |
| Claimed history hidden in oracle | TR14_PLAN_CORRECT | Existing authored user turn about originally scheduling Kiểm Mành was under oracle_draft.history while visible history was empty. Moved that exact turn into agent_visible.history. Latest self-contained task request/gold unchanged; all218 runtime rows unchanged. Test checks visible history and removal from oracle. |

`observe_fact` relative-day logic has one Wave20 verifier caller; historical absolute calendar facts bypass it. The seven relative IDs above exhaust its design users. General Wave19 fact extraction was not changed. Batch02 uses its own verifier. Wave10 wrapper is called by its runner and focused tests; its parent Wave02 has separate default-mode handling. No other caller inherits the new Wave10 exception.

Pre-repair Wave12/14 evidence is preserved once as each run's `replay.pre_audit.json`. Current canonical files were replaced only after reconciliation and a second fresh process. [resumed_repair_reconciliation.json](../../artifacts/synthetic/quality_audit_1000/resumed_repair_reconciliation.json) records the comparisons:

- Wave20: all **84** canonical runtime paths unchanged, **58 accepted / 26 rejected**; all26 standards pass. No new runtime rows. Existing authored-answer/ablation checks remain separate and unchanged.
- Batch02: all46 rows unchanged (13 accepted runtime,32 rejected runtime,one review probe), excluding only declared timing fields.
- Wave10: all430 runtime rows unchanged (169 accepted/261 rejected); canonical evidence preserved. Only temporary replay's global inventory reflects the now-complete collection.
- Wave12: all399 runtime rows unchanged (141 accepted/258 rejected). Nonvolatile changes are twelve visible clocks, their fixture metadata clocks, and global inventory refresh.
- Wave14: all218 runtime rows unchanged (87 accepted/131 rejected). Nonvolatile changes are one visible history and global inventory refresh.
- Independent fresh-process pairs for Wave10/12/14 and Wave20 match complete parsed output after excluding only `created_utc` and `replay_wall_seconds`. Inventory refresh in old Wave12/14 evidence is reported, not hidden by the timing exclusion.

The resumed full replay regression suite passed **196 tests** in 748.133 seconds before the final three Wave10/12/14 regressions were added. Post-repair focused/neighbor checks passed: absence1; Wave10 twelve; Wave12 ten; Wave14 seven; Wave20 sixteen; Wave19 seventeen; Wave13 eleven; Wave16 seven; factual/adapter thirteen. These total94 passing checks. Additional neighboring Wave02 twelve and Wave18 ten checks pass, giving **116 post-repair focused/neighbor tests**. The full suite was not repeated after these three localized tests/repairs; the affected and neighboring suites were rerun. Tests include actual local SDK boundary execution; answer and modified-response probes are not model observations. No claim of model quality follows.

## Collection-wide review conclusions

Inspection supports the recorded effects/answers within the authored scope for984 cases, while16 require the specific decisions above or the preserved original holds. It does not certify universal semantic grading. Older observe-only tool verifiers often establish reads/state preservation without binding final answer text. The factual trace adapter currently binds three designated cases (TR10_APPL_LOOK, TR13_CONTACT_INSPECT, TR16_APP_KEEP); sidecar probes and Waves19/20 answer checks are separate coverage. Do not claim all239 observe-only cases have calibrated same-run answer evaluation.

Legitimate contrasts include changed visible profile versus historical address (TR15_PICKUP_PROFILE/CORRECTION/PROFILE_CORRECTION), historical workout type plus later duration (TR15_FITNESS_FROMTWO), default mode versus current robot job (TR10_ROBOT_INHERIT), delivered no-op versus successful reschedule (TR16_PARCEL_DELIVERED/SUCCESS/ATTEMPT), and work/home absence-gated search (TR16_MAP_WORK/HOME/NONE). They isolate different authorized effects or evidence, rather than independent language samples. Explicit controls and rephrasings contribute robustness checks, not one new mechanism each.

Finite fixture-specific witnesses sometimes include extra expected values beyond the user-supplied selector. No universal counterfactual-selector safety is inferred from their authored passing paths. Literal note/reminder/task text comparisons in older waves have limited wording coverage; the per-ID notes retain that limitation. Unfamiliar plausible wording needs review rather than an inferred factual failure. Wave19/20 scoped answer rules remain finite, not a Vietnamese semantic parser.

Actual runtime inspection also limits alternative-path claims: phone.recent_calls ignores the authored missed_only argument and TV guide ignores date; changed arguments returning the same complete evidence are reproducibility repeats, not proof of filtered retrieval. A broad actual response can still establish the needed fact when uniquely selected. Entity names, apps and repeated fixtures are not independence. Five train ancestry components, no held-out split and the seven mail holds prevent claims of clean independent evaluation or general training readiness.

The read-only coverage check reconciles **4,672 combined trace/check rows, 2,142 passes**, including separately marked verifier probes; these are not 4,672 scenarios or model executions. All 1,000 IDs,108 WORLDs,31 lineages, fixture variants, contrast links and ancestry resolve. No existing development descendant moved to train. No exact normalized-request group crosses splits, but semantic-template overlap still requires the mail adjudication and future split review.

Exact local commands (workspace root):

```powershell
python -X utf8 scripts/check_synthetic_quality_audit.py
python -X utf8 scripts/audit_synthetic_coverage.py
python -X utf8 -m unittest discover -s tests -p "test_replay_train_wave_20.py"
python -X utf8 -m unittest discover -s tests -p "test_audit_calendar_absence.py"
python -X utf8 -m unittest discover -s tests -p "test_replay_train_wave_10.py"
python -X utf8 -m unittest discover -s tests -p "test_replay_train_wave_12.py"
python -X utf8 -m unittest discover -s tests -p "test_replay_train_wave_14.py"
python -X utf8 scripts/replay_train_wave_20.py --output "$env:TEMP/lifemate_wave20_audit_replay.json"
```

Other repaired evidence reproduces with the corresponding `replay_train_wave_12.py` / `replay_train_wave_14.py` command and a temporary `--output`. Keep canonical evidence intact during rechecks. The audit's complete elapsed wall time was not measured; replay/test durations are separate diagnostics. No external constraint left any direct inspection outstanding.

The exact clock-repair IDs are: TR12_ALERT_ACK, TR12_ALERT_ARM, TR12_ALERT_BOTH, TR12_ALERT_ORDER, TR12_ALERT_VERIFY, TR12_ALERT_IFACK, TR12_ALERT_IFOPEN, TR12_ALERT_TWO, TR12_ALERT_OFFAFTER, TR12_ALERT_OFF, TR12_ALERT_OTHER, TR12_ALERT_LOOK.

Changed implementation files in this resumed iteration: `scripts/replay_train_wave_20.py`, `scripts/replay_batch02.py`, `scripts/replay_train_wave_10.py`, and the read-only `scripts/check_synthetic_quality_audit.py`; focused tests in `test_replay_train_wave_20.py`, `test_audit_calendar_absence.py`, `test_replay_train_wave_10.py`, `test_replay_train_wave_12.py`, `test_replay_train_wave_14.py`. Design changes are limited to Wave12 clocks and Wave14 history placement. Only Wave12/14 canonical evidence was refreshed in this resumed iteration, with one prior copy each preserved. The ledger, this report, Wave10/12/14/20 handoffs, coverage status and expansion-plan audit status were updated. No scenario ID/split/export status changed.
