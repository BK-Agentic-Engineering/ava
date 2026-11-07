"""Gipformer ONNX FP16 CUDA, greedy một symbol/frame.

Điều phối theo icefall/zipformer/onnx_pretrained.py (Apache 2.0,
Copyright 2022 Xiaomi Corp., tác giả Fangjun Kuang). Log-mel preprocessing
dùng FP32; encoder/decoder/joiner có trọng số và input/output FP16.
"""

from pathlib import Path

import kaldi_native_fbank as knf
import numpy as np
import onnxruntime as ort
import soundfile as sf
import torch


class GipformerASR:
    def __init__(self, model_dir, num_threads=4):
        if not torch.cuda.is_available():
            raise RuntimeError("Gipformer FP16 cần GPU CUDA.")

        # Dùng CUDA/cuDNN đi kèm PyTorch trên máy Windows này.
        ort.preload_dlls()
        model_dir = Path(model_dir)
        options = ort.SessionOptions()
        options.intra_op_num_threads = num_threads
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        self.sessions = {}

        for name in ("encoder", "decoder", "joiner"):
            session = ort.InferenceSession(
                str(model_dir / "fp16" / f"{name}.onnx"),
                sess_options=options,
                providers=[(
                    "CUDAExecutionProvider",
                    {
                        "arena_extend_strategy": "kSameAsRequested",
                        "cudnn_conv_algo_search": "HEURISTIC",
                    },
                )],
            )
            if session.get_providers()[0] != "CUDAExecutionProvider":
                raise RuntimeError("ONNX Runtime chưa chạy được trên CUDA.")
            self.sessions[name] = session

        metadata = self.sessions["decoder"].get_modelmeta()
        self.context_size = int(metadata.custom_metadata_map["context_size"])
        self.tokens = {}
        for line in (model_dir / "tokens.txt").read_text(
            encoding="utf-8"
        ).splitlines():
            piece, index = line.rsplit(maxsplit=1)
            self.tokens[int(index)] = piece
        self.blank_id = next(
            index for index, piece in self.tokens.items() if piece == "<blk>"
        )

        self.fbank_options = knf.FbankOptions()
        self.fbank_options.frame_opts.dither = 0
        self.fbank_options.frame_opts.snip_edges = False
        self.fbank_options.frame_opts.samp_freq = 16000
        self.fbank_options.mel_opts.num_bins = 80
        self.fbank_options.mel_opts.high_freq = -400

    def _run(self, name, *values):
        session = self.sessions[name]
        inputs = {
            node.name: value
            for node, value in zip(session.get_inputs(), values)
        }
        return session.run(None, inputs)

    def transcribe(self, audio_path):
        waveform, sample_rate = sf.read(audio_path, dtype="float32")
        if sample_rate != 16000:
            raise ValueError("Gipformer hiện nhận audio 16 kHz; chưa tự resample.")
        if waveform.ndim == 2:
            waveform = waveform.mean(axis=1)

        fbank = knf.OnlineFbank(self.fbank_options)
        fbank.accept_waveform(sample_rate, waveform.tolist())
        fbank.input_finished()
        features = np.stack([
            fbank.get_frame(i) for i in range(fbank.num_frames_ready)
        ]).astype(np.float16)

        encoded, lengths = self._run(
            "encoder",
            features[None, :, :],
            np.asarray([len(features)], dtype=np.int64),
        )
        if not np.isfinite(encoded).all():
            raise FloatingPointError("ASR FP16 encoder sinh NaN/Inf.")

        hypothesis = [self.blank_id] * self.context_size

        def decode_context():
            context = np.asarray(
                [hypothesis[-self.context_size:]], dtype=np.int64
            )
            return self._run("decoder", context)[0]

        decoded = decode_context()
        for frame in range(int(lengths[0])):
            logits = self._run("joiner", encoded[:, frame, :], decoded)[0]
            if not np.isfinite(logits).all():
                raise FloatingPointError("ASR FP16 joiner sinh NaN/Inf.")
            token = int(logits.argmax(axis=-1)[0])
            if token != self.blank_id:
                hypothesis.append(token)
                decoded = decode_context()

        pieces = [self.tokens[token] for token in hypothesis[self.context_size:]]
        return "".join(pieces).replace("▁", " ").strip()
