"""Finding the main content of a page."""

from __future__ import annotations

from politescrape import Page
from politescrape.extract import Content, extract_content

LONG = "Tea is a drink made by pouring hot water over cured leaves of the tea plant. "


def test_boilerplate_is_removed_and_the_article_is_kept() -> None:
    html = f"""
    <html><body>
      <header class="site-header"><a href="/">Example Mag</a></header>
      <nav><a href="/news">News</a></nav>
      <div class="cookie-banner">We use cookies <button>Accept</button></div>
      <div id="newsletter_popup">Subscribe now</div>
      <main>
        <article>
          <header><h1>All about tea</h1><p class="byline">By A. Writer</p></header>
          <p>{LONG}</p>
          <div hidden>hidden attribute</div>
          <div style="display: none">hidden by style</div>
          <span aria-hidden="true">decorative</span>
          <div class="share-buttons">Share this</div>
          <aside>Pull quote</aside>
          <form action="/comment"><input name="q"> Leave a comment</form>
          <p>The end.</p>
        </article>
        <section class="related">Related stories</section>
      </main>
      <div role="complementary">Sidebar</div>
      <footer>Copyright Example Mag</footer>
      <script>track()</script>
    </body></html>
    """
    content = extract_content(html)

    assert content.markdown == f"# All about tea\n\nBy A. Writer\n\n{LONG.strip()}\n\nThe end."
    assert content.text == f"All about tea\n\nBy A. Writer\n\n{LONG.strip()}\n\nThe end."
    assert content.word_count == len(content.text.split())
    assert content.to_dict() == {
        "markdown": content.markdown,
        "text": content.text,
        "word_count": content.word_count,
    }


def test_a_single_article_wins_over_the_rest_of_the_page() -> None:
    html = f"<body><div>Trending now</div><article><p>{LONG}</p></article><div>More</div></body>"
    assert extract_content(html).text == LONG.strip()


def test_a_listing_of_articles_is_kept_whole() -> None:
    cards = "".join(f"<article><h2>Story {n}</h2><p>{LONG}</p></article>" for n in range(1, 4))
    content = extract_content(f"<body><main><h1>Latest</h1>{cards}</main></body>")
    assert content.markdown.startswith("# Latest\n\n## Story 1")
    assert "## Story 3" in content.markdown

    without_main = extract_content(f"<body><h1>Latest</h1>{cards}</body>")
    assert "## Story 1" in without_main.markdown
    assert "## Story 3" in without_main.markdown


def test_one_long_article_among_teasers_is_the_story() -> None:
    html = (
        f"<body><article><h1>The story</h1><p>{LONG * 6}</p></article>"
        "<article><h2>Teaser</h2><p>Short.</p></article></body>"
    )
    content = extract_content(html)
    assert content.markdown.startswith("# The story")
    assert "Teaser" not in content.markdown


def test_main_and_role_main_are_used_when_there_is_no_article() -> None:
    assert extract_content(f"<body><div>Menu</div><main><p>{LONG}</p></main></body>").text == (
        LONG.strip()
    )
    html = f'<body><div>Menu</div><div role="main"><p>{LONG}</p></div></body>'
    assert extract_content(html).text == LONG.strip()


def test_without_landmarks_the_element_with_the_most_paragraph_text_wins() -> None:
    html = f"""
    <body>
      <div id="top">Example Mag <a href="/">home</a></div>
      <div id="wrap">
        <div class="col"><h1>Tea</h1><p>{LONG}</p><p>{LONG}</p></div>
        <div class="links"><p>Short note</p></div>
      </div>
    </body>
    """
    content = extract_content(html)
    assert content.markdown.startswith("# Tea")
    assert "Example Mag" not in content.text
    assert "Short note" not in content.text


def test_short_pages_fall_back_to_the_whole_body() -> None:
    assert extract_content("<body><p>Hi.</p><div>Bye.</div></body>").text == "Hi.\n\nBye."


def test_a_form_that_wraps_the_whole_page_is_kept() -> None:
    # Common on older ASP.NET sites: everything sits inside one <form>.
    html = f"""
    <body><form id="aspnetForm">
      <input type="hidden" name="__VIEWSTATE" value="abc">
      <div><h1>Notice</h1><p>{LONG}</p><p>{LONG}</p></div>
    </form></body>
    """
    content = extract_content(html)
    assert content.markdown.startswith("# Notice")
    assert LONG.strip() in content.text


def test_a_big_container_is_not_boilerplate_whatever_its_class_says() -> None:
    html = f'<body><div class="layout has-sidebar"><p>{LONG}</p><p>{LONG}</p></div></body>'
    assert LONG.strip() in extract_content(html).text


def test_relative_links_are_resolved() -> None:
    html = '<article><p>Read <a href="/more">more</a>.</p></article>'
    content = extract_content(html, "https://example.test/a/")
    assert content.markdown == "Read [more](https://example.test/more)."


def test_the_pages_own_parsed_document_is_left_intact() -> None:
    page = Page.from_html("<nav><a href='/x'>x</a></nav><article><p>Body text.</p></article>")
    assert page.markdown == "Body text."
    assert page.soup.find("nav") is not None
    assert [link.url for link in page.links] == ["/x"]


def test_empty_and_non_html_documents() -> None:
    assert extract_content("") == Content(markdown="", text="")
    assert extract_content("<html><head><title>t</title></head><body></body></html>").text == ""
