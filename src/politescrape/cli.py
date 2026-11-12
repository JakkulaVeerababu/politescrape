"""The ``politescrape`` command."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import os
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, TextIO

import httpx

from politescrape._util import NO_BASE
from politescrape._version import __version__
from politescrape.client import DEFAULT_USER_AGENT, Client
from politescrape.crawler import Crawler
from politescrape.errors import PoliteScrapeError, RobotsDisallowed, SchemaError
from politescrape.extract.schema import load_schema
from politescrape.page import PARTS, Page
from politescrape.urls import is_http_url, origin, site_name

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_ROBOTS = 3

log = logging.getLogger("politescrape")


class _UsageError(Exception):
    """The command was given something it cannot work with."""


class _Failure(Exception):
    """The command ran but could not produce a result."""


# --------------------------------------------------------------------- output


def _stdout() -> TextIO:
    """Standard output, switched to UTF-8 so non-English text survives pipes on Windows."""
    stream = sys.stdout
    if isinstance(stream, io.TextIOWrapper):
        encoding = (stream.encoding or "").lower().replace("-", "")
        if encoding != "utf8":
            with contextlib.suppress(OSError, ValueError):
                stream.reconfigure(encoding="utf-8")
    return stream


def _write(text: str, path: str | None) -> None:
    if not text.endswith("\n"):
        text += "\n"
    if path is None or path == "-":
        _stdout().write(text)
    else:
        Path(path).write_text(text, encoding="utf-8", newline="")


@contextlib.contextmanager
def _open_output(path: str | None) -> Iterator[TextIO]:
    if path is None or path == "-":
        stream = _stdout()
        yield stream
        stream.flush()
    else:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            yield handle


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _note(message: str) -> None:
    print(f"politescrape: {message}", file=sys.stderr)


# -------------------------------------------------------------------- helpers


def _parts(value: str | None, default: Sequence[str] = PARTS) -> list[str]:
    if not value:
        return list(default)
    parts = [part.strip() for part in value.split(",") if part.strip()]
    unknown = [part for part in parts if part not in PARTS]
    if unknown:
        raise _UsageError(f"unknown part {unknown[0]!r} in --only (choose from {', '.join(PARTS)})")
    return parts


def _client(args: argparse.Namespace, transport: httpx.BaseTransport | None) -> Client:
    return Client(
        user_agent=args.user_agent,
        delay=args.delay,
        timeout=args.timeout,
        retries=args.retries,
        cache_dir=args.cache_dir,
        respect_robots=not args.ignore_robots,
        transport=transport,
    )


def _load_page(args: argparse.Namespace, transport: httpx.BaseTransport | None) -> Page:
    """Fetch a URL, or read a saved HTML file."""
    source: str = args.source
    if is_http_url(source):
        with _client(args, transport) as client:
            return client.get(source).raise_for_status()
    path = Path(source)
    if not path.is_file():
        raise _UsageError(f"{source!r} is neither an http(s) address nor an existing file")
    return Page.from_html(path.read_bytes(), args.base_url or NO_BASE)


# ------------------------------------------------------------------- commands


def _cmd_page(args: argparse.Namespace, transport: httpx.BaseTransport | None) -> int:
    parts = _parts(args.only)
    page = _load_page(args, transport)
    if args.format == "markdown":
        _write(page.markdown, args.output)
    elif args.format == "text":
        _write(page.text, args.output)
    else:
        _write(_json(page.to_dict(parts)), args.output)
    return EXIT_OK


def _cmd_tables(args: argparse.Namespace, transport: httpx.BaseTransport | None) -> int:
    tables = _load_page(args, transport).tables
    if args.format == "json":
        _write(_json([table.to_dict() for table in tables]), args.output)
        return EXIT_OK
    if not tables:
        raise _Failure("no tables found on the page")
    index = args.index
    if index is None:
        index = 0
        if len(tables) > 1:
            _note(f"{len(tables)} tables found; writing the first. Choose another with --index:")
            for number, table in enumerate(tables):
                size = f"{len(table.rows)} rows x {len(table.columns)} columns"
                label = table.caption or ", ".join(table.columns[:4])
                print(f"  {number}: {size}  {label}", file=sys.stderr)
    if not 0 <= index < len(tables):
        raise _UsageError(f"--index must be between 0 and {len(tables) - 1}")
    _write(tables[index].to_csv(), args.output)
    return EXIT_OK


def _cmd_extract(args: argparse.Namespace, transport: httpx.BaseTransport | None) -> int:
    schema = load_schema(args.schema)
    page = _load_page(args, transport)
    _write(_json(page.extract(schema)), args.output)
    return EXIT_OK


def _cmd_crawl(args: argparse.Namespace, transport: httpx.BaseTransport | None) -> int:
    parts = _parts(args.only, default=("metadata", "content"))
    schema = load_schema(args.schema) if args.schema else None
    for url in args.urls:
        if not is_http_url(url):
            raise _UsageError(f"{url!r} is not an http(s) address")
    # --allow-domain widens the crawl: the start sites stay allowed as well.
    domains = (
        [site_name(url) for url in args.urls] + args.allow_domain if args.allow_domain else None
    )
    with _client(args, transport) as client:
        try:
            crawler = Crawler(
                args.urls,
                client=client,
                max_pages=args.max_pages,
                max_depth=args.max_depth,
                allowed_domains=domains,
                include=args.include,
                exclude=args.exclude,
                sitemaps=args.sitemaps,
                follow_nofollow=args.follow_nofollow,
            )
        except ValueError as error:
            raise _UsageError(str(error)) from error
        with _open_output(args.output) as out:
            for page in crawler:
                record = page.to_dict(parts)
                if schema is not None:
                    record["data"] = page.extract(schema) if page.is_html else None
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
    stats = crawler.stats
    _note(
        f"crawled {stats.pages} pages "
        f"({stats.errors} failed, {stats.blocked} not allowed by robots.txt)"
    )
    return EXIT_OK if stats.pages else EXIT_FAILED


def _cmd_robots(args: argparse.Namespace, transport: httpx.BaseTransport | None) -> int:
    url: str = args.url
    if not is_http_url(url):
        raise _UsageError(f"{url!r} is not an http(s) address")
    with _client(args, transport) as client:
        rules = client.robots(url)
        result = {
            "url": url,
            "robots_url": f"{origin(url)}/robots.txt",
            "user_agent": client.user_agent,
            "allowed": rules.can_fetch(client.user_agent, url),
            "crawl_delay": rules.crawl_delay(client.user_agent),
            "delay_between_requests": client.site_delay(url),
            "sitemaps": rules.sitemaps,
        }
    _write(_json(result), args.output)
    return EXIT_OK


# --------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="politescrape",
        description=(
            "Polite, structured web scraping. Respects robots.txt, rate limits itself "
            "and turns pages into JSON, tables and Markdown."
        ),
        epilog="Documentation: https://github.com/JakkulaVeerababu/politescrape",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-o", "--output", metavar="FILE", help="write here instead of the screen")
    common.add_argument(
        "-v", "--verbose", action="count", default=0, help="show progress (-vv for more detail)"
    )
    polite = common.add_argument_group("politeness and network")
    polite.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        metavar="TEXT",
        help="who you are; name your project and give a URL or email address",
    )
    polite.add_argument(
        "--delay",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="pause between requests to one site (default: 1)",
    )
    polite.add_argument("--timeout", type=float, default=20.0, metavar="SECONDS")
    polite.add_argument(
        "--retries", type=int, default=3, metavar="N", help="retries after a failed request"
    )
    polite.add_argument(
        "--cache-dir",
        metavar="DIR",
        help="keep copies of pages here and only download them again when they change",
    )
    polite.add_argument(
        "--ignore-robots",
        action="store_true",
        help="skip robots.txt checks; only for sites you own or have permission to scrape",
    )

    saved = argparse.ArgumentParser(add_help=False)
    saved.add_argument("source", metavar="URL_OR_FILE", help="a web address, or a saved HTML file")
    saved.add_argument(
        "--base-url",
        metavar="URL",
        help="for saved files: the address the page came from, to resolve its links",
    )

    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    page = commands.add_parser(
        "page",
        parents=[saved, common],
        help="everything from one page: metadata, structured data, tables, links, content",
        description="Extract everything from one page as JSON, or its main content as Markdown.",
    )
    page.add_argument("--format", choices=["json", "markdown", "text"], default="json")
    page.add_argument(
        "--only",
        metavar="PARTS",
        help=f"comma-separated parts to include in the JSON: {', '.join(PARTS)}",
    )
    page.set_defaults(handler=_cmd_page)

    tables = commands.add_parser(
        "tables",
        parents=[saved, common],
        help="the tables on a page as CSV or JSON",
        description="Save a table from a page as CSV, or all tables as JSON.",
    )
    tables.add_argument("--format", choices=["csv", "json"], default="csv")
    tables.add_argument(
        "--index", type=int, metavar="N", help="which table to write as CSV (the first is 0)"
    )
    tables.set_defaults(handler=_cmd_tables)

    extract = commands.add_parser(
        "extract",
        parents=[saved, common],
        help="the fields described by a schema file",
        description="Extract the fields described in a JSON schema file (CSS selectors).",
    )
    extract.add_argument("--schema", required=True, metavar="FILE", help="the schema, as JSON")
    extract.set_defaults(handler=_cmd_extract)

    crawl = commands.add_parser(
        "crawl",
        parents=[common],
        help="follow links and save every page as one line of JSON",
        description="Crawl a site politely and write one JSON object per page (JSON Lines).",
    )
    crawl.add_argument("urls", nargs="+", metavar="URL", help="where to start")
    crawl.add_argument("--max-pages", type=int, default=100, metavar="N", help="default: 100")
    crawl.add_argument(
        "--max-depth",
        type=int,
        default=3,
        metavar="N",
        help="how many links away from the start to go (default: 3)",
    )
    crawl.add_argument("--sitemaps", action="store_true", help="also read the site's sitemaps")
    crawl.add_argument(
        "--include", action="append", metavar="REGEX", help="only follow links matching this"
    )
    crawl.add_argument(
        "--exclude", action="append", metavar="REGEX", help="never follow links matching this"
    )
    crawl.add_argument(
        "--allow-domain",
        action="append",
        metavar="DOMAIN",
        help="follow links to this domain too (default: stay on the start site)",
    )
    crawl.add_argument(
        "--follow-nofollow", action="store_true", help="follow links marked rel=nofollow"
    )
    crawl.add_argument(
        "--only",
        metavar="PARTS",
        help=f"parts to save for each page (default: metadata,content): {', '.join(PARTS)}",
    )
    crawl.add_argument(
        "--schema", metavar="FILE", help="also extract these fields from every page, as 'data'"
    )
    crawl.set_defaults(handler=_cmd_crawl)

    robots = commands.add_parser(
        "robots",
        parents=[common],
        help="what a site's robots.txt says about an address",
        description="Show whether robots.txt allows an address, and the site's crawl delay.",
    )
    robots.add_argument("url", metavar="URL")
    robots.set_defaults(handler=_cmd_robots)

    return parser


class _StderrHandler(logging.Handler):
    """Write log messages to whatever ``sys.stderr`` is at the time."""

    def emit(self, record: logging.LogRecord) -> None:
        with contextlib.suppress(OSError, ValueError):
            print(self.format(record), file=sys.stderr)


def _configure_logging(verbosity: int) -> None:
    if not any(isinstance(handler, _StderrHandler) for handler in log.handlers):
        handler = _StderrHandler()
        handler.setFormatter(logging.Formatter("politescrape: %(message)s"))
        log.addHandler(handler)
    levels = {0: logging.WARNING, 1: logging.INFO}
    log.setLevel(levels.get(verbosity, logging.DEBUG))


def main(argv: Sequence[str] | None = None, *, transport: httpx.BaseTransport | None = None) -> int:
    """Run the command line. Returns the process exit code.

    ``transport`` replaces the network layer and exists for tests.
    """
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    if args.ignore_robots:
        _note("robots.txt checks are off; only do this on sites you may scrape")
    try:
        return int(args.handler(args, transport))
    except (_UsageError, SchemaError) as error:
        _note(str(error))
        return EXIT_USAGE
    except RobotsDisallowed as error:
        _note(str(error))
        return EXIT_ROBOTS
    except BrokenPipeError:
        # The reader went away (for example `politescrape ... | head`).
        with contextlib.suppress(OSError, ValueError):
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return EXIT_OK
    except (PoliteScrapeError, _Failure, OSError) as error:
        _note(str(error))
        return EXIT_FAILED
    except KeyboardInterrupt:
        _note("interrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
