"""On-demand source audio for early-stop highlight scanning.

For one or a few requested clips there is no need to download a multi-hour
recording's complete audio. Read three-minute audio chunks when a transcript
block or an audio-offset check needs them. The existing full-audio downloader
is retained as a compatibility fallback when section streams are unavailable.
"""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from . import media, segment_download

RATE = 16000
SECTION_SECONDS = 180
AUDIO_EXTS = {".m4a", ".mp4", ".webm", ".mkv", ".opus", ".aac", ".mp3", ".ts", ".ogg"}


class ProgressiveAudio:
    """A read-only, sliceable 16 kHz audio array backed by time-bounded downloads."""

    def __init__(self, url: str, directory: Path, duration: float, cancelled=None, section_seconds=SECTION_SECONDS):
        if duration <= 0:
            raise ValueError("Audio duration must be known for progressive scanning.")
        self.url = url
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.cancelled = cancelled
        self.section_seconds = int(section_seconds)
        if self.section_seconds < 30:
            raise ValueError("Audio section length is too short.")
        self.section_samples = self.section_seconds * RATE
        self.total_samples = max(1, int(duration * RATE))
        self._sections: dict[int, np.ndarray] = {}
        self._whole: np.ndarray | None = None
        self._lock = threading.RLock()
        self.fallback_used = False

    def __len__(self):
        return self.total_samples

    def _check(self):
        if self.cancelled and self.cancelled():
            raise segment_download.DownloadCancelled("Audio scan cancelled.")

    def _read_section(self, index: int) -> np.ndarray:
        """Fetch just this audio time window using yt-dlp's ffmpeg section mode."""
        self._check()
        start = index * self.section_seconds
        end = min(self.total_samples / RATE, start + self.section_seconds)
        if end <= start:
            return np.empty(0, dtype=np.int16)
        folder = self.directory / "_audio_scan"
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"scan_{index:05d}"
        for p in folder.glob(stem + ".*"):
            if p.is_file():
                p.unlink(missing_ok=True)
        if segment_download._is_youtube_url(self.url):
            fmt = "234/ba[protocol^=m3u8]/ba[protocol=https][ext=m4a]/ba"
        else:
            fmt = "ba[ext=m4a]/ba"
        args = segment_download._yt_dlp_base(self.url) + [
            "--download-sections", f"*{start:.3f}-{end:.3f}",
            "-f", fmt,
            "-o", str(folder / (stem + ".%(ext)s")),
            self.url,
        ]
        wav = folder / f"{stem}.wav"
        try:
            segment_download._run_bounded(
                args, folder, stem + ".*",
                max_seconds=max(90, min(600, self.section_seconds * 3)),
                cancelled=self.cancelled, idle_seconds=75,
            )
            files = [p for p in folder.glob(stem + ".*")
                     if p.is_file() and p.suffix.lower() in AUDIO_EXTS and p.stat().st_size > 512]
            if not files:
                raise RuntimeError("No audio section file was produced.")
            source = max(files, key=lambda p: p.stat().st_size)
            media.extract_audio(source, wav, cancelled=self.cancelled)
            result = media.load_audio(wav)
            if result.ndim != 1:
                raise RuntimeError("Section audio must be mono.")
            return result
        finally:
            # Section files can be large; only the decoded sample window is cached.
            for p in folder.glob(stem + ".*"):
                if p.is_file():
                    p.unlink(missing_ok=True)

    def _load_full(self):
        """Compatibility path: use the already-working full-audio downloader."""
        self._check()
        source = media.download_audio(self.url, self.directory, cancelled=self.cancelled)
        wav = self.directory / "audio_scan_fallback.wav"
        try:
            media.extract_audio(source, wav, cancelled=self.cancelled)
            full = media.load_audio(wav)
            self._whole = np.asarray(full, dtype=np.int16)
            self._sections.clear()
            self.fallback_used = True
        finally:
            wav.unlink(missing_ok=True)
            source.unlink(missing_ok=True)

    def _section(self, index: int) -> np.ndarray:
        with self._lock:
            self._check()
            if self._whole is not None:
                a = index * self.section_samples
                return self._whole[a: a + self.section_samples]
            if index not in self._sections:
                expected = min(self.section_samples, self.total_samples - index * self.section_samples)
                try:
                    part = np.asarray(self._read_section(index), dtype=np.int16)
                    # A stream seek that returns the wrong span would shift all
                    # following transcript timestamps. Fall back instead.
                    if len(part) < max(1, expected - 2 * RATE) or len(part) > expected + 5 * RATE:
                        raise RuntimeError("Audio section has a mismatched duration.")
                    if len(part) < expected:
                        part = np.pad(part, (0, expected - len(part)))
                    self._sections[index] = part[:expected]
                except segment_download.DownloadCancelled:
                    raise
                except Exception:
                    self._load_full()
                    a = index * self.section_samples
                    return self._whole[a: a + self.section_samples]
            return self._sections[index]

    def __getitem__(self, key):
        if isinstance(key, int):
            idx = key if key >= 0 else self.total_samples + key
            if idx < 0 or idx >= self.total_samples:
                raise IndexError(idx)
            return self[idx:idx + 1][0]
        if not isinstance(key, slice):
            raise TypeError("Audio scanning only supports integer and slice indexes.")
        start, stop, step = key.indices(self.total_samples)
        if step != 1:
            raise ValueError("Audio scanner slices require step=1.")
        if stop <= start:
            return np.empty(0, dtype=np.int16)
        chunks = []
        for idx in range(start // self.section_samples, (stop - 1) // self.section_samples + 1):
            part = self._section(idx)
            a = max(start, idx * self.section_samples) - idx * self.section_samples
            b = min(stop, (idx + 1) * self.section_samples) - idx * self.section_samples
            chunks.append(part[a:b])
        if not chunks:
            return np.empty(0, dtype=np.int16)
        return chunks[0] if len(chunks) == 1 else np.concatenate(chunks)
