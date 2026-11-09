# VN-SLU: VALSEA versus GIPFormer

**GIPFormer 1.5: FP16 weights with mixed computation, greedy decoding.**
**VALSEA/Glot: recorded glot-transcribe alias; submitted correction/tags/diarization disabled; scored response text.**

| Model | Word edits / reference tokens | WER | Character edits / reference characters | CER |
| --- | ---: | ---: | ---: | ---: |
| GIPFormer | 6,566 / 32,351 | 20.296% | 18,172 / 102,236 | 17.775% |
| VALSEA | 5,661 / 32,351 | 17.499% | 12,788 / 102,236 | 12.508% |

VALSEA minus GIPFormer: **WER -2.797 percentage points; CER -5.266 percentage points**. Negative favors VALSEA. Deltas use unrounded corpus ratios. These are descriptive paired differences, without uncertainty intervals or significance claims.
Both models: 2,401 expected / 2,401 recorded / 2401 and 2401 successful respectively; 0 / 0 inference errors; 0 / 0 empty successful texts. Source duration **11768.119625 s (3.268922 h)**, identical denominators and all official records retained.

## Independent execution validation

Both archived test manifests equal the canonical manifest. Exact ID joins reject duplicates, missing/unknown IDs, malformed statuses or duration disagreements. GIPFormer configuration, final child exit 0/completed inference and package freezes revalidate against its accepted pinned single-T4/cuda:0 setup; recomputed scores match every saved baseline row and all overall/intent additive totals. Existing baseline artifacts were not overwritten.
VALSEA chronological attempt replay verifies successful response text equals its persisted prediction, no already successful ID was resubmitted/replaced, all retries were explicitly authorized, no blocked work remains, and final sessions are complete. Dev smoke/full endpoint, flags, upload, preprocessing, code and package configuration match, allowing only mode/split differences. Six dev smoke requests succeeded; the recorded completed smoke-resume session contains no new request outcomes. No smoke recognition score was calculated.
Full VALSEA event counts: `{'started': 2402, 'ok': 2401, 'unresolved': 1, 'retry_authorized': 1}`. Historical HTTP 502 at attempt 2340 for `VN-SLU/test/659d1013ff471bbe244b9ccd` remains an unknown remote outcome. An explicit operator note authorizes its retry; successful retry does not prove the first request was unprocessed/unbilled. Outstanding unresolved/blocked samples: zero. **Exactly-once remote processing is not guaranteed.**

## Provider and execution provenance

Source runs: GIPFormer `gip15_vnslu_test_fp16_20261102_06`; VALSEA `valsea_vnslu_test_20261102_01`; dev smoke `valsea_vnslu_dev_smoke_20261102_01`.
GIPFormer pinned model/source revisions: `{'gipformer': '0cac5b183d2e1a9e3429ff69080e09cc62ebdf9b', 'icefall': '9c966762e058bd7ba79d9da71e42fc06b64b703e', 'model': 'dd9227dcd8705c13f33bdbe59728d546ab94480f'}`. Author README revision `aad93e560f8ec4ab979e76d5dfe36528160b797f` pins README, not mutable Drive assets; preserved release provenance remains in metrics.json.
Full-run exposed engine counts: {'valsea-4': 802, 'valsea-6': 1599}. These labels have unverified meanings; no engine ranking or immutable revision is inferred. Per-session variation and missing version fields are retained below and in metrics.json.

| VALSEA session UTC start → end | Status | Successful outcomes | Engine labels |
| --- | --- | ---: | --- |
| 2026-11-02T09:07:10.999343+00:00 → 2026-11-02T11:47:18.505932+00:00 | stopped | 2339 | {'valsea-4': 780, 'valsea-6': 1559} |
| 2026-11-02T13:39:13.637210+00:00 → 2026-11-02T13:43:36.426609+00:00 | completed | 62 | {'valsea-4': 22, 'valsea-6': 40} |

Provider model_version: `[{'value': None, 'count': 2401, 'first_observed_utc': '2026-11-02T09:07:18.294719+00:00', 'last_observed_utc': '2026-11-02T13:43:36.405965+00:00'}]`. Exposed provider version: `[{'value': None, 'count': 2401, 'first_observed_utc': '2026-11-02T09:07:18.294719+00:00', 'last_observed_utc': '2026-11-02T13:43:36.405965+00:00'}]`. Request IDs present/distinct: 2401/2401.
All execution dates are 2026-11-02. UTC session times above correspond to Asia/Saigon UTC+07:00. GIPFormer executed 07:13:06–07:25:16 UTC (14:13:06–14:25:16 Asia/Saigon). No API elapsed-time versus local-model compute-latency comparison is made. Requested flags do not independently establish all backend processing details.

## Per-sample edit-count comparisons

Counts describe VALSEA having fewer/equal/more edits than GIPFormer on the same record; they are not corpus WER/CER or semantic wins. Corpus ratios weight by reference denominators, not utterance win counts.

| Edits | Lower | Equal | Higher |
| --- | ---: | ---: | ---: |
| word | 1068 | 653 | 680 |
| character | 1283 | 450 | 668 |

## Descriptive supplied-intent groups

All 28 original labels retained. These are ASR reference-agreement groups, not predicted-intent accuracy or statistically established category rankings. Each cell G / V denotes GIPFormer / VALSEA. Shared counts, durations and denominators reconcile to the whole test.

| Official intent | N | Seconds | Ref words | Word edits G / V | WER G / V | ΔWER pp | Ref chars | Char edits G / V | CER G / V | ΔCER pp |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bật nhạc | 176 | 903.297812 | 2377 | 649 / 478 | 27.303% / 20.109% | -7.194 | 7887 | 1814 / 1084 | 23.000% / 13.744% | -9.256 |
| bật thiết bị | 91 | 340.860000 | 990 | 165 / 149 | 16.667% / 15.051% | -1.616 | 3065 | 450 / 310 | 14.682% / 10.114% | -4.568 |
| giảm mức độ của thiết bị | 9 | 39.840000 | 103 | 28 / 18 | 27.184% / 17.476% | -9.709 | 318 | 73 / 43 | 22.956% / 13.522% | -9.434 |
| giảm nhiệt độ của thiết bị | 10 | 53.880000 | 135 | 40 / 21 | 29.630% / 15.556% | -14.074 | 388 | 126 / 29 | 32.474% / 7.474% | -25.000 |
| giảm âm lượng của thiết bị | 3 | 19.080000 | 38 | 17 / 6 | 44.737% / 15.789% | -28.947 | 135 | 48 / 16 | 35.556% / 11.852% | -23.704 |
| giảm độ sáng của thiết bị | 56 | 229.860000 | 611 | 242 / 110 | 39.607% / 18.003% | -21.604 | 1937 | 754 / 230 | 38.926% / 11.874% | -27.052 |
| gọi taxi | 145 | 736.132938 | 1866 | 352 / 315 | 18.864% / 16.881% | -1.983 | 6011 | 940 / 698 | 15.638% / 11.612% | -4.026 |
| gợi ý phim | 180 | 985.962688 | 2749 | 564 / 426 | 20.517% / 15.497% | -5.020 | 8752 | 1586 / 1054 | 18.122% / 12.043% | -6.079 |
| gợi ý địa điểm | 126 | 760.966812 | 2207 | 418 / 372 | 18.940% / 16.855% | -2.084 | 6859 | 1024 / 782 | 14.929% / 11.401% | -3.528 |
| hỏi thông tin | 76 | 346.589625 | 902 | 113 / 151 | 12.528% / 16.741% | +4.213 | 2946 | 341 / 382 | 11.575% / 12.967% | +1.392 |
| hủy hoạt cảnh | 21 | 85.800000 | 278 | 39 / 46 | 14.029% / 16.547% | +2.518 | 864 | 109 / 94 | 12.616% / 10.880% | -1.736 |
| kiểm tra tình trạng thiết bị | 88 | 350.160000 | 1105 | 154 / 199 | 13.937% / 18.009% | +4.072 | 3437 | 379 / 426 | 11.027% / 12.395% | +1.367 |
| kích hoạt cảnh | 39 | 181.380000 | 514 | 64 / 26 | 12.451% / 5.058% | -7.393 | 1656 | 170 / 50 | 10.266% / 3.019% | -7.246 |
| mở thiết bị | 86 | 311.700000 | 912 | 148 / 140 | 16.228% / 15.351% | -0.877 | 2701 | 352 / 261 | 13.032% / 9.663% | -3.369 |
| tra công thức nấu ăn | 161 | 941.959125 | 2484 | 422 / 363 | 16.989% / 14.614% | -2.375 | 7906 | 1134 / 847 | 14.344% / 10.713% | -3.630 |
| tra cứu lịch | 113 | 585.946937 | 1660 | 311 / 324 | 18.735% / 19.518% | +0.783 | 5121 | 907 / 784 | 17.711% / 15.310% | -2.402 |
| tra cứu thời tiết | 147 | 746.669313 | 2098 | 356 / 356 | 16.969% / 16.969% | +0.000 | 6770 | 1016 / 874 | 15.007% / 12.910% | -2.097 |
| tra cứu đường đi | 124 | 672.404250 | 1863 | 507 / 454 | 27.214% / 24.369% | -2.845 | 6086 | 1311 / 903 | 21.541% / 14.837% | -6.704 |
| tăng mức độ của thiết bị | 7 | 33.120000 | 93 | 19 / 12 | 20.430% / 12.903% | -7.527 | 295 | 47 / 24 | 15.932% / 8.136% | -7.797 |
| tăng nhiệt độ của thiết bị | 14 | 70.980000 | 195 | 45 / 24 | 23.077% / 12.308% | -10.769 | 594 | 139 / 42 | 23.401% / 7.071% | -16.330 |
| tăng âm lượng của thiết bị | 5 | 21.000000 | 56 | 14 / 21 | 25.000% / 37.500% | +12.500 | 181 | 35 / 37 | 19.337% / 20.442% | +1.105 |
| tăng độ sáng của thiết bị | 62 | 271.380000 | 702 | 297 / 97 | 42.308% / 13.818% | -28.490 | 2194 | 948 / 189 | 43.209% / 8.614% | -34.594 |
| tắt thiết bị | 80 | 289.130688 | 799 | 120 / 130 | 15.019% / 16.270% | +1.252 | 2481 | 293 / 291 | 11.810% / 11.729% | -0.081 |
| xóa lịch | 109 | 469.301688 | 1157 | 274 / 317 | 23.682% / 27.398% | +3.717 | 3713 | 816 / 822 | 21.977% / 22.138% | +0.162 |
| đóng thiết bị | 96 | 347.160000 | 1035 | 146 / 188 | 14.106% / 18.164% | +4.058 | 3222 | 365 / 374 | 11.328% / 11.608% | +0.279 |
| đặt lịch | 124 | 659.093000 | 1830 | 411 / 279 | 22.459% / 15.246% | -7.213 | 5667 | 1211 / 592 | 21.369% / 10.446% | -10.923 |
| đặt vé | 123 | 687.016438 | 1820 | 325 / 283 | 17.857% / 15.549% | -2.308 | 5540 | 911 / 658 | 16.444% / 11.877% | -4.567 |
| đặt đồ ăn | 130 | 627.448313 | 1772 | 326 / 356 | 18.397% / 20.090% | +1.693 | 5510 | 873 / 892 | 15.844% / 16.189% | +0.345 |

Intent-group delta directions (VALSEA lower/equal/higher): WER {'lower': 18, 'equal': 1, 'higher': 9}; CER {'lower': 22, 'equal': 0, 'higher': 6}. Group counts are not sample-weighted headline rates or established category capabilities.
For example, tăng độ sáng của thiết bị (62 clips) is 42.308% / 13.818% WER (GIPFormer / VALSEA), while hỏi thông tin (76) is 12.528% / 16.741% and kiểm tra tình trạng thiết bị (88) is 13.937% / 18.009%. Thus the overall direction does not hold for every intent. The volume-change groups have only three/five clips; their large displayed deltas do not establish stable population effects. These statements describe the frozen scores, not error mechanisms or semantic accuracy.

## Frozen protocol and boundaries

NFC → lowercase → Unicode P* punctuation to spaces → whitespace collapse; preserve Vietnamese diacritics, number forms, fillers and repetitions. WER uses whitespace-token Levenshtein (not linguistic word segmentation); CER uses normalized Unicode code points with spaces removed. Corpus summed edits/reference denominators, never mean utterance rates. Successful empty text stays included with full denominators; empty normalized references reject scoring. VALSEA text alone is scored; raw_transcript remains existing evidence, not an alternative selected hypothesis.
This is the author-released official **2,401-sample** VN-SLU test, distinct from the paper’s **2,454** count. Official sentence references, intent/entities, issue flags and scoring policy are unchanged. Strict scoring penalizes number-format differences; prior numeric diagnostics are not applied and no alternate numeric headline score is produced.
Speaker/region metadata is absent. Confidence intervals under the established speaker-cluster protocol are unavailable; no fabricated clusters, regional results, utterance-bootstrap substitute, significance tests or universal superiority claims. No intent accuracy, SLU-F1, slot correctness or LifeMate task success is measured. VN-SLU and ViMD describe different datasets and must not be pooled. Release-license/API-upload permission is not established by this offline scoring exercise.

## Reproduction and validation

`python scripts/compare_vnslu_models.py` from the package root with authorized external input bundles produces only paired rows (excluded local source: `per_sample.jsonl`; see FILE_SELECTION.json), [metrics](metrics.json) and this report. Existing matching outputs can be reused; conflicting outputs are refused. Tests: `python -m unittest discover -s tests -p test_compare_vnslu_models.py -v`.
Input text artifacts are snapshotted and verified byte-unchanged before output. Source run histories, baseline scores and canonical labels remain untouched. CPU/standard-library scoring only: no network/API/model calls, audio access, dependency upgrades, gold edits or changes to the completed ViMD benchmark. Stop after comparison; no further error analysis was performed.

Handoff: independent full-run validation and actual CPU scoring completed. **11 focused comparison tests and 7 existing VN-SLU scorer tests passed**, plus Python compilation. Full/intent counts, durations, edit totals and common denominators reconcile; the 2,401 saved GIPFormer per-sample scores reproduce exactly. Historical 502/retry and engine variation remain documented; no immutable provider revision or uncertainty interval is available. No execution/scoring blocker remains.
