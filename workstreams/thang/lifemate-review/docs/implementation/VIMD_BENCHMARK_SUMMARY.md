> Historical GIPFormer–VALSEA detail (2026-11-02); the [three-model closeout](ASR_BENCHMARK_CLOSEOUT.md) now includes QUAN and the baseline recommendation for team review.

# ViMD benchmark — canonical team handoff

Updated **2026-11-02, Asia/Saigon**. Detailed ViMD evidence summary for Thắng’s ASR benchmark assignment. The [combined ViMD + VN-SLU closeout](ASR_BENCHMARK_CLOSEOUT.md) is now the canonical entry point and records the completed iteration; this document retains ViMD detail. Dated implementation handoffs remain historical records. No inference, API call, scoring rerun, gold change or new experiment was performed during consolidation.

**Conclusion:** GIPFormer 1.5 has lower official-reference error on the same complete ViMD test split than the recorded VALSEA/Glot service run. GIPFormer FP16 remains the established baseline. This does **not** establish universal Vietnamese ASR superiority, LifeMate deployment selection, semantic-slot accuracy, or task-success advantage. VALSEA is not established as a better labeling teacher.

| Workstream | Current state |
| --- | --- |
| Engineering smoke and full-test execution | Complete for both recorded models/runs |
| Official-reference scoring and paired comparison | Complete; frozen full-test results below |
| Exploratory analysis | Complete for documented scope: full-corpus mechanical audit, 29 text-inspected utterances / 47 selected spans |
| Human listening | Thắng reports completing observations; accessible evidence and limits are recorded below. Exhaustive adjudicated review is not established. |
| LifeMate suitability / deployment selection | Not established; this does not make the completed ViMD benchmark unfinished |
| Next handoff | The combined closeout governs current status; earlier next-step proposals below are historical, not authorization for another run, training or experiment. |

## 1. Requirements, ownership and decisions

| Kind / owner | Applicable requirement or decision | Source and boundary |
| --- | --- | --- |
| Organizer, as recorded locally | Fully offline contest inference; no external services at inference; ≤30 s/sample on one A30, 16-core Xeon Gold 6442Y, 64 GB RAM; deterministic seeds/decoding. Public model/data before 26 October 2026, compatible licenses; no labeling contest public/private tests to train/tune. | [Provided competition description](../project/description.md), “Technical requirements.” Not reverified live here. A Kaggle T4 ASR run is not an A30 end-to-end compliance test; ViMD is separate from contest data. |
| Team assignment | Thắng compares the selected ASR with VALSEA. Using VALSEA for later training was conditional on evidence, not an approved consequence. | [Milestone assignments](../project/README.md), “Thắng: Tạo data để train model.” |
| Team engineering policy | Non-quantized 16-bit inference; concise implementation, traces; PR review rather than direct push. No training on organizer `train`; treat contest public test as holdout. | [Team README](../project/README.md), “Lưu ý chung” and “Tài: Setup workspace repo đầu cuối.” These are team instructions, not all organizer rules. No repository publication is performed here. |
| Thắng / current instructions | Keep GIPFormer 1.5 FP16 **weights with mixed computation**, greedy, one visible T4 / `cuda:0`; preserve full valid official splits; lean reproducible implementation. No FP32 comparison requested. | Current explicit instructions; [original workspace guidance](../project/WORKSPACE_GUIDANCE.md), “Benchmark data quality and engineering constraints”; recorded GIP configuration (excluded local source: `../../artifacts/kaggle_vimd_test/gip15_vimd_test_fp16_20261101_02/configuration.json`; see FILE_SELECTION.json). |
| Thắng / reference decision | Accept official references for `20_0306.wav`, `12_0241.wav`, `97_0283.wav` as trustworthy and correct; no repeat listening prerequisite for their reference-based conclusions. | User instruction, preserved in comparative report (excluded local source: `../../artifacts/analysis/vimd_comparative_limitations_20261102/report.md`; see FILE_SELECTION.json), “Reference confirmation for three cases,” and its evidence records. No gold file changed. |

The 31 October operational plan (excluded local source: `../plans/KAGGLE_ASR_BENCHMARK.md`; see FILE_SELECTION.json) and earlier ASR plan (excluded local source: `../plans/ASR_BENCHMARK_PLAN.md`; see FILE_SELECTION.json) contain proposals, including pilot90, GIPFormer 1.0, corrected-VALSEA arms and later datasets. They are **not evidence that those arms ran or were approved for the next iteration**. Actual engineering used six frozen validation clips; actual full comparison used only GIPFormer 1.5 and correction-disabled VALSEA. No hybrid, pseudo-labeling, fine-tuning, gold correction or FP32 experiment is approved by this consolidation. No agreement from other team members is inferred.

## 2. Dataset, distribution and audit

**Vietnamese Multi-Dialect (ViMD)**, [nguyendv02/ViMD_Dataset](https://huggingface.co/datasets/nguyendv02/ViMD_Dataset), revision **`3a5b30157034e7eadd5c75fae1a820c6f9383398`**, official **`test`**, with **all 2,026 records retained**. Canonical evidence: full manifest (excluded local source: `../../manifests/vimd_test.json`; see FILE_SELECTION.json) and coverage/audit + frozen scoring specification (excluded local source: `VIMD_TEST_MANIFEST_AUDIT.md`; see FILE_SELECTION.json), sections “Provenance and scope,” “Coverage,” “Issues and overlap.”

| Source region | Clips | Supplied speaker IDs | Audio seconds | Hours |
| --- | ---: | ---: | ---: | ---: |
| North | 783 | 528 | 15,275.982501 | 4.243328 |
| Central | 623 | 444 | 11,836.789384 | 3.287997 |
| South | 620 | 372 | 12,027.705420 | 3.341029 |
| **Total** | **2,026** | **1,344** | **39,140.477305** | **10.872355** |

There are **63 source province labels**, preserved exactly rather than mapped to current administrative boundaries. TienGiang and BacLieu each have only 10 supplied speaker IDs, the lowest province support observed. Coverage does not establish population representativeness, independently verified accents, or sufficient support for code-switching, names, numbers, noise, conversation, or LifeMate tasks.

**Collection context supported locally:** the saved dataset card (excluded local source: `../../artifacts/gipformer-inspection/dataset_card.txt`; see FILE_SELECTION.json), “Overview of the Dataset,” identifies news programs from broadcasting stations of 63 provinces; it cites Dinh et al., EMNLP 2024. Thus the evaluated distribution is province-labeled broadcast/news clips, not a verified voice-command or natural-dialogue benchmark. The locally saved card does not establish segment-boundary construction, proportions of read/spontaneous/interview speech, microphone/noise/SNR conditions, speaking rate, age, or verification of speaker origin/accent. Those details remain **unverified**; they are not inferred from wording. The card defines `gender` codes 0=female, 1=male, but these and speaker IDs are supplied labels, not independently verified demographics/identity. Split-construction/randomization and global speaker separation are not established by the accessible card. The actual valid/test speaker overlap below rules out claiming complete separation for those splits.

**Reproduction fields:** `filename` → `ViMD_Dataset/test/<filename>`; reference=`text`; `speakerID`, region, province code/name, gender; pinned shard and zero-based row group/row offsets; original embedded audio path, bytes, frames, sample rate, channels, format/subtype, duration and issue flags. Original test WAVs have 32/44.1/48 kHz sample rates, mono/stereo channels, PCM_16/PCM_32/FLOAT subtypes. The manifest preserves each exact header. No train split was downloaded for this audit; validation metadata only was used for overlap checks.

**Checks actually completed:** all 2,026 audios header-checked and incrementally decoded finite/nonempty; zero missing IDs/speaker/region/province metadata or empty raw/normalized references. No duplicate ID, filename, source locator, embedded source path or exact repeated-reference group detected; no speaker/region conflict; no valid/test shared filenames. These checks are not exhaustive audio-content deduplication: no universal audio fingerprinting, train overlap audit, independent speaker identification or model-training overlap verification was done. Repeated text alone would not prove duplicate speech. No sample was removed for difficulty or a flag.

Two supplied speaker IDs overlap with `valid` across three retained test clips:

- `spk_73_0186`: `ViMD_Dataset/test/73_0307.wav`, `ViMD_Dataset/test/73_0308.wav`.
- `spk_76_0219`: `ViMD_Dataset/test/76_0294.wav`.

All three keep `speaker_overlap_valid` and remain in every headline denominator. This is observed metadata overlap, not proof of duplicate audio or training leakage. Outside the three user-confirmed references above, exhaustive reference correctness remains unadjudicated; the official baseline is still unchanged.

## 3. Actual runs, precision and operational outcomes

### GIPFormer 1.5

Model: `g-group-ai-lab/gipformer1.5-68M-rnnt`, checkpoint `model.pt` and matching tokenizer assets. Full run: **`gip15_vimd_test_fp16_20261101_02`**. Exact sources/pins, remaining package versions, native-wheel URLs and embedded executed code are in configuration.json (excluded local source: `../../artifacts/kaggle_vimd_test/gip15_vimd_test_fp16_20261101_02/configuration.json`; see FILE_SELECTION.json); observed runtime is in run_metadata.json (excluded local source: `../../artifacts/kaggle_vimd_test/gip15_vimd_test_fp16_20261101_02/run_metadata.json`; see FILE_SELECTION.json).

| Asset | Revision / observed version |
| --- | --- |
| HF checkpoint/tokenizer | `dd9227dcd8705c13f33bdbe59728d546ab94480f` |
| Upstream `ggroup-ai-lab/gipformer` code | `0cac5b183d2e1a9e3429ff69080e09cc62ebdf9b` |
| icefall | `9c966762e058bd7ba79d9da71e42fc06b64b703e` |
| Kaggle host / isolated child | Python 3.13.15 / CPython 3.12.12, uv 0.9.5; Linux x86_64, glibc 2.39 |
| Torch / torchaudio | `2.8.0+cu128`; CUDA runtime 12.8, driver 580.178.04 |
| k2 | `1.24.4.dev20250807+cuda12.8.torch2.8.0` |
| kaldifeat | `1.25.5.dev20250807+cuda12.8.torch2.8.0` |

The host exposed two T4s; child `CUDA_VISIBLE_DEVICES=0`, one visible Tesla T4, **`cuda:0`**, batch **1**. Decoder=`greedy_search_batch`, `max_sym_per_frame=1`, blank penalty 0, context size 2, vocabulary 2,000; eval/inference mode, seed **20261031**, deterministic algorithms enabled. Model loaded once, one separate warmup, one measured prediction per test ID. Missing checkpoint keys: none; only expected auxiliary `ctc_output.1.weight` / `.bias` unexpected. Parameter count 68,625,511; all 743 parameter tensors FP16.

Precision is **non-quantized FP16 weights and model input with CUDA FP16 autocast, allowing upstream FP32 activation/normalization computation**. The finite FP32 encoder output is preserved; monitored encoder-convolution, decoder-embedding, joiner projections/logits produced finite FP16 outputs at warmup. Audio and 80-bin CPU fbank are FP32 (`dither=0`, `snip_edges=false`, `high_freq=-400`). This is not uniformly FP16 arithmetic; no BF16/INT8 or automatic FP32 fallback. The driver’s CUDA 13.0 capability label is not the native runtime version. No FP32 comparison is requested or reported.

**Shared audio protocol:** decode original bytes to float32, average channels, SciPy polyphase resample to contiguous mono 16 kHz; no VAD, denoising, trimming or content filtering. Both models used identical test IDs and this shared preprocessing function. GIP recorded NumPy 2.2.6 / SciPy 1.15.3; API client recorded NumPy 2.4.3 / SciPy 1.17.1, so do not assert independently tested bitwise waveform identity across package versions.

Completion summary (excluded local source: `../../artifacts/kaggle_vimd_test/gip15_vimd_test_fp16_20261101_02/completion_summary.json`; see FILE_SELECTION.json): **2,026 successful, 0 errors, 0 empty, 0 remaining**; one fresh completed session, no restore/resume or interrupted session in this full run. Earlier failed engineering attempts remain historical artifacts and are not erased by that count. Session **2026-11-01 11:31:06–11:55:49 UTC** (18:31:06–18:55:49 Asia/Saigon), **24m43s including provisioning/downloads**. Model load 1.164486 s and warmup 1.762386 s are separate diagnostics. Per-call timing covers synchronized fbank/transfer/encoder/greedy, excludes source preparation/loading/warmup. Session time is neither compute latency nor RTF nor contest runtime evidence.

### VALSEA / Glot

Run **`valsea_vimd_full_20261101_01`**. Recorded configuration (excluded local source: `../../artifacts/valsea/valsea_vimd_full_20261101_01/configuration.json`; see FILE_SELECTION.json): account-confirmed endpoint `https://api.glotlabs.ai/v1/audio/transcriptions`; alias **`glot-transcribe`**, `language=vietnamese`, `enable_correction=false`, `enable_tags=false`, `diarize=false`, `response_format=verbose_json`. Sequential requests, operator limit **60 RPM**, connect timeout 15 s, read/write timeout 120 s, automatic retries disabled. Host Python 3.14.2; audio/Parquet client versions are recorded in config/session metadata. Upload: **WAV IEEE FLOAT32, mono 16 kHz** from the shared FP32 waveform; accepted by the successful requests. References and competing predictions were not submitted.

Scored field: **`text` only**. All **2,026** saved successful `raw_transcript` strings are nonempty and **exactly equal to `text`**; field choice does not explain the gap. Submitted flags do not prove every internal processing detail. Responses expose **valsea-4: 982 / valsea-6: 1,044**; these are unverified engine labels, not immutable model revisions. All raw `model_version` and extracted provider versions are null; returned model name absent/null. All 2,026 request IDs are present and distinct. Details: [saved API provenance](../../artifacts/scoring/valsea_vs_gipformer_vimd_20261101/metrics.json) and attempt ledger (excluded local source: `../../artifacts/valsea/valsea_vimd_full_20261101_01/attempts.jsonl`; see FILE_SELECTION.json).

Independently reconciled **2,026 request intents / 2,026 successful outcomes / 2,026 predictions**, zero empty, failed, unresolved, historical unknown, source-error or authorized-retry events. One completed fresh full-test session, no interrupted/resumed full session. Exactly-once remote processing is not guaranteed by the API. The preceding six-validation-clip live smoke has six successful requests and a second no-call resume session; it is separate from full-test counts. Zero observed failures is not a general service-reliability guarantee.

Session metadata (excluded local source: `../../artifacts/valsea/valsea_vimd_full_20261101_01/run_metadata.json`; see FILE_SELECTION.json): **2026-11-01T14:19:20.978850Z–17:52:50.117550Z**, Asia/Saigon **Nov 1 21:19:20.978850–Nov 2 00:52:50.117550**; elapsed **12,809.138700 s**. This includes source preparation, pacing, network/service overhead; per-request elapsed includes upload, service and response transfer, not isolated provider compute. Neither timing is directly comparable to GIP GPU compute latency. **Actual billing/spending is unknown**; no invoice/account usage export is present in the inspected artifacts. Prior public price estimates are not a bill.

## 4. Frozen scoring and primary results

Specification: audit, “Frozen scoring specification” (excluded local source: `VIMD_TEST_MANIFEST_AUDIT.md`; see FILE_SELECTION.json); implementation: [core scorer](../../lifemate/benchmark.py), [single-model scoring](../../scripts/score_vimd_test.py), [paired scorer](../../scripts/compare_vimd_models.py). Exact unique-ID joins retain all 2,026 unchanged official references and both model outputs, regardless of row order. No selection of a better repeated output or response field.

Normalizer **`nfc-lower-punctuation-space-v1`**: NFC → Python lowercase → every Unicode punctuation P* character to space → split/join whitespace collapse. Preserve Vietnamese diacritics, number forms, fillers and repetitions. WER is summed Levenshtein edits on **whitespace tokens**, not linguistic Vietnamese word segmentation; CER uses normalized Unicode code points with spaces removed. Both are corpus sums divided by reference denominators, not average utterance rates. Explicit error/timeout hypotheses score as empty, retaining full denominators; successful empty strings also remain included but are counted separately. Missing/duplicate predictions halt audit rather than silently disappear. Here both runs are fully successful and nonempty.

**Primary full-test results** and **exploratory regional results**, verified from [metrics.json](../../artifacts/scoring/valsea_vs_gipformer_vimd_20261101/metrics.json). Percent values; bracketed paired intervals are absolute percentage points, **VALSEA minus GIPFormer** (negative favors VALSEA).

| Group | GIP WER | VALSEA WER | GIP CER | VALSEA CER | Paired ΔWER [95% CI] | Paired ΔCER [95% CI] |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| **Full test** | **6.992%** | **13.130%** | **5.431%** | **10.379%** | **+6.137 [+5.676, +6.578]** | **+4.948 [+4.546, +5.334]** |
| North | 6.198% | 11.567% | 4.892% | 9.497% | +5.368 [+4.681, +6.153] | +4.605 [+3.955, +5.359] |
| Central | 8.855% | 16.029% | 6.876% | 12.257% | +7.174 [+6.304, +7.983] | +5.381 [+4.660, +6.072] |
| South | 6.198% | 12.308% | 4.729% | 9.699% | +6.110 [+5.413, +6.899] | +4.970 [+4.343, +5.684] |

Full-test single-model 95% intervals: GIP WER **6.683–7.321%**, CER **5.185–5.690%**; VALSEA WER **12.603–13.640%**, CER **9.932–10.813%**. Regional single-model intervals and descriptive province results remain in the [paired report](../../artifacts/scoring/valsea_vs_gipformer_vimd_20261101/report.md), not duplicated here. Unweighted mean of the three regional corpus rates: GIP WER/CER **7.084% / 5.499%**; VALSEA **13.301% / 10.484%**. These regional macros are distinct from full-test corpus micro.

| Model | Word edits / reference tokens | Character edits / reference characters |
| --- | --- | --- |
| GIPFormer | 9,263 / 132,471 | 23,714 / 436,649 |
| VALSEA | 17,393 / 132,471 | 45,319 / 436,649 |

Counts, duration, edits and denominators reconcile across regions/provinces; the saved GIP baseline was independently reproduced in the comparison iteration and not overwritten. Paired per-sample scores (excluded local source: `../../artifacts/scoring/valsea_vs_gipformer_vimd_20261101/per_sample.jsonl`; see FILE_SELECTION.json) retain both raw/normalized texts, scores and source flags.

Bootstrap: **2,000 replicates, seed 42**, sorted source/region strata and supplied speaker IDs; sample speakers with replacement, retain every utterance and repeated-draw multiplicity, recompute corpus ratios. Paired draws apply identical multiplicities to both models. Percentiles use sorted draws at **`int(q*(B-1))`, q=.025/.975**. Regional calls reset the frozen seed. The positive paired intervals support lower GIP reference error here; do not infer a paired difference from separate CI overlap. Zero-containing intervals would be inconclusive, not equivalence. Intervals address sampling uncertainty under these clustering assumptions, not reference errors, speaker misidentification, training leakage, backend drift or distribution mismatch. Regional/province interpretation is exploratory, not a causal accent ranking or LifeMate success measure.

## 5. Exposure, diagnostic findings and human evidence

**Split roles:** six frozen `valid` clips (two per region) were engineering smoke checks, with references kept out of inference. Full `test` then supplied the frozen complete evaluation. Its outputs/references have since been exposed in post-result exploratory analysis and listening packages: **the test is no longer unseen**. Available configurations/handoffs show no model, decoder, normalizer, preprocessing policy or scored-field choice changed in response to test performance. Pre-test Python/precision implementation fixes and later original-audio export transport repair are documented engineering work, not test-driven model tuning. Reference confirmation did not change gold or scores. If future development tunes on these errors, an independent untouched evaluation set is needed for generalization.

**Post hoc findings:** full-corpus mechanical analysis (excluded local source: `../../artifacts/analysis/vimd_comparison_20261102/report.md`; see FILE_SELECTION.json) reports VALSEA lower/equal/higher word edits on **286 / 268 / 1,472** utterances (character edits **353 / 163 / 1,510**). Balanced limitations report (excluded local source: `../../artifacts/analysis/vimd_comparative_limitations_20261102/report.md`; see FILE_SELECTION.json) and 29-record / 47-span evidence (excluded local source: `../../artifacts/analysis/vimd_comparative_limitations_20261102/evidence.jsonl`; see FILE_SELECTION.json) distinguish raw text facts, hypotheses, user observations and reference decisions. These selected-span counts are not corpus linguistic-category accuracy.

- **Local VALSEA advantages:** `handmade` versus GIP `HEN` (20_0306), `Lạc Cái` versus `NÀ CÁI` (12_0241), `Thụy Sơn` versus `THIỆU SƠN` (17_0302), `Inox` versus `IN NÓC` (63_0243). GIP also wins local spans, e.g. `tỉ mỉ` vs VALSEA `tỉ mì` in 20_0306. Utterance WER does not establish recognition of a particular span. No general code-switching/name/term winner is established.
- **Trusted three cases:** Thắng explicitly accepts the official references for 20_0306, 12_0241 and 97_0283 as correct. Whole-utterance word edits GIP/VALSEA remain **25/7, 1/0, 1/90**, respectively. No repeat listening is required for these reference-based conclusions; GIP is not error-free in 97_0283.
- **Limitations of interpretation:** additions relative to a reference are not automatically hallucinations; deletions are not automatically confirmed missing audible speech. Number words versus digits can change scores without proving a wrong value (97_0281, 73_0308). Severe VALSEA subscription-style mismatches (81_0288, 60_0268) are observed text, not an established failure mechanism. Both models have opening material absent from the reference in 77_0282; reference completeness remains a question outside the three confirmed cases. Neither model adjudicates it. Fluency/readability does not prove fidelity; no semantic-slot/task metric exists.

**Human-review evidence checked afresh on 2026-11-02:** the accessible review.csv (excluded local source: `../../artifacts/review/gip15_vimd_test_fp16_20261101_02/review.csv`; see FILE_SELECTION.json) has **0 recorded reviewed unique samples**, 2,026 pending rows, blank reviewer/date/stream/draft/timestamp/notes/proposed-correction fields, and no accepted adjudications. This is **not a claim that Thắng did not listen**: he reports completed manual observations, but their separate storage location and full coverage have not been verified locally. Conversation-attributed evidence exists for **two distinct IDs**, handmade/HEN in 20_0306 and better GIP recognition in 97_0283, plus the three-reference confirmation above. Exact listening times, reference/prediction exposure order, independent drafts, review stream and proposed/accepted corrections for that reported work are unknown. No independent implementor listening or adjudication is claimed; annotations were not overwritten. These storage gaps do not invalidate the completed official-reference scoring.

Existing review methods, not proof of completed coverage: shared protocol (excluded local source: `../../artifacts/review/gip15_vimd_test_fp16_20261101_02/README.md`; see FILE_SELECTION.json) offers a seed-20261101 speaker-round-robin/region-interleaved order and a separate score-driven diagnostic order, sharing one annotation per ID. The 63-province listening package (excluded local source: `../../artifacts/review/vimd_one_per_province/README.md`; see FILE_SELECTION.json) contains **63 verified original-audio/text pairs**, selected by sorted province codes, sorted IDs within province, one `random.Random(42)` instance and one choice per province. No performance-based replacement; 63_0278 was recovered with bounded HTTP ranges and prior failures retained. Package completion is not evidence that all clips were listened to, a representative evaluation sample, or adequate subgroup support.

## 6. Reproduction, essential artifacts and preservation limits

All paths below are relative to this summary; source bundles remain unchanged.

| Need | Existing location |
| --- | --- |
| Dataset identity, all references, source locators/headers/flags | manifests/vimd_test.json (excluded local source: `../../manifests/vimd_test.json`; see FILE_SELECTION.json), audit/spec (excluded local source: `VIMD_TEST_MANIFEST_AUDIT.md`; see FILE_SELECTION.json), saved card (excluded local source: `../../artifacts/gipformer-inspection/dataset_card.txt`; see FILE_SELECTION.json) |
| GIP full run: manifest/config, sessions/logs, raw predictions, summary, ZIP | run directory (excluded local source: `../../artifacts/kaggle_vimd_test/gip15_vimd_test_fp16_20261101_02/`; see FILE_SELECTION.json), predictions (excluded local source: `../../artifacts/kaggle_vimd_test/gip15_vimd_test_fp16_20261101_02/predictions.jsonl`; see FILE_SELECTION.json) |
| GIP original baseline scores/metrics | scoring directory (excluded local source: `../../artifacts/scoring/gip15_vimd_test_fp16_20261101_02/`; see FILE_SELECTION.json) |
| VALSEA config, manifest, raw responses/requests, predictions, metadata/summary | full directory (excluded local source: `../../artifacts/valsea/valsea_vimd_full_20261101_01/`; see FILE_SELECTION.json), six-clip smoke + no-call resume (excluded local source: `../../artifacts/valsea/valsea_vimd_smoke_pacing_20261101_01/`; see FILE_SELECTION.json) |
| Both model metrics, paired differences, province description and all paired rows | [comparison directory](../../artifacts/scoring/valsea_vs_gipformer_vimd_20261101/) |
| Full mechanical audit / selected comparative evidence | mechanical directory (excluded local source: `../../artifacts/analysis/vimd_comparison_20261102/`; see FILE_SELECTION.json), comparative directory (excluded local source: `../../artifacts/analysis/vimd_comparative_limitations_20261102/`; see FILE_SELECTION.json) |
| Original-audio sampler / existing annotation records | province package (excluded local source: `../../artifacts/review/vimd_one_per_province/`; see FILE_SELECTION.json), review protocol/table (excluded local source: `../../artifacts/review/gip15_vimd_test_fp16_20261101_02/`; see FILE_SELECTION.json) |
| Rerunnable pinned local GPU implementation, not a launch instruction | self-contained full-test notebook (excluded local source: `../../notebooks/02_gipformer15_vimd_test_kaggle.ipynb`; see FILE_SELECTION.json), test runner (excluded local source: `../../scripts/gipformer15_vimd_test.py`; see FILE_SELECTION.json), [shared runtime](../../scripts/gipformer15_smoke.py), historical launch handoff (excluded local source: `GIPFORMER15_VIMD_TEST_HANDOFF.md`; see FILE_SELECTION.json) |

**Archived scoring is reproducible without either model, credentials, GPU or audio downloads:** repository, manifest, both saved prediction/run ledgers, verified smoke evidence, baseline scores and standard-library Python suffice (actual scoring Python 3.14.2; focused code compatibility checked previously under 3.12.12). From the package root with authorized external input bundles, commands below reproduce scores/diagnostics from saved inputs; **none was executed during this documentation iteration**:

```powershell
python scripts/score_vimd_test.py
python scripts/compare_vimd_models.py
python scripts/analyze_vimd_errors.py
python scripts/review_vimd_limitations.py
```

The last command regenerates evidence/computed counts, not manually reviewed prose. These commands write their derived outputs; use preserved source artifacts. No inference command is required to reproduce scores.

**Rerunning GIP inference** additionally requires original pinned test audio/shards, checkpoint/tokenizer, pinned upstream/icefall code, Linux/CUDA-compatible native wheels and the recorded T4 environment. Network access to HF/GitHub/PyPI/Torch/native-wheel hosts is needed unless assets are separately staged; those external assets may become unavailable. A pinned rerunnable recipe does not promise bit-identical output on every future runtime. **Hosted inference** additionally requires an authorized account/credit/quota and access to its endpoint; the alias can change even when the request is unchanged. Archived responses/scores are reproducible; the historical remote backend is not pinned or recoverable from exposed version fields.

**Portable export actually verified here:** the existing GIP results ZIP (excluded local source: `../../artifacts/kaggle_vimd_test/gip15_vimd_test_fp16_20261101_02/gip15_vimd_test_fp16_20261101_02_results.zip`; see FILE_SELECTION.json) passes its CRC test and all **14/14** contained files match the local run bundle byte-for-byte. It preserves results, not the entire downloaded environment/audio corpus. VALSEA and analysis artifacts are present locally; no portable VALSEA export or independent off-machine backup was verified. Local existence and a local ZIP are not proof of backup. No new archive or backup infrastructure was created.

## 7. Internal use, rights and open questions

Recorded dataset license: **CC BY-NC-ND 4.0**, from the saved dataset card front matter and manifest provenance; cite **Dinh et al., “Multi-Dialect Vietnamese: Task, Dataset, Baseline Models and Challenges,” EMNLP 2024**, as requested by that card. These are recorded attribution/license facts, not a legal determination of commercial, derivative, third-party-processing or audio-redistribution permission. Keep the internal audio package distinct from any public-release claim. Permission to benchmark does not automatically grant permission to redistribute audio or train on service outputs.

The existing research §3.4 (excluded local source: `../research/THANG_LifeMate_Deep_Research_COMPLETE_2026-10-31.md`; see FILE_SELECTION.json) records a 31 October policy finding about written permission for training competing models on service outputs. Applicable account contract, current publication terms and any written training/redistribution authorization are **not verified in accessible evidence**; no live legal/terms check or provider contact occurred here. No keys, authorization headers or secret values belong in this summary. Nothing was published/uploaded.

Material limits that **do not undo this completed benchmark**: source/reference conventions outside confirmed cases; supplied speaker identity/overlap and unassessed audio duplication/training exposure; limited domain and linguistic annotations; API backend immutability; human-note storage/coverage; no measured critical-slot or LifeMate task success. **Prerequisites for a future action**, rather than blockers to current results: establish data/access/rights and trustworthy split/labels before another corpus; establish written permissions before any proposed training/redistribution; assess A30 offline end-to-end behavior before contest/deployment claims. Contest asset-release/cutoff eligibility needs separate verification: a revision pin alone does not establish its release date. Actual spending and off-machine backup status remain unknown.

**Proposed next iteration — dataset audit only:** determine what independent data can answer (1) whether the GIP advantage persists outside ViMD, (2) how both systems handle shared English/name/number spans, (3) recognition differences versus transcription conventions, and (4) what independently labeled critical information is needed for LifeMate. Audit access, provenance, source audio/labels, split/speaker separation, coverage and applicable rights before selecting the next evaluation. Older LSVSC/VN-SLU suggestions remain candidates, not automatic commitments. Agree practical application-linked acceptance criteria **before** seeing next-evaluation results; no thresholds are invented from the current winner. No next audit, additional inference or training was launched by this handoff. Official-reference results remain immutable; any later adjudicated reference analysis must be separately versioned.

The next-iteration proposal above was written at the ViMD-only handoff stage and is retained as history. The combined closeout supersedes it as the current completion and handoff record.

## Consolidation verification

Re-read current configs, summaries, request ledger, metrics, manifest/card, comparative evidence and accessible review notes. Checked displayed metrics/intervals, counts/durations, IDs/revisions/settings, ZIP integrity/member equality and local links. This was documentation-only: no full unrelated test-suite run, scoring rerun, source/annotation modification, new experiment or external API call. Historical handoffs retain their original dates/status; use the combined closeout linked above for current completion state and this summary for ViMD detail.
