"""tombaugh.http against a fake session: allow-list, retries, deadlines, range checks. No network."""

from __future__ import annotations

import os
import threading
import time

import pytest
import requests

from tombaugh import http

SIA = "https://irsa.ipac.caltech.edu/SIA"
OBJECT = "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/level2/some.fits"


class FakeResponse:
    def __init__(self, status: int = 200, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self.content = body
        self.headers = headers or {}
        self.url = None
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeSession:
    """Plays back a script of responses and exceptions (the last step repeats) and records every call."""

    def __init__(self, *script: FakeResponse | Exception) -> None:
        self.script = list(script)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((url, kwargs))
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture
def use(monkeypatch: pytest.MonkeyPatch):
    """Install a fake session; returns (install, sleeps) where sleeps lists every backoff taken."""
    sleeps: list[float] = []
    monkeypatch.setattr(http, "_sleep", sleeps.append)

    def install(*script: FakeResponse | Exception) -> FakeSession:
        session = FakeSession(*script)
        monkeypatch.setattr(http, "_session", lambda: session)
        return session

    return install, sleeps


def partial(body: bytes, start: int, total: int) -> FakeResponse:
    return FakeResponse(206, body, {"Content-Range": f"bytes {start}-{start + len(body) - 1}/{total}"})


# --------------------------------------------------------------------------- allow-list
def test_allowed_hosts_are_exactly_the_agreed_eight() -> None:
    assert http.ALLOWED_HOSTS == frozenset(
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


@pytest.mark.parametrize(
    "url",
    [
        "http://irsa.ipac.caltech.edu/SIA",  # not https
        "https://example.org/SIA",  # unknown host
        "https://irsa.ipac.caltech.edu.example.org/SIA",  # look-alike suffix
        "https://irsa.ipac.caltech.edu@example.org/SIA",  # allow-listed name used as credentials
        "https://user@irsa.ipac.caltech.edu/SIA",  # credentials
        "https://irsa.ipac.caltech.edu:8443/SIA",  # another port
        "https://s3.us-east-1.amazonaws.com/nasa-irsa-spherex/x.fits",  # the bucket, but not the agreed host
        "ftp://irsa.ipac.caltech.edu/SIA",
        "irsa.ipac.caltech.edu/SIA",
        "",
    ],
)
def test_urls_off_the_allow_list_are_refused_before_any_request(use, url: str) -> None:
    install, _ = use
    session = install(FakeResponse(200, b"never"))
    with pytest.raises(ValueError):
        http.get(url)
    with pytest.raises(ValueError):
        http.get_range(url, 0, 10)
    assert session.calls == []


def test_every_allowed_host_is_accepted(use) -> None:
    install, _ = use
    session = install(FakeResponse(200, b"ok"))
    for host in sorted(http.ALLOWED_HOSTS):
        assert http.get(f"https://{host}/path").content == b"ok"
    assert len(session.calls) == len(http.ALLOWED_HOSTS)


def test_redirect_off_the_allow_list_is_not_followed(use) -> None:
    install, _ = use
    session = install(FakeResponse(302, b"", {"Location": "https://example.org/elsewhere"}))
    with pytest.raises(http.UpstreamError) as caught:
        http.get(SIA)
    assert [url for url, _ in session.calls] == [SIA]  # the foreign host was never contacted
    assert caught.value.attempts == 1


def test_redirect_on_the_allow_list_is_followed_by_hand(use) -> None:
    install, _ = use
    session = install(FakeResponse(301, b"", {"Location": "/SIA/v2?x=1"}), FakeResponse(200, b"moved"))
    assert http.get(SIA, params={"a": "b"}).content == b"moved"
    assert [url for url, _ in session.calls] == [SIA, "https://irsa.ipac.caltech.edu/SIA/v2?x=1"]
    assert all(kwargs["allow_redirects"] is False for _, kwargs in session.calls)


# --------------------------------------------------------------------------- identity
def test_user_agent_names_the_tool_and_carries_no_personal_detail_by_default() -> None:
    assert http.user_agent() == f"tombaugh/{http.__version__} (SPHEREx time-domain viewer)"
    assert http.user_agent(" team mailbox ") == (
        f"tombaugh/{http.__version__} (SPHEREx time-domain viewer; team mailbox)"
    )
    assert http.user_agent("a(b)\r\nX-Injected: 1") == (
        f"tombaugh/{http.__version__} (SPHEREx time-domain viewer; abX-Injected: 1)"
    )
    assert http.USER_AGENT == http.user_agent(os.environ.get("TOMBAUGH_CONTACT"))
    assert "github" not in http.user_agent().lower() and "@" not in http.user_agent()


def test_each_thread_gets_its_own_keep_alive_session() -> None:
    mine = http._session()
    assert mine is http._session()
    assert mine.headers["User-Agent"] == http.USER_AGENT
    assert mine.get_adapter(SIA)._pool_maxsize == http.POOL_SIZE == 32
    theirs: list[requests.Session] = []
    worker = threading.Thread(target=lambda: theirs.append(http._session()))
    worker.start()
    worker.join()
    assert theirs[0] is not mine


# --------------------------------------------------------------------------- retries
def test_transient_failures_are_retried_with_bounded_backoff(use) -> None:
    install, sleeps = use
    session = install(
        requests.ConnectionError("reset by peer"),
        requests.Timeout("slow"),
        FakeResponse(503),
        FakeResponse(429),
        FakeResponse(200, b"at last"),
    )
    assert http.get(SIA, params={"POS": "circle 1 2 3"}).content == b"at last"
    assert len(session.calls) == 5
    assert len(sleeps) == 4 and all(0.1 <= s <= 2.0 for s in sleeps)
    assert session.calls[0][1]["params"] == {"POS": "circle 1 2 3"}
    assert session.calls[0][1]["timeout"] == (5.0, 30.0)


def test_backoff_stays_between_a_tenth_and_two_seconds() -> None:
    waits = [http._backoff(attempt) for attempt in range(12) for _ in range(50)]
    assert min(waits) >= 0.1 and max(waits) <= 2.0
    assert max(http._backoff(0) for _ in range(50)) <= 0.15  # starts small
    assert min(http._backoff(8) for _ in range(50)) >= 1.0  # grows


def test_gives_up_after_the_given_number_of_tries(use) -> None:
    install, sleeps = use
    session = install(FakeResponse(500))
    with pytest.raises(http.UpstreamError) as caught:
        http.get(SIA, tries=3)
    assert len(session.calls) == 3 and len(sleeps) == 2
    assert (caught.value.url, caught.value.status, caught.value.attempts) == (SIA, 500, 3)
    assert not isinstance(caught.value, http.DeadlineExceeded)


def test_connection_errors_report_no_status(use) -> None:
    install, _ = use
    install(requests.ConnectionError("reset by peer"))
    with pytest.raises(http.UpstreamError) as caught:
        http.get(SIA, tries=2)
    assert caught.value.status is None and caught.value.attempts == 2


@pytest.mark.parametrize("status", [400, 403, 404, 416])
def test_other_4xx_are_never_retried(use, status: int) -> None:
    install, sleeps = use
    session = install(FakeResponse(status))
    with pytest.raises(http.UpstreamError) as caught:
        http.get(SIA)
    assert len(session.calls) == 1 and sleeps == []
    assert (caught.value.status, caught.value.attempts) == (status, 1)


# --------------------------------------------------------------------------- deadlines
def test_deadline_counts_down() -> None:
    deadline = http.Deadline(30.0)
    assert 29.0 < deadline.remaining() <= 30.0 and not deadline.expired
    deadline.raise_if_expired()
    spent = http.Deadline(0.0)
    assert spent.expired and spent.remaining() == 0.0
    with pytest.raises(http.DeadlineExceeded):
        spent.raise_if_expired()
    assert issubclass(http.DeadlineExceeded, http.UpstreamError)


def test_nothing_is_sent_after_the_deadline(use) -> None:
    install, sleeps = use
    session = install(FakeResponse(200, b"never"))
    with pytest.raises(http.DeadlineExceeded):
        http.get(SIA, deadline=http.Deadline(0.0))
    with pytest.raises(http.DeadlineExceeded):
        http.get_range(OBJECT, 0, 10, deadline=http.Deadline(0.0))
    assert session.calls == [] and sleeps == []


def test_never_sleeps_past_the_deadline(use, monkeypatch: pytest.MonkeyPatch) -> None:
    install, sleeps = use
    session = install(FakeResponse(503))
    monkeypatch.setattr(http, "_backoff", lambda attempt: 1.0)
    started = time.monotonic()
    with pytest.raises(http.DeadlineExceeded) as caught:
        http.get(SIA, deadline=http.Deadline(0.5))
    assert time.monotonic() - started < 0.4
    assert len(session.calls) == 1 and sleeps == []  # the 1 s backoff would outlast the 0.5 s left
    assert (caught.value.status, caught.value.attempts) == (503, 1)


def test_timeouts_are_shortened_to_the_deadline(use) -> None:
    install, _ = use
    session = install(FakeResponse(200, b"ok"))
    http.get(SIA, deadline=http.Deadline(2.0))
    connect, read = session.calls[0][1]["timeout"]
    assert 0 < connect <= 2.0 and 0 < read <= 2.0


# --------------------------------------------------------------------------- ranges
def test_get_range_asks_for_the_half_open_range_and_reports_the_object_size(use) -> None:
    install, _ = use
    session = install(partial(b"0123456789", 10, 1000))
    body = http.get_range(OBJECT, 10, 20)
    assert body == b"0123456789" and isinstance(body, bytes) and body.total == 1000
    headers = session.calls[0][1]["headers"]
    assert headers["Range"] == "bytes=10-19" and headers["Accept-Encoding"] == "identity"


def test_a_short_body_is_detected_and_retried(use) -> None:
    install, sleeps = use
    cut_off = FakeResponse(206, b"01234", {"Content-Range": "bytes 10-19/1000"})
    session = install(cut_off, partial(b"0123456789", 10, 1000))
    assert http.get_range(OBJECT, 10, 20) == b"0123456789"
    assert len(session.calls) == 2 and len(sleeps) == 1


def test_a_body_that_stays_short_is_an_error(use) -> None:
    install, _ = use
    session = install(
        partial(b"01234", 10, 1000)
    )  # the server says it sent 10-14 of 1000: not what was asked
    with pytest.raises(http.UpstreamError) as caught:
        http.get_range(OBJECT, 10, 20)
    assert len(session.calls) == http.RANGE_TRIES == 8
    assert (caught.value.attempts, caught.value.status) == (8, 206)


def test_a_short_body_without_content_range_is_an_error(use) -> None:
    install, _ = use
    install(FakeResponse(206, b"01234"))
    with pytest.raises(http.UpstreamError):
        http.get_range(OBJECT, 10, 20, tries=2)


def test_a_short_body_at_the_end_of_the_object_is_accepted(use) -> None:
    install, sleeps = use
    session = install(partial(b"01234", 10, 15))  # the object has only 15 bytes
    body = http.get_range(OBJECT, 10, 20)
    assert body == b"01234" and body.total == 15
    assert len(session.calls) == 1 and sleeps == []


def test_a_range_that_starts_elsewhere_is_rejected(use) -> None:
    install, _ = use
    install(FakeResponse(206, b"0123456789", {"Content-Range": "bytes 0-9/1000"}))
    with pytest.raises(http.UpstreamError):
        http.get_range(OBJECT, 10, 20, tries=2)


def test_a_200_with_the_whole_object_is_an_error_and_is_not_read(use) -> None:
    install, sleeps = use
    whole = FakeResponse(200, b"x" * 1000)
    session = install(whole)
    with pytest.raises(http.UpstreamError) as caught:
        http.get_range(OBJECT, 10, 20)
    assert len(session.calls) == 1 and sleeps == [] and whole.closed
    assert session.calls[0][1]["stream"] is True
    assert (caught.value.status, caught.value.attempts) == (200, 1)


def test_get_range_does_not_retry_a_404(use) -> None:
    install, sleeps = use
    session = install(FakeResponse(404))
    with pytest.raises(http.UpstreamError) as caught:
        http.get_range(OBJECT, 0, 10)
    assert len(session.calls) == 1 and sleeps == [] and caught.value.status == 404


def test_empty_or_negative_ranges_are_refused(use) -> None:
    install, _ = use
    session = install(FakeResponse(206, b""))
    for start, end in [(10, 10), (10, 5), (-1, 5)]:
        with pytest.raises(ValueError):
            http.get_range(OBJECT, start, end)
    assert session.calls == []


@pytest.mark.parametrize(
    ("header", "size"),
    [
        ("bytes 0-34559/65790720", 65790720),
        ("bytes */65790720", 65790720),
        ("BYTES 5-9/10", 10),
        ("bytes 0-9/*", None),
        ("", None),
        ("items 0-9/10", None),
    ],
)
def test_total_size_reads_content_range(header: str, size: int | None) -> None:
    assert http.total_size(FakeResponse(206, b"", {"Content-Range": header} if header else {})) == size


# --------------------------------------------------------------------------- bookkeeping
def test_counters_follow_requests_retries_and_bytes(use) -> None:
    install, _ = use
    install(FakeResponse(503), FakeResponse(200, b"12345"))
    before = http.stats()
    http.get(SIA)
    after = http.stats()
    assert after["requests"] - before["requests"] == 2
    assert after["retries"] - before["retries"] == 1
    assert after["failures"] - before["failures"] == 1
    assert after["bytes"] - before["bytes"] == 5


def test_irsa_never_sees_more_than_two_requests_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    lock = threading.Lock()
    seen = {"in_flight": 0, "peak": 0}
    pair = threading.Barrier(2, timeout=10)  # a request returns only once a second one is in flight with it
    finished: list[bytes] = []

    class PairedSession:
        def get(self, url: str, **kwargs: object) -> FakeResponse:
            with lock:
                seen["in_flight"] += 1
                seen["peak"] = max(seen["peak"], seen["in_flight"])
            try:
                pair.wait()
            finally:
                with lock:
                    seen["in_flight"] -= 1
            return FakeResponse(200, b"ok")

    monkeypatch.setattr(http, "_session", PairedSession)
    workers = [threading.Thread(target=lambda: finished.append(http.get(SIA).content)) for _ in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert http.HOST_CONCURRENCY == {"irsa.ipac.caltech.edu": 2}
    assert finished == [b"ok"] * 8  # two at a time are allowed ...
    assert seen["peak"] == 2  # ... and never a third


def test_the_bucket_is_not_throttled(monkeypatch: pytest.MonkeyPatch) -> None:
    together = threading.Barrier(8, timeout=10)  # released only when all eight requests are in flight at once
    finished: list[bytes] = []

    class CrowdSession:
        def get(self, url: str, **kwargs: object) -> FakeResponse:
            together.wait()
            return partial(b"0123456789", 0, 100)

    monkeypatch.setattr(http, "_session", CrowdSession)
    workers = [
        threading.Thread(target=lambda: finished.append(http.get_range(OBJECT, 0, 10))) for _ in range(8)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert finished == [b"0123456789"] * 8
