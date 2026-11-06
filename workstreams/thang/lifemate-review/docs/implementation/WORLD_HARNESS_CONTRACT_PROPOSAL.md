# LifeMate harness contract proposal

**Status: lifemate-harness-proposal-0.1, proposed for Tài and Tú.** Scope is text-only replay of independently authored synthetic cases with the pinned train catalog and local runtime from release v3.2.0, schema 2.7.0. This proposal does not define the team harness, training serialization or official evaluation. [Organizer interface review](ORGANIZER_DATASET_STRUCTURE_REVIEW.md)

## Current setup: authorized external SDK

Use the [curated three-case workflow](../../integration/three_cases/README.md) from the [package root](../../README.md). The portable source/evidence package does **not** distribute organizer SDK modules or catalog/schema definitions. Actual SDK replay requires an authorized external **v3.2.0 archive, schema 2.7.0**:

```powershell
python -X utf8 integration/three_cases/verify.py --archive "X:/authorized/train+public_test.zip"
```

This temporarily loads only allowlisted SDK/catalog members and verifies our synthetic latest-turn reference traces. Historical actions are already applied in the private post-history WORLD and must not run again. Keep private state/gold outside model-visible inputs. Prepared examples are authored reference evidence, not model-generated traces or official full-score guarantees. Tài owns Jaz mapping, real run identity, execution, trace/submission and scorer integration; Tú owns serialization and loss masking. Native harness acceptance and training export remain pending.

Earlier project-bound examples and the bundled-SDK ZIP below are **historical**, not current setup instructions or redistribution-cleared assets. Complete ASR rescoring separately needs withheld authorized benchmark inputs; this external-SDK command does not supply those inputs.

## Input and session boundaries

| Boundary | Proposed mapping and invariant |
| --- | --- |
| Agent request | Render canonical agent_visible.request as the latest user text. This is synthetic text input. Organizer train has audio and audio_text. Public test lacks audio_text. Keep any future audio/ASR adapter separate. |
| Context | Pass the authored current_time, timezone, profile and other supplied fields unchanged. Render installed_apps from the per-sample allowlist where absent. When supplied, reconcile its flattened names with the allowlist and keep the system-tool rule explicit. Preserve absence of unauthored profile fields and location. |
| Schemas and permissions | Supply only the selected catalog schemas intersected with the sample allowlist, plus sys.ask_missing_info under the runtime rule. Preserve qualified names, required arguments and nested values. Set private _meta.tools from the same source and assert effective Session.allowed equals the rendered schema names. An app key alone grants no tools. |
| Visible history | Preserve order, roles and text. Map authored legacy user text to the text-mode user transcript field, and accept existing audio_text. Reject conflicting duplicate text fields rather than choosing silently. For assistant turns, preserve text, tool_calls and tool_results, pairing by index within the turn. Preserve omitted arrays versus empty arrays until Tài confirms normalization. Reject unmatched nonempty arrays and keep actual ok:false / done:false results. No fabricated assistant turn or result. |
| Private input | Scenario ID, WORLD and variant, fixture metadata, oracle, expected traces, aliases and pre-history call plans stay in the runner/verifier. Keep generated entity IDs in observations that actually returned them. Reference private IDs only in tool results or supplied values that intentionally expose them. |
| Session | Use the canonical post-history state and latest _meta.current_time. For executed history, preserve per-turn clocks in private replay evidence. Open a fresh session, verify the initial snapshot and assert an empty latest-turn log. History appears in the visible input once. Do not replay historical writes inside the latest session. |

## Latest-turn evidence and adjudication

Proposed runner result contains ordered call/result pairs, optional assistant final text, termination status and final complete app state. A pair retains the original name and arguments and the raw result. Keep call position and errors distinct from successful application no-ops. A validation or runtime error may give ok:false. The app may return ok:true with done:false and no change. A question can give waiting_for_user:true and leave state unchanged. Neither log length nor a state delta determines the goal verdict.

Proposed termination values are completed, waiting_for_user, budget_exhausted, externally_interrupted and runner_error. An empty completed log is meaningful for a wholly unavailable action under the current local policy. Observe-only may require a successful read and a correct factual response, even with unchanged state. Preserve the response for review. Ask ends this replay segment. User continuation is a separate pending interface decision.

Verifier inputs are the private scenario/oracle, rendered visible input, post-history initial snapshot, actual latest calls/results, final text if captured, termination and final snapshot. Return pass, fail or unresolved with reason codes and evidence positions. Check the authorized effects, preservation, order and source grounding where required. Missing semantic criteria for free text, or an unconfirmed policy, should stay unresolved/manual-review. Keep local trace verdict, response-content verdict and integration status separable. Canonical local snapshots include unchanged apps. Organizer train final_state instead contains whole states of changed apps only. The documented submission contains id, tool_calls and state_hash. Official matching and hashing remain a separate pending boundary. [Structure review](ORGANIZER_DATASET_STRUCTURE_REVIEW.md)

## Review slice

| Existing scenario | Concrete mapping and expected evidence |
| --- | --- |
| TR15_PLANNING_TOMORROW, history-dependent execution | Read scenarios.TR15_PLANNING_TOMORROW.agent_visible and .post_history_state. The historical reminders.create result has rem_02 at 08:20. Latest context is September 17 at 00:10 in Vietnam. Select replays entry with scenario_id and trace_case standard. The latest log has one calendar.create_event with start 2027-09-18T08:20:00+07:00 and no reminder write. Keep the previous reminder and existing event. MIDNIGHT changes only the latest clock and changes the target day. [Evidence](../../artifacts/synthetic/train_wave_15_replay/replay.json) |
| B02_N_C, clarification | Use agent_visible.B02_N_C and fixtures.B02_N_C. In the standard row, unfiltered calendar.list_events returns an unrelated event. The only valid next action in that path is sys.ask_missing_info with tool_name reminders.create and params containing time. Map the actual waiting_for_user:true to the proposed waiting status. State remains unchanged. The returned unrelated start cannot fill the missing parameter. [Evidence](../../artifacts/synthetic/batch_02_replay/replay.json) |
| TR16_APP_KEEP, conditional observe-only | Use scenarios.TR16_APP_KEEP.agent_visible and .post_history_state. Select its standard replay row. appliances.list returns the target washer running eco, so the latest turn makes no write. State stays unchanged. Final text may be absent under the existing local policy. [Evidence](../../artifacts/synthetic/train_wave_16_replay/replay.json) |

## Team decisions

- **Tài, pending.** Confirm field names and role rendering, whether and how history lacking audio is accepted, installed-app/schema projection and the system-tool exception, how to seed post-history state, ordered result capture and error handling, stop/wait semantics, and the verifier/manual-review boundary. Demonstrate the three cases above without exposing private fields or replaying prior writes. Confirm changed-app projection and any official submission mapping separately.
- **Tú, pending.** An exporter needs an eligible split-qualified case, approved visible request/context/history and permitted schemas, a vetted target trajectory and responses, provenance and review status. Confirm template/tokenizer, representation of multiple calls and results, text-only and empty-log targets, clarification stop and end tokens, and which assistant call/text tokens receive loss. Decide how history, tool outputs, schemas, control tokens and unresolved/negative traces are masked or excluded. Use the current slice only for contract review because every case remains non-exportable. Private fixtures and oracle fields stay out of model input and target serialization.

## Proposed final-text pilot boundary

Capture final_text after the last tool result and before closing the latest turn. Associate it with the private scenario ID and the same trace/run ID that indexes the ordered latest calls/results and final state. Preserve null for no emitted final answer. For a completed turn with required facts, missing or blank text fails answer content. An optional response can be omitted. A tool failure or interrupted capture remains separately visible in the trace verdict and termination status.

The pilot test adapter uses the canonical passing trace and authored text. A future integration must verify that the actual trace provides the required evidence before applying the factual rules. Report trace/state, answer-content, and overall verdicts separately, with any efficiency notes outside task correctness. Either correctness failure fails the overall task. With no failure, an unresolved factual judgment keeps the overall result unresolved. Route language outside the scoped rules, uncertain evidence and unsupported response policies to manual review. Tài must confirm capture and trace association. Tú must confirm whether and how final-text targets enter training serialization. [Pilot](FACTUAL_ANSWER_PILOT_HANDOFF.md)

The [three-case local adapter](FACTUAL_ANSWER_PILOT_HANDOFF.md#three-case-trace-binding-integration) now exercises this proposed boundary. It uses one scenario/run envelope for rendered input, ordered calls and actual results, private snapshots, final_text and termination. It recomputes the applicable verifier verdict and checks factual evidence on the submitted record. Tài still needs to confirm who assigns run IDs, how final-text capture binds to that run, private snapshot references or representations, historical result alignment, and termination mappings. Tú should preserve absent and empty text distinctly and keep unresolved judgments outside approved target serialization. The local examples provide no native harness or export acceptance.

## Historical project-bound contract examples

The review directory (excluded local source: `../../artifacts/synthetic/harness_contract_examples/README.md`; see FILE_SELECTION.json) contains one input/output pair for each case in the review slice and nine shared exact catalog schemas. The committee devkit remains the interface baseline. These proposed fields provide a reviewable mapping to the team runner. Dataset authoring and local replay can proceed while team-specific rendering decisions are pending.

| Proposed field | Boundary and meaning |
| --- | --- |
| contract_version | lifemate-harness-proposal-0.1 on every input and output. |
| sample_id, run_id | Existing scenario identity and a distinct prepared-example run identity, equal across the corresponding pair. Tài's runner must own real execution IDs. |
| agent_visible | request, supplied context, ordered history and tool_schema_refs. Resolve the nine shared definitions before rendering. The effective set is the sample's explicit tools plus sys.ask_missing_info, matching Session.allowed. Preserve supplied context. Any additional installed_apps projection is a renderer decision. |
| private_execution | Project-relative scenario, oracle, source rendering and initial-state references, the latest runtime clock, explicit fixture tools, empty starting log and pinned train release/schema. These fields stay outside model messages. |
| execution | Separate ordered tool_calls and tool_results arrays for the latest turn. Each call has call_id, name and original arguments. Its result has result_id, matching call_id and original payload. |
| final_text | null when unavailable. Preserve an actually captured empty string as an empty string. The examples have no captured final text. |
| termination | Proposed execution status and its origin. The examples infer completed or waiting_for_user from the actual recorded behavior. |
| task_outcome | Original scenario oracle outcome and local_expected status. This carries local semantic intent, separately from execution status and verifier judgment. |
| private_final_state_ref | Project-relative canonical snapshot and JSON Pointer selector. Complete app snapshots are private verification inputs. |
| local_verification, provenance, availability | Preserve the recorded local tool/state verdict, available answer judgment, exact canonical replay row, input filename and unavailable model metrics. Expected outputs come from local execution evidence. |

Selectors use JSON Pointer over parsed JSON, or over a parsed YAML design. The package README defines key escaping and the optional omit_keys projection. The examples avoid fixture copies. Private references require the matching project checkout. Every model-visible request, supplied context value, historical response and schema definition is available inside the review directory.

Call IDs include the run identity and a history or latest namespace. They are unique across both namespaces within the run, including all earlier turns. Result IDs append /result and carry the paired call_id. Array order remains significant. History conversion adds these identifiers to the original index-paired calls/results. The model-specific renderer may turn a pair into native tool messages if that model requires them, preserving association and payload. Tài and Tú must confirm that rendering and its training representation.

| Execution status | Proposed meaning |
| --- | --- |
| completed | The runner ended normally. Semantic correctness is evaluated separately. |
| waiting_for_user | The turn paused after a real clarification request. The B02_N_C response explicitly contains waiting_for_user:true. |
| budget_exhausted | The configured call/token/time budget ended execution. Record any captured partial trace. |
| externally_interrupted | An operator or external session interruption ended execution. Preserve the last captured evidence. |
| runner_error | A runner failure prevented normal completion. A single returned tool error does not automatically imply this status if the runner can continue. |

Never insert synthetic tool calls to signal these statuses. Keep returned validation failures, runtime responses, application no-ops and waiting responses exactly as captured. Local semantic outcomes such as execute, ask_missing and observe_no_write, and verifier pass/reject/unresolved, remain separate fields. The earlier three-case factual adapter currently accepts completed, runner_error and incomplete. The finer budget/interruption values here are a proposed external format. A future mapping must retain their reasons when adapting them to incomplete.

| Decision for Tài | Proposed behavior to confirm | Current implementation comparison |
| --- | --- | --- |
| Fields and model messages | Keep visible and private envelopes separate, resolve schemas before rendering and preserve message order. | Pending Tài's review. |
| Run identity and final text | Tài owns real run IDs and Jaz capture of final_text for the same sample/run as calls and snapshots. | Ownership confirmed by Thắng. Implementation mapping pending. |
| Call/result identifiers | Generate unique run-scoped IDs across history and latest calls and pair results explicitly. | Pending. |
| Post-history initialization | Load the provided post-history snapshot once and assert an empty latest log. | Local runtime boundary validated. Native runner pending. |
| Permissions and schemas | Explicit tool names intersected with the pinned catalog, plus the system question tool. | All three examples match actual Session.allowed. Native renderer pending. |
| Raw responses | Capture ordered actual payloads including errors and no-ops. | Canonical examples verified. Native capture pending. |
| Termination | Use the five execution statuses above, distinct from task outcome and verifier verdict. | Native mapping pending. |
| Verification state access | Keep complete initial/final states and oracle references private. | Local selectors resolve. Native access pending. |
| Existing harness differences | Tài records field renames, rendering differences and unsupported statuses against this package. | Unknown until review. |

Tú's pending choices are model-specific serialization, representation of multiple calls and results, end-of-turn tokens, loss masking, and preservation of absent versus empty final text. Those decisions concern eventual model inputs and targets. This package is for interface review and retains the current non-exportable dataset status.

## Historical bundled-SDK handoff — do not use for current setup

Thắng confirmed that **Tài owns the Jaz adapter, field conversion, real run IDs and model execution**. The v0.1 envelope remains a proposed interchange contract. Tài can implement its mapping to Jaz using the committee SDK/catalog as the baseline. Confirmation of model-message rendering and implementation differences is still needed. These integration choices do not block synthetic design and local verification.

**Historical workflow only.** The directory and ZIP described in the next paragraph bundled organizer SDK/catalog content whose redistribution authorization has not been established. They are excluded from this publication set. The old `python verify.py` instruction is not the current command; use the external-archive command above.

The historical portable package (excluded local source: `../../artifacts/synthetic/lifemate_harness_handoff_v01/README.md`; see FILE_SELECTION.json) includes the three case pairs, their concrete private initialization and gold, nine exact tool schemas, the necessary pinned SDK modules and unchanged extracted verifier functions. The ZIP (excluded local source: `../../artifacts/synthetic/lifemate_harness_handoff_v01.zip`; see FILE_SELECTION.json) can be extracted outside this project. Its historical instruction was `python verify.py` from that old root using Python 3.10+; do not use it as current setup. The script performs actual local calls, compares every response and final snapshot, invokes the existing verifier and checks permissions. Private initial states and oracle/gold stay outside agent_visible. Historical actions are already applied and never replayed in the latest session. Run IDs identify prepared local examples.

Tài must map the five proposed execution termination statuses to Jaz, preserve actual failures/no-ops and bind captured final text to the same run. Null final_text in this package records unavailable source evidence. The silent conditional example is permitted locally. Tú retains the model-specific serialization, end-token and loss-masking decisions. Existing source scenarios and their spec_only/non-exportable status remain unchanged.

## Current curated review package — 2026-11-06

The current handoff is team_review/README.md (workspace) or README.md at the curated package root. Tài owns Jaz mapping, actual run identity, model execution, trace/submission and scorer integration; Tú owns model serialization and loss masking. Acceptance remains pending. The old portable directory/ZIP described above is a historical local artifact, **not redistribution-cleared**: it bundles organizer SDK modules and exact catalog definitions. Do not publish that old ZIP. The curated integration/three_cases/ copy includes our synthetic envelopes, private post-history snapshots, authored reference calls/results and current verifiers, with the SDK/catalog supplied externally from an authorized v3.2.0 archive. Its verify.py --archive command materializes allowlisted SDK modules and nine schemas only in a temporary directory. No organizer sample/environment member is read. B02 verifier extraction is refreshed to the current collection-validation repair. Historical actions appear as context, never re-executed in the latest session. These reference traces are not model results or the only semantically valid trajectories.
