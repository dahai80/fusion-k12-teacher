"""MuseTalkAvatar — digital human plugin for fusion_mlx.video.musetalk_mlx.

In-process library API (not HTTP): encode_audio_from_wav(wav) -> mel chunks,
render(latent_batch, audio_chunks) -> (B,256,256,3) BGR uint8 frames.
No word timestamps needed (TTS only provides PCM; MuseTalk infers lip sync from mel).

2-level degradation: resolution down -> StaticAvatar fallback.
When fusion_mlx cannot be imported, available=False and the manager auto-falls back to StaticAvatar.
PTS drives the frame pace (monotonic clock, late frames skipped — linguakids mode).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .base import AvatarPlugin

logger = logging.getLogger(__name__)


_mx_executor: ThreadPoolExecutor | None = None


def _get_mx_executor() -> ThreadPoolExecutor:
    global _mx_executor
    if _mx_executor is None:
        _mx_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="musetalk-mx")
        _mx_executor.submit(_init_mx_thread).result()
    return _mx_executor


def _init_mx_thread() -> None:
    try:
        import mlx.core as mx
        dev = mx.default_device()
        mx.default_stream(dev)
        logger.info("avatar_musetalk: MLX thread stream initialized thread=%s", _thread_name())
    except Exception as exc:
        logger.warning("avatar_musetalk: MLX thread stream init failed %s", exc)


def _thread_name() -> str:
    import threading
    return threading.current_thread().name


def _resolve_fusion_mlx_source() -> str | None:
    env_src = os.environ.get("FUSION_MLX_SOURCE", "").strip()
    candidates = [env_src] if env_src else []
    candidates += [
        str(Path.home() / "fusion" / "fusion-mlx"),
        str(Path.home() / "claude-home" / "fusion-mlx"),
    ]
    for c in candidates:
        if c and Path(c, "fusion_mlx", "video", "musetalk_mlx").is_dir():
            return c
    return None


def _try_import_musetalk():
    try:
        from fusion_mlx.video.musetalk_mlx.pipeline_mlx import MuseTalkPipeline as _P
        return _P
    except Exception:
        src = _resolve_fusion_mlx_source()
        if src and src not in sys.path:
            sys.path.insert(0, src)
            logger.info("avatar_musetalk: injected fusion-mlx source path %s", src)
        try:
            from fusion_mlx.video.musetalk_mlx.pipeline_mlx import MuseTalkPipeline as _P
            return _P
        except Exception as exc:
            logger.warning("avatar_musetalk: MuseTalk not importable (%s), degrading to StaticAvatar", str(exc)[:120])
            return None


_MuseTalkPipeline = _try_import_musetalk()
_HAS_MUSETALK = _MuseTalkPipeline is not None

_MUSETALK_REPO = Path.home() / ".fusion-mlx" / "models" / "models--TMElyralab--MuseTalk"
_MUSETALK_NATIVE = Path.home() / ".fusion-mlx" / "models" / "musetalk-mlx-native"


def _resolve_musetalk_native() -> Path | None:
    env = os.environ.get("MUSETALK_NATIVE", "").strip()
    if env and Path(env, "config.json").exists():
        return Path(env)
    if (_MUSETALK_NATIVE / "config.json").exists():
        return _MUSETALK_NATIVE
    return None


def _resolve_musetalk_assets() -> Path | None:
    env_assets = os.environ.get("MUSETALK_ASSETS", "").strip()
    if env_assets and Path(env_assets, "sd-vae-ft-mse").exists():
        return Path(env_assets)
    if not _MUSETALK_REPO.exists():
        return None
    snapshots = _MUSETALK_REPO / "snapshots"
    if not snapshots.is_dir():
        return None
    for snap in sorted(snapshots.iterdir(), reverse=True):
        if (snap / "sd-vae-ft-mse").exists():
            return snap
    return None


_MUSETALK_NATIVE_DIR = _resolve_musetalk_native()
_MUSETALK_ASSETS = _resolve_musetalk_assets()


def _free_mem_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().available / (1024 ** 3)
    except Exception:
        return 8.0


def _disk_cache_key(text: str) -> str:
    import hashlib
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


class MuseTalkAvatar(AvatarPlugin):
    name = "musetalk_avatar"

    def __init__(self, session_id: str = "", reference_image: str = "") -> None:
        self.session_id = session_id
        self._reference = reference_image
        self._pipeline: Any = None
        self._lock = asyncio.Lock()
        self._available = False
        self._cancelled = False
        self._rendering_text: str | None = None
        self._cache: dict[str, list[bytes]] = {}
        self._speed = 1.0
        self._idle_frames: list[bytes] = []
        self._disk_dir = Path.home() / ".fusion-mlx" / "cache" / "musetalk_frames"
        self._low_mem = False

    @property
    def available(self) -> bool:
        return self._available

    async def init(self) -> None:
        self._low_mem = _free_mem_gb() < 4.0
        if self._low_mem:
            logger.warning("avatar_musetalk[%s]: available memory <4GB, render degrades to idle-only", self.session_id)
        if not _HAS_MUSETALK:
            logger.warning("avatar_musetalk[%s]: fusion_mlx.video.musetalk_mlx not importable, available=False", self.session_id)
            self._available = False
            return
        try:
            if _MUSETALK_ASSETS is not None:
                weights = str(_MUSETALK_ASSETS)
                self._pipeline = await asyncio.get_event_loop().run_in_executor(
                    _get_mx_executor(), _MuseTalkPipeline.from_pretrained, weights)
                logger.info("avatar_musetalk[%s]: init (from_pretrained) assets=%s", self.session_id, weights)
            elif _MUSETALK_NATIVE_DIR is not None:
                dist = str(_MUSETALK_NATIVE_DIR)
                self._pipeline = await asyncio.get_event_loop().run_in_executor(
                    _get_mx_executor(), _MuseTalkPipeline.from_pretrained_mlx, dist)
                logger.info("avatar_musetalk[%s]: init (native MLX) dist=%s", self.session_id, dist)
            else:
                logger.warning("avatar_musetalk[%s]: MuseTalk assets not ready, available=False", self.session_id)
                self._available = False
                return
            self._available = True
            logger.info("avatar_musetalk[%s]: pipeline ready %s", self.session_id, type(self._pipeline).__name__)
        except Exception as exc:
            logger.error("avatar_musetalk[%s]: init failed %s, degrading to StaticAvatar", self.session_id, exc)
            self._available = False
            self._pipeline = None

    def set_speed(self, speed: float) -> None:
        self._speed = speed

    async def render(self, text: str, pcm: bytes, emotion: str = "neutral") -> list[bytes]:
        if not self._available or self._pipeline is None or self._low_mem:
            return await self._fallback_render(text, pcm, emotion)
        cached = self.cached_frames(text)
        if cached is not None:
            return cached
        disk = self._disk_get(text)
        if disk is not None:
            self._cache[text] = disk
            logger.info("avatar_musetalk[%s]: disk cache hit text=%d bytes", self.session_id, len(text))
            return disk
        self._rendering_text = text
        self._cancelled = False
        try:
            frames = await self._render_sync(text, pcm)
            self._cache[text] = frames
            self._disk_put(text, frames)
            return frames
        except Exception as exc:
            logger.error("avatar_musetalk[%s]: render failed %s, degrading to idle", self.session_id, exc)
            return list(self._idle_frames) or await self._fallback_render(text, pcm, emotion)
        finally:
            self._rendering_text = None

    def _disk_get(self, text: str) -> list[bytes] | None:
        try:
            import pickle
            p = self._disk_dir / (_disk_cache_key(text) + ".pkl")
            if p.exists():
                with p.open("rb") as f:
                    obj = pickle.load(f)
                if isinstance(obj, list):
                    return obj
        except Exception as exc:
            logger.debug("avatar_musetalk[%s]: disk_get failed %s", self.session_id, exc)
        return None

    def _disk_put(self, text: str, frames: list[bytes]) -> None:
        try:
            import pickle
            self._disk_dir.mkdir(parents=True, exist_ok=True)
            p = self._disk_dir / (_disk_cache_key(text) + ".pkl")
            with p.open("wb") as f:
                pickle.dump(frames, f)
        except Exception as exc:
            logger.debug("avatar_musetalk[%s]: disk_put failed %s", self.session_id, exc)

    async def _render_sync(self, text: str, pcm: bytes) -> list[bytes]:
        if not pcm:
            return list(self._idle_frames)
        crop_bgr = self._load_reference_crop()
        if crop_bgr is None:
            logger.warning("avatar_musetalk[%s]: no reference face, degrading to idle", self.session_id)
            return list(self._idle_frames)
        wav_path = await self._pcm_to_wav(pcm)
        # Full pipeline runs on the main thread: encode_audio (librosa CPU, but internally touches mx ops) +
        # get_latents + generate_faces — a ThreadPoolExecutor triggers
        # "no Stream(gpu,*) in current thread"; mx.default_stream cannot be persisted in a worker.
        chunks_tail = self._pipeline.encode_audio_from_wav(wav_path, 25)
        audio_chunks = chunks_tail[0] if isinstance(chunks_tail, tuple) else chunks_tail
        n_frames = audio_chunks.shape[0] if hasattr(audio_chunks, "shape") else 0
        if n_frames == 0:
            return list(self._idle_frames)
        # Robustness: over-long audio (LLM chatty ramble) triggers giant-batch OOM — truncate to 750 frames (30s).
        if n_frames > 750:
            logger.warning("avatar_musetalk[%s]: frame count %d too large, truncated to 750 (text=%d bytes)", self.session_id, n_frames, len(text))
            n_frames = 750
            audio_chunks = audio_chunks[:750]
        import mlx.core as mx
        latent_single = self._pipeline.get_latents_for_unet(crop_bgr, True)
        logger.info("avatar_musetalk[%s]: shapes latent=%s audio=%s n=%d", self.session_id, latent_single.shape, audio_chunks.shape, n_frames)
        latent_batch = mx.broadcast_to(latent_single, (n_frames, *latent_single.shape[1:]))
        frames_raw = self._pipeline.generate_faces(latent_batch, audio_chunks, 1)
        frames: list[bytes] = []
        for i, frame in enumerate(frames_raw):
            if self._cancelled:
                logger.info("avatar_musetalk[%s]: render cancelled at frame %d", self.session_id, i)
                break
            frames.append(self._encode_jpeg(frame))
        logger.info("avatar_musetalk[%s]: render text=%d bytes frames=%d", self.session_id, len(text), len(frames))
        return frames

    def _load_reference_crop(self):
        import cv2
        ref = self._reference or str(Path(__file__).parent.parent / "assets" / "default_teacher.jpg")
        try:
            img = cv2.imread(ref)
            if img is None:
                logger.warning("avatar_musetalk[%s]: reference image read failed %s", self.session_id, ref)
                return None
            h, w = img.shape[:2]
            if h != 256 or w != 256:
                img = cv2.resize(img, (256, 256))
            return img
        except Exception as exc:
            logger.warning("avatar_musetalk[%s]: reference image load error %s", self.session_id, exc)
            return None

    async def _pcm_to_wav(self, pcm: bytes) -> str:
        import tempfile
        import wave
        path = tempfile.mkstemp(suffix=".wav", prefix="dh_tts_")[1]
        # When TTS already returns WAV (RIFF header), write to disk directly, avoiding re-wrapping that breaks sample rate/length.
        if pcm[:4] == b"RIFF" and b"WAVE" in pcm[:12]:
            Path(path).write_bytes(pcm)
            return path
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm)
        return path

    @staticmethod
    def _encode_jpeg(frame: Any) -> bytes:
        try:
            import cv2
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                return buf.tobytes()
        except Exception:
            pass
        return bytes(frame) if isinstance(frame, (bytes, bytearray)) else b""

    async def _fallback_render(self, text: str, pcm: bytes, emotion: str) -> list[bytes]:
        return list(self._idle_frames) or [b""]

    async def generate_idle_frames(self) -> list[bytes]:
        if self._idle_frames:
            return list(self._idle_frames)
        crop_bgr = self._load_reference_crop()
        if crop_bgr is not None and self._pipeline is not None:
            try:
                import mlx.core as mx
                # GPU inference runs on the main thread (Stream(gpu,0) limitation, see _render_sync comment)
                latent = self._pipeline.get_latents_for_unet(crop_bgr, True)
                idle_raw = self._pipeline.generate_faces(latent, mx.zeros((1, 50, 384)), 1)
                self._idle_frames = [self._encode_jpeg(f) for f in idle_raw[:1]]
                logger.info("avatar_musetalk[%s]: generated idle frames=%d", self.session_id, len(self._idle_frames))
            except Exception as exc:
                logger.warning("avatar_musetalk[%s]: idle frame generation failed %s, falling back to JPEG", self.session_id, exc)
                self._idle_frames = [self._encode_jpeg(crop_bgr)]
        else:
            self._idle_frames = [b""]
        return list(self._idle_frames)

    def is_rendering(self, text: str) -> bool:
        return self._rendering_text == text

    def cached_frames(self, text: str) -> list[bytes] | None:
        return self._cache.get(text)

    async def stop_playback(self) -> None:
        self._rendering_text = None

    async def cancel_render(self) -> None:
        self._cancelled = True
        self._rendering_text = None

    def clear(self) -> None:
        self._cache.clear()
        self._cancelled = False

    async def close(self) -> None:
        self._cache.clear()
        self._idle_frames.clear()
        self._pipeline = None
        self._available = False
