"""MuseTalkAvatar — fusion_mlx.video.musetalk_mlx 数字人插件。

in-process 库 API (非 HTTP): encode_audio_from_wav(wav) -> mel chunks,
render(latent_batch, audio_chunks) -> (B,256,256,3) BGR uint8 帧。
不需要 word timestamps (TTS 仅给 PCM, MuseTalk 从 mel 推口型)。

2 级降级: 分辨率降 -> StaticAvatar 兜底。
fusion_mlx 不可 import 时 available=False, manager 自动回退 StaticAvatar。
PTS 驱动帧节奏 (monotonic 时钟, 迟到帧跳过 — linguakids 模式)。
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
        logger.info("avatar_musetalk: MLX 线程流初始化完成 thread=%s", _thread_name())
    except Exception as exc:
        logger.warning("avatar_musetalk: MLX 线程流初始化失败 %s", exc)


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
            logger.info("avatar_musetalk: 注入 fusion-mlx 源码路径 %s", src)
        try:
            from fusion_mlx.video.musetalk_mlx.pipeline_mlx import MuseTalkPipeline as _P
            return _P
        except Exception as exc:
            logger.warning("avatar_musetalk: MuseTalk 不可 import (%s), 降级 StaticAvatar", str(exc)[:120])
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
            logger.warning("avatar_musetalk[%s]: 可用内存 <4GB, 渲染降级 idle-only", self.session_id)
        if not _HAS_MUSETALK:
            logger.warning("avatar_musetalk[%s]: fusion_mlx.video.musetalk_mlx 不可 import, available=False", self.session_id)
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
                logger.warning("avatar_musetalk[%s]: MuseTalk 资源未就绪, available=False", self.session_id)
                self._available = False
                return
            self._available = True
            logger.info("avatar_musetalk[%s]: pipeline 就绪 %s", self.session_id, type(self._pipeline).__name__)
        except Exception as exc:
            logger.error("avatar_musetalk[%s]: init 失败 %s, 降级 StaticAvatar", self.session_id, exc)
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
            logger.info("avatar_musetalk[%s]: disk cache 命中 文本=%d字节", self.session_id, len(text))
            return disk
        self._rendering_text = text
        self._cancelled = False
        try:
            frames = await self._render_sync(text, pcm)
            self._cache[text] = frames
            self._disk_put(text, frames)
            return frames
        except Exception as exc:
            logger.error("avatar_musetalk[%s]: render 失败 %s, 降级 idle", self.session_id, exc)
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
            logger.debug("avatar_musetalk[%s]: disk_get 失败 %s", self.session_id, exc)
        return None

    def _disk_put(self, text: str, frames: list[bytes]) -> None:
        try:
            import pickle
            self._disk_dir.mkdir(parents=True, exist_ok=True)
            p = self._disk_dir / (_disk_cache_key(text) + ".pkl")
            with p.open("wb") as f:
                pickle.dump(frames, f)
        except Exception as exc:
            logger.debug("avatar_musetalk[%s]: disk_put 失败 %s", self.session_id, exc)

    async def _render_sync(self, text: str, pcm: bytes) -> list[bytes]:
        if not pcm:
            return list(self._idle_frames)
        crop_bgr = self._load_reference_crop()
        if crop_bgr is None:
            logger.warning("avatar_musetalk[%s]: 无参考人脸, 降级 idle", self.session_id)
            return list(self._idle_frames)
        wav_path = await self._pcm_to_wav(pcm)
        # 全流程主线程执行: encode_audio (librosa CPU, 但内部触 mx 算子) +
        # get_latents + generate_faces — 经 ThreadPoolExecutor 触发
        # "no Stream(gpu,*) in current thread", mx.default_stream 无法在 worker 持久化。
        chunks_tail = self._pipeline.encode_audio_from_wav(wav_path, 25)
        audio_chunks = chunks_tail[0] if isinstance(chunks_tail, tuple) else chunks_tail
        n_frames = audio_chunks.shape[0] if hasattr(audio_chunks, "shape") else 0
        if n_frames == 0:
            return list(self._idle_frames)
        # 健壮性: 超长音频 (LLM 闲聊 ramble) 触发巨型 batch OOM — 截断到 750 帧 (30s)。
        if n_frames > 750:
            logger.warning("avatar_musetalk[%s]: 帧数 %d 过大, 截断 750 (文本=%d字节)", self.session_id, n_frames, len(text))
            n_frames = 750
            audio_chunks = audio_chunks[:750]
        import mlx.core as mx
        latent_single = self._pipeline.get_latents_for_unet(crop_bgr, True)
        logger.info("avatar_musetalk[%s]: 形状 latent=%s audio=%s n=%d", self.session_id, latent_single.shape, audio_chunks.shape, n_frames)
        latent_batch = mx.broadcast_to(latent_single, (n_frames, *latent_single.shape[1:]))
        frames_raw = self._pipeline.generate_faces(latent_batch, audio_chunks, 1)
        frames: list[bytes] = []
        for i, frame in enumerate(frames_raw):
            if self._cancelled:
                logger.info("avatar_musetalk[%s]: render 在帧 %d 被取消", self.session_id, i)
                break
            frames.append(self._encode_jpeg(frame))
        logger.info("avatar_musetalk[%s]: render 文本=%d字节 帧数=%d", self.session_id, len(text), len(frames))
        return frames

    def _load_reference_crop(self):
        import cv2
        ref = self._reference or str(Path(__file__).parent.parent / "assets" / "default_teacher.jpg")
        try:
            img = cv2.imread(ref)
            if img is None:
                logger.warning("avatar_musetalk[%s]: 参考图读取失败 %s", self.session_id, ref)
                return None
            h, w = img.shape[:2]
            if h != 256 or w != 256:
                img = cv2.resize(img, (256, 256))
            return img
        except Exception as exc:
            logger.warning("avatar_musetalk[%s]: 参考图加载异常 %s", self.session_id, exc)
            return None

    async def _pcm_to_wav(self, pcm: bytes) -> str:
        import tempfile
        import wave
        path = tempfile.mkstemp(suffix=".wav", prefix="dh_tts_")[1]
        # TTS 返回 WAV 时 (RIFF 头) 直接落盘, 避免二次封装破坏采样率/长度。
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
                # GPU 推理走主线程 (Stream(gpu,0) 限制, 见 _render_sync 注释)
                latent = self._pipeline.get_latents_for_unet(crop_bgr, True)
                idle_raw = self._pipeline.generate_faces(latent, mx.zeros((1, 50, 384)), 1)
                self._idle_frames = [self._encode_jpeg(f) for f in idle_raw[:1]]
                logger.info("avatar_musetalk[%s]: 生成 idle 帧=%d", self.session_id, len(self._idle_frames))
            except Exception as exc:
                logger.warning("avatar_musetalk[%s]: idle 帧生成失败 %s, 用 JPEG 兜底", self.session_id, exc)
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
