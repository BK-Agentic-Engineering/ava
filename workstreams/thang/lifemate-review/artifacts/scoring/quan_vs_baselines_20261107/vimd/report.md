# QUAN versus GIPFormer and VALSEA — VIMD

- **QUAN-Transcribe-1.0: FP32 weights, FP16 autocast; explicit FP32 audio attention/features/CTC head; greedy CTC**
- **GIPFormer 1.5: FP16 weights with mixed computation; greedy decoding**
- **VALSEA/Glot glot-transcribe: submitted correction/tags/diarization false; scored response text only**

## Corpus official-reference agreement

| Model | N | Word edits / ref tokens | WER | Character edits / ref characters | CER | Empty successes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| quan | 2026 | 13081 / 132471 | 9.875% | 31958 / 436649 | 7.319% | 0 |
| gipformer | 2026 | 9263 / 132471 | 6.992% | 23714 / 436649 | 5.431% | 0 |
| valsea | 2026 | 17393 / 132471 | 13.130% | 45319 / 436649 | 10.379% | 0 |

## Paired differences

QUAN minus baseline, absolute percentage points; negative favors QUAN. Corpus ratios are used, never averaged utterance rates.

| Baseline | Scope | ΔWER pp | Paired 95% CI | ΔCER pp | Paired 95% CI |
| --- | --- | ---: | --- | ---: | --- |
| gipformer | overall | +2.882 | +2.687 to +3.081 | +1.888 | +1.745 to +2.034 |
| gipformer | North | +2.217 | +1.970 to +2.483 | +1.618 | +1.412 to +1.844 |
| gipformer | Central | +3.780 | +3.345 to +4.206 | +2.420 | +2.115 to +2.740 |
| gipformer | South | +2.857 | +2.536 to +3.189 | +1.721 | +1.495 to +1.955 |
| valsea | overall | -3.255 | -3.665 to -2.813 | -3.060 | -3.419 to -2.680 |
| valsea | North | -3.151 | -3.918 to -2.480 | -2.987 | -3.689 to -2.361 |
| valsea | Central | -3.394 | -4.189 to -2.602 | -2.961 | -3.652 to -2.302 |
| valsea | South | -3.253 | -4.051 to -2.503 | -3.249 | -3.956 to -2.607 |

Single-model full/regional 95% speaker intervals:

| Scope | Model | Speakers | WER interval | CER interval |
| --- | --- | ---: | --- | --- |
| overall | quan | 1344 | 9.488% to 10.284% | 7.022% to 7.622% |
| overall | gipformer | 1344 | 6.683% to 7.321% | 5.185% to 5.690% |
| overall | valsea | 1344 | 12.603% to 13.640% | 9.932% to 10.813% |
| North | quan | 528 | 7.869% to 8.992% | 6.049% to 6.984% |
| North | gipformer | 528 | 5.740% to 6.689% | 4.503% to 5.297% |
| North | valsea | 528 | 10.767% to 12.431% | 8.769% to 10.303% |
| Central | quan | 444 | 11.766% to 13.610% | 8.639% to 10.033% |
| Central | gipformer | 444 | 8.195% to 9.588% | 6.347% to 7.455% |
| Central | valsea | 444 | 14.965% to 17.114% | 11.398% to 13.140% |
| South | quan | 372 | 8.437% to 9.702% | 5.992% to 6.926% |
| South | gipformer | 372 | 5.717% to 6.679% | 4.341% to 5.113% |
| South | valsea | 372 | 11.501% to 13.167% | 8.990% to 10.463% |

Unweighted macro of the three regional corpus rates (not corpus micro):
- quan: WER 10.035%; CER 7.419%.
- gipformer: WER 7.084%; CER 5.499%.
- valsea: WER 13.301%; CER 10.484%.

## Regions

Q / G / V denotes QUAN / GIPFormer / VALSEA. Group findings are exploratory, not semantic accuracy or formal rankings.

| Group | N | Speakers | Seconds | Ref tokens | Word edits Q / G / V | WER Q / G / V | Ref chars | Char edits Q / G / V | CER Q / G / V |
| --- | ---: | ---: | ---: | ---: | --- | --- | ---: | --- | --- |
| North | 783 | 528 | 15275.983 | 51917 | 4369 / 3218 / 6005 | 8.415% / 6.198% / 11.567% | 172557 | 11233 / 8441 / 16387 | 6.510% / 4.892% / 9.497% |
| Central | 623 | 444 | 11836.789 | 39604 | 5004 / 3507 / 6348 | 12.635% / 8.855% / 16.029% | 129686 | 12056 / 8917 / 15896 | 9.296% / 6.876% / 12.257% |
| South | 620 | 372 | 12027.705 | 40950 | 3708 / 2538 / 5040 | 9.055% / 6.198% / 12.308% | 134406 | 8669 / 6356 / 13036 | 6.450% / 4.729% / 9.699% |

## Provinces (descriptive)

Q / G / V denotes QUAN / GIPFormer / VALSEA. Group findings are exploratory, not semantic accuracy or formal rankings.

| Group | N | Speakers | Seconds | Ref tokens | Word edits Q / G / V | WER Q / G / V | Ref chars | Char edits Q / G / V | CER Q / G / V |
| --- | ---: | ---: | ---: | ---: | --- | --- | ---: | --- | --- |
| 11 CaoBang | 35 | 12 | 637.646 | 2151 | 180 / 144 / 197 | 8.368% / 6.695% / 9.159% | 7206 | 475 / 360 / 513 | 6.592% / 4.996% / 7.119% |
| 12 LangSon | 33 | 12 | 603.283 | 1993 | 154 / 99 / 213 | 7.727% / 4.967% / 10.687% | 6568 | 360 / 252 / 567 | 5.481% / 3.837% / 8.633% |
| 14 QuangNinh | 34 | 27 | 606.296 | 2051 | 142 / 113 / 246 | 6.923% / 5.510% / 11.994% | 6812 | 357 / 299 / 668 | 5.241% / 4.389% / 9.806% |
| 15 HaiPhong | 33 | 21 | 630.856 | 2300 | 187 / 127 / 275 | 8.130% / 5.522% / 11.957% | 7612 | 520 / 344 / 800 | 6.831% / 4.519% / 10.510% |
| 17 ThaiBinh | 33 | 32 | 614.626 | 2198 | 209 / 165 / 252 | 9.509% / 7.507% / 11.465% | 7366 | 579 / 457 / 686 | 7.860% / 6.204% / 9.313% |
| 18 NamDinh | 31 | 15 | 642.114 | 2259 | 119 / 74 / 194 | 5.268% / 3.276% / 8.588% | 7599 | 331 / 191 / 545 | 4.356% / 2.513% / 7.172% |
| 19 PhuTho | 32 | 28 | 637.737 | 2188 | 160 / 124 / 294 | 7.313% / 5.667% / 13.437% | 7416 | 390 / 322 / 827 | 5.259% / 4.342% / 11.152% |
| 20 ThaiNguyen | 31 | 26 | 606.249 | 2101 | 209 / 175 / 202 | 9.948% / 8.329% / 9.614% | 6981 | 547 / 485 / 558 | 7.836% / 6.947% / 7.993% |
| 21 YenBai | 33 | 20 | 658.217 | 2100 | 130 / 94 / 252 | 6.190% / 4.476% / 12.000% | 7023 | 335 / 230 / 711 | 4.770% / 3.275% / 10.124% |
| 22 TuyenQuang | 34 | 19 | 608.322 | 2051 | 112 / 77 / 220 | 5.461% / 3.754% / 10.726% | 6883 | 280 / 190 / 619 | 4.068% / 2.760% / 8.993% |
| 23 HaGiang | 33 | 28 | 614.155 | 2084 | 213 / 140 / 275 | 10.221% / 6.718% / 13.196% | 6875 | 535 / 374 / 710 | 7.782% / 5.440% / 10.327% |
| 24 LaoCai | 38 | 30 | 596.278 | 1868 | 132 / 99 / 201 | 7.066% / 5.300% / 10.760% | 6220 | 343 / 244 / 557 | 5.514% / 3.923% / 8.955% |
| 25 LaiChau | 27 | 19 | 600.200 | 2032 | 159 / 108 / 214 | 7.825% / 5.315% / 10.531% | 6812 | 391 / 278 / 560 | 5.740% / 4.081% / 8.221% |
| 26 SonLa | 35 | 18 | 573.938 | 2002 | 119 / 81 / 246 | 5.944% / 4.046% / 12.288% | 6671 | 292 / 197 / 665 | 4.377% / 2.953% / 9.969% |
| 27 DienBien | 28 | 20 | 598.644 | 1972 | 180 / 122 / 232 | 9.128% / 6.187% / 11.765% | 6643 | 481 / 336 / 674 | 7.241% / 5.058% / 10.146% |
| 28 HoaBinh | 32 | 17 | 628.568 | 2046 | 178 / 139 / 238 | 8.700% / 6.794% / 11.632% | 6694 | 457 / 368 / 667 | 6.827% / 5.497% / 9.964% |
| 30 HaNoi | 29 | 14 | 589.746 | 2111 | 184 / 142 / 164 | 8.716% / 6.727% / 7.769% | 6745 | 468 / 370 / 424 | 6.938% / 5.486% / 6.286% |
| 34 HaiDuong | 30 | 22 | 627.136 | 2230 | 180 / 120 / 252 | 8.072% / 5.381% / 11.300% | 7364 | 456 / 297 / 664 | 6.192% / 4.033% / 9.017% |
| 35 NinhBinh | 26 | 24 | 602.223 | 2197 | 219 / 156 / 224 | 9.968% / 7.101% / 10.196% | 7135 | 552 / 418 / 577 | 7.737% / 5.858% / 8.087% |
| 36 ThanhHoa | 29 | 18 | 569.688 | 1912 | 165 / 115 / 224 | 8.630% / 6.015% / 11.715% | 6413 | 441 / 303 / 590 | 6.877% / 4.725% / 9.200% |
| 37 NgheAn | 43 | 34 | 745.797 | 2652 | 227 / 166 / 358 | 8.560% / 6.259% / 13.499% | 8779 | 566 / 426 / 855 | 6.447% / 4.852% / 9.739% |
| 38 HaTinh | 33 | 27 | 644.411 | 2143 | 343 / 239 / 497 | 16.006% / 11.153% / 23.192% | 6899 | 766 / 573 / 1143 | 11.103% / 8.306% / 16.568% |
| 43 DaNang | 33 | 22 | 622.691 | 2199 | 252 / 194 / 323 | 11.460% / 8.822% / 14.688% | 7469 | 646 / 494 / 854 | 8.649% / 6.614% / 11.434% |
| 47 DakLak | 34 | 25 | 612.366 | 2004 | 274 / 184 / 273 | 13.673% / 9.182% / 13.623% | 6501 | 674 / 465 / 712 | 10.368% / 7.153% / 10.952% |
| 48 DakNong | 31 | 31 | 632.365 | 2125 | 187 / 138 / 229 | 8.800% / 6.494% / 10.776% | 6925 | 459 / 340 / 597 | 6.628% / 4.910% / 8.621% |
| 49 LamDong | 33 | 23 | 618.047 | 2165 | 271 / 206 / 286 | 12.517% / 9.515% / 13.210% | 7055 | 691 / 558 / 705 | 9.794% / 7.909% / 9.993% |
| 59 HoChiMinh | 34 | 29 | 573.300 | 2279 | 154 / 116 / 246 | 6.757% / 5.090% / 10.794% | 7421 | 374 / 285 / 631 | 5.040% / 3.840% / 8.503% |
| 60 DongNai | 31 | 18 | 615.695 | 2208 | 165 / 98 / 242 | 7.473% / 4.438% / 10.960% | 7049 | 391 / 260 / 673 | 5.547% / 3.688% / 9.547% |
| 61 BinhDuong | 33 | 32 | 626.695 | 2269 | 142 / 104 / 201 | 6.258% / 4.584% / 8.859% | 7679 | 339 / 273 / 523 | 4.415% / 3.555% / 6.811% |
| 62 LongAn | 38 | 21 | 697.087 | 2457 | 202 / 130 / 277 | 8.221% / 5.291% / 11.274% | 8116 | 473 / 323 / 695 | 5.828% / 3.980% / 8.563% |
| 63 TienGiang | 33 | 10 | 631.626 | 2151 | 193 / 121 / 284 | 8.973% / 5.625% / 13.203% | 7053 | 426 / 296 / 734 | 6.040% / 4.197% / 10.407% |
| 64 VinhLong | 30 | 14 | 636.055 | 2083 | 196 / 117 / 337 | 9.410% / 5.617% / 16.179% | 6755 | 445 / 287 / 967 | 6.588% / 4.249% / 14.315% |
| 65 CanTho | 28 | 23 | 539.190 | 1797 | 177 / 127 / 316 | 9.850% / 7.067% / 17.585% | 5912 | 431 / 332 / 812 | 7.290% / 5.616% / 13.735% |
| 66 DongThap | 28 | 21 | 606.151 | 2188 | 201 / 123 / 233 | 9.186% / 5.622% / 10.649% | 7269 | 470 / 284 / 579 | 6.466% / 3.907% / 7.965% |
| 67 AnGiang | 31 | 15 | 636.955 | 1975 | 184 / 129 / 233 | 9.316% / 6.532% / 11.797% | 6487 | 425 / 318 / 584 | 6.552% / 4.902% / 9.003% |
| 68 KienGiang | 32 | 13 | 648.665 | 2024 | 177 / 105 / 191 | 8.745% / 5.188% / 9.437% | 6515 | 390 / 262 / 468 | 5.986% / 4.021% / 7.183% |
| 69 CaMau | 37 | 21 | 653.160 | 2139 | 217 / 148 / 236 | 10.145% / 6.919% / 11.033% | 7061 | 508 / 384 / 561 | 7.194% / 5.438% / 7.945% |
| 70 TayNinh | 34 | 20 | 620.339 | 2129 | 200 / 126 / 237 | 9.394% / 5.918% / 11.132% | 7101 | 480 / 343 / 599 | 6.760% / 4.830% / 8.435% |
| 71 BenTre | 31 | 17 | 660.621 | 2094 | 183 / 127 / 237 | 8.739% / 6.065% / 11.318% | 6930 | 428 / 322 / 593 | 6.176% / 4.646% / 8.557% |
| 72 BaRiaVungTau | 31 | 25 | 628.453 | 2115 | 243 / 149 / 263 | 11.489% / 7.045% / 12.435% | 6908 | 569 / 377 / 638 | 8.237% / 5.457% / 9.236% |
| 73 QuangBinh | 36 | 22 | 728.693 | 2523 | 389 / 251 / 611 | 15.418% / 9.948% / 24.217% | 8337 | 934 / 658 / 1449 | 11.203% / 7.893% / 17.380% |
| 74 QuangTri | 30 | 13 | 591.337 | 1763 | 170 / 155 / 278 | 9.643% / 8.792% / 15.769% | 5875 | 397 / 399 / 642 | 6.757% / 6.791% / 10.928% |
| 75 ThuaThienHue | 32 | 22 | 630.704 | 1945 | 290 / 220 / 388 | 14.910% / 11.311% / 19.949% | 6257 | 682 / 548 / 887 | 10.900% / 8.758% / 14.176% |
| 76 QuangNgai | 38 | 25 | 604.802 | 2072 | 433 / 275 / 460 | 20.898% / 13.272% / 22.201% | 6507 | 1036 / 666 / 1129 | 15.921% / 10.235% / 17.351% |
| 77 BinhDinh | 28 | 14 | 619.152 | 2266 | 352 / 264 / 417 | 15.534% / 11.650% / 18.402% | 7393 | 890 / 740 / 1092 | 12.038% / 10.009% / 14.771% |
| 78 PhuYen | 32 | 26 | 592.226 | 2065 | 303 / 205 / 353 | 14.673% / 9.927% / 17.094% | 6862 | 758 / 520 / 927 | 11.046% / 7.578% / 13.509% |
| 79 KhanhHoa | 30 | 20 | 587.917 | 2040 | 181 / 110 / 273 | 8.873% / 5.392% / 13.382% | 6826 | 461 / 288 / 744 | 6.754% / 4.219% / 10.900% |
| 81 GiaLai | 33 | 31 | 615.379 | 2075 | 188 / 125 / 293 | 9.060% / 6.024% / 14.120% | 6841 | 438 / 321 / 786 | 6.403% / 4.692% / 11.490% |
| 82 KonTum | 31 | 23 | 594.244 | 1667 | 236 / 162 / 236 | 14.157% / 9.718% / 14.157% | 5242 | 544 / 397 / 586 | 10.378% / 7.573% / 11.179% |
| 83 SocTrang | 31 | 15 | 595.030 | 1905 | 252 / 173 / 263 | 13.228% / 9.081% / 13.806% | 6026 | 565 / 417 / 649 | 9.376% / 6.920% / 10.770% |
| 84 TraVinh | 40 | 17 | 677.075 | 2267 | 191 / 151 / 354 | 8.425% / 6.661% / 15.615% | 7593 | 435 / 385 / 1003 | 5.729% / 5.070% / 13.210% |
| 85 NinhThuan | 34 | 31 | 598.567 | 1935 | 177 / 154 / 219 | 9.147% / 7.959% / 11.318% | 6425 | 429 / 387 / 611 | 6.677% / 6.023% / 9.510% |
| 86 BinhThuan | 33 | 16 | 640.453 | 1982 | 315 / 199 / 295 | 15.893% / 10.040% / 14.884% | 6208 | 668 / 491 / 747 | 10.760% / 7.909% / 12.033% |
| 88 VinhPhuc | 28 | 21 | 600.489 | 2063 | 214 / 146 / 313 | 10.373% / 7.077% / 15.172% | 6896 | 575 / 408 / 885 | 8.338% / 5.916% / 12.834% |
| 89 HungYen | 30 | 25 | 598.981 | 2012 | 307 / 241 / 351 | 15.258% / 11.978% / 17.445% | 6613 | 772 / 635 / 929 | 11.674% / 9.602% / 14.048% |
| 90 HaNam | 27 | 15 | 562.794 | 1882 | 173 / 141 / 174 | 9.192% / 7.492% / 9.245% | 6387 | 461 / 395 / 477 | 7.218% / 6.184% / 7.468% |
| 92 QuangNam | 30 | 21 | 587.950 | 2071 | 251 / 145 / 335 | 12.120% / 7.001% / 16.176% | 6872 | 576 / 343 / 840 | 8.382% / 4.991% / 12.224% |
| 93 BinhPhuoc | 35 | 26 | 682.745 | 2521 | 267 / 233 / 319 | 10.591% / 9.242% / 12.654% | 8260 | 640 / 549 / 805 | 7.748% / 6.646% / 9.746% |
| 94 BacLieu | 33 | 10 | 724.214 | 2433 | 232 / 175 / 362 | 9.536% / 7.193% / 14.879% | 8067 | 557 / 440 / 961 | 6.905% / 5.454% / 11.913% |
| 95 HauGiang | 30 | 25 | 574.649 | 1916 | 132 / 86 / 209 | 6.889% / 4.489% / 10.908% | 6204 | 323 / 219 / 561 | 5.206% / 3.530% / 9.043% |
| 97 BacKan | 34 | 20 | 669.496 | 2097 | 168 / 139 / 349 | 8.011% / 6.629% / 16.643% | 6996 | 432 / 360 / 958 | 6.175% / 5.146% / 13.694% |
| 98 BacGiang | 28 | 22 | 575.106 | 1891 | 154 / 109 / 206 | 8.144% / 5.764% / 10.894% | 6247 | 385 / 269 / 556 | 6.163% / 4.306% / 8.900% |
| 99 BacNinh | 29 | 21 | 592.882 | 2038 | 187 / 143 / 221 | 9.176% / 7.017% / 10.844% | 6793 | 459 / 362 / 590 | 6.757% / 5.329% / 8.685% |

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

## Portable package boundary

This is saved aggregate evidence. Per-sample references/predictions, original run bundles and the QUAN scoring integration remain withheld in the authorized source workspace. The reproduction command above requires those inputs; it cannot run from this package alone. No scoring was rerun for packaging.
