"""Save the main content of any article as a Markdown file.

python examples/article_to_markdown.py https://example.com/some-article article.md
"""

import sys
from pathlib import Path

import politescrape

url, target = sys.argv[1], Path(sys.argv[2])
page = politescrape.get(url).raise_for_status()

title = page.metadata["title"] or url
target.write_text(f"# {title}\n\nSource: {page.url}\n\n{page.markdown}\n", encoding="utf-8")
print(f"Wrote {page.content.word_count} words to {target}")
