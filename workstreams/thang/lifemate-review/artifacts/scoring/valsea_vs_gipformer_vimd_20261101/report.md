# VALSEA/Glot versus GIPFormer 1.5 — full ViMD test

GIPFormer 1.5: FP16 weights with mixed computation, greedy decoding.
VALSEA/Glot: glot-transcribe alias; submitted correction/tags/diarization disabled; scored response text only.

## Model reference agreement

| Group | Model | Clips | Speakers | Audio hours | WER | 95% CI | CER | 95% CI |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- |
| overall | gipformer | 2026 | 1344 | 10.872355 | 6.992% | 6.683%–7.321% | 5.431% | 5.185%–5.690% |
| overall | valsea | 2026 | 1344 | 10.872355 | 13.130% | 12.603%–13.640% | 10.379% | 9.932%–10.813% |
| North | gipformer | 783 | 528 | 4.243328 | 6.198% | 5.740%–6.689% | 4.892% | 4.503%–5.297% |
| North | valsea | 783 | 528 | 4.243328 | 11.567% | 10.767%–12.431% | 9.497% | 8.769%–10.303% |
| Central | gipformer | 623 | 444 | 3.287997 | 8.855% | 8.195%–9.588% | 6.876% | 6.347%–7.455% |
| Central | valsea | 623 | 444 | 3.287997 | 16.029% | 14.965%–17.114% | 12.257% | 11.398%–13.140% |
| South | gipformer | 620 | 372 | 3.341029 | 6.198% | 5.717%–6.679% | 4.729% | 4.341%–5.113% |
| South | valsea | 620 | 372 | 3.341029 | 12.308% | 11.501%–13.167% | 9.699% | 8.990%–10.463% |

Unweighted regional macro (mean of three corpus rates, not full-corpus micro):
- gipformer: WER 7.084%, CER 5.499%.
- valsea: WER 13.301%, CER 10.484%.

## Paired differences

Absolute percentage-point differences: VALSEA minus GIPFormer; negative favors VALSEA. Intervals use the same speaker draws for both models, not overlap of separate CIs. Regional comparisons are exploratory.

| Group | Delta WER pp | Paired 95% CI pp | Interpretation | Delta CER pp | Paired 95% CI pp | Interpretation |
| --- | ---: | --- | --- | ---: | --- | --- |
| overall | +6.137 | +5.676–+6.578 | lower GIPFormer reference error | +4.948 | +4.546–+5.334 | lower GIPFormer reference error |
| North | +5.368 | +4.681–+6.153 | lower GIPFormer reference error | +4.605 | +3.955–+5.359 | lower GIPFormer reference error |
| Central | +7.174 | +6.304–+7.983 | lower GIPFormer reference error | +5.381 | +4.660–+6.072 | lower GIPFormer reference error |
| South | +6.110 | +5.413–+6.899 | lower GIPFormer reference error | +4.970 | +4.343–+5.684 | lower GIPFormer reference error |

## Descriptive provinces

Source-code order, not a ranking. No province CIs or statistically established province differences are claimed.

| Province | Region | Clips | Speakers | Hours | GIP WER | VALSEA WER | GIP CER | VALSEA CER |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 11 CaoBang | North | 35 | 12 | 0.177124 | 6.695% | 9.159% | 4.996% | 7.119% |
| 12 LangSon | North | 33 | 12 | 0.167578 | 4.967% | 10.687% | 3.837% | 8.633% |
| 14 QuangNinh | North | 34 | 27 | 0.168416 | 5.510% | 11.994% | 4.389% | 9.806% |
| 15 HaiPhong | North | 33 | 21 | 0.175238 | 5.522% | 11.957% | 4.519% | 10.510% |
| 17 ThaiBinh | North | 33 | 32 | 0.170730 | 7.507% | 11.465% | 6.204% | 9.313% |
| 18 NamDinh | North | 31 | 15 | 0.178365 | 3.276% | 8.588% | 2.513% | 7.172% |
| 19 PhuTho | North | 32 | 28 | 0.177149 | 5.667% | 13.437% | 4.342% | 11.152% |
| 20 ThaiNguyen | North | 31 | 26 | 0.168403 | 8.329% | 9.614% | 6.947% | 7.993% |
| 21 YenBai | North | 33 | 20 | 0.182838 | 4.476% | 12.000% | 3.275% | 10.124% |
| 22 TuyenQuang | North | 34 | 19 | 0.168978 | 3.754% | 10.726% | 2.760% | 8.993% |
| 23 HaGiang | North | 33 | 28 | 0.170599 | 6.718% | 13.196% | 5.440% | 10.327% |
| 24 LaoCai | North | 38 | 30 | 0.165633 | 5.300% | 10.760% | 3.923% | 8.955% |
| 25 LaiChau | North | 27 | 19 | 0.166722 | 5.315% | 10.531% | 4.081% | 8.221% |
| 26 SonLa | North | 35 | 18 | 0.159427 | 4.046% | 12.288% | 2.953% | 9.969% |
| 27 DienBien | North | 28 | 20 | 0.166290 | 6.187% | 11.765% | 5.058% | 10.146% |
| 28 HoaBinh | North | 32 | 17 | 0.174602 | 6.794% | 11.632% | 5.497% | 9.964% |
| 30 HaNoi | North | 29 | 14 | 0.163818 | 6.727% | 7.769% | 5.486% | 6.286% |
| 34 HaiDuong | North | 30 | 22 | 0.174205 | 5.381% | 11.300% | 4.033% | 9.017% |
| 35 NinhBinh | North | 26 | 24 | 0.167284 | 7.101% | 10.196% | 5.858% | 8.087% |
| 36 ThanhHoa | Central | 29 | 18 | 0.158247 | 6.015% | 11.715% | 4.725% | 9.200% |
| 37 NgheAn | Central | 43 | 34 | 0.207166 | 6.259% | 13.499% | 4.852% | 9.739% |
| 38 HaTinh | Central | 33 | 27 | 0.179003 | 11.153% | 23.192% | 8.306% | 16.568% |
| 43 DaNang | Central | 33 | 22 | 0.172970 | 8.822% | 14.688% | 6.614% | 11.434% |
| 47 DakLak | Central | 34 | 25 | 0.170102 | 9.182% | 13.623% | 7.153% | 10.952% |
| 48 DakNong | Central | 31 | 31 | 0.175657 | 6.494% | 10.776% | 4.910% | 8.621% |
| 49 LamDong | Central | 33 | 23 | 0.171680 | 9.515% | 13.210% | 7.909% | 9.993% |
| 59 HoChiMinh | South | 34 | 29 | 0.159250 | 5.090% | 10.794% | 3.840% | 8.503% |
| 60 DongNai | South | 31 | 18 | 0.171026 | 4.438% | 10.960% | 3.688% | 9.547% |
| 61 BinhDuong | South | 33 | 32 | 0.174082 | 4.584% | 8.859% | 3.555% | 6.811% |
| 62 LongAn | South | 38 | 21 | 0.193635 | 5.291% | 11.274% | 3.980% | 8.563% |
| 63 TienGiang | South | 33 | 10 | 0.175452 | 5.625% | 13.203% | 4.197% | 10.407% |
| 64 VinhLong | South | 30 | 14 | 0.176682 | 5.617% | 16.179% | 4.249% | 14.315% |
| 65 CanTho | South | 28 | 23 | 0.149775 | 7.067% | 17.585% | 5.616% | 13.735% |
| 66 DongThap | South | 28 | 21 | 0.168375 | 5.622% | 10.649% | 3.907% | 7.965% |
| 67 AnGiang | South | 31 | 15 | 0.176932 | 6.532% | 11.797% | 4.902% | 9.003% |
| 68 KienGiang | South | 32 | 13 | 0.180185 | 5.188% | 9.437% | 4.021% | 7.183% |
| 69 CaMau | South | 37 | 21 | 0.181433 | 6.919% | 11.033% | 5.438% | 7.945% |
| 70 TayNinh | South | 34 | 20 | 0.172317 | 5.918% | 11.132% | 4.830% | 8.435% |
| 71 BenTre | South | 31 | 17 | 0.183506 | 6.065% | 11.318% | 4.646% | 8.557% |
| 72 BaRiaVungTau | South | 31 | 25 | 0.174570 | 7.045% | 12.435% | 5.457% | 9.236% |
| 73 QuangBinh | Central | 36 | 22 | 0.202415 | 9.948% | 24.217% | 7.893% | 17.380% |
| 74 QuangTri | Central | 30 | 13 | 0.164260 | 8.792% | 15.769% | 6.791% | 10.928% |
| 75 ThuaThienHue | Central | 32 | 22 | 0.175195 | 11.311% | 19.949% | 8.758% | 14.176% |
| 76 QuangNgai | Central | 38 | 25 | 0.168001 | 13.272% | 22.201% | 10.235% | 17.351% |
| 77 BinhDinh | Central | 28 | 14 | 0.171987 | 11.650% | 18.402% | 10.009% | 14.771% |
| 78 PhuYen | Central | 32 | 26 | 0.164507 | 9.927% | 17.094% | 7.578% | 13.509% |
| 79 KhanhHoa | Central | 30 | 20 | 0.163310 | 5.392% | 13.382% | 4.219% | 10.900% |
| 81 GiaLai | Central | 33 | 31 | 0.170938 | 6.024% | 14.120% | 4.692% | 11.490% |
| 82 KonTum | Central | 31 | 23 | 0.165068 | 9.718% | 14.157% | 7.573% | 11.179% |
| 83 SocTrang | South | 31 | 15 | 0.165286 | 9.081% | 13.806% | 6.920% | 10.770% |
| 84 TraVinh | South | 40 | 17 | 0.188076 | 6.661% | 15.615% | 5.070% | 13.210% |
| 85 NinhThuan | Central | 34 | 31 | 0.166269 | 7.959% | 11.318% | 6.023% | 9.510% |
| 86 BinhThuan | Central | 33 | 16 | 0.177904 | 10.040% | 14.884% | 7.909% | 12.033% |
| 88 VinhPhuc | North | 28 | 21 | 0.166802 | 7.077% | 15.172% | 5.916% | 12.834% |
| 89 HungYen | North | 30 | 25 | 0.166384 | 11.978% | 17.445% | 9.602% | 14.048% |
| 90 HaNam | North | 27 | 15 | 0.156332 | 7.492% | 9.245% | 6.184% | 7.468% |
| 92 QuangNam | Central | 30 | 21 | 0.163319 | 7.001% | 16.176% | 4.991% | 12.224% |
| 93 BinhPhuoc | South | 35 | 26 | 0.189651 | 9.242% | 12.654% | 6.646% | 9.746% |
| 94 BacLieu | South | 33 | 10 | 0.201171 | 7.193% | 14.879% | 5.454% | 11.913% |
| 95 HauGiang | South | 30 | 25 | 0.159625 | 4.489% | 10.908% | 3.530% | 9.043% |
| 97 BacKan | North | 34 | 20 | 0.185971 | 6.629% | 16.643% | 5.146% | 13.694% |
| 98 BacGiang | North | 28 | 22 | 0.159752 | 5.764% | 10.894% | 4.306% | 8.900% |
| 99 BacNinh | North | 29 | 21 | 0.164689 | 7.017% | 10.844% | 5.329% | 8.685% |

Smallest province speaker support: 10 supplied IDs in TienGiang and BacLieu. Counts alone do not establish adequacy.

## Validation, provider provenance and limits

- All 2,026 IDs are unique, complete and successfully reconciled with successful attempt evidence. Empty text is valid and retains full reference denominators. All three speaker-overlap-flagged records remain included. No files were repaired or excluded.
- Canonical test manifest matches both archived full-test manifests; smoke matches the six frozen validation records. Full VALSEA configuration equals the verified smoke configuration except mode. Final sessions are completed; summaries were recomputed, not trusted. Historical failed/uncertain attempts and explicit retry authorizations are retained in metrics.json, not used to exclude samples.
- Baseline saved per-sample scores and aggregates reconcile with independent CPU rescoring; neither baseline nor inputs were overwritten. Counts/durations/edit totals/reference denominators reconcile across regions/provinces. Both models have identical reference denominators.
- Frozen normalizer: NFC, lowercase, Unicode punctuation to spaces, collapse whitespace. WER uses whitespace units, not linguistic Vietnamese word segmentation. CER removes normalized spaces and compares Unicode code points. Diacritics, number forms, fillers and repetitions are not rewritten. Raw texts remain in paired per_sample.jsonl; raw_transcript remains evidence in the original attempt log and was never selected for scoring.
- Single-model and paired intervals: 2,000 replicates, seed 42, sorted source/region strata and speaker IDs, speakers sampled with replacement with all their utterances and repeated-draw multiplicity. Sorted empirical endpoints int(q*(B−1)), q=0.025/0.975; each overall/regional call resets the seed. No significance tests or equivalence thresholds. A paired interval containing zero is inconclusive, not proof of equivalence.
- Actual API alias/configuration, execution dates, exposed versions/engine variation and request-ID counts follow. Submitted false flags and HTTP success do not independently prove all backend processing details. No immutable API revision is invented.
- engine: [{"value": "valsea-4", "count": 982, "first_observed_utc": "2026-11-01T14:20:11.734432+00:00", "last_observed_utc": "2026-11-01T17:52:50.063721+00:00"}, {"value": "valsea-6", "count": 1044, "first_observed_utc": "2026-11-01T14:20:47.337859+00:00", "last_observed_utc": "2026-11-01T17:52:29.453964+00:00"}].
- model_version: [{"value": null, "count": 2026, "first_observed_utc": "2026-11-01T14:20:11.734432+00:00", "last_observed_utc": "2026-11-01T17:52:50.063721+00:00"}].
- exposed_provider_version: [{"value": null, "count": 2026, "first_observed_utc": "2026-11-01T14:20:11.734432+00:00", "last_observed_utc": "2026-11-01T17:52:50.063721+00:00"}].
- returned_model: [{"value": null, "count": 2026, "first_observed_utc": "2026-11-01T14:20:11.734432+00:00", "last_observed_utc": "2026-11-01T17:52:50.063721+00:00"}].
- API session: {"started_utc": "2026-11-01T14:19:20.978850+00:00", "ended_utc": "2026-11-01T17:52:50.117550+00:00", "status": "completed", "successful_outcomes": 2026, "engine_counts": {"valsea-4": 982, "valsea-6": 1044}, "provider_version_counts": {"None": 2026}}.
- Request IDs: 2026 present, 2026 distinct.
- smoke attempt accounting: {"expected": 6, "attempted_samples": 6, "request_attempts": 6, "successful": 6, "failed_attempts": 0, "unresolved_attempts": 0, "historical_unknown_remote_outcomes": 0, "source_error_events": 0, "blocked_sample_ids": [], "remaining": 0, "empty_successful_transcripts": [], "coverage_complete": true, "review_status": "pending_human_review", "exactly_once_remote_processing": "not guaranteed"}.
- full attempt accounting: {"expected": 2026, "attempted_samples": 2026, "request_attempts": 2026, "successful": 2026, "failed_attempts": 0, "unresolved_attempts": 0, "historical_unknown_remote_outcomes": 0, "source_error_events": 0, "blocked_sample_ids": [], "remaining": 0, "empty_successful_transcripts": [], "coverage_complete": true, "review_status": "pending_human_review", "exactly_once_remote_processing": "not guaranteed"}.
- Metrics measure agreement with official ViMD references. Reference correctness, training overlap and LifeMate generalization remain unresolved. Speaker-ID overlap alone does not establish leakage. Mixed backend engine labels are observed routing/provenance, not evidence of immutable model versions or a causal subgroup effect.
- Client API elapsed times include upload/service/transfer; the 24m43s GIPFormer session includes setup/downloads. Neither is local-model compute latency or comparable performance/cost benchmarking. Those analyses are outside scope.
- No inference, GPU/Kaggle use, gold changes or tuning was performed. Formal recognition-quality acceptance remains pending human review.

Reproduce from project root: `python scripts/compare_vimd_models.py`. See metrics.json for exact ratios, additive totals, source run IDs, revisions and bootstrap settings.
