# ViMD + VN-SLU ASR benchmark — canonical closeout

**Updated 2026-11-07, Asia/Saigon.** Thắng’s completed benchmark compares GIPFormer 1.5, VALSEA/Glot and QUAN-Transcribe-1.0 on the complete released ViMD and VN-SLU test splits. It measures agreement with official references across multi-dialect speech and spoken assistant requests. Inference and CPU scoring are complete for all three systems. Exhaustive reference adjudication and downstream LifeMate task evaluation are not complete.

**Recommendation for team review:** use **GIPFormer 1.5 as LifeMate’s primary ASR baseline**. It has the lowest WER/CER on ViMD overall and in all three reported regions, outperforms QUAN on both datasets, and has a verified single-T4 path with locally pinnable code/checkpoint/dependencies. **VALSEA has the lowest WER/CER on VN-SLU** and remains a comparison candidate; this establishes no automatic fallback/routing policy. QUAN has not demonstrated an accuracy advantage sufficient to replace GIPFormer in these tests. This is a benchmark-supported recommendation, **not a ratified team decision or universal ranking**. Do not average the datasets into a combined winner.

## Datasets and complete coverage

| Official test | Coverage and distribution | Version and retained issues |
| --- | --- | --- |
| ViMD, Vietnamese multi-dialect speech | 2,026 clips; 39,140.477305 s (10.872355 h); 1,344 supplied speaker IDs; 63 source provinces; North 783, Central 623, South 620 | Dataset revision `3a5b30157034e7eadd5c75fae1a820c6f9383398`; all three `speaker_overlap_valid` records retained. TienGiang and BacLieu have only 10 speakers each; coverage is not a sufficiency claim. |
| VN-SLU, spoken Vietnamese assistant commands/questions | 2,401 author-released test clips; 11,768.119625 s (3.268922 h); 28 supplied intents; speaker/region metadata unavailable | Author README revision `aad93e560f8ec4ab979e76d5dfe36528160b797f`; Drive snapshot `2026-11-02T04:18:29.627357+00:00`. The README pin does not freeze mutable Drive assets. All 20 repeated-reference flags retained. Released count 2,401 differs from paper count 2,454; no records repaired to force that count. |

Canonical membership, original references and labels are unchanged; dataset manifests and preparation/audit files are identified in the source map below. No duration/difficulty/digit filter, cap or downsampling was used. Speaker-ID overlap is observed metadata, not proof of training leakage.

Each model has exactly 2,026 / 2,401 unique successful final predictions and zero inference errors. GIPFormer and VALSEA have no empty predictions; QUAN has zero on ViMD and **two unchanged successful empty VN-SLU predictions**:
`VN-SLU/test/659ea4ef3e9a97673ad897c8` (8 word / 21 character deletions) and `VN-SLU/test/659ebc663e9a97673ad89866` (12 / 35). Both retain their full reference denominators. Final coverage is distinct from historical request failures or recognition quality.

## Frozen scoring and results

Common normalizer **`nfc-lower-punctuation-space-v1`**: NFC → lowercase → Unicode P* punctuation to spaces → whitespace collapse. Preserve diacritics, number forms, fillers and repetitions. WER uses whitespace tokens, not linguistic Vietnamese word segmentation. CER uses normalized Unicode code points with spaces removed. Corpus ratios divide **summed Levenshtein edits by summed reference denominators**, never average utterance rates. Empty/error hypotheses retain all denominators; missing/duplicate/unknown IDs or empty normalized references block scoring. No number-equivalence correction changes headline scores.

Checked against saved [three-model ViMD metrics](../../artifacts/scoring/quan_vs_baselines_20261107/vimd/metrics.json) and [VN-SLU metrics](../../artifacts/scoring/quan_vs_baselines_20261107/vnslu/metrics.json). Rates are percentages.

| Official test | Model | Word edits / reference tokens | WER | Character edits / reference characters | CER |
| --- | --- | ---: | ---: | ---: | ---: |
| ViMD | GIPFormer | 9,263 / 132,471 | 6.992% | 23,714 / 436,649 | 5.431% |
| ViMD | VALSEA | 17,393 / 132,471 | 13.130% | 45,319 / 436,649 | 10.379% |
| ViMD | QUAN | 13,081 / 132,471 | 9.875% | 31,958 / 436,649 | 7.319% |
| VN-SLU | GIPFormer | 6,566 / 32,351 | 20.296% | 18,172 / 102,236 | 17.775% |
| VN-SLU | VALSEA | 5,661 / 32,351 | 17.499% | 12,788 / 102,236 | 12.508% |
| VN-SLU | QUAN | 8,349 / 32,351 | 25.808% | 22,070 / 102,236 | 21.587% |

### Paired differences and uncertainty

Differences use unrounded saved ratios, in absolute percentage points. Each row is **first model minus second**; a negative difference favors the first. Brackets are saved ViMD paired 95% speaker-cluster intervals.

| Test | Comparison | ΔWER pp [95% CI] | ΔCER pp [95% CI] |
| --- | --- | --- | --- |
| ViMD | VALSEA − GIPFormer | +6.137 [+5.676, +6.578] | +4.948 [+4.546, +5.334] |
| ViMD | QUAN − GIPFormer | +2.882 [+2.687, +3.081] | +1.888 [+1.745, +2.034] |
| ViMD | QUAN − VALSEA | −3.255 [−3.665, −2.813] | −3.060 [−3.419, −2.680] |
| VN-SLU | VALSEA − GIPFormer | −2.797; unavailable | −5.266; unavailable |
| VN-SLU | QUAN − GIPFormer | +5.511; unavailable | +3.813; unavailable |
| VN-SLU | QUAN − VALSEA | +8.309; unavailable | +9.079; unavailable |

ViMD uses 2,000 paired speaker draws, seed 42, sorted source/region strata and speaker IDs; all utterances and repeated-draw multiplicities are retained with identical draws for both models. Percentile indices are `int(q*(B-1))`, q=.025/.975; each overall/regional call resets the seed. These intervals do not quantify unknown training exposure or reference errors. An interval containing zero is inconclusive under this analysis, not proof of equivalence; separate-model interval overlap is not a paired comparison.

| ViMD region | Clips / speakers | GIPFormer WER / CER | VALSEA WER / CER | QUAN WER / CER |
| --- | ---: | ---: | ---: | ---: |
| North | 783 / 528 | 6.198% / 4.892% | 11.567% / 9.497% | 8.415% / 6.510% |
| Central | 623 / 444 | 8.855% / 6.876% | 16.029% / 12.257% | 12.635% / 9.296% |
| South | 620 / 372 | 6.198% / 4.729% | 12.308% / 9.699% | 9.055% / 6.450% |

GIPFormer’s advantage over each model has paired regional WER/CER intervals excluding zero. Regional findings remain exploratory. [ViMD three-model report](../../artifacts/scoring/quan_vs_baselines_20261107/vimd/report.md) contains exact regional intervals, single-model intervals, descriptive province counts/denominators and unweighted regional macros. [VN-SLU report](../../artifacts/scoring/quan_vs_baselines_20261107/vnslu/report.md) retains all 28 descriptive intent groups; these are ASR groups, not intent accuracy. Its missing speaker metadata makes speaker-cluster intervals unavailable: no invented clusters or utterance-bootstrap substitute. Neither subgroup counts nor selected examples establish population superiority.

## Actual configurations and reproducibility

**GIPFormer:** `g-group-ai-lab/gipformer1.5-68M-rnnt`; checkpoint/tokenizer revision `dd9227dcd8705c13f33bdbe59728d546ab94480f`, upstream code `0cac5b183d2e1a9e3429ff69080e09cc62ebdf9b`, icefall `9c966762e058bd7ba79d9da71e42fc06b64b703e`. FP16 weights with mixed computation and permitted FP32 internals, CPU FP32 audio/fbank; explicit `greedy_search_batch`, max symbols/frame 1, blank penalty 0, **batch 1**, **one visible T4 / cuda:0**. Isolated CPython 3.12.12, Torch/torchaudio 2.8.0+cu128, seed 20261031 and deterministic settings; exact dependencies, native wheels, code, checkpoint checks and observed runtime stay in each run’s configuration/metadata. This is not pure-FP16 arithmetic or a contest A30 end-to-end runtime certification.

**VALSEA/Glot:** recorded endpoint `https://api.glotlabs.ai/v1/audio/transcriptions`, alias `glot-transcribe`, language `vietnamese`; submitted `enable_correction=false`, `enable_tags=false`, `diarize=false`, `response_format=verbose_json`; scored **response `text` only**. `raw_transcript` remains response evidence, never a quality-selected alternative. Shared mono 16 kHz FP32 preprocessing; API upload IEEE FLOAT32 WAV. Requested flags do not independently establish all backend processing. Engine labels `valsea-4`/`valsea-6` vary and are **not immutable model revisions**: ViMD counts 982/1,044, VN-SLU 802/1,599. Exposed model/provider-version values are null. Execution dates, packages, request IDs and raw responses remain in the archived ledgers; no historical backend revision is invented.

**QUAN:** `qnguyen3/QUAN-Transcribe-1.0`; checkpoint `a08726d9fffeb5f16fc1ab05eecc8ad0b86af5a0`, inference code `88ddcd2130a3c355d081bc002439f29e5e849060`; encoder/tokenizer/feature extractor `f9972ac22e696a105c482202646979e33e4b5a1e` (`google/embeddinggemma-2`). **FP32 weights, FP16 outer CUDA autocast and explicit FP32 log-mel/audio attention/CTC head**, not FP16 weights or BF16 inference. Returned diagnostics confirm 12 FP32 attention modules, original −1e9 invalid-logit sentinel, FP32 attention outputs/logits, isolated Python 3.12.12, Torch CUDA 12.8 and one visible T4 / `cuda:0`. Greedy CTC, `use_lm=False`, batch 1, seed 20261031, deterministic algorithms; contiguous ≤30 s chunks retain every sample including the short tail, no VAD/denoising/trimming. Shared CPU float32 mono/resample-to-16-kHz preprocessing; 56 pinned installed versions match the lock. The 707 missing overlay keys are encoder-only, with zero missing reader/unexpected keys. **Equivalence of this attention/precision repair to upstream execution has not been established.**

Actual QUAN runs: `quan_vimd_fp16amp_20261107_01` (2026-11-07 15:39:24–15:52:07 UTC) and `quan_vnslu_fp16amp_20261107_01` (16:06:22–16:12:12 UTC). Scoring handoff, ViMD returned-artifact review and VN-SLU review preserve archive, configuration, completion and precision checks. The manual launcher handoff retains historical setup/failure context.

The configurations and deployment conditions differ. No comparable latency, cost or memory experiment establishes superiority. API timing includes transfer/service overhead; whole Kaggle session time includes setup and is not isolated inference latency/RTF. Single-T4 ASR execution does not certify end-to-end A30 contest compliance or all-system precision policy.

Historical VALSEA accounting remains unchanged: ViMD 2,026 requests/successes with no recorded retry; VN-SLU 2,402 started requests, 2,401 successes, one HTTP 502 unknown remote outcome at attempt 2340 (`VN-SLU/test/659d1013ff471bbe244b9ccd`), explicit operator authorization, then successful retry. No final blocked/unresolved samples remain, but the historical unknown remains one. No already-successful prediction was replaced; exactly-once remote processing/billing is not proven.

### Evidence and supported reproduction

**Included in this package:** current three-model [ViMD report](../../artifacts/scoring/quan_vs_baselines_20261107/vimd/report.md) / [metrics](../../artifacts/scoring/quan_vs_baselines_20261107/vimd/metrics.json) and [VN-SLU report](../../artifacts/scoring/quan_vs_baselines_20261107/vnslu/report.md) / [metrics](../../artifacts/scoring/quan_vs_baselines_20261107/vnslu/metrics.json), including run IDs, revisions, API provenance, unrounded ratios and bootstrap settings. The [ViMD detailed handoff](VIMD_BENCHMARK_SUMMARY.md), [original ViMD comparison](../../artifacts/scoring/valsea_vs_gipformer_vimd_20261101/report.md) and [original VN-SLU comparison](../../artifacts/scoring/valsea_vs_gipformer_vnslu_20261102/report.md) are historical two-model evidence. Historical [ViMD scoring](../../scripts/score_vimd_test.py), [VN-SLU scoring](../../scripts/score_vnslu_test.py) and comparison utilities are included; QUAN's integration scorer is not.

**Retained in the source workspace:** these locators preserve the source-to-evidence mapping. They are relative to this document’s original source location, not links to bundled files.

| Evidence | Source-workspace locator |
| --- | --- |
| ViMD membership and frozen audit/specification | `../../manifests/vimd_test.json`; `VIMD_TEST_MANIFEST_AUDIT.md` |
| VN-SLU membership and preparation | `../../manifests/vnslu_test.json`; `VNSLU_TEST_PREPARATION.md` |
| QUAN scoring/validation and manual setup | `QUAN_SCORING_HANDOFF.md`; `QUAN_BENCHMARK_HANDOFF.md` |
| QUAN returned-run archive/configuration/precision reviews | `QUAN_VIMD_RESULT_REVIEW.md`; `QUAN_VNSLU_RESULT_REVIEW.md` |
| Exact ViMD paired texts, labels and flags | `../../artifacts/scoring/quan_vs_baselines_20261107/vimd/per_sample.jsonl` |
| Exact VN-SLU paired texts, labels and flags | `../../artifacts/scoring/quan_vs_baselines_20261107/vnslu/per_sample.jsonl` |
| QUAN integration scorer | `../../scripts/score_quan_comparison.py` |
| VN-SLU numeric, device-ID and name observations below | `../../artifacts/analysis/vnslu_paired_errors/report.md#individual-paired-text-review` |
| Three ViMD reference-confirmed examples | `../../artifacts/analysis/vimd_comparative_limitations_20261102/report.md#reference-confirmation-for-three-cases` |

**Complete rescoring requires** the source-workspace QUAN integration scorer plus authorized original manifests, predictions, configurations, attempt ledgers and historical baseline scores at their documented locations. From that complete workspace, `python -X utf8 scripts/score_quan_comparison.py` reproduces the six derived files; its scoring handoff records dependencies and separate-output options. This portable aggregate package cannot independently reproduce full QUAN scoring. Reproducing saved text scores is distinct from recreating a mutable hosted backend. No scoring/replay command was run for this documentation update.

## Historical GIPFormer–VALSEA diagnostic findings

Full mechanical coverage is complete for both datasets. ViMD’s balanced individual text review covers **29 utterances / 47 selected spans**, not 2,026 semantic adjudications. Its [existing review status](VIMD_BENCHMARK_SUMMARY.md#5-exposure-diagnostic-findings-and-human-evidence) distinguishes user-reported listening observations from implementor text-only inspection: the accessible review table has no recorded completed adjudications; the complete 63-province listening package does not prove all clips were listened to. Thắng’s explicit reference confirmations for three cases remain valid and do not require repeat listening.

VN-SLU uses **2,877 shared reference numeric candidates / 5,252 official entity occurrences**, identical rules and occurrence mapping for both models. Individual paired text inspection covers **65 views across 60 records**; the **94 prior GIPFormer-only views across 83 records** are attributed separately, not counted as VALSEA review. Unresolved mappings remain visible, not silently wrong or excluded.

**Mixture, not a single explanation:** 982 shared numeric occurrences have GIPFormer’s supported equivalent representation and VALSEA’s exact reference form. GIPFormer’s **2,291 representation-associated word edits (34.89% of 6,566)** are edits within expressions classified by the documented rules/mapping as equal in value/unit but different in representation. This is **diagnostic attribution, not corrected WER or a causal decomposition of the model gap**. VALSEA has 237 such attributed edits. Content agreement also differs in both directions; local equivalence is not complete intent/semantic equivalence. The narrow boundary-unit mapping correction and its four affected VALSEA views are documented in the paired report; prior GIPFormer evidence and headline scores remain unchanged.

Illustrative cases, with exact full texts/mapping evidence identified in the source map above:

- **Numeric value:** VN-SLU `648c833ff73a5730717d42a3`: reference 33%; GIPFormer says 3%, VALSEA preserves 33%. Both change reference 11:30 to 1:30 in `652d5d0ecf7989dd5bd6d456`.
- **Device ID counterexample:** `652cd9c02cf3931147df9c19`: GIPFormer preserves 11 as words; VALSEA says 21 despite fewer whole-utterance edits. Whole WER advantage does not establish correctness of this identifier.
- **Names/foreign terms in both directions:** VALSEA preserves *Waiting for You* where GIPFormer changes the title (`65943e6b2883f803e891c047`); GIPFormer preserves *sơn tùng mtp* where VALSEA says *Sơn Thùng MTP* (`659d098fff471bbe244b9c72`). On ViMD, VALSEA preserves *handmade* where GIPFormer has *HEN*, while GIPFormer better matches *tỉ mỉ* in that same utterance, `20_0306`. These examples do not establish general English/name superiority.

## Limitations and next validation

- WER/CER measure official-reference agreement, not intent, slot, target/value/time/tool correctness, tool-call score or LifeMate task success. Strict number-representation differences can inflate errors; the numeric diagnostics above are scoped evidence, not semantic equivalence for every sample or corrected headline scores. Local English/name advantages do not establish general superiority.
- **QUAN’s model card lists ViMD among training sources; test-split overlap remains unverified. ViMD is not confirmed unseen evaluation.** Training overlap is not fully established for GIPFormer or VALSEA either. Post-result evaluation records must not become training material or automatic gold.
- QUAN’s repaired precision has not been proven equivalent to upstream execution. VALSEA’s exposed engine labels have unverified meanings and no immutable provider revision; neither requested flags nor HTTP success prove all backend processing details. Retain retry history rather than infer exactly-once service execution.
- Reference correctness, rare-subgroup adequacy and generalization to LifeMate remain incompletely verified. Selective text/listening reviews are not exhaustive gold validation. Thắng’s reference confirmations for three ViMD examples remain preserved in the historical review; no new gold edits or listening claims are made.
- Redistribution/remote-processing/training permissions are not established by completed runs: recorded ViMD CC BY-NC-ND 4.0, unspecified VN-SLU release license and provider-output terms remain qualified. Aggregate findings do not authorize distribution of underlying audio/reference/provider text. No new legal/terms research was performed.

**Smallest useful next validation:** compare the same eligible LifeMate tasks with **gold transcripts versus audio processed by GIPFormer**, using matched contexts/history/tool permissions. Measure downstream target, value, time, tool-selection and task/state errors, with ASR-caused discrepancies separated from agent failures. This would test whether the benchmark-supported baseline preserves application-critical information. It is a proposal, not an executed experiment or harness acceptance. Do not conclude that fine-tuning is necessary or unnecessary before that evidence exists; do not infer routing, pseudo-labeling or deployment approval.

## Documentation verification history

The original 2026-11-02 two-model documentation closeout checked 112 local links and 134 protected source/result/code files; those historical counts are not new checks. The later QUAN scoring iteration ran 51 CPU tests and reproduced six scoring files byte-for-byte; those results are recorded in its handoff, not rerun here. This 2026-11-07 documentation-only extension reads saved metrics/reviews, checks ratios/deltas/intervals and package links/selection, and preserves benchmark evidence and pending synthetic statuses. Its actual checks are recorded in the team package VALIDATION.md. No inference, API/network call, audio access/download, scoring rerun, gold change or new experiment is part of this update.
