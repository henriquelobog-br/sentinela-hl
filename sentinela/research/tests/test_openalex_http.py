from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from sentinela.research.openalex_http import (
    OpenAlexProtocolError,
    OpenAlexRateLimitError,
    OpenAlexResponseError,
    OpenAlexTransportError,
    OpenAlexWorksClient,
)


def client(handler, **kwargs):
    transport = httpx.MockTransport(handler)
    return OpenAlexWorksClient(
        mailto="research@example.org",
        client=httpx.Client(transport=transport),
        **kwargs,
    )


def test_request_contract_and_raw_results_are_preserved():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={
            "meta": {"count": 1, "next_cursor": None},
            "results": [{"id": "https://openalex.org/W1", "extra": {"x": 1}}],
        })

    page = client(handler).fetch_works_page(
        filters="type:article", per_page=25, select="id,title"
    )
    assert page.results[0]["extra"] == {"x": 1}
    request = seen[0]
    assert request.url.path == "/works"
    assert request.url.params["cursor"] == "*"
    assert request.url.params["per-page"] == "25"
    assert request.url.params["filter"] == "type:article"
    assert request.url.params["mailto"] == "research@example.org"
    assert "mailto:research@example.org" in request.headers["user-agent"]


def test_cursor_pagination_and_max_pages():
    cursors = []

    def handler(request):
        cursor = request.url.params["cursor"]
        cursors.append(cursor)
        payloads = {
            "*": {"meta": {"next_cursor": "next"}, "results": [{"id": "W1"}]},
            "next": {"meta": {"next_cursor": "last"}, "results": [{"id": "W2"}]},
        }
        return httpx.Response(200, json=payloads[cursor])

    works = list(client(handler).iter_works(filters="type:article", max_pages=2))
    assert [item["id"] for item in works] == ["W1", "W2"]
    assert cursors == ["*", "next"]


def test_repeated_cursor_is_rejected():
    def handler(request):
        return httpx.Response(200, json={
            "meta": {"next_cursor": "*"}, "results": []
        })

    with pytest.raises(OpenAlexProtocolError, match="repeated"):
        list(client(handler).iter_works(filters="type:article"))


@pytest.mark.parametrize("per_page", [0, 201])
def test_invalid_page_size_fails_before_request(per_page):
    calls = []
    api = client(lambda request: calls.append(request))
    with pytest.raises(ValueError):
        api.fetch_works_page(filters="type:article", per_page=per_page)
    assert calls == []


def test_429_honors_retry_after_then_succeeds():
    calls = 0
    sleeps = []

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "2.5"})
        return httpx.Response(200, json={"meta": {}, "results": []})

    api = client(handler, sleeper=sleeps.append)
    assert api.fetch_works_page(filters="type:article").results == ()
    assert sleeps == [2.5]


def test_retry_after_http_date_uses_injected_clock():
    calls = 0
    sleeps = []

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={
                "Retry-After": "Sun, 04 Oct 2026 12:00:05 GMT"
            })
        return httpx.Response(200, json={"meta": {}, "results": []})

    api = client(
        handler,
        sleeper=sleeps.append,
        clock=lambda: datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc),
    )
    api.fetch_works_page(filters="type:article")
    assert sleeps == [5.0]


def test_persistent_rate_limit_is_bounded_and_sanitized():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(429, text="secret response body")

    with pytest.raises(OpenAlexRateLimitError) as caught:
        client(handler, sleeper=lambda _: None, max_attempts=2).fetch_works_page(
            filters="type:article"
        )
    assert calls == 2
    assert "secret" not in str(caught.value)


def test_retryable_server_error_uses_exponential_backoff():
    calls = 0
    sleeps = []

    def handler(request):
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"meta": {}, "results": []})

    client(handler, sleeper=sleeps.append).fetch_works_page(filters="type:article")
    assert sleeps == [1.0, 2.0]


def test_ordinary_4xx_is_not_retried():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(404, text="private body")

    with pytest.raises(OpenAlexResponseError) as caught:
        client(handler).fetch_works_page(filters="type:article")
    assert calls == 1
    assert "private" not in str(caught.value)


def test_transport_failure_is_retried_and_sanitized():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("secret endpoint", request=request)

    with pytest.raises(OpenAlexTransportError) as caught:
        client(handler, sleeper=lambda _: None, max_attempts=2).fetch_works_page(
            filters="type:article"
        )
    assert calls == 2
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    "payload",
    [[], {"results": {}}, {"results": ["bad"]}, {"results": [], "meta": []}],
)
def test_malformed_envelope_is_not_retried(payload):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=payload)

    with pytest.raises(OpenAlexProtocolError):
        client(handler).fetch_works_page(filters="type:article")
    assert calls == 1
