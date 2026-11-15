"""Upstream HTTP for Tombaugh: a fixed host allow-list, keep-alive sessions, retries and deadlines.

Every outgoing request of the API goes through `get` or `get_range`. A URL that is not https, or whose
host is not in `ALLOWED_HOSTS`, raises ValueError before any socket is opened. Redirects are followed by
hand so that every hop passes the same check. Requests are synchronous: callers that want concurrency use
threads, and each thread keeps its own keep-alive `requests.Session`.

All durations are seconds; all byte offsets are 0-based.
"""

from __future__ import annotations

import os
import random
import re
import threading
import time
from collections.abc import Callable, Mapping
from typing import Self
from urllib.parse import urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter

from tombaugh import __version__

ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "irsa.ipac.caltech.edu",
        "nasa-irsa-spherex.s3.us-east-1.amazonaws.com",
        "vizier.cfa.harvard.edu",
        "vizier.idia.ac.za",
        "simbad.harvard.edu",
        "gaia.ari.uni-heidelberg.de",
        "dc.g-vo.org",
        "ssp.imcce.fr",
    }
)

HOST_CONCURRENCY: dict[str, int] = {
    "irsa.ipac.caltech.edu": 2
}  # most requests in flight per host, process-wide
POOL_SIZE = 32  # connections kept alive per session
BACKOFF_MIN_S = 0.1
BACKOFF_MAX_S = 2.0
MAX_REDIRECTS = 3
RANGE_TRIES = 8  # range reads are cheap to repeat, and this network resets many new TLS connections
MIN_TIMEOUT_S = 0.05  # floor for a timeout clamped to a nearly expired deadline

_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_CONTENT_RANGE = re.compile(r"^\s*bytes\s+(?:(\d+)\s*-\s*(\d+)|\*)\s*/\s*(\d+|\*)\s*$", re.IGNORECASE)


def user_agent(contact: str | None = None) -> str:
    """User-Agent value. `contact` (free text, for example a team mailbox) goes inside the parentheses."""
    note = "SPHEREx time-domain viewer"
    clean = re.sub(r"[^\x20-\x7e]|[()]", "", contact or "").strip()[:120]
    return f"tombaugh/{__version__} ({note}; {clean})" if clean else f"tombaugh/{__version__} ({note})"


USER_AGENT = user_agent(os.environ.get("TOMBAUGH_CONTACT"))


class UpstreamError(RuntimeError):
    """An upstream service could not be read.

    `url` is the address asked for, `status` the last HTTP status (None when no response arrived) and
    `attempts` the number of requests that were sent.
    """

    def __init__(self, message: str, *, url: str = "", status: int | None = None, attempts: int = 0) -> None:
        super().__init__(message)
        self.url = url
        self.status = status
        self.attempts = attempts


class DeadlineExceeded(UpstreamError):
    """The caller's deadline ran out before the upstream answered."""


class Deadline:
    """A point `seconds` after construction, on the monotonic clock."""

    def __init__(self, seconds: float) -> None:
        self._end = time.monotonic() + float(seconds)

    def remaining(self) -> float:
        """Seconds left, never negative."""
        return max(0.0, self._end - time.monotonic())

    @property
    def expired(self) -> bool:
        """True once the deadline has passed."""
        return time.monotonic() >= self._end

    def raise_if_expired(self) -> None:
        """Raise DeadlineExceeded once the deadline has passed."""
        if self.expired:
            raise DeadlineExceeded("deadline expired")


class RangeBytes(bytes):
    """Body of a range response. `total` is the object size in bytes from Content-Range, None if unknown."""

    total: int | None

    def __new__(cls, data: bytes = b"", total: int | None = None) -> Self:
        obj = super().__new__(cls, data)
        obj.total = total
        return obj


# --------------------------------------------------------------------------- counters
_stats_lock = threading.Lock()
_stats = {"requests": 0, "retries": 0, "failures": 0, "bytes": 0}


def stats() -> dict[str, int]:
    """Process-wide counters: requests sent, retries among them, failed attempts, body bytes received."""
    with _stats_lock:
        return dict(_stats)


def _count(**deltas: int) -> None:
    with _stats_lock:
        for name, delta in deltas.items():
            _stats[name] += delta


# --------------------------------------------------------------------------- plumbing
_local = threading.local()
_host_slots = {host: threading.BoundedSemaphore(n) for host, n in HOST_CONCURRENCY.items()}
_sleep = time.sleep


def check_url(url: str) -> str:
    """Return the host of `url` when it is https on the allow-list; raise ValueError otherwise."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValueError(f"only https URLs are fetched, got {parts.scheme or 'no scheme'!r}")
    host = parts.hostname or ""
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"host {host!r} is not on the upstream allow-list")
    if parts.username is not None or parts.password is not None or parts.port not in (None, 443):
        raise ValueError("URLs with credentials or a non-standard port are not fetched")
    return host


def _session() -> requests.Session:
    """This thread's keep-alive session (created on first use)."""
    session = getattr(_local, "session", None)
    if session is None:
        session = requests.Session()
        session.mount(
            "https://", HTTPAdapter(pool_connections=POOL_SIZE, pool_maxsize=POOL_SIZE, max_retries=0)
        )
        session.headers["User-Agent"] = USER_AGENT
        _local.session = session
    return session


def _backoff(attempt: int) -> float:
    """Seconds to wait after failed attempt `attempt` (0-based): exponential with jitter, 0.1 to 2 s."""
    base = min(BACKOFF_MAX_S, BACKOFF_MIN_S * 2.0**attempt)
    return min(BACKOFF_MAX_S, max(BACKOFF_MIN_S, base * random.uniform(0.5, 1.5)))


def _clamp(timeout: tuple[float, float], deadline: Deadline | None) -> tuple[float, float]:
    """(connect, read) timeouts, shortened so that neither outlasts the deadline."""
    if deadline is None:
        return timeout
    left = max(MIN_TIMEOUT_S, deadline.remaining())
    return (min(timeout[0], left), min(timeout[1], left))


def _send(
    url: str,
    params: Mapping[str, str] | None,
    headers: Mapping[str, str] | None,
    timeout: tuple[float, float],
    want_partial: bool,
) -> requests.Response:
    """One request, following redirects that stay on the allow-list, with the body fully read.

    A redirect off the allow-list raises ValueError. With `want_partial`, a 200 answer is returned
    unread and closed (the body would be the whole object).
    """
    session = _session()
    _count(requests=1)
    response = session.get(
        url, params=params, headers=headers, timeout=timeout, allow_redirects=False, stream=True
    )
    for _ in range(MAX_REDIRECTS):
        location = response.headers.get("Location")
        if response.status_code not in _REDIRECTS or not location:
            break
        target = urljoin(getattr(response, "url", None) or url, location)
        response.close()
        check_url(target)
        _count(requests=1)
        response = session.get(target, headers=headers, timeout=timeout, allow_redirects=False, stream=True)
    if want_partial and response.status_code == 200:
        response.close()
        return response
    _ = response.content  # read now, so that a broken transfer is raised here and retried
    return response


def _attempt(
    url: str,
    host: str,
    params: Mapping[str, str] | None,
    headers: Mapping[str, str] | None,
    timeout: tuple[float, float],
    deadline: Deadline | None,
    want_partial: bool,
) -> requests.Response:
    """`_send` under the per-host concurrency limit."""
    slots = _host_slots.get(host)
    if slots is None:
        return _send(url, params, headers, _clamp(timeout, deadline), want_partial)
    if not slots.acquire(timeout=None if deadline is None else deadline.remaining()):
        raise DeadlineExceeded(f"deadline expired while waiting for a free slot on {host}", url=url)
    try:
        return _send(url, params, headers, _clamp(timeout, deadline), want_partial)
    finally:
        slots.release()


def _fetch(
    url: str,
    *,
    params: Mapping[str, str] | None,
    headers: Mapping[str, str] | None,
    timeout: tuple[float, float],
    tries: int,
    deadline: Deadline | None,
    problem: Callable[[requests.Response], str | None] | None = None,
    want_partial: bool = False,
) -> requests.Response:
    """The retry loop shared by `get` and `get_range`.

    `problem` inspects a 2xx response and returns None when it is good, or a short description when it
    should be retried (a truncated body, for example).
    """
    host = check_url(url)
    tries = max(1, tries)
    status: int | None = None
    reason = "no attempt made"
    for attempt in range(tries):
        if deadline is not None and deadline.expired:
            raise DeadlineExceeded(f"deadline expired: {reason}", url=url, status=status, attempts=attempt)
        _count(retries=1 if attempt else 0)
        try:
            response = _attempt(url, host, params, headers, timeout, deadline, want_partial)
        except ValueError as exc:  # a redirect that leaves the allow-list, or a malformed URL
            _count(failures=1)
            raise UpstreamError(str(exc), url=url, status=None, attempts=attempt + 1) from exc
        except (requests.RequestException, OSError) as exc:
            status, reason = None, f"{type(exc).__name__}: {exc}"[:200]
        else:
            status = response.status_code
            if want_partial and status == 200:
                _count(failures=1)
                raise UpstreamError(
                    "the server ignored the Range header", url=url, status=200, attempts=attempt + 1
                )
            if 200 <= status < 300:
                reason = problem(response) if problem is not None else None
                if reason is None:
                    _count(bytes=len(response.content))
                    return response
            elif status == 429 or status >= 500:
                reason = f"HTTP {status}"
            else:  # any other 4xx, or a redirect that could not be followed: not worth repeating
                _count(failures=1)
                raise UpstreamError(f"HTTP {status}", url=url, status=status, attempts=attempt + 1)
        _count(failures=1)
        if attempt + 1 < tries:
            delay = _backoff(attempt)
            if deadline is not None and deadline.remaining() <= delay:
                raise DeadlineExceeded(
                    f"deadline expired: {reason}", url=url, status=status, attempts=attempt + 1
                )
            _sleep(delay)
    raise UpstreamError(f"gave up after {tries} attempts: {reason}", url=url, status=status, attempts=tries)


# --------------------------------------------------------------------------- public calls
def get(
    url: str,
    *,
    params: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: tuple[float, float] = (5.0, 30.0),
    tries: int = 5,
    deadline: Deadline | None = None,
) -> requests.Response:
    """GET `url` and return the response, body already read.

    `timeout` is (connect, read) in seconds. Connection errors, timeouts, HTTP 5xx and 429 are retried up
    to `tries` attempts in all, with a jittered exponential backoff of 0.1 to 2 s between attempts. Any
    other 4xx raises UpstreamError at once. With a `deadline`, no request or sleep outlasts it and
    DeadlineExceeded (a subclass of UpstreamError) is raised when it runs out. A URL that is not https or
    not on the allow-list raises ValueError before anything is sent.
    """
    return _fetch(url, params=params, headers=headers, timeout=timeout, tries=tries, deadline=deadline)


def total_size(response: requests.Response) -> int | None:
    """Object size in bytes from the Content-Range header, or None when it is absent or unknown."""
    match = _CONTENT_RANGE.match(response.headers.get("Content-Range") or "")
    if match is None or match.group(3) == "*":
        return None
    return int(match.group(3))


def _range_problem(response: requests.Response, start: int, end: int) -> str | None:
    """None when `response` is exactly bytes [start, end), else what is wrong with it."""
    if response.status_code != 206:
        return f"expected HTTP 206, got {response.status_code}"
    got = len(response.content)
    match = _CONTENT_RANGE.match(response.headers.get("Content-Range") or "")
    first = int(match.group(1)) if match and match.group(1) is not None else None
    last = int(match.group(2)) if match and match.group(2) is not None else None
    if first is not None and first != start:
        return f"range starts at byte {first}, asked for {start}"
    if got == end - start:
        return None
    total = total_size(response)
    at_end_of_object = total is not None and total < end and last == total - 1 and got == total - start
    return None if at_end_of_object else f"body has {got} bytes, expected {end - start}"


def get_range(
    url: str,
    start: int,
    end: int,
    *,
    tries: int = RANGE_TRIES,
    timeout: tuple[float, float] = (5.0, 30.0),
    deadline: Deadline | None = None,
) -> RangeBytes:
    """Bytes of the half-open range [start, end) of `url`.

    The answer must be HTTP 206 with exactly end - start bytes. A shorter body is accepted only when
    Content-Range shows that `end` lies beyond the end of the object; any other length is retried as a
    broken transfer. A 200 answer carrying the whole object raises UpstreamError without being read.
    Retries, timeouts (seconds) and the deadline work as in `get`.
    The result is `bytes` with one extra attribute, `total`: the object size, when the server stated it.
    """
    if start < 0 or end <= start:
        raise ValueError(f"empty or negative byte range [{start}, {end})")
    headers = {"Range": f"bytes={start}-{end - 1}", "Accept-Encoding": "identity"}
    response = _fetch(
        url,
        params=None,
        headers=headers,
        timeout=timeout,
        tries=tries,
        deadline=deadline,
        problem=lambda r: _range_problem(r, start, end),
        want_partial=True,
    )
    return RangeBytes(response.content, total_size(response))
