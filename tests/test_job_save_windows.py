"""Regression tests for Windows job.json writes (WinError 5) and noisy download progress.

Run with: python tests/test_job_save_windows.py
Uses only temporary files. Does not touch a user's PeakCut data or contact video sites.
"""
import contextlib
import json
import tempfile
import threading
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio import jobs, media


def check(description, condition):
    if not condition:
        raise AssertionError(description)
    print("PASS " + description)


def job_at(folder):
    return {"id": "test-job", "dir": str(folder), "user": "u_test", "source": {"type": "url"},
            "clips": [], "progress": 0.0, "status": "running"}


with tempfile.TemporaryDirectory(prefix="peakcut-job-save-") as folder:
    folder = Path(folder)
    job = job_at(folder)
    jobs.save(job)
    target = folder / "job.json"
    check("a job is saved and can be read as JSON", json.loads(target.read_text())["id"] == "test-job")

    original_replace = Path.replace
    attempts = []

    def replace_with_short_lock(self, target_path):
        attempts.append(1)
        if len(attempts) <= 3:
            raise PermissionError(13, "Windows file is temporarily locked", str(target_path))
        return original_replace(self, target_path)

    job["progress"] = 0.4
    with mock.patch.object(Path, "replace", replace_with_short_lock):
        jobs.save(job)
    check("a temporary Windows lock is retried instead of killing the worker", len(attempts) == 4)
    check("the updated job survives the temporary lock", json.loads(target.read_text())["progress"] == 0.4)
    check("no stale .tmp files after a successful retry", not list(folder.glob("job.json.*.tmp")))

    before = target.read_bytes()
    with mock.patch.object(Path, "replace", side_effect=PermissionError(13, "Protected folder")):
        try:
            jobs.save(job)
        except PermissionError:
            denied = True
        else:
            denied = False
    check("a real permanent permission error is reported", denied)
    check("permanent failures preserve the last complete job.json", target.read_bytes() == before)
    check("permanent failures remove temporary files", not list(folder.glob("job.json.*.tmp")))

    failures = []

    def write_many(index):
        for n in range(10):
            job["progress"] = (index * 10 + n) / 60
            try:
                jobs.save(job)
            except Exception as e:
                failures.append(e)

    threads = [threading.Thread(target=write_many, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("many overlapping job updates do not crash", not failures)
    check("overlapping job updates leave valid JSON", json.loads(target.read_text())["id"] == "test-job")
    check("overlapping writes leave no temporary files", not list(folder.glob("job.json.*.tmp")))

    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def download(self, urls):
            for i in range(1, 101):
                for hook in self.opts["progress_hooks"]:
                    hook({"status": "downloading", "total_bytes": 100, "downloaded_bytes": i})
            (folder / "audio_src.m4a").write_bytes(b"fake")

    updates = []
    with mock.patch.object(media, "_ydl", FakeYoutubeDL), mock.patch.object(media, "_youtube_guard", lambda u: contextlib.nullcontext()):
        result = media.download_audio("https://www.youtube.com/watch?v=fake", folder, updates.append)
    check("audio download still returns its output", result.name == "audio_src.m4a")
    check("progress is throttled, but the final update remains", 1 <= len(updates) <= 3 and updates[-1] == 1.0)

print("ALL PASSED")
