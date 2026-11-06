> Historical interface-only review from2026-11-03. Its initial no-gold status is superseded by the completed synthetic audit and this package README. SDK/catalog redistribution authorization is not established; supply them externally.

# Organizer dataset structure review — 03/11/2026

Structural review complete. Independent seed **specification** can proceed against the real catalogs. A documented lower-level fixture loader and state inspection interface exist, but fixture integration is not yet verified or wired into Tài’s harness. No executable synthetic gold or training export is ready.

## Scope and evidence

Read-only review of the downloaded archive (external authorized asset; original local locator `D:/Downloads/train+public_test.zip`), supplied documentation, catalogs and safe Python source. Every nonblank train/public-test/submission JSONL record was processed locally for structure; sample values were neither printed nor retained. IDs and audio paths were compared in memory only. Nested payloads were traversed for keys/types, not interpreted. No sample-derived tasks, distributions, entity inventories or failure cases were constructed.

No organizer environment-file contents were opened, parsed, copied or extracted. Only ZIP directory entries were used to count their files/bytes. No package code was imported or executed; no ToolEnv was instantiated. No audio playback, transcription, ASR, waveform decoding, header inspection, agent execution, gold replay, scoring, training, tuning, synthetic seeding, external model/API call or upload occurred. Local Python standard-library code inspected ZIP metadata, JSON structures and source text/AST only. No hashes were generated. Organizer files, benchmark artifacts and prior WORLD documents were preserved; this report is the sole workspace output. No structural helper or derived dataset was retained.

Evidence notation below: `Z!member:Lx–Ly` means original UTF-8 line numbers within the linked ZIP, relative to `train+public_test/`; `T` = `train/zaic_tools/`, `P` = `public_test/zaic_tools/`, `TC` = `train/train_tools_catalog.json`, `PC` = `public_test/public_test_tools_catalog.json`. These are archive-member locators, not extracted files. **Observed** means full local structural traversal; **code-verified** means static source inspection, not runtime verification; **documented** means supplied text, not independently checked against a live organizer website. Instructions/examples embedded in documentation were treated as evidence, not authorization to run anything.

## Package and layout

Package: `D:/Downloads/train+public_test.zip`, 876,430,231 bytes (about 836 MiB). `Z!VERSION:L1–L3`: release **v3.2.0**, built **2026-10-24T23:35:25+0700**, advertised train 1,545 / public_test 634, matching observed records. Catalog schema version is separately **2.7.0** in both splits. No private-test split is supplied.

```text
train+public_test/
  VERSION; README.md; .DS_Store
  train/
    train.jsonl; train_tools_catalog.json
    audio/<id>/<id>.wav and <id>_uN.wav
    train_environment/<id>/state.json     # names only; contents never accessed
    zaic_tools/{README.md,__init__.py,__main__.py,executor.py,validate.py,utils.py,apps/}
    .DS_Store
  public_test/
    public_test.jsonl; public_test_tools_catalog.json; sample_submission.jsonl
    audio/<id>/<id>.wav and <id>_uN.wav
    public_test_environment/<id>/state.json  # names only; contents never accessed
    zaic_tools/{same core filenames,apps/}
__MACOSX/                                 # AppleDouble metadata; not dataset records
```

Counts exclude directory entries and `__MACOSX` metadata. Sizes are uncompressed bytes from ZIP listings, rounded below.

| Component | Train | Public test |
|---|---:|---:|
| Total files under split | 6,639 | 2,616 |
| Input JSONL | 1; 7,198,841 B | 1; 1,593,830 B |
| Catalog JSON | 1; 91,423 B | 1; 76,805 B |
| WAV files | 5,036; about 787 MB | 1,933; about 318 MB |
| Audio metadata files | 1 `.DS_Store`, 6,148 B | 0 |
| Environment files (listing only) | 1,545; about 11.55 MB | 634; about 5.00 MB |
| zaic_tools files, including README | 54; 107,570 B | 46; 97,038 B |
| Submission template | absent | 1; 607 B; 3 illustrative records |

Root README is 9,848 B; VERSION is 77 B. Archive also contains 13,627 `__MACOSX` files, about 2.22 MB; these were not read. Relevant types are JSONL, JSON, WAV, Python and Markdown, plus extensionless VERSION and macOS metadata. No full extraction was performed.

## Record contracts — observed over all records

| Property | Train | Public test |
|---|---:|---:|
| Records / unique IDs | 1,545 / 1,545 | 634 / 634 |
| Duplicate IDs within split | 0 | 0 |
| Common top-level fields | `id`, `audio`, `context`, `history` | same |
| Additional fields | `audio_text`, `label`, on every record | neither present |
| Empty history lists | 527 | 215 |
| History user / assistant turns | 3,491 / 3,491 | 1,299 / 1,299 |
| Latest + history audio references | 5,036 | 1,933 |
| Existing / distinct referenced WAV members | 5,036 / 5,036 | 1,933 / 1,933 |

No IDs overlap between splits. No referenced WAV is missing and no WAV is unreferenced. This establishes path resolution only, not duplicate-audio absence, speech quality or label reliability. No duplicate-audio, leakage or semantic audit was attempted. Documentation specifies WAV 16 kHz, mono, 16-bit ([description.md](../project/description.md), line 102); **headers were not checked**, so encoding is documented rather than measured.

| Input key path | Observed type / presence |
|---|---|
| `id`, `audio` | strings, required in every supplied record |
| `audio` convention | `audio/<id>/<id>.wav`, relative to the split directory; exact match for every record |
| `audio_text` | string on every train record; absent from public test |
| `context` | object, same five keys on every record in both splits |
| `context.current_time`, `.timezone` | strings |
| `context.location.lat`, `.lng` | floating-point numbers |
| `context.user_profile.{name,home_address,work_address,city}` | strings; all four keys always present |
| `context.installed_apps` | object keyed by app identifier; each value has exactly `tools: array<string>`; no state embedded in these entries |
| `history` | array of objects, possibly empty |

No nulls occurred in these input/context fields. Observed universal presence does not establish a formal future-schema guarantee. Time strings/profile/coordinates were not displayed or semantically validated.

| History representation | Train turns | Public turns | Contract |
|---|---:|---:|---|
| User | 3,491 | 1,299 | `role`, `audio`; train additionally has `audio_text`, all strings |
| Assistant text only | 113 | 51 | `role`, `text`, both strings |
| Assistant text + calls, without results | 397 | 142 | also `tool_calls`; every such list is empty |
| Assistant text + calls + results | 2,981 | 1,106 | both arrays; 3,661 / 1,330 call-result pairs respectively |

Only `user` and `assistant` roles occur. Tool observations are nested `assistant.tool_results`, not separate `role: tool` messages. History audio paths all follow `audio/<id>/<id>_uN.wav`; suffix sequences were not audited. Every history call is an object with exactly `name: string` and `arguments: object`. Where results exist, per-turn call/result lengths match. Result objects always contain boolean `ok`; payload keys vary by tool. Public history therefore exposes prior tool observations, even though it supplies no latest-turn transcript or gold label. History text/tool payloads were inspected structurally only.

| Label / submission key path | Observed contract |
|---|---|
| `label` | train-only object; exactly `tool_calls`, `tool_results`, `final_state` on all 1,545 records |
| `label.tool_calls[]` | exactly `{name: string, arguments: object}`; 3,541 calls total; 111 empty lists |
| `label.tool_results[]` | object, boolean `ok` plus tool-specific payload; 3,541 results; 111 empty lists; paired lengths match on every record |
| `label.final_state` | object keyed by changed app; each app value is an object; 373 empty objects |
| Nested arguments | strings, numbers, booleans, arrays and objects as applicable; no null argument leaves observed; nested objects/arrays must be preserved |
| Nested results / final state | objects, arrays and scalar leaves including null; fields/collections vary by app and tool; no single universal entity schema |
| Submission | exactly `id: string`, `tool_calls: array`, `state_hash: string`; 3 unique illustrative IDs, not a full 634-row submission |
| Submission calls | same `{name, arguments}` structure; no input/context/history/transcript, tool results or raw final state included |

The traversal covered nested key paths and type variants; the report contracts app-specific payloads to `<app>/<collection>/<entity fields>` rather than reproducing a sample-derived state inventory. Results include collection arrays, individual entity objects, primitive summaries and nullable fields. For example, the **structural** key `message` can be a string or object, so it must not be assumed to be an error string. Numeric leaves can be integers or floats. No universal non-null or closed-field schema can be inferred for payloads. `Z!README.md:L49–L55` documents final_state as the **whole state of each changed app**, not a sparse field patch; unchanged apps are omitted. Labels are reference data, never a synthetic-authoring source.

## Catalog and tool interfaces

Both catalogs have `{schema_version, note, apps}`. Each app has `{id,name_vi,group,description,tools}`; each tool has `{name,kind,description,parameters,returns,app}`. Tool names are qualified `app.method`; kinds are `read`, `write`, `meta`. Parameters are object schemas with `properties`, optional `required` and `x-one-of`; property metadata includes types, descriptions, enums, bounds, formats, items, x-ref and x-match. **Returns are descriptive strings, not JSON return schemas**: 77/147 train and 60/122 public tools have empty return descriptions. Source methods are needed to establish concrete return shapes. Evidence: `Z!README.md:L57–L73`, complete structural inspection of TC/PC, `T/apps/base.py:L30–L103`.

| Catalog | Apps | Read | Write | Meta | Tools |
|---|---:|---:|---:|---:|---:|
| Train | 46 | 62 | 84 | 1 | 147 |
| Public test | 36 | 52 | 69 | 1 | 122 |

There are 25 common apps; all common tool specifications are identical across the supplied catalogs. Catalog coverage is a capability specification, **not an estimate of task frequencies**. App groups are home, planning, communication, finance, information, mobility, food, travel, shopping, media, health, personal (train only), and control.

| Catalog membership | App identifiers |
|---|---|
| Both | smart_home, alarm, reminders, calendar, notes, tasks, contacts, phone, sms, chat_ott, email, banking, ewallet, bill_payment, weather, gold_price, fuel_price, maps, food_delivery, ride_hailing, flights, shopping_list, music, tv, sys |
| Train only | appliances, bike_rental, calculator, door_lock, exchange_rate, fitness, home_automation, home_energy, home_security, household_chores, learning, library, lottery, loyalty, medication, news, package_tracking, podcast_radio, robot_vacuum, subscriptions, video_meeting |
| Public only | ecommerce, event_tickets, grocery, habit_tracker, pantry, parking, public_transit, recipes, stocks, train_bus_tickets, translator |

The following interface examples resolve existing WORLD questions; they come solely from catalogs/source, never sample gold. `!` means required, `?` optional; constraints/enums remain authoritative in TC/PC. Keep the original catalogs as the per-tool reference rather than making a second catalog artifact.

| Tool; description; kind | Parameters | Return description / source evidence |
|---|---|---|
| `smart_home.get_status`; filter devices/status; read | `room?:string`, `floor?:integer`, `type?:string` | `devices[]`; also scenes when unfiltered in description. TC:12 |
| `smart_home.light_set`; change light; write | `device_id!:string` x-ref; `power?:string` on/off; `brightness?:integer`; `color?:string` | catalog empty; generic patch returns `{ok,item}` or no-op. TC:43; T/apps/base.py:93–103 |
| `contacts.search`; name/relation/phone substring search; read | `query?:string` | `contacts[]`; no query returns all. TC:1027; T/apps/base.py:55–84 |
| `phone.call`; contact or number call; write | `contact_id?:string`, `phone_number?:string`; one group required | catalog empty. TC:1107 |
| `sms.send`; contact or number SMS; write | same alternative targets; `content!:string` fuzzy | catalog empty. TC:1161 |
| `email.list` / `email.read`; list/read mail; read | `unread_only?:boolean` / `email_id!:string` | `emails[]` / `email`; list excludes body, read returns full entity. TC:1339/1355; T/apps/email.py:28–40 |
| `email.send`; send/store mail; write | `to!:array<string>`, `subject!:string`, `body!:string`, `cc?:array<string>`; subject/body fuzzy | `email` description; implementation `{ok,id,email}`, address problems produce no-op. TC:1375; T/apps/email.py:42–54 |
| `reminders.create`; create reminder; write | `content!:string` fuzzy, `time!:string`, `repeat?:string` once/daily/weekly | catalog empty; `{ok,id,item}`; defaults repeat=once, done=false. TC:675; T/apps/reminders.py:14–16; T/apps/base.py:86–91 |
| `ride_hailing.get_quotes`; price/pickup estimate; read | `pickup!:string`, `dropoff!:string` fuzzy; `vehicle?:string` | `quotes[]`; implementation filters stored quotes by vehicle, does not calculate a route/arrival event. TC:2562; T/apps/ride_hailing.py:29–31 |
| `ride_hailing.book`; book ride; write | `pickup!:string`, `dropoff!:string` fuzzy; `vehicle!:string` bike/car4/car7; `schedule_time?:string`, `payment?:string` cash/ewallet | catalog empty; creates ride with booked status; absent/past/current schedule means immediate. TC:2594; T/apps/ride_hailing.py:33–38 |
| `ride_hailing.get_ride`; current/specified ride; read | `ride_id?:string` | `ride`; absent ID selects latest noncancelled ride, no documented arrival callback. TC:2660; T/apps/ride_hailing.py:44–53 |

### Extensions, defaults and validation — code-verified

- **x-ref** documents the source collection/ID relationship; schema validation does **not** check referential existence. Lookup/business behavior belongs to the app method, commonly an accepted no-op for missing IDs. Do not fabricate `ok:false` recovery targets for nonexistent IDs. `Z!README.md:L71`, `T/validate.py:L100–L120`, `T/apps/base.py:L41–L45,L93–L103`.
- **x-one-of** means **at least one entire listed group has nonempty arguments**; multiple groups can be supplied. It is not exclusive XOR. Required fields still apply. `T/validate.py:L111–L117`.
- Missing required includes `null`, empty string/list/object. Nonempty property values are checked for type, enum, numeric bounds, finite numbers, supported date/time format, and recursively array item value rules. Booleans are excluded from integer/number. Unknown arguments are not rejected; object-property schemas are not recursively validated as full JSON Schema. No x-ref or x-match enforcement occurs here. `T/validate.py:L23,L43–L97,L100–L120`.
- ISO requirements can be prose-only: `reminders.create.time` is a string with an ISO description but no `format` constraint (TC:675); do not mistake documented formatting for enforced validation. No parameter has a JSON Schema `default` keyword in either catalog. Defaults live in descriptions/methods/helpers. Validator does not inject defaults. Empty optional values skip validation but can still be forwarded to the implementation; do not equate explicit empties with omission. Generic create/patch ignore `None`, not every empty value. `T/executor.py:L48–L62`, `T/apps/base.py:L86–L103`.
- **x-match:fuzzy** marks free-text argument scoring, not simulator search semantics. [description.md](../project/description.md), lines 54–60, documents token-F1 > 0.6 after lowercase + Unicode NFC and one-to-one, order-independent call matching. No official call matcher/scorer is supplied in the inspected package. Exact tokenizer, optional/default argument equivalence and matching assignment remain unresolved.
- Search helpers are not that scorer: generic read uses case/diacritic-folded substring matching (`T/apps/base.py:L55–L84`); shopping helpers use whole-query substring then meaningful-token overlap (`P/apps/_shop_match.py:L12–L41`). `_tokens` exists (`T/utils.py:L22–L24`) but is not an included token-F1 scorer.

### Installed capabilities and exact clarification contract

Agent-visible tools are the catalog intersected with the explicit names in `context.installed_apps.<app>.tools`, plus `sys.ask_missing_info`, not every method belonging to an installed app. Runtime Session reconstructs its allowlist from fixture `_meta.tools`; it does **not** consume the JSONL installed_apps field. Independently authored fixtures and visible context must agree. `Z!README.md:L44`, `T/executor.py:L35–L44,L82–L91`; catalog membership validation at `T/validate.py:L103–L108`.

`sys.ask_missing_info`: name as shown; kind `meta`; description “report missing required parameters of a tool”; app `sys`; catalog returns description is the empty string. Exact parameter schema, including catalog descriptions:

```json
{"type":"object","properties":{"tool_name":{"type":"string","description":"Tên tool bị thiếu tham số, dạng app_name.tool_name, ví dụ sms.send"},"params":{"type":"array","items":{"type":"string"},"description":"Tên các tham số bắt buộc còn thiếu, đúng tên trong schema, ví dụ [\"contact_id\"]"}},"required":["tool_name","params"]}
```

`tool_name` is documented as the intended qualified tool name; `params` contains missing required parameter names exactly as in that tool schema. No question-text, candidate-ID, ambiguity-reason field, enum or minItems is declared. Normal missingness validation rejects an empty params list. Runtime returns exactly `{"ok":true,"waiting_for_user":true}` without state change; it does not check that the named tool/parameter exists or is actually missing. Evidence: `TC:L3801–L3826`, `PC:L3195–L3220`, `T/apps/sys.py:L10–L13`, `T/validate.py:L111–L117`.

[description.md](../project/description.md), lines 29–31, permits asking after other calls and specifies empty calls for wholly unsupported requests. Neither catalog nor this implementation supplies a general ambiguity-resolution policy, a user-answer continuation mechanism, or a policy for every mixed supported/unsupported request. Do not invent extra ask fields or treat runtime acceptance as proof that an ambiguity gold is correct.

## Environment, synthetic fixtures and verification

| Interface | Static finding and evidence |
|---|---|
| `ToolEnv(split, question_id, root=None)` | Reads catalog plus `<root>/<split>/<split>_environment/<id>/state.json`, returns Session; calling again resets. Participant API in `__all__` includes ToolEnv, schema_validate, state_hash. No construction performed. T/__init__.py:25–44 |
| `Session(sample_id, entry, catalog)` | Lower-level constructor accepts an in-memory entry; requires `_meta.current_time`, reads `_meta.tools`, optional city, and app-state objects. Deep-copies state into Simulator. T/executor.py:35–45,79–93 |
| `Executor(env_path, catalog_path=None)` | Documented lower-level API. Loader accepts a directory layout **or one JSON file `{id: entry}`**; `.open(id)` returns a fresh Session. This can structurally accept independently authored synthetic fixtures without accessing organizer fixtures or patching package code. It is outside the narrow participant API and not a dedicated, guaranteed synthetic authoring schema. T/executor.py:11,114–135; T/__init__.py:14,44 |
| `validate(name,args)` | Schema/allowlist check only, returns `{ok,error}`, no execution or log append. T/executor.py:64–67 |
| `call(name,args)` | Checks schema/allowlist and implementation, invokes app method; results copied. Session logs every attempted call including rejections; Simulator.log also contains results. T/executor.py:48–76,95–102 |
| `get_tool_calls()` | Deep copy of ordered `{name,arguments}` calls, including rejected calls. T/executor.py:95–102 |
| `get_state()` | Deep copy of all current app states: a verifier can inspect its **own synthetic** state through this method. T/executor.py:104–107 |
| `get_state_hash()` | Hash of canonical current state. Environment-generated value belongs in execution/submission, never an authored placeholder. T/executor.py:109–111; T/utils.py:49–67 |
| `Executor.replay(id,calls)` | Opens a session, returns results and complete states for apps changed relative to initial state. Not used in this review. T/executor.py:137–143 |

Initialization does not replay history or load conversation messages. Supplied fixtures are documented as the state **after prior history actions**, at the latest request; source simply loads that state. History construction and fixture consistency remain the synthetic author’s responsibility. `Z!README.md:L45–L47,L75–L82`, `T/executor.py:L82–L93`. Agent view must exclude `_meta`/hidden state and oracle; verifier access to synthetic state is separate.

Canonical state removes `_meta`, live information apps and a fixed recursive set of free-text key names; lowercases/collapses whitespace and joins number-unit spacing in strings; sorts scalar lists; preserves dictionary-list order. Despite the source docstring’s “set” wording, sorting does **not deduplicate scalar lists**. It hashes sorted compact ASCII JSON with SHA-256. `T/utils.py:L33–L67`. This describes an interface; no hashes were calculated here.

Split-specific utils differ: train excludes live apps exchange_rate/fuel_price/gold_price/lottery/weather and free-text `expression`; public excludes fuel_price/gold_price/weather and free-text `text` instead. All other same-named supplied source files are byte-identical by in-memory comparison. Pin package release, selected split catalog **and its runtime**. Hash equality cannot prove free-text meaning, forbid every extra write, or replace independent goal/frame assertions. Static AST checks confirmed every catalog tool has a decorated implementation in its split package; no implementation was invoked. No complete official scorer or synthetic verifier is included; available runtime/hash/search helpers are only components.

## Documentation comparison and preparation corrections

| Finding | Status / implication |
|---|---|
| Package README and description agree on input, history already applied, labels, calls/hash submission, kinds and one-session rule | Documented, with structural/source support as above. One-session rule is procedural: constructor itself allows reset; do not exploit that in official execution. |
| Description’s illustrative `ride.book` with `from/to` differs from actual `ride_hailing.book` with `pickup/dropoff/vehicle` | Documentation discrepancy, not silently normalized. Use actual catalog; conceptual examples are not executable contracts. [description.md](../project/description.md):37–45; TC:2594. |
| Description calls x-ref a valid-ID requirement; runtime validator does not enforce existence | Separate grounding/semantic requirement from schema-validity; inspect app behavior for no-op outcomes. Description:108 versus T/validate.py:100–120. |
| Full scorer is described but absent | State canonicalization is code-verified; fuzzy/call matching is documented only. A replacement scorer cannot yet claim organizer equivalence. Description:54–75. |
| Team policy prohibits organizer train for training and treats public as holdout | [project README](../project/README.md):8; stricter than package’s labeled “train” naming. Description:257 prohibits public/private labeling for tuning. This review changes neither policy; no sample-based prompt selection/tuning is permitted. |
| Older README suggests public-score checks and experiments on “train” | README:23,37–39 is not authorization to tune on organizer data; current user boundaries prohibit it. Record this tension rather than infer an exception. |
| WORLD plan/preparation say actual catalogs/runtime unavailable | Historical status now superseded for interface discovery only. WORLD plan (excluded local source: `../plans/WORLD_DATA_PLAN.md`; see FILE_SELECTION.json):3; preparation (excluded local source: `WORLD_DATA_PREPARATION.md`; see FILE_SELECTION.json):3,14,82. Harness integration/training format remain unavailable. |
| x-one-of and history corrections | Preparation:37,42 are confirmed by source; maintain post-history initial fixture and permit more than one complete x-one-of group. |
| Partial completion and ambiguity | Preparation:38 and WORLD plan:181–185: partial-then-ask is documented in principle; exact identity ambiguity/mixed-OOS policies remain unresolved. Ask schema is now known; do not invent policy. |
| Email, ride dependencies and recovery assumptions | Preparation:39–43: email requires recipients, subject and body; ride quote/ride interfaces do not establish an arrival event callback; invalid-ID recovery is normally no-op, not schema failure. Only schema/source-backed dependencies may become executable. |
| Catalog digest and many separate artifacts in older plan | WORLD plan:20–41 are proposals, not organizer requirements. Current AGENTS.md and preparation:30,76 favor source release + frozen config, lean authoring, coverage-driven scale; no automatic digest/manifests/quotas are needed for this review. |

Package README’s distribution restriction is recorded (`Z!README.md:L4`); no content was uploaded. Competition schedules/hardware/model rules in the supplied description were not revalidated online, since this is a local package/interface review, not current competition guidance. Older research examples, including documentation examples, were not reused as synthetic seeds.

## Mapping to independent synthetic data and next step

| Layer | Ready to specify | Remaining dependency |
|---|---|---|
| WORLD | Independently authored app objects/relationships; per-split catalog/runtime selection; fixture entry envelope `_meta` + app state; visible capability list aligned to `_meta.tools` | Tài confirms lower-level Executor/Session integration and concrete app fixture expectations from safe source; no organizer fixtures needed |
| Scenario | Independently authored utterance; context fields, audio reference convention when audio exists; user/assistant history and nested call/result structure; initial state after history | Harness renders agent-visible history/tool schemas and defines text-only authoring adapter; do not claim native organizer input supports text-only public requests |
| Oracle | Independent intended outcome, grounding evidence, allowed/forbidden changes; semantic assertions separate from normalized hash | Explicit ambiguity/mixed-OOS rules for affected scenarios; no sample-derived decisions |
| Execution | Real ordered calls/results, all rejected attempts, deep-copy final-state inspection and environment-generated hash interfaces identified | One real synthetic fixture-to-session integration and verifier checks; no trace/hash is verified yet |
| Training view | Only allowed visible inputs, tool observations and verified assistant targets; no oracle/hidden fixture | Tú’s tokenizer/chat template, tool encoding, loss masking, stop behavior; Tài’s message/trace adapter; no training export now |

**Decision:** proceed next to independently authored seed specs using catalog contracts. Fixture integration is technically plausible through the documented lower-level interface, but not yet operationally validated; bulk generation, verified-gold claims and SFT export remain premature. Do not infer task distributions or seed inventories from these split statistics. Preserve lineage splits, coverage/uncertainty-driven sufficiency and separate representative/challenge evaluation per AGENTS.md and preparation:72–78.

**Smallest next implementation step (future task, not executed):** Tài confirms the documented Executor single-file fixture path; author one independent fixture/scenario/oracle using safe app source, execute a manually specified trace in that synthetic session, inspect full final state against goal and forbidden-change assertions, and retain actual calls/results/hash. Only then connect Tú’s training template. No generator, new backend, package patch or training run is needed to establish that first integration.

Review stops here. No organizer data was used for training/tuning or synthetic seeding, no organizer environment contents were accessed, and no model or external API execution occurred.
