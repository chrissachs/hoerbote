"""The qwen3-tts engine's GPU side, on Modal (image: Dockerfile.qwen3-tts).
Modal imports this file in the container too, on its own: only the
standard library and modal at the top."""

import logging
import os
import time
from pathlib import Path

import modal

MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
MODEL_REVISION = "fd4b254389122332181a7c3db7f27e918eec64e3"  # 2026-01-23
GPU = "L4"
# Generation is one busy Python thread; the model lives on the GPU.
CPU = 1.0
MEMORY_MIB = 4096
LANGUAGE = "German"
SEED = 1408
GEN_KWARGS = {"max_new_tokens": 1024, "do_sample": True, "temperature": 0.9, "top_p": 0.95}
# Codec tokens per character a sentence may take: twice the slowest pace
# heard, plus 2 s. A sentence that never stops would otherwise hold up its
# whole batch until max_new_tokens.
TOKENS_PER_CHAR_CAP = 2 * 0.82
TOKENS_CAP_MARGIN = 24
# Re-renders of a sentence that hit the cap; after that it stays cut off.
RUNAWAY_RETRIES = 1

image = modal.Image.from_dockerfile(
    Path(__file__).parent / "Dockerfile.qwen3-tts",
    context_dir=Path(__file__).parent,
    build_args={"MODEL": MODEL, "MODEL_REVISION": MODEL_REVISION},
)
app = modal.App("hoerbote-audio", image=image)
log = logging.getLogger(__name__)


def token_cap(texts: list[str]) -> int:
    """max_new_tokens for a batch: the cap of its longest sentence."""
    return min(GEN_KWARGS["max_new_tokens"], int(TOKENS_PER_CHAR_CAP * max(map(len, texts))) + TOKENS_CAP_MARGIN)


def hit_cap(duration_s: float, cap: int) -> bool:
    """Whether a take ran into the cap, with slack: the "12Hz" codec may
    run at 12.5 tokens/s."""
    return duration_s >= 0.97 * cap / 12.5


@app.cls(gpu=GPU, cpu=CPU, memory=MEMORY_MIB, timeout=20 * 60, max_containers=1, scaledown_window=60)
class Speaker:
    @modal.enter()
    def load(self) -> None:
        # Before torch sets up CUDA. Not in the Dockerfile: any change there
        # rebuilds the image, weights included.
        os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
        import torch
        from huggingface_hub import snapshot_download
        from qwen_tts import Qwen3TTSModel

        # Libraries at WARNING: qwen-tts logs its config defaults on every batch.
        logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
        log.setLevel(logging.INFO)
        t0 = time.perf_counter()
        self.model = Qwen3TTSModel.from_pretrained(
            snapshot_download(MODEL, revision=MODEL_REVISION),
            device_map="cuda:0",
            dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
            attn_implementation="sdpa",
        )
        self.prompts = {}  # voice name -> (clip bytes, prompt item)
        torch.manual_seed(SEED)
        log.info("model loaded in %.0f s on %s", time.perf_counter() - t0, torch.cuda.get_device_name())

    @modal.method()
    def render(self, batches: list[list[tuple[str, str]]], voices: dict[str, bytes]) -> list[list[dict]]:
        """Batches of (voice, sentence) -> per sentence {"pcm": 16-bit
        mono samples as bytes, "sample_rate", "capped": ran into the cap
        even after the retries}. `voices`: name -> reference clip."""
        t0 = time.perf_counter()
        out = []
        for batch in batches:
            out.append(self._render_batch(batch, voices))
        log.info("%d batches, %d sentences in %.0f s", len(batches), sum(map(len, batches)), time.perf_counter() - t0)
        return out

    def _prompt(self, voice: str, voices: dict[str, bytes]):
        """The voice's speaker embedding, computed once per clip."""
        import io

        import soundfile as sf

        clip = voices[voice]
        if voice not in self.prompts or self.prompts[voice][0] != clip:
            samples, sr = sf.read(io.BytesIO(clip), dtype="float32")
            if samples.ndim > 1:
                samples = samples.mean(axis=1)
            item = self.model.create_voice_clone_prompt(ref_audio=(samples, sr), x_vector_only_mode=True)[0]
            self.prompts[voice] = (clip, item)
        return self.prompts[voice][1]

    def _render_batch(self, batch: list[tuple[str, str]], voices: dict[str, bytes]) -> list[dict]:
        import numpy as np

        wavs, sr, caps = self._generate(batch, voices)
        for attempt in range(RUNAWAY_RETRIES):
            runaways = [i for i, w in enumerate(wavs) if hit_cap(len(w) / sr, caps[i])]
            if not runaways:
                break
            log.warning("%d sentence(s) ran into the cap, retry %d", len(runaways), attempt + 1)
            again, _, again_caps = self._generate([batch[i] for i in runaways], voices)
            for i, w, cap in zip(runaways, again, again_caps, strict=True):
                wavs[i], caps[i] = w, cap
        return [
            {
                "pcm": (np.clip(w, -1.0, 1.0) * 32767).astype(np.int16).tobytes(),
                "sample_rate": sr,
                "capped": hit_cap(len(w) / sr, cap),
            }
            for w, cap in zip(wavs, caps, strict=True)
        ]

    def _generate(self, batch: list[tuple[str, str]], voices: dict[str, bytes]):
        """-> (one float32 waveform per sentence, sample rate, the cap each
        ran with). Out of memory: the two halves, one after the other."""
        import gc

        import numpy as np
        import torch

        cap = token_cap([text for _, text in batch])
        tb = time.perf_counter()
        wavs = None
        try:
            wavs, sr = self.model.generate_voice_clone(
                text=[text for _, text in batch],
                language=[LANGUAGE] * len(batch),
                voice_clone_prompt=[self._prompt(voice, voices) for voice, _ in batch],
                **{**GEN_KWARGS, "max_new_tokens": cap},
            )
        except torch.OutOfMemoryError:
            if len(batch) == 1:
                raise
        if wavs is None:
            # Retried out here: inside the except block, the traceback still
            # holds the failed attempt's tensors, so the retry runs out too.
            gc.collect()
            torch.cuda.empty_cache()
            log.warning("out of memory at %d sentences, splitting", len(batch))
            half = len(batch) // 2
            first, sr, first_caps = self._generate(batch[:half], voices)
            second, _, second_caps = self._generate(batch[half:], voices)
            return first + second, sr, first_caps + second_caps
        longest = max(len(text) for _, text in batch)
        log.info("%d sentences (up to %d chars) in %.0f s", len(batch), longest, time.perf_counter() - tb)
        return [np.asarray(w, dtype=np.float32).squeeze() for w in wavs], sr, [cap] * len(batch)
