"""Transcribe videos locally with faster-whisper — free, offline drop-in for Scribe.

Same audio extraction, silence check, cache path and JSON shape as
transcribe.py, so pack_transcripts.py / timeline_view.py / render.py read
the output unchanged. Writes <edit_dir>/transcripts/<video_stem>.json.

Differences from Scribe:
  - one speaker only (every word is speaker_0); --num-speakers is ignored
  - no audio-event tags ((laughter), (applause))
  - fillers (umm, uh) are coaxed out with a verbatim initial prompt, but
    Whisper can still drop some — check timeline_view at suspicious gaps

Accepts a single video or a directory (batch, sequential, one model load —
parallel workers would each load their own copy into VRAM).

Model: large-v3 on an NVIDIA GPU. Without one it falls back to CPU and, unless
--model was given, uses small (large-v3 on CPU is far too slow for long footage).

Usage:
    python helpers/transcribe_local.py <video_path>
    python helpers/transcribe_local.py <videos_dir>
    python helpers/transcribe_local.py <video_path> --language en
    python helpers/transcribe_local.py <video_path> --model medium --device cpu
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import wave
from pathlib import Path

from transcribe import count_audio_tracks, extract_audio, peak_dbfs, transcript_path
from transcribe_batch import find_videos


# Biases Whisper toward verbatim output so fillers survive into the transcript.
VERBATIM_PROMPT = "Umm, so, uh, let me think, like, hmm... Okay, I mean, you know, here's what I'm, uh, thinking."


def add_cuda_dlls() -> None:
    """Expose the pip-installed CUDA/cuDNN DLLs (nvidia-cublas-cu12, nvidia-cudnn-cu12) on Windows."""
    if os.name != "nt":
        return
    nvidia = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    for bin_dir in nvidia.glob("*/bin"):
        os.add_dll_directory(str(bin_dir))
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


GPU_MODEL = "large-v3"
CPU_MODEL = "small"


def load_model(name: str | None, device: str):
    """Load Whisper on cuda (float16) or cpu (int8). name=None picks
    GPU_MODEL on cuda, CPU_MODEL on cpu. Returns (model, device, name)."""
    add_cuda_dlls()
    from faster_whisper import WhisperModel

    if device in ("auto", "cuda"):
        try:
            gpu_name = name or GPU_MODEL
            return WhisperModel(gpu_name, device="cuda", compute_type="float16"), "cuda", gpu_name
        except Exception as e:
            if device == "cuda":
                raise
            print(f"  cuda unavailable ({e}), falling back to cpu", flush=True)
    if name is None:
        name = CPU_MODEL
        reason = "cpu requested" if device == "cpu" else "no usable NVIDIA GPU"
        print(f"  {reason}: using the {CPU_MODEL} model on cpu "
              f"(pass --model {GPU_MODEL} for best accuracy, much slower)", flush=True)
    return WhisperModel(name, device="cpu", compute_type="int8"), "cpu", name


def load_wav(path: Path):
    """16 kHz mono s16 wav -> float32 array. Bypasses faster-whisper's PyAV decode,
    which breaks on PyAV >= 15 (open() lost its metadata_errors argument)."""
    import numpy as np

    with wave.open(str(path), "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def to_scribe_payload(segments, info, model_name: str) -> dict:
    """Flatten faster-whisper segments into Scribe's word/spacing list."""
    words: list[dict] = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if not text:
                continue
            if words:
                prev_end = words[-1]["end"]
                words.append({
                    "text": " ", "start": prev_end, "end": max(prev_end, w.start),
                    "type": "spacing", "speaker_id": "speaker_0",
                })
            words.append({
                "text": text, "start": round(w.start, 3), "end": round(w.end, 3),
                "type": "word", "speaker_id": "speaker_0",
                "logprob": round(float(w.probability), 4),
            })
    return {
        "language_code": info.language,
        "language_probability": round(float(info.language_probability), 4),
        "text": "".join(w["text"] for w in words),
        "words": words,
        "engine": f"faster-whisper/{model_name}",
    }


def transcribe_one(
    video: Path,
    edit_dir: Path,
    model,
    model_name: str,
    language: str | None = None,
    audio_track: int = 0,
) -> Path:
    """Transcribe a single video. Cached: returns existing path if present."""
    (edit_dir / "transcripts").mkdir(parents=True, exist_ok=True)
    out_path = transcript_path(edit_dir, video, audio_track)
    if out_path.exists():
        print(f"cached: {out_path.name}")
        return out_path

    n_tracks = count_audio_tracks(video)
    if n_tracks > 1:
        print(f"  note: {video.name} has {n_tracks} audio tracks, using track "
              f"{audio_track + 1} (--audio-track to change)", flush=True)

    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / f"{video.stem}.wav"
        extract_audio(video, audio, audio_track)

        peak = peak_dbfs(audio)
        if peak < -60.0:
            raise RuntimeError(
                f"track {audio_track + 1} of {video.name} is silent (peak {peak:.1f} dBFS). "
                + ("Try --audio-track " + " or ".join(str(i) for i in range(n_tracks) if i != audio_track) + "."
                   if n_tracks > 1 else "Check the source audio.")
            )

        print(f"  transcribing {video.name}", flush=True)
        segments, info = model.transcribe(
            load_wav(audio),
            language=language,
            word_timestamps=True,
            initial_prompt=VERBATIM_PROMPT,
            vad_filter=True,  # stops Whisper inventing text over long silences
            vad_parameters={"min_silence_duration_ms": 500},
        )
        payload = to_scribe_payload(segments, info, model_name)

    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    n_words = sum(1 for w in payload["words"] if w["type"] == "word")
    print(f"  saved: {out_path.name} ({n_words} words, {payload['language_code']}) in {time.time() - t0:.1f}s")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Transcribe video(s) locally with faster-whisper")
    ap.add_argument("source", type=Path, help="Video file or directory of videos")
    ap.add_argument("--edit-dir", type=Path, default=None,
                    help="Edit output directory (default: <video_parent>/edit or <videos_dir>/edit)")
    ap.add_argument("--language", type=str, default=None,
                    help="Optional ISO language code (e.g., 'en'). Omit to auto-detect.")
    ap.add_argument("--model", type=str, default=None,
                    help="Whisper model (large-v3, medium, small...). "
                         "Default: large-v3 on an NVIDIA GPU, small on cpu")
    ap.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    ap.add_argument("--audio-track", type=int, default=0,
                    help="Zero-based audio track to transcribe (OBS: 0 = game, 1 = mic).")
    ap.add_argument("--num-speakers", type=int, default=None,
                    help="Accepted for parity with transcribe.py; ignored (no diarization).")
    args = ap.parse_args()

    source = args.source.resolve()
    if source.is_dir():
        videos = find_videos(source)
        edit_dir = (args.edit_dir or (source / "edit")).resolve()
    elif source.exists():
        videos = [source]
        edit_dir = (args.edit_dir or (source.parent / "edit")).resolve()
    else:
        sys.exit(f"not found: {source}")
    if not videos:
        sys.exit(f"no videos found in {source}")

    pending = [v for v in videos if not transcript_path(edit_dir, v, args.audio_track).exists()]
    print(f"found {len(videos)} videos ({len(videos) - len(pending)} cached, {len(pending)} to transcribe)")
    if not pending:
        return

    t0 = time.time()
    model, device, model_name = load_model(args.model, args.device)
    print(f"  loaded {model_name} on {device} in {time.time() - t0:.1f}s", flush=True)

    errors: list[tuple[Path, str]] = []
    for v in pending:
        try:
            transcribe_one(v, edit_dir, model, model_name, args.language, args.audio_track)
        except Exception as e:
            errors.append((v, str(e)))
            print(f"  x {v.name} FAILED: {e}")

    print(f"\ndone in {time.time() - t0:.1f}s")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
