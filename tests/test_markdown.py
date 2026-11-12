"""HTML to Markdown and plain text."""

from __future__ import annotations

import pytest

from politescrape import html_to_markdown
from politescrape._util import parse_html
from politescrape.markdown import to_markdown, to_text

BASE = "https://example.test/articles/"


def md(html: str) -> str:
    return html_to_markdown(html, BASE)


def plain(html: str) -> str:
    return to_text(parse_html(html), BASE)


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        # Headings and paragraphs
        ("<h1>Title</h1><h3>Sub <em>part</em></h3>", "# Title\n\n### Sub *part*"),
        ("<p>Hello\n   <b>big</b>\t world</p>", "Hello **big** world"),
        ("<p>one</p><p>two</p>", "one\n\ntwo"),
        ("<div>loose text<p>para</p>more text</div>", "loose text\n\npara\n\nmore text"),
        ("<p>a&nbsp;&nbsp;b</p>", "a b"),
        ("<p>line one<br>line two</p>", "line one\nline two"),
        ("<p>a</p><hr><p>b</p>", "a\n\n---\n\nb"),
        ("<h2><div>Deep</div> title</h2>", "## Deep title"),
        ("<h2>  </h2><p></p>", ""),
        # Emphasis keeps spaces outside the markers
        ("<p>a<strong> b </strong>c</p>", "a **b** c"),
        ("<p><i>very</i> <del>old</del> <s>gone</s></p>", "*very* ~~old~~ ~~gone~~"),
        ("<p>x<b> </b>y</p>", "x y"),
        # Links
        ('<p><a href="/x y">go</a></p>', "[go](https://example.test/x%20y)"),
        ('<p><a href="other">rel</a></p>', "[rel](https://example.test/articles/other)"),
        (
            '<p><a href="/wiki/Tea_(drink)">tea</a></p>',
            "[tea](https://example.test/wiki/Tea_%28drink%29)",
        ),
        (
            '<p><a href="#top">top</a> <a href="javascript:void(0)">js</a> <a>bare</a></p>',
            "top js bare",
        ),
        ('<p>a<a href="/x"></a>b</p>', "ab"),
        ('<p>see<a href="/x"> this </a>now</p>', "see [this](https://example.test/x) now"),
        # Images
        (
            '<img src="/a.png" alt="A [nice] cup">',
            "![A (nice) cup](https://example.test/a.png)",
        ),
        ('<img data-src="lazy.jpg">', "![](https://example.test/articles/lazy.jpg)"),
        ('<p>x<img src="data:image/png;base64,AAAA">y<img alt="none"></p>', "xy"),
        (
            '<a href="/big"><img src="/thumb.png" alt="Thumb"></a>',
            "[![Thumb](https://example.test/thumb.png)](https://example.test/big)",
        ),
        # Code
        ("<p>Use <code>a * b</code> or <kbd>Ctrl</kbd></p>", "Use `a * b` or `Ctrl`"),
        ("<p><code>x `y` z</code> <code>`tick`</code></p>", "``x `y` z`` `` `tick` ``"),
        (
            '<pre><code class="language-python">def f():\n    return 1\n</code></pre>',
            "```python\ndef f():\n    return 1\n```",
        ),
        ("<pre>a  b\n\n  c</pre>", "```\na  b\n\n  c\n```"),
        ("<pre>has ``` inside</pre>", "````\nhas ``` inside\n````"),
        ("<pre>   </pre>", ""),
        # Lists
        ("<ul><li>a</li><li>b</li></ul>", "- a\n- b"),
        ('<ol start="3"><li>c</li><li>d</li></ol>', "3. c\n4. d"),
        (
            "<ul><li>Green<ul><li>Sencha</li><li>Matcha</li></ul></li><li>Black</li></ul>",
            "- Green\n  - Sencha\n  - Matcha\n- Black",
        ),
        ("<ol><li>one<ul><li>inner</li></ul></li></ol>", "1. one\n   - inner"),
        ("<ul><li><p>First</p><p>More</p></li><li>Second</li></ul>", "- First\n  More\n- Second"),
        ("<ul><li>a</li><ul><li>b</li></ul></ul>", "- a\n  - b"),
        ("<ul><li></li><li>only</li></ul>", "- only"),
        ("<li>stray</li>", "- stray"),
        # Quotes
        (
            "<blockquote><p>Tea is nice.</p><p>Really.</p></blockquote>",
            "> Tea is nice.\n>\n> Really.",
        ),
        ("<blockquote>a<blockquote>b</blockquote></blockquote>", "> a\n>\n> > b"),
        # Definition lists
        ("<dl><dt>Term</dt><dd>Meaning</dd></dl>", "**Term**\n\nMeaning"),
        # Things a reader never sees
        (
            "<p>keep</p><script>drop()</script><style>p{}</style><noscript>no</noscript>"
            "<button>Click</button><svg><text>icon</text></svg><!-- note -->",
            "keep",
        ),
        # A block inside an inline element keeps its text
        ('<a href="/x"><div>Card title</div></a>', "Card title"),
    ],
)
def test_markdown(html: str, expected: str) -> None:
    assert md(html) == expected


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("<p>5 * 3 = 15</p>", r"5 \* 3 = 15"),
        ("<p>a `tick`</p>", r"a \`tick\`"),
        ("<p>snake_case and _under_ and a_</p>", r"snake_case and \_under\_ and a\_"),
        ("<p>a &lt;div&gt; tag, 1 &lt; 2</p>", r"a \<div> tag, 1 < 2"),
        ("<p># not a heading</p>", r"\# not a heading"),
        ("<p>- not a list</p>", r"\- not a list"),
        ("<p>+ plus</p>", r"\+ plus"),
        ("<p>1. not numbered</p>", r"1\. not numbered"),
        ("<p>12) nor this</p>", r"12\) nor this"),
        ("<p>&gt; not a quote</p>", r"\> not a quote"),
        ("<p>Title<br>---</p>", "Title\n\\---"),
        ("<p>Total<br>- 5 items</p>", "Total\n\\- 5 items"),
        ("<p>3.14 is pi, #hashtag, -5 degrees</p>", "3.14 is pi, #hashtag, -5 degrees"),
    ],
)
def test_text_that_looks_like_markdown_is_escaped(html: str, expected: str) -> None:
    assert md(html) == expected


def test_tables() -> None:
    html = """
    <table>
      <caption>Caffeine per cup</caption>
      <tr><th>Kind</th><th>mg</th></tr>
      <tr><td>Green | Sencha</td><td><b>28</b></td></tr>
      <tr><td rowspan="2">Black</td><td>47</td></tr>
      <tr><td>50</td></tr>
      <tr><td colspan="2">no data</td></tr>
    </table>
    """
    assert md(html) == (
        "Caffeine per cup\n\n"
        "| Kind | mg |\n"
        "| --- | --- |\n"
        "| Green \\| Sencha | **28** |\n"
        "| Black | 47 |\n"
        "| Black | 50 |\n"
        "| no data | no data |"
    )
    assert plain(html) == (
        "Caffeine per cup\n\nKind\tmg\nGreen | Sencha\t28\nBlack\t47\nBlack\t50\nno data\tno data"
    )


@pytest.mark.parametrize(
    "html",
    [
        "<table><tr><td><p>First</p></td></tr><tr><td><p>Second</p></td></tr></table>",
        '<table role="presentation"><tr><td>First</td><td>Second</td></tr></table>',
        "<table><tr><td>First</td><td><table><tr><td>Second</td></tr></table></td></tr></table>",
    ],
)
def test_layout_tables_become_paragraphs(html: str) -> None:
    assert md(html) == "First\n\nSecond"


def test_empty_table_is_dropped() -> None:
    assert md("<p>a</p><table><tr></tr></table><p>b</p>") == "a\n\nb"


def test_plain_text_has_no_markup() -> None:
    html = (
        "<h1>Title</h1><p>a <b>bold</b> <a href='/x'>link</a> <code>code</code> 2 * 3"
        "<img src='/a.png' alt='pic'></p><ul><li>item</li></ul><ol><li>first</li></ol>"
        "<pre>keep   spacing</pre><blockquote>quoted</blockquote><hr><dl><dt>T</dt><dd>D</dd></dl>"
    )
    assert plain(html) == (
        "Title\n\na bold link code 2 * 3\n\n- item\n\n1. first\n\n"
        "keep   spacing\n\nquoted\n\nT\n\nD"
    )


def test_a_single_element_can_be_converted() -> None:
    soup = parse_html("<div><ul><li>a</li><li>b</li></ul><pre>code</pre><p>p <b>b</b></p></div>")
    assert soup.ul is not None
    assert soup.pre is not None
    assert soup.p is not None
    assert to_markdown(soup.ul) == "- a\n- b"
    assert to_markdown(soup.pre) == "```\ncode\n```"
    assert to_markdown(soup.p) == "p **b**"
    assert to_text(soup.p) == "p b"


def test_links_stay_relative_without_a_base_url() -> None:
    assert html_to_markdown('<a href="/x">go</a>') == "[go](/x)"


def test_empty_document() -> None:
    assert html_to_markdown("") == ""
    assert html_to_markdown("<html><head><title>Only a title</title></head></html>") == ""
