"""Crawl every page of quotes.toscrape.com and save all quotes to quotes.csv.

Run it from the repository root:

    python examples/crawl_quotes.py
"""

from pathlib import Path

import politescrape
from politescrape.export import write_csv

schema = politescrape.load_schema(Path(__file__).with_name("quotes.json"))

quotes = []
crawler = politescrape.crawl(
    "https://quotes.toscrape.com/",
    include=r"^https://quotes\.toscrape\.com/page/\d+/$",  # follow the "Next" pages only
    max_pages=20,
    user_agent="politescrape-example/1.0 (+https://github.com/JakkulaVeerababu/politescrape)",
)
for page in crawler:
    quotes.extend(page.extract(schema))

write_csv(quotes, "quotes.csv")
print(f"Saved {len(quotes)} quotes from {crawler.stats.pages} pages to quotes.csv")
