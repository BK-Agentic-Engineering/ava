# QUAN versus GIPFormer and VALSEA — VNSLU

- **QUAN-Transcribe-1.0: FP32 weights, FP16 autocast; explicit FP32 audio attention/features/CTC head; greedy CTC**
- **GIPFormer 1.5: FP16 weights with mixed computation; greedy decoding**
- **VALSEA/Glot glot-transcribe: submitted correction/tags/diarization false; scored response text only**

## Corpus official-reference agreement

| Model | N | Word edits / ref tokens | WER | Character edits / ref characters | CER | Empty successes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| quan | 2401 | 8349 / 32351 | 25.808% | 22070 / 102236 | 21.587% | 2 |
| gipformer | 2401 | 6566 / 32351 | 20.296% | 18172 / 102236 | 17.775% | 0 |
| valsea | 2401 | 5661 / 32351 | 17.499% | 12788 / 102236 | 12.508% | 0 |

## Paired differences

QUAN minus baseline, absolute percentage points; negative favors QUAN. Corpus ratios are used, never averaged utterance rates.

| Baseline | Scope | ΔWER pp | Paired 95% CI | ΔCER pp | Paired 95% CI |
| --- | --- | ---: | --- | ---: | --- |
| gipformer | overall | +5.511 | unavailable | +3.813 | unavailable |
| valsea | overall | +8.309 | unavailable | +9.079 | unavailable |

## Supplied intents (descriptive ASR groups)

Q / G / V denotes QUAN / GIPFormer / VALSEA. Group findings are exploratory, not semantic accuracy or formal rankings.

| Group | N | Speakers | Seconds | Ref tokens | Word edits Q / G / V | WER Q / G / V | Ref chars | Char edits Q / G / V | CER Q / G / V |
| --- | ---: | ---: | ---: | ---: | --- | --- | ---: | --- | --- |
| bật nhạc | 176 | unavailable | 903.298 | 2377 | 752 / 649 / 478 | 31.637% / 27.303% / 20.109% | 7887 | 2120 / 1814 / 1084 | 26.880% / 23.000% / 13.744% |
| bật thiết bị | 91 | unavailable | 340.860 | 990 | 287 / 165 / 149 | 28.990% / 16.667% / 15.051% | 3065 | 716 / 450 / 310 | 23.361% / 14.682% / 10.114% |
| giảm mức độ của thiết bị | 9 | unavailable | 39.840 | 103 | 32 / 28 / 18 | 31.068% / 27.184% / 17.476% | 318 | 93 / 73 / 43 | 29.245% / 22.956% / 13.522% |
| giảm nhiệt độ của thiết bị | 10 | unavailable | 53.880 | 135 | 44 / 40 / 21 | 32.593% / 29.630% / 15.556% | 388 | 143 / 126 / 29 | 36.856% / 32.474% / 7.474% |
| giảm âm lượng của thiết bị | 3 | unavailable | 19.080 | 38 | 17 / 17 / 6 | 44.737% / 44.737% / 15.789% | 135 | 51 / 48 / 16 | 37.778% / 35.556% / 11.852% |
| giảm độ sáng của thiết bị | 56 | unavailable | 229.860 | 611 | 290 / 242 / 110 | 47.463% / 39.607% / 18.003% | 1937 | 846 / 754 / 230 | 43.676% / 38.926% / 11.874% |
| gọi taxi | 145 | unavailable | 736.133 | 1866 | 471 / 352 / 315 | 25.241% / 18.864% / 16.881% | 6011 | 1236 / 940 / 698 | 20.562% / 15.638% / 11.612% |
| gợi ý phim | 180 | unavailable | 985.963 | 2749 | 658 / 564 / 426 | 23.936% / 20.517% / 15.497% | 8752 | 1816 / 1586 / 1054 | 20.750% / 18.122% / 12.043% |
| gợi ý địa điểm | 126 | unavailable | 760.967 | 2207 | 487 / 418 / 372 | 22.066% / 18.940% / 16.855% | 6859 | 1143 / 1024 / 782 | 16.664% / 14.929% / 11.401% |
| hỏi thông tin | 76 | unavailable | 346.590 | 902 | 154 / 113 / 151 | 17.073% / 12.528% / 16.741% | 2946 | 435 / 341 / 382 | 14.766% / 11.575% / 12.967% |
| hủy hoạt cảnh | 21 | unavailable | 85.800 | 278 | 51 / 39 / 46 | 18.345% / 14.029% / 16.547% | 864 | 131 / 109 / 94 | 15.162% / 12.616% / 10.880% |
| kiểm tra tình trạng thiết bị | 88 | unavailable | 350.160 | 1105 | 251 / 154 / 199 | 22.715% / 13.937% / 18.009% | 3437 | 578 / 379 / 426 | 16.817% / 11.027% / 12.395% |
| kích hoạt cảnh | 39 | unavailable | 181.380 | 514 | 75 / 64 / 26 | 14.591% / 12.451% / 5.058% | 1656 | 200 / 170 / 50 | 12.077% / 10.266% / 3.019% |
| mở thiết bị | 86 | unavailable | 311.700 | 912 | 202 / 148 / 140 | 22.149% / 16.228% / 15.351% | 2701 | 486 / 352 / 261 | 17.993% / 13.032% / 9.663% |
| tra công thức nấu ăn | 161 | unavailable | 941.959 | 2484 | 549 / 422 / 363 | 22.101% / 16.989% / 14.614% | 7906 | 1392 / 1134 / 847 | 17.607% / 14.344% / 10.713% |
| tra cứu lịch | 113 | unavailable | 585.947 | 1660 | 406 / 311 / 324 | 24.458% / 18.735% / 19.518% | 5121 | 1090 / 907 / 784 | 21.285% / 17.711% / 15.310% |
| tra cứu thời tiết | 147 | unavailable | 746.669 | 2098 | 482 / 356 / 356 | 22.974% / 16.969% / 16.969% | 6770 | 1240 / 1016 / 874 | 18.316% / 15.007% / 12.910% |
| tra cứu đường đi | 124 | unavailable | 672.404 | 1863 | 556 / 507 / 454 | 29.844% / 27.214% / 24.369% | 6086 | 1443 / 1311 / 903 | 23.710% / 21.541% / 14.837% |
| tăng mức độ của thiết bị | 7 | unavailable | 33.120 | 93 | 28 / 19 / 12 | 30.108% / 20.430% / 12.903% | 295 | 68 / 47 / 24 | 23.051% / 15.932% / 8.136% |
| tăng nhiệt độ của thiết bị | 14 | unavailable | 70.980 | 195 | 55 / 45 / 24 | 28.205% / 23.077% / 12.308% | 594 | 150 / 139 / 42 | 25.253% / 23.401% / 7.071% |
| tăng âm lượng của thiết bị | 5 | unavailable | 21.000 | 56 | 20 / 14 / 21 | 35.714% / 25.000% / 37.500% | 181 | 50 / 35 / 37 | 27.624% / 19.337% / 20.442% |
| tăng độ sáng của thiết bị | 62 | unavailable | 271.380 | 702 | 332 / 297 / 97 | 47.293% / 42.308% / 13.818% | 2194 | 1050 / 948 / 189 | 47.858% / 43.209% / 8.614% |
| tắt thiết bị | 80 | unavailable | 289.131 | 799 | 215 / 120 / 130 | 26.909% / 15.019% / 16.270% | 2481 | 507 / 293 / 291 | 20.435% / 11.810% / 11.729% |
| xóa lịch | 109 | unavailable | 469.302 | 1157 | 335 / 274 / 317 | 28.954% / 23.682% / 27.398% | 3713 | 934 / 816 / 822 | 25.155% / 21.977% / 22.138% |
| đóng thiết bị | 96 | unavailable | 347.160 | 1035 | 255 / 146 / 188 | 24.638% / 14.106% / 18.164% | 3222 | 596 / 365 / 374 | 18.498% / 11.328% / 11.608% |
| đặt lịch | 124 | unavailable | 659.093 | 1830 | 491 / 411 / 279 | 26.831% / 22.459% / 15.246% | 5667 | 1351 / 1211 / 592 | 23.840% / 21.369% / 10.446% |
| đặt vé | 123 | unavailable | 687.016 | 1820 | 401 / 325 / 283 | 22.033% / 17.857% / 15.549% | 5540 | 1068 / 911 / 658 | 19.278% / 16.444% / 11.877% |
| đặt đồ ăn | 130 | unavailable | 627.448 | 1772 | 453 / 326 / 356 | 25.564% / 18.397% / 20.090% | 5510 | 1137 / 873 / 892 | 20.635% / 15.844% / 16.189% |

## Protocol, provenance and limits

NFC → lowercase → Unicode P* punctuation to spaces → whitespace collapse. Diacritics, number forms, fillers and repetitions remain. Whitespace WER is not linguistic word segmentation. CER compares normalized Unicode code points without spaces. All rates divide summed edits by summed reference denominators. Empty/error hypotheses retain full denominators. No number-normalized alternative score, semantic/slot metric, reference edit or model retry.
ViMD uses the frozen 2,000-replicate, seed-42 speaker bootstrap within sorted source/region strata and speaker IDs, with repeated speaker multiplicity and percentile indices int(q*(B-1)). Every paired replicate applies the same draw to both models. Intervals containing zero are inconclusive under this analysis, not equivalence. Separate-model interval overlap is not a paired test.
VN-SLU has no speaker/region metadata: descriptive corpus/intent reporting only, no invented cluster or utterance-bootstrap substitute. Its released test count is 2,401, distinct from the paper count of 2,454.
QUAN’s official model card lists ViMD as training data; test-split overlap remains unverified. ViMD is not confirmed unseen evaluation. Metrics measure official-reference agreement, not semantic correctness or LifeMate task success. Do not pool datasets or declare a universal winner. GIPFormer and QUAN precision policies differ as labelled above.
VALSEA scored response text only; raw_transcript was not selected after seeing scores. Requested false flags do not prove backend processing. Exposed engine labels vary and are not immutable revisions or evidence of causal engine superiority. Saved API version/session and historical retry accounting are preserved in metrics.json; no exactly-once service-processing claim is added.
Raw/normalized strings, source flags, supplied labels, edits/denominators and per-sample paired differences are in per_sample.jsonl. Utterance edit wins/ties/losses in metrics.json are supplementary, not corpus metrics or independent statistical samples. No inference, audio access, network, scoring-policy changes or speed/cost comparisons occurred.

## Validation and reproduction

QUAN source ZIP/extracted bytes, canonical manifest, completed child/session, observed precision and frozen dependencies revalidated. Both baselines were rescored from original predictions; every saved baseline row, corpus/subgroup aggregate and applicable interval reconciled. All three models share identical references/denominators. Subgroup counts, edits, durations and denominators reconcile. Input byte snapshots were checked unchanged after scoring.
`python -X utf8 scripts/score_quan_comparison.py` from the project root. Existing matching outputs are reusable; conflicting outputs are refused. See metrics.json for exact paths, run IDs, revisions, source validation and frozen bootstrap settings.

The two preserved successful empty QUAN predictions are: `VN-SLU/test/659ea4ef3e9a97673ad897c8`, `VN-SLU/test/659ebc663e9a97673ad89866`. Both contribute full reference deletion errors.

## Portable package boundary

This is saved aggregate evidence. Per-sample references/predictions, original run bundles and the QUAN scoring integration remain withheld in the authorized source workspace. The reproduction command above requires those inputs; it cannot run from this package alone. No scoring was rerun for packaging.
