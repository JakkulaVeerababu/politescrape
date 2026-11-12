from __future__ import annotations

import pytest

from politescrape.urls import (
    is_http_url,
    normalize_percent_encoding,
    normalize_url,
    origin,
    path_and_query,
    same_site,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("HTTPS://Example.COM/Path", "https://example.com/Path"),
        ("https://example.com", "https://example.com/"),
        ("https://example.com:443/a", "https://example.com/a"),
        ("http://example.com:80/a", "http://example.com/a"),
        ("https://example.com:8443/a", "https://example.com:8443/a"),
        ("https://example.com/a#section", "https://example.com/a"),
        ("https://example.com/%7Euser/a%2fb", "https://example.com/~user/a%2Fb"),
        ("https://example.com/a b", "https://example.com/a%20b"),
        ("  https://example.com/a  ", "https://example.com/a"),
        ("http://[2001:DB8::1]:8080/x", "http://[2001:db8::1]:8080/x"),
    ],
)
def test_normalize_url(url: str, expected: str) -> None:
    assert normalize_url(url) == expected


def test_normalize_url_removes_tracking_parameters_and_keeps_the_rest_in_order() -> None:
    url = "https://example.com/p?b=2&utm_source=news&a=1&fbclid=xyz&gclid=1"
    assert normalize_url(url) == "https://example.com/p?b=2&a=1"
    assert normalize_url(url, strip_tracking=False) == url


def test_normalize_url_drops_the_question_mark_when_only_tracking_was_there() -> None:
    assert normalize_url("https://example.com/p?utm_medium=email") == "https://example.com/p"


def test_normalize_url_rejects_a_bad_port() -> None:
    with pytest.raises(ValueError, match=r"[Pp]ort"):
        normalize_url("https://example.com:notaport/")


def test_normalize_percent_encoding_encodes_non_ascii() -> None:
    cafe = "/caf" + chr(0xE9)
    assert normalize_percent_encoding(cafe) == "/caf%C3%A9"
    assert normalize_percent_encoding("/caf%c3%a9") == "/caf%C3%A9"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/", True),
        ("http://example.com", True),
        ("ftp://example.com/", False),
        ("mailto:someone@example.com", False),
        ("/relative/path", False),
        ("https://", False),
    ],
)
def test_is_http_url(url: str, expected: bool) -> None:
    assert is_http_url(url) is expected


def test_origin_and_path_and_query() -> None:
    assert origin("HTTPS://Example.com:8443/a/b?c=1") == "https://example.com:8443"
    assert path_and_query("https://example.com/a/b?c=1#d") == "/a/b?c=1"
    assert path_and_query("https://example.com") == "/"


def test_same_site_ignores_www() -> None:
    assert same_site("https://www.example.com/a", "https://example.com/b")
    assert not same_site("https://blog.example.com/", "https://example.com/")
    assert not same_site("about:blank", "about:blank")
