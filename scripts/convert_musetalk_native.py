#!/usr/bin/env python3
"""One-time MuseTalk asset conversion: .pth (torch) -> MLX-native safetensors (torch-free).

Run in fusion-mlx venv (has torch). Produces dist/ usable by from_pretrained_mlx.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/Users/dahai/fusion/fusion-mlx")

from fusion_mlx.video.musetalk_mlx.pipeline_mlx import MuseTalkPipeline
from fusion_mlx.video.musetalk_mlx.utils.weights import save_native

SRC = Path("/Users/dahai/.fusion-mlx/models/models--TMElyralab--MuseTalk/snapshots/3ef28bc5cff08c90ad8178a25f1b570cd800170f")
DIST = Path("/Users/dahai/.fusion-mlx/models/musetalk-mlx-native")
DIST.mkdir(parents=True, exist_ok=True)

print(f"[convert] loading from {SRC} (needs torch for .pth unet)...")
pipe = MuseTalkPipeline.from_pretrained(SRC)
print(f"[convert] loaded pipeline scaling={pipe.scaling_factor} dtype={pipe.dtype}")

print("[convert] saving vae.safetensors...")
save_native(pipe.vae, DIST / "vae.safetensors")
print("[convert] saving unet.safetensors...")
save_native(pipe.unet, DIST / "unet.safetensors")
print("[convert] saving whisper_encoder.safetensors...")
save_native(pipe.whisper_encoder, DIST / "whisper_encoder.safetensors")

meta = {
    "scaling_factor": float(pipe.scaling_factor) if pipe.scaling_factor else 0.18215,
    "dtype": "bfloat16",
    "source": "TMElyralab/MuseTalk + stabilityai/sd-vae-ft-mse + openai/whisper-tiny",
    "converted_by": "scripts/convert_musetalk_native.py",
}
(DIST / "config.json").write_text(json.dumps(meta, indent=2))
print(f"[convert] done -> {DIST}")
print(f"[convert] files: {[f.name for f in DIST.iterdir()]}")
