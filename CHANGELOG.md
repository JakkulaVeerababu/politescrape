# Changelog

All notable changes to this project are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [semantic versioning](https://semver.org/).

## Unreleased

## 0.1.0 (2026-11-12)

First release.

- `Client`: fetches politely, with RFC 9309 robots.txt rules, a delay between requests to each site, `Crawl-delay`, retries with growing pauses, `Retry-After`, slowing down after 429 and 503, redirects checked hop by hop, a response size limit and an optional on-disk cache with `ETag` and `Last-Modified` revalidation.
- `Page`: metadata, JSON-LD, tables (with merged cells handled), links, main content as Markdown and text, CSS queries and `to_dict()`.
- Extraction schemas: describe fields with CSS selectors in JSON, with types, patterns, defaults, lists and nested fields.
- `crawl()`: breadth-first crawling with page and depth limits, include and exclude patterns, sitemaps and `nofollow` support.
- Command line: `page`, `tables`, `extract`, `crawl` and `robots`.
