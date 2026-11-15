"""Content-addressed disk cache of built fields, with a request index, a size cap and pinned keys.

Layout under the cache directory (``TOMBAUGH_CACHE_DIR``; during development ``.cache`` at the repository
root, found relative to this package):

    fields/<key>/manifest.json     the manifest exactly as served
    fields/<key>/frames.bin.gz     frames.bin, gzip-compressed (served with Content-Encoding: gzip)
    derived/<key>/<name>           answers derived from a field: its exposure list, catalogue overlays,
                                   spectra (written by tombaugh.main; the key may also be a recorded field's)
    requests.json                  snapped request -> {"key", "at", "newest_mjd", "listing"}
    pinned.json                    a JSON list of keys that are never evicted

A key is 16 hexadecimal characters and names its content, so writing a key twice is harmless. Every file is
written to a temporary name in its own directory and renamed, so a reader never sees half a file.

The cap (``TOMBAUGH_CACHE_MAX_MB``, default 2500) counts the bytes under ``fields``. When it is exceeded the
least recently used keys are removed, never a pinned key and never the key just written. Derived files have
a cap of their own, a tenth of that one (at least 16 MB), and the least recently used files go first; the
derived files of a field go with it when the field is evicted.

Sizes are bytes unless a name says megabytes (2**20 bytes); times are Unix seconds.

    python -m tombaugh.cache list | pin KEY | unpin KEY
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tombaugh.grid import snap

ENV_DIR = "TOMBAUGH_CACHE_DIR"
ENV_MAX_MB = "TOMBAUGH_CACHE_MAX_MB"
DEFAULT_MAX_MB = 2500.0
MB = 1024 * 1024
REQUEST_TTL_S = 24 * 3600.0  # a request index entry answers without rediscovery for this long
TOUCH_EVERY_S = 60.0  # how often a read may rewrite the modification time that records "last used"
GZIP_LEVEL = 6
KEY_PATTERN = re.compile(r"^[0-9a-f]{16}$")
MANIFEST_NAME = "manifest.json"
FRAMES_NAME = "frames.bin.gz"
DERIVED_DIR = "derived"
DERIVED_SHARE = 0.1  # derived files may use this share of the cap ...
DERIVED_MIN_MB = 16.0  # ... and at least this many megabytes
DERIVED_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")  # a file name, never a path
_TMP_SUFFIX = ".tmp"


def default_cache_dir() -> Path:
    """The cache directory: ``TOMBAUGH_CACHE_DIR`` when set, else ``.cache`` at the repository root."""
    configured = os.environ.get(ENV_DIR, "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / ".cache"


def default_max_mb() -> float:
    """The size cap in megabytes: ``TOMBAUGH_CACHE_MAX_MB`` when it is a positive number, else 2500."""
    try:
        value = float(os.environ.get(ENV_MAX_MB, ""))
    except ValueError:
        return DEFAULT_MAX_MB
    return value if value > 0.0 else DEFAULT_MAX_MB


def is_key(text: str) -> bool:
    """True when `text` has the shape of a content key (16 lower-case hexadecimal characters)."""
    return isinstance(text, str) and KEY_PATTERN.fullmatch(text) is not None


def request_id(ra: float, dec: float, fov_arcmin: int) -> str:
    """Index name of a request: the snapped centre (degrees, 4 decimals) and the field of view in arcmin."""
    ra0, dec0 = snap(ra, dec)
    return f"{ra0:.4f},{dec0:.4f},{int(fov_arcmin)}"


def compress_frames(frames: bytes) -> bytes:
    """Gzip bytes of a frame file. The same input always gives the same output (no timestamp inside)."""
    return gzip.compress(frames, compresslevel=GZIP_LEVEL, mtime=0)


def write_atomic(path: Path, data: bytes) -> None:
    """Write `data` to `path` so that a reader sees the old file or the new one, never a part of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}{_TMP_SUFFIX}")
    try:
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass
class _Entry:
    size: int  # bytes on disk of the manifest and the compressed frames
    used_at: float  # Unix seconds of the last read or write
    touched_at: float = 0.0  # Unix seconds when used_at was last written to the disk


class FieldCache:
    """The disk cache of one service process. Safe to use from several threads."""

    def __init__(
        self,
        root: Path | str | None = None,
        max_mb: float | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.root = Path(root) if root is not None else default_cache_dir()
        self.max_bytes = int((max_mb if max_mb is not None else default_max_mb()) * MB)
        self.derived_max_bytes = max(int(DERIVED_MIN_MB * MB), int(DERIVED_SHARE * self.max_bytes))
        self._clock = clock
        self._lock = threading.RLock()
        self._entries: dict[str, _Entry] = {}
        self._derived: dict[tuple[str, str], _Entry] = {}
        self._requests: dict[str, dict] = {}
        self._fields = self.root / "fields"
        self._derived_root = self.root / DERIVED_DIR
        self._requests_path = self.root / "requests.json"
        self._pinned_path = self.root / "pinned.json"
        self._fields.mkdir(parents=True, exist_ok=True)
        self._scan()
        self._scan_derived()
        self._load_requests()

    # ------------------------------------------------------------------ fields
    def _dir(self, key: str) -> Path:
        if not is_key(key):
            raise ValueError(f"not a cache key: {key!r}")
        return self._fields / key

    def _scan(self) -> None:
        """Rebuild the table of entries from the disk; drop folders left incomplete by a crash."""
        for folder in self._fields.iterdir():
            if not folder.is_dir() or not is_key(folder.name):
                continue
            for leftover in folder.glob(f".*{_TMP_SUFFIX}"):
                leftover.unlink(missing_ok=True)
            manifest, frames = folder / MANIFEST_NAME, folder / FRAMES_NAME
            if not manifest.is_file():
                shutil.rmtree(folder, ignore_errors=True)
                continue
            size = manifest.stat().st_size + (frames.stat().st_size if frames.is_file() else 0)
            used_at = manifest.stat().st_mtime
            self._entries[folder.name] = _Entry(size, used_at, used_at)

    def put(self, key: str, manifest_json: bytes, frames: bytes | None) -> list[str]:
        """Store a field: its manifest (UTF-8 JSON) and its uncompressed frame bytes, None for an empty field.

        The frames are compressed here. Returns the keys that were evicted to stay under the cap.
        """
        folder = self._dir(key)
        packed = compress_frames(frames) if frames else None
        size = len(manifest_json) + (len(packed) if packed else 0)
        with self._lock:
            if packed:
                write_atomic(folder / FRAMES_NAME, packed)
            write_atomic(folder / MANIFEST_NAME, manifest_json)
            now = self._clock()
            os.utime(folder / MANIFEST_NAME, (now, now))  # "last used", as a restart will read it
            self._entries[key] = _Entry(size, now, now)
            return self._evict(protect=key)

    def has(self, key: str) -> bool:
        """True when the field `key` is stored."""
        with self._lock:
            return key in self._entries

    def _read(self, key: str, name: str) -> bytes | None:
        if not is_key(key):
            return None
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            path = self._fields / key / name
            try:
                data = path.read_bytes()
            except FileNotFoundError:
                return None
            self._touch(key, entry)
            return data

    def _touch(self, key: str, entry: _Entry) -> None:
        """Record that `key` was used now; the time reaches the disk at most once a minute."""
        now = self._clock()
        entry.used_at = now
        if now - entry.touched_at >= TOUCH_EVERY_S:
            entry.touched_at = now
            try:
                os.utime(self._fields / key / MANIFEST_NAME, (now, now))
            except OSError:
                pass

    def get_manifest(self, key: str) -> bytes | None:
        """The stored manifest JSON of `key`, or None."""
        return self._read(key, MANIFEST_NAME)

    def get_frames_gz(self, key: str) -> bytes | None:
        """The gzip-compressed frame file of `key`, or None (also None for an empty field)."""
        return self._read(key, FRAMES_NAME)

    def get_field(self, key: str) -> tuple[bytes | None, bytes | None]:
        """(manifest JSON, gzip-compressed frame file) of `key`, read as one pair.

        A `put` of the same key cannot fall between the two reads, so the manifest describes these frames.
        """
        with self._lock:
            return self._read(key, MANIFEST_NAME), self._read(key, FRAMES_NAME)

    def keys_by_use(self) -> list[str]:
        """Stored keys, least recently used first."""
        with self._lock:
            return sorted(self._entries, key=lambda key: (self._entries[key].used_at, key))

    # ------------------------------------------------------------------ size cap
    def used_bytes(self) -> int:
        """Bytes held under ``fields``."""
        with self._lock:
            return sum(entry.size for entry in self._entries.values())

    def free_bytes(self) -> int:
        """Bytes that can still be stored: what is left under the cap, and no more than the disk has free."""
        under_cap = max(0, self.max_bytes - self.used_bytes())
        try:
            return min(under_cap, shutil.disk_usage(self.root).free)
        except OSError:
            return under_cap

    def _evict(self, protect: str | None = None) -> list[str]:
        """Remove least recently used keys until the cap holds; pinned keys and `protect` stay."""
        removed: list[str] = []
        total = sum(entry.size for entry in self._entries.values())
        if total <= self.max_bytes:
            return removed
        pinned = self.pinned()
        for key in self.keys_by_use():
            if total <= self.max_bytes:
                break
            if key in pinned or key == protect:
                continue
            total -= self._entries[key].size
            self._remove(key)
            removed.append(key)
        if removed:
            self._save_requests()
        return removed

    def _remove(self, key: str) -> None:
        shutil.rmtree(self._fields / key, ignore_errors=True)
        self._entries.pop(key, None)
        for name in [name for name, entry in self._requests.items() if entry.get("key") == key]:
            del self._requests[name]
        self._remove_derived(key)

    # ------------------------------------------------------------------ derived files
    def _derived_path(self, key: str, name: str) -> Path:
        if not is_key(key):
            raise ValueError(f"not a cache key: {key!r}")
        if not isinstance(name, str) or DERIVED_NAME.fullmatch(name) is None:
            raise ValueError(f"not a derived file name: {name!r}")
        return self._derived_root / key / name

    def _scan_derived(self) -> None:
        """Rebuild the table of derived files from the disk; drop temporary leftovers."""
        if not self._derived_root.is_dir():
            return
        for folder in self._derived_root.iterdir():
            if not folder.is_dir() or not is_key(folder.name):
                continue
            for path in folder.iterdir():
                if path.name.endswith(_TMP_SUFFIX):
                    path.unlink(missing_ok=True)
                elif path.is_file() and DERIVED_NAME.fullmatch(path.name):
                    stat = path.stat()
                    self._derived[(folder.name, path.name)] = _Entry(
                        stat.st_size, stat.st_mtime, stat.st_mtime
                    )

    def put_derived(self, key: str, name: str, data: bytes) -> list[tuple[str, str]]:
        """Store a file derived from the field `key` (which need not be stored here: a recorded field's key
        is allowed). Returns the (key, name) pairs evicted to stay under the derived cap."""
        path = self._derived_path(key, name)
        with self._lock:
            write_atomic(path, data)
            now = self._clock()
            os.utime(path, (now, now))
            self._derived[(key, name)] = _Entry(len(data), now, now)
            return self._evict_derived(protect=(key, name))

    def get_derived(self, key: str, name: str) -> bytes | None:
        """A derived file of the field `key`, or None."""
        try:
            path = self._derived_path(key, name)
        except ValueError:
            return None
        with self._lock:
            entry = self._derived.get((key, name))
            if entry is None:
                return None
            try:
                data = path.read_bytes()
            except FileNotFoundError:
                self._derived.pop((key, name), None)
                return None
            now = self._clock()
            entry.used_at = now
            if now - entry.touched_at >= TOUCH_EVERY_S:
                entry.touched_at = now
                try:
                    os.utime(path, (now, now))
                except OSError:
                    pass
            return data

    def derived_bytes(self) -> int:
        """Bytes held under ``derived``."""
        with self._lock:
            return sum(entry.size for entry in self._derived.values())

    def _evict_derived(self, protect: tuple[str, str] | None = None) -> list[tuple[str, str]]:
        """Remove least recently used derived files until their cap holds; `protect` stays."""
        removed: list[tuple[str, str]] = []
        total = sum(entry.size for entry in self._derived.values())
        if total <= self.derived_max_bytes:
            return removed
        for pair in sorted(self._derived, key=lambda pair: (self._derived[pair].used_at, pair)):
            if total <= self.derived_max_bytes:
                break
            if pair == protect:
                continue
            total -= self._derived.pop(pair).size
            (self._derived_root / pair[0] / pair[1]).unlink(missing_ok=True)
            removed.append(pair)
        return removed

    def _remove_derived(self, key: str) -> None:
        """Remove every derived file of `key` (its field was evicted)."""
        for pair in [pair for pair in self._derived if pair[0] == key]:
            del self._derived[pair]
        shutil.rmtree(self._derived_root / key, ignore_errors=True)

    # ------------------------------------------------------------------ pinned keys
    def pinned(self) -> frozenset[str]:
        """Keys that are never evicted (read from ``pinned.json`` each time, so an edit needs no restart)."""
        try:
            listed = json.loads(self._pinned_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return frozenset()
        if not isinstance(listed, list):
            return frozenset()
        return frozenset(key for key in listed if is_key(key))

    def pin(self, key: str) -> None:
        """Never evict `key`."""
        self._dir(key)
        with self._lock:
            self._write_pinned(self.pinned() | {key})

    def unpin(self, key: str) -> None:
        """Allow `key` to be evicted again."""
        with self._lock:
            self._write_pinned(self.pinned() - {key})

    def _write_pinned(self, keys: frozenset[str]) -> None:
        write_atomic(self._pinned_path, (json.dumps(sorted(keys), indent=2) + "\n").encode("utf-8"))

    # ------------------------------------------------------------------ request index
    def _load_requests(self) -> None:
        try:
            loaded = json.loads(self._requests_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(loaded, dict):
            return
        for name, entry in loaded.items():
            if isinstance(entry, dict) and entry.get("key") in self._entries:
                self._requests[name] = entry

    def _save_requests(self) -> None:
        text = json.dumps(self._requests, indent=0, sort_keys=True) + "\n"
        write_atomic(self._requests_path, text.encode("utf-8"))

    def remember(
        self,
        ra: float,
        dec: float,
        fov_arcmin: int,
        key: str,
        *,
        newest_mjd: float | None = None,
        age_s: float = 0.0,
        listing_key: str | None = None,
    ) -> None:
        """Record that the request (snapped position, field of view) is answered by `key`.

        `newest_mjd` is the mid-time (MJD days) of the newest exposure the archive listed for the request;
        None keeps the value recorded before. `age_s` records the entry as already that many seconds old,
        so that it stops answering sooner: used for results that deserve an early retry.

        `listing_key` is the key of the listing whose complete build gave `key` (see
        `tombaugh.build.BuildStats.listing_key`); it is what `field_for_listing` compares. Pass it only for
        a build that read every exposure it selected. None keeps the one recorded before when `key` is the
        field recorded before, and records none otherwise.
        """
        self._dir(key)
        name = request_id(ra, dec, fov_arcmin)
        with self._lock:
            before = self._requests.get(name, {})
            if newest_mjd is None:
                newest_mjd = before.get("newest_mjd")
            if listing_key is None and before.get("key") == key:
                listing_key = before.get("listing")
            entry = {
                "key": key,
                "at": round(self._clock() - max(0.0, age_s), 3),
                "newest_mjd": newest_mjd,
            }
            if listing_key is not None:
                entry["listing"] = listing_key
            self._requests[name] = entry
            self._save_requests()

    def field_for_listing(self, ra: float, dec: float, fov_arcmin: int, listing_key: str) -> str | None:
        """The stored field that a complete build of a listing gave for a request, or None.

        `listing_key` is `field_key` over the exposures the archive lists now. The field is known in two
        cases: a stored field has that very key (every listed exposure was used), or the request's index
        entry, of any age, records that listing and its field is still stored (some listed exposures are
        never used: off the detector, unusable).
        """
        with self._lock:
            if listing_key in self._entries:
                return listing_key
            entry = self._requests.get(request_id(ra, dec, fov_arcmin))
            if entry is None or entry.get("listing") != listing_key:
                return None
            return entry["key"] if entry.get("key") in self._entries else None

    def lookup(
        self, ra: float, dec: float, fov_arcmin: int, *, max_age_s: float | None = REQUEST_TTL_S
    ) -> str | None:
        """The key that answers a request, or None.

        Only an entry younger than `max_age_s` seconds counts; pass None to accept any age (used to serve
        a stale copy when the archive is down). An entry whose field has been evicted is forgotten.
        """
        name = request_id(ra, dec, fov_arcmin)
        with self._lock:
            entry = self._requests.get(name)
            if entry is None:
                return None
            if entry.get("key") not in self._entries:
                del self._requests[name]
                return None
            age = self._clock() - float(entry.get("at", 0.0))
            if max_age_s is not None and age > max_age_s:
                return None
            return entry["key"]

    def newest_mjd(self) -> float | None:
        """The newest exposure mid-time (MJD days) seen by any request in the index, or None."""
        with self._lock:
            seen = [entry.get("newest_mjd") for entry in self._requests.values()]
        times = [float(value) for value in seen if isinstance(value, int | float)]
        return max(times, default=None)


def main(argv: list[str] | None = None) -> int:
    """Command line: list the stored keys, or pin and unpin one."""
    parser = argparse.ArgumentParser(
        prog="python -m tombaugh.cache", description=(__doc__ or "").split("\n")[0]
    )
    parser.add_argument("action", choices=("list", "pin", "unpin"))
    parser.add_argument("key", nargs="?")
    args = parser.parse_args(argv)
    cache = FieldCache()
    if args.action == "list":
        pinned = cache.pinned()
        for key in cache.keys_by_use():
            print(key, "pinned" if key in pinned else "")
        print(f"{cache.used_bytes() / MB:.1f} MB used of {cache.max_bytes / MB:.0f} MB")
        return 0
    if args.key is None or not is_key(args.key):
        parser.error("a 16-character hexadecimal key is required")
    (cache.pin if args.action == "pin" else cache.unpin)(args.key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
