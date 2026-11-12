# politescrape

**Polite, structured web scraping for Python.** Point it at a page and get clean data back: metadata, embedded structured data (JSON-LD), tables, links, and the main content as Markdown. It reads each site's robots.txt, paces its requests, and backs off when a site asks it to.

[![CI](https://github.com/JakkulaVeerababu/politescrape/actions/workflows/ci.yml/badge.svg)](https://github.com/JakkulaVeerababu/politescrape/actions/workflows/ci.yml)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

```console
$ politescrape extract https://books.toscrape.com/ --schema examples/books.json
[
  {
    "title": "A Light in the Attic",
    "price": 51.77,
    "in_stock": true,
    "rating": "Three",
    "url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
    ...
```

## Why politescrape

Most scraping projects start with the same chores: fetch without hammering the site, retry when it fails, respect robots.txt, and then pull out the title, the tables or the article text. politescrape does those chores for you, so you can get to your data.

- **Polite by default.** It follows robots.txt the way [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309) describes, waits between requests to the same site, honours `Crawl-delay` and `Retry-After`, and slows down when a site answers 429 or 503.
- **Useful output without writing selectors.** Every page gives you its metadata, JSON-LD, tables (with merged cells handled), links and main content as Markdown.
- **Your own fields, when you need them.** Describe them in a small JSON schema with CSS selectors.
- **A command line and a library.** Use it from the terminal or from Python. It needs only two packages: [httpx](https://www.python-httpx.org/) and [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/).
- **Typed and tested.** Full type hints and more than 300 tests, none of which touch the network.

## Install

politescrape is not on PyPI yet. Until it is, install it from GitHub:

```bash
pip install "git+https://github.com/JakkulaVeerababu/politescrape"
```

This needs Python 3.10 or newer. For faster parsing, also install `lxml` and pass `parser="lxml"` to `Client`.

## Command line

```bash
# Everything about a page, as JSON
politescrape page https://quotes.toscrape.com/

# Just the main content, as Markdown (handy for reading or for language models)
politescrape page https://en.wikipedia.org/wiki/Web_scraping --format markdown

# A table as CSV; with several tables it lists them so you can pick one with --index
politescrape tables https://en.wikipedia.org/wiki/List_of_largest_cities --index 1 -o cities.csv

# Your own fields, described in a schema file
politescrape extract https://books.toscrape.com/ --schema examples/books.json

# Follow links and save every page as one line of JSON
politescrape crawl https://quotes.toscrape.com/ --max-pages 20 -o quotes.jsonl

# What does robots.txt say about an address?
politescrape robots https://example.com/some/page
```

`page`, `tables` and `extract` also accept a saved HTML file instead of an address. Run `politescrape COMMAND --help` for every option.

Options that work with every command:

| Option | Meaning |
| --- | --- |
| `--user-agent TEXT` | Who you are. Name your project and give a URL or email address. |
| `--delay SECONDS` | Pause between requests to one site (default 1). |
| `--cache-dir DIR` | Keep copies of pages and download them again only when they change. |
| `--retries N`, `--timeout SECONDS` | Network behaviour. |
| `-o FILE` | Write to a file instead of the screen. |
| `-v`, `-vv` | Show progress, or more detail. |
| `--ignore-robots` | Skip robots.txt checks. Only for sites you own or have permission to scrape. |

Exit codes: `0` success, `1` the request or extraction failed, `2` the command was used wrongly, `3` robots.txt does not allow the address.

## Python

```python
import politescrape

page = politescrape.get("https://books.toscrape.com/")

page.metadata["title"]  # 'All products | Books to Scrape - Sandbox'
page.tables  # [Table(headers=[...], rows=[...]), ...]
page.links[0].url  # absolute, de-duplicated links
page.markdown  # the main content as Markdown
page.find_json_ld("Product")  # embedded schema.org data of one type
```

For more than one page, keep a `Client` open. It remembers each site's robots.txt and paces requests to it:

```python
from politescrape import Client

with Client(user_agent="price-tracker/1.0 (+mailto:you@example.com)", delay=2) as client:
    for number in range(1, 4):
        page = client.get(f"https://books.toscrape.com/catalogue/page-{number}.html")
        books = page.extract(
            {
                "items": "article.product_pod",
                "fields": {
                    "title": "h3 a@title",
                    "price": {"selector": ".price_color", "type": "number"},
                },
            }
        )
```

Crawl a site, breadth first:

```python
from politescrape import crawl

crawler = crawl("https://quotes.toscrape.com/", max_pages=50, max_depth=2)
for page in crawler:
    print(page.status, page.url, page.metadata["title"])
print(crawler.stats)  # CrawlStats(pages=50, errors=0, blocked=0, skipped=12)
```

Already have the HTML? Skip the network:

```python
from politescrape import Page

page = Page.from_html(html, url="https://example.com/where-it-came-from")
```

See [`examples/`](examples) for complete scripts.

## What you get from a page

| Attribute | What it holds |
| --- | --- |
| `page.metadata` | Title, description, canonical URL, language, author, publish and update dates, site name, image, favicon, keywords, robots directives, RSS/Atom feeds, Open Graph and Twitter tags. The keys are always the same; missing values are `None`. |
| `page.json_ld` | Every JSON-LD object on the page, with `@graph` containers flattened. Common mistakes (comments around the JSON, trailing commas, raw line breaks) are tolerated. |
| `page.tables` | Data tables. Cells that span rows or columns are repeated so rows line up with the headings, stacked header rows are merged, and layout tables are skipped. Each `Table` has `records()`, `to_csv()` and `save_csv()`. |
| `page.links` | Absolute links with their text, `rel` values and whether they stay on the site. `mailto:`, `javascript:` and fragment-only links are left out. |
| `page.content` | The main content as `markdown` and `text`, with navigation, cookie banners, sidebars, share buttons and footers removed. |
| `page.extract(schema)` | Your own fields; see [the schema reference](docs/extraction-schema.md). |

`page.to_dict()` returns all of it as plain data, ready for `json.dumps`.

## Polite by default

| Behaviour | Default |
| --- | --- |
| robots.txt | Read once per site and kept for 24 hours. Rules follow RFC 9309: the most specific rule wins, `*` and `$` wildcards work, and a robots.txt that cannot be reached means nothing is fetched from that site. Redirects are checked hop by hop. |
| Pace | 1 second between requests to the same site, or the site's `Crawl-delay` if it is longer (capped at 60 seconds). |
| Retries | 3 retries on network errors, 429 and 5xx, with pauses that double each time. A `Retry-After` header is obeyed. If a site asks for more than 120 seconds, politescrape gives up instead. |
| Slowing down | After a 429 or 503, the pause for that site doubles, up to 60 seconds. |
| Identity | A `User-Agent` that names politescrape and links to this page. Please set your own, with a way to reach you. |
| Size | Responses over 10 MB are refused, and the download stops as soon as the limit is passed. |
| Crawling | `rel="nofollow"` links and `<meta name="robots" content="nofollow">` pages are not followed. No address is fetched twice. Links to files such as PDFs and images are skipped. |

## What politescrape will not do

politescrape is for reading public pages the way their owners allow. It does not solve CAPTCHAs, get around bot checks, rotate IP addresses or user agents to avoid detection, log in, or get past paywalls. It does not run JavaScript, so pages that build their content in the browser will look empty. If a site offers an API or a data download, use that instead.

Before you scrape, read [Scraping responsibly](docs/responsible-scraping.md).

## Contributing

Bug reports, ideas and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to set up a development environment and run the checks.

## License

[MIT](LICENSE)
