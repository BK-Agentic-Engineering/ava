# Three-case integration slice, proposal v0.1

Each ID has `<ID>.input.json`, `<ID>.output.json` and `private/<ID>.json`: TR15_PLANNING_TOMORROW, B02_N_C, TR16_APP_KEEP. `SOURCES.json` records original design/replay locators and current verifier extraction ranges. `verifiers/` is our local verification code, not a replacement Jaz harness.

Only `agent_visible` is rendered to the model. It contains request, context, history and references to permitted schemas. Private initialization contains post-history WORLD, clock, permissions and oracle. Expected calls/results/final snapshots are authored local reference evidence, not future model output. History must not execute again. Prepared run IDs are examples; Tài owns real run identity and trace/submission/scorer integration. Tú owns serialization/loss masking.

From the package root:

```powershell
python -X utf8 integration/three_cases/verify.py --archive "X:/authorized/train+public_test.zip"
```

The authorized external release must be v3.2.0, catalog schema2.7.0. SDK modules and catalog definitions are not redistributed. The command reads only named code/catalog members, builds nine exact schemas in temporary storage, resolves every JSON reference, then executes each latest reference trace and invokes the current verifier. It compares actual results and final state, confirms effective permissions and an empty starting log. It does not replay historical writes, call a model or submit official scores.

`tool_schemas.json` references are intentional external requirements and are resolved by that command; they are not a missing bundled file. Do not reuse the old local bundled-SDK ZIP as a publication artifact. Reference passes do not certify that every valid alternative is covered or receives full fixed-reference contest score. In particular the package’s16 held cases retain their gold and pending status.
