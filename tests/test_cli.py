"""The command line, driven through ``main`` with a fake site."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from politescrape import __version__
from politescrape.cli import EXIT_FAILED, EXIT_OK, EXIT_ROBOTS, EXIT_USAGE, main

from .conftest import SITE, FakeSite

PAGE = """
<html lang="en"><head><title>Tea shop</title></head><body>
<article>
  <h1>Tea shop</h1>
  <p>We sell <b>tea</b>.</p>
  <div class="product"><span class="name">Green</span> <span class="price">Rs. 250</span></div>
  <div class="product"><span class="name">Black</span> <span class="price">Rs. 180</span></div>
  <table><caption>Stock</caption><tr><th>Kind</th><th>Tins</th></tr><tr><td>Green</td><td>4</td></tr></table>
  <table><tr><th>Day</th></tr><tr><td>Monday</td></tr></table>
  <a href="/about">About</a>
</article>
</body></html>
"""

SCHEMA = {
    "items": ".product",
    "fields": {"name": ".name", "price": {"selector": ".price", "type": "number"}},
}

Run = Callable[..., int]


@pytest.fixture
def shop(site: FakeSite) -> FakeSite:
    site.add("/robots.txt", "User-agent: *\nDisallow: /private/\n", content_type="text/plain")
    site.add("/", PAGE)
    site.add("/about", "<title>About us</title><p>About the shop.</p><a href='/'>Home</a>")
    site.add("/private/accounts", "<title>Secret</title>")
    return site


@pytest.fixture
def run(shop: FakeSite) -> Run:
    """Run the command line against the fake site, without pauses."""

    def run_main(*arguments: str) -> int:
        return main([*arguments, "--delay", "0"], transport=httpx.MockTransport(shop.handle))

    return run_main


@pytest.fixture
def schema_file(tmp_path: Path) -> str:
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(SCHEMA), encoding="utf-8")
    return str(path)


# ------------------------------------------------------------------------ page


def test_page_as_json(run: Run, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("page", SITE + "/") == EXIT_OK
    data = json.loads(capsys.readouterr().out)
    assert data["url"] == SITE + "/"
    assert data["status"] == 200
    assert data["metadata"]["title"] == "Tea shop"
    assert data["tables"][0]["caption"] == "Stock"
    assert data["links"] == [{"url": SITE + "/about", "text": "About", "rel": [], "internal": True}]
    assert data["content"]["markdown"].startswith("# Tea shop\n\nWe sell **tea**.")


def test_page_only_some_parts(run: Run, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("page", SITE + "/", "--only", "metadata, links") == EXIT_OK
    data = json.loads(capsys.readouterr().out)
    assert "metadata" in data
    assert "links" in data
    assert "tables" not in data
    assert "content" not in data


def test_page_as_markdown_and_text(run: Run, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("page", SITE + "/about", "--format", "markdown") == EXIT_OK
    assert capsys.readouterr().out == f"About the shop.\n\n[Home]({SITE}/)\n"
    assert run("page", SITE + "/about", "--format", "text") == EXIT_OK
    assert capsys.readouterr().out == "About the shop.\n\nHome\n"


def test_page_to_a_file(run: Run, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "page.json"
    assert run("page", SITE + "/", "-o", str(target)) == EXIT_OK
    assert capsys.readouterr().out == ""
    assert json.loads(target.read_text(encoding="utf-8"))["metadata"]["title"] == "Tea shop"


def test_page_from_a_saved_file(
    run: Run, tmp_path: Path, capsys: pytest.CaptureFixture[str], shop: FakeSite
) -> None:
    saved = tmp_path / "saved.html"
    saved.write_text(PAGE, encoding="utf-8")

    assert run("page", str(saved), "--only", "links") == EXIT_OK
    assert json.loads(capsys.readouterr().out)["links"][0]["url"] == "/about"

    assert run("page", str(saved), "--only", "links", "--base-url", "https://shop.test/") == EXIT_OK
    assert json.loads(capsys.readouterr().out)["links"][0]["url"] == "https://shop.test/about"
    assert shop.requests == []  # nothing was fetched


def test_page_problems(run: Run, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("page", SITE + "/", "--only", "metadata,pictures") == EXIT_USAGE
    assert "unknown part 'pictures'" in capsys.readouterr().err

    assert run("page", "no-such-file.html") == EXIT_USAGE
    assert "neither an http(s) address nor an existing file" in capsys.readouterr().err

    assert run("page", SITE + "/missing") == EXIT_FAILED
    assert "HTTP 404" in capsys.readouterr().err


def test_robots_txt_is_respected_unless_switched_off(
    run: Run, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("page", SITE + "/private/accounts") == EXIT_ROBOTS
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "robots.txt does not allow" in captured.err

    assert run("page", SITE + "/private/accounts", "--only", "metadata", "--ignore-robots") == (
        EXIT_OK
    )
    captured = capsys.readouterr()
    assert json.loads(captured.out)["metadata"]["title"] == "Secret"
    assert "robots.txt checks are off" in captured.err


def test_network_failures_are_reported(
    shop: FakeSite, run: Run, capsys: pytest.CaptureFixture[str]
) -> None:
    shop.fail("/down", httpx.ConnectError("connection refused"))
    assert run("page", SITE + "/down", "--retries", "0") == EXIT_FAILED
    assert "could not fetch" in capsys.readouterr().err


# ---------------------------------------------------------------------- tables


def test_tables_as_csv(run: Run, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("tables", SITE + "/") == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out == "Kind,Tins\nGreen,4\n"
    assert "2 tables found" in captured.err
    assert "0: 1 rows x 2 columns  Stock" in captured.err
    assert "1: 1 rows x 1 columns  Day" in captured.err

    assert run("tables", SITE + "/", "--index", "1") == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out == "Day\nMonday\n"
    assert captured.err == ""


def test_tables_as_json_and_to_a_file(
    run: Run, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("tables", SITE + "/", "--format", "json") == EXIT_OK
    tables = json.loads(capsys.readouterr().out)
    assert [table["headers"] for table in tables] == [["Kind", "Tins"], ["Day"]]

    target = tmp_path / "stock.csv"
    assert run("tables", SITE + "/", "--index", "0", "--output", str(target)) == EXIT_OK
    assert target.read_bytes() == b"Kind,Tins\nGreen,4\n"


def test_tables_problems(run: Run, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("tables", SITE + "/", "--index", "5") == EXIT_USAGE
    assert "--index must be between 0 and 1" in capsys.readouterr().err

    assert run("tables", SITE + "/about") == EXIT_FAILED
    assert "no tables found" in capsys.readouterr().err

    assert run("tables", SITE + "/about", "--format", "json") == EXIT_OK
    assert json.loads(capsys.readouterr().out) == []


# --------------------------------------------------------------------- extract


def test_extract(run: Run, schema_file: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("extract", SITE + "/", "--schema", schema_file) == EXIT_OK
    assert json.loads(capsys.readouterr().out) == [
        {"name": "Green", "price": 250},
        {"name": "Black", "price": 180},
    ]


def test_extract_schema_problems(
    run: Run, tmp_path: Path, capsys: pytest.CaptureFixture[str], shop: FakeSite
) -> None:
    assert run("extract", SITE + "/", "--schema", str(tmp_path / "missing.json")) == EXIT_USAGE
    assert "cannot read schema file" in capsys.readouterr().err

    bad = tmp_path / "bad.json"
    bad.write_text('{"fields": {"name": {"selector": ".name", "type": "date"}}}', "utf-8")
    assert run("extract", SITE + "/", "--schema", str(bad)) == EXIT_USAGE
    assert "'type' must be one of" in capsys.readouterr().err
    assert shop.requests == []  # the schema is checked before anything is fetched


# ----------------------------------------------------------------------- crawl


def test_crawl_writes_one_json_object_per_page(
    run: Run, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "pages.jsonl"
    assert run("crawl", SITE + "/", "-o", str(target)) == EXIT_OK
    records = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert [record["url"] for record in records] == [SITE + "/", SITE + "/about"]
    assert set(records[0]) == {
        "url",
        "status",
        "content_type",
        "fetched_at",
        "from_cache",
        "metadata",
        "content",
    }
    assert "crawled 2 pages (0 failed, 0 not allowed by robots.txt)" in capsys.readouterr().err


def test_crawl_options(run: Run, schema_file: str, capsys: pytest.CaptureFixture[str]) -> None:
    arguments = ("crawl", SITE + "/", "--only", "links", "--schema", schema_file)
    assert run(*arguments, "--max-pages", "1", "-v") == EXIT_OK
    captured = capsys.readouterr()
    (record,) = [json.loads(line) for line in captured.out.splitlines()]
    assert record["data"][0] == {"name": "Green", "price": 250}
    assert "links" in record
    assert "metadata" not in record
    assert f"[1/1] 200 {SITE}/" in captured.err

    assert run(*arguments, "--max-depth", "0") == EXIT_OK
    assert len(capsys.readouterr().out.splitlines()) == 1

    assert run(*arguments, "--exclude", "about") == EXIT_OK
    assert len(capsys.readouterr().out.splitlines()) == 1

    assert run(*arguments, "--include", "about", "--sitemaps", "--follow-nofollow") == EXIT_OK
    assert len(capsys.readouterr().out.splitlines()) == 2


def test_crawl_can_be_widened_to_other_domains(
    shop: FakeSite, run: Run, capsys: pytest.CaptureFixture[str]
) -> None:
    shop.add("/links", "<a href='https://partner.test/'>Partner</a><a href='/about'>About</a>")
    shop.add("https://partner.test/", "<title>Partner</title>")
    assert run("crawl", SITE + "/links", "--allow-domain", "partner.test") == EXIT_OK
    urls = [json.loads(line)["url"] for line in capsys.readouterr().out.splitlines()]
    assert urls[:3] == [SITE + "/links", "https://partner.test/", SITE + "/about"]


def test_crawl_problems(run: Run, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("crawl", "example.test") == EXIT_USAGE
    assert "is not an http(s) address" in capsys.readouterr().err

    assert run("crawl", SITE + "/", "--include", "(") == EXIT_USAGE
    assert "invalid pattern" in capsys.readouterr().err

    assert run("crawl", SITE + "/", "--max-pages", "0") == EXIT_USAGE
    assert "max_pages" in capsys.readouterr().err

    # Nothing could be fetched at all: that is a failure.
    assert run("crawl", SITE + "/private/accounts") == EXIT_FAILED
    assert "crawled 0 pages (0 failed, 1 not allowed by robots.txt)" in capsys.readouterr().err


# ---------------------------------------------------------------------- robots


def test_robots(run: Run, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("robots", SITE + "/private/accounts", "--user-agent", "research-bot/1.0") == EXIT_OK
    assert json.loads(capsys.readouterr().out) == {
        "url": SITE + "/private/accounts",
        "robots_url": SITE + "/robots.txt",
        "user_agent": "research-bot/1.0",
        "allowed": False,
        "crawl_delay": None,
        "delay_between_requests": 0.0,
        "sitemaps": [],
    }
    assert run("robots", SITE + "/about") == EXIT_OK
    assert json.loads(capsys.readouterr().out)["allowed"] is True

    assert run("robots", "example.test") == EXIT_USAGE
    assert "is not an http(s) address" in capsys.readouterr().err


# --------------------------------------------------------------------- general


def test_version_and_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--version"])
    assert raised.value.code == 0
    assert capsys.readouterr().out.strip() == f"politescrape {__version__}"

    with pytest.raises(SystemExit) as raised:
        main([])
    assert raised.value.code == EXIT_USAGE
    assert "COMMAND" in capsys.readouterr().err

    with pytest.raises(SystemExit):
        main(["crawl", "--help"])
    assert "--max-pages" in capsys.readouterr().out


def test_runs_as_a_module() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "politescrape", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == f"politescrape {__version__}"
