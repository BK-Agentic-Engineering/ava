# Model provenance — no training

This submission does not fine-tune or train a model. There is no training dataset or training command.

- LLM: LiquidAI/LFM3-1.7B-GGUF, revision `cd0c74c575b5c416f3011b5b4c298077f26ca8c2`, file `LFM3-1.7B-F16.gguf`, SHA-256 `b7ab8b69a85e4dfbf62cdfd0e02d7d051ed09f2c5b84c701771dddb073b85970`.
- ASR: g-group-ai-lab/gipformer1.5-68M-rnnt, revision `dd9227dcd8705c13f33bdbe59728d546ab94480f`. Encoder/decoder/joiner converted from FP32 ONNX to FP16 with ONNX Runtime's float16 converter and `keep_io_types=False`; conversion metadata is included with the assets. Audio features remain FP32 before FP16 encoder input. No quantization.
- LLM parameters: approximately 1.73B; ASR: approximately 68M; total below 6B. Context fixed to 16,384 tokens.
- Inference implementation: `/code/src/lifemate/deploy.py` uses smolagents ToolCallingAgent, llama.cpp b12110, and the organizer SDK from the mounted split.

Public model sources:
https://huggingface.co/LiquidAI/LFM3-1.7B-GGUF/tree/cd0c74c575b5c416f3011b5b4c298077f26ca8c2
https://huggingface.co/g-group-ai-lab/gipformer1.5-68M-rnnt/tree/dd9227dcd8705c13f33bdbe59728d546ab94480f

Models and dependencies are packaged before inference; these URLs are provenance, not inference downloads.
