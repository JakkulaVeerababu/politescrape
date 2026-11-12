"""Convert HTML to Markdown or plain text.

The converter works on blocks. Block elements (paragraphs, headings, lists,
tables, code) each become one block of output; the inline content between
them is gathered into paragraphs. Blocks are joined with one blank line, so
the result has no stray whitespace to clean up afterwards.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup
from bs4.element import NavigableString, PreformattedString, Tag

from politescrape._grid import own_rows, read_grid, row_cells
from politescrape._util import (
    BLOCK_TAGS,
    SKIP_TAGS,
    absolute,
    attr,
    attr_list,
    collapse,
    only_tags,
    parse_html,
)

_BLOCK_LIST = sorted(BLOCK_TAGS)
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_STRONG = frozenset({"b", "strong"})
_EMPHASIS = frozenset({"em", "i"})
_STRIKE = frozenset({"del", "s", "strike"})
_CODE = frozenset({"code", "kbd", "samp", "tt"})

_LINE_BREAK = "\x00"  # stands in for <br> until whitespace has been collapsed
_SPACES = re.compile(r"[ \t\r\n\f\v\xa0]+")
_AROUND_BREAK = re.compile(r" ?\x00 ?")
_SPECIAL = re.compile(r"([*`])")
_LOOSE_UNDERSCORE = re.compile(r"(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])")
_TAG_START = re.compile(r"<(?=[A-Za-z/!?])")
_BLOCK_START = re.compile(r"(#{1,6}(\s|$)|>|[-+](\s|$)|={3,}\s*$|-{3,}\s*$)")
_ORDERED_START = re.compile(r"(\d+)[.)](?=\s|$)")
_CODE_LANGUAGE = re.compile(r"(?:language|lang)-([A-Za-z0-9#+.-]+)$")
_BACKTICKS = re.compile(r"`+")


def to_markdown(node: Tag, base_url: str = "") -> str:
    """Render an element (or a whole parsed document) as Markdown."""
    return "\n\n".join(_Renderer(base_url, plain=False).render(node))


def to_text(node: Tag, base_url: str = "") -> str:
    """Render an element as plain text, keeping paragraphs and list structure."""
    return "\n\n".join(_Renderer(base_url, plain=True).render(node))


def html_to_markdown(html: str, base_url: str = "", *, parser: str = "html.parser") -> str:
    """Convert an HTML string to Markdown. Relative links are resolved against ``base_url``."""
    return to_markdown(parse_html(html, parser), base_url)


def _escape(text: str) -> str:
    """Escape the characters that would otherwise turn text into Markdown syntax."""
    text = _SPECIAL.sub(r"\\\1", text)
    text = _LOOSE_UNDERSCORE.sub(r"\\_", text)
    return _TAG_START.sub(r"\\<", text)


def _wrap(inner: str, marker: str) -> str:
    """Put ``marker`` around the text, keeping surrounding spaces outside the markers."""
    core = inner.strip()
    if not core:
        return inner
    start = len(inner) - len(inner.lstrip())
    end = len(inner.rstrip())
    return f"{inner[:start]}{marker}{core}{marker}{inner[end:]}"


def _protect_line(line: str) -> str:
    ordered = _ORDERED_START.match(line)
    if ordered:
        # "1. text" would start a numbered list; "1\. text" does not.
        return f"{ordered.group(1)}\\{line[ordered.end(1) :]}"
    return "\\" + line if _BLOCK_START.match(line) else line


def _link_target(url: str) -> str:
    return url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


class _Renderer:
    def __init__(self, base_url: str, *, plain: bool) -> None:
        self.base_url = base_url
        self.plain = plain

    def render(self, node: Tag) -> list[str]:
        if isinstance(node, BeautifulSoup):
            return self.blocks(node)
        return self.block(node)

    # ------------------------------------------------------------------ blocks

    def blocks(self, node: Tag) -> list[str]:
        """Render the children of ``node`` as a list of blocks."""
        out: list[str] = []
        pending: list[str] = []

        def flush() -> None:
            text = self.finish_inline("".join(pending))
            pending.clear()
            if text:
                out.append(text if self.plain else self.protect_start(text))

        for child in node.children:
            if isinstance(child, NavigableString):
                if not isinstance(child, PreformattedString):
                    pending.append(self.text(str(child)))
            elif isinstance(child, Tag):
                if child.name in SKIP_TAGS:
                    continue
                if child.name in BLOCK_TAGS or child.find(_BLOCK_LIST) is not None:
                    flush()
                    out.extend(self.block(child))
                else:
                    pending.append(self.inline(child))
        flush()
        return out

    def block(self, tag: Tag) -> list[str]:
        name = tag.name
        if name in SKIP_TAGS:
            return []
        if name in _HEADINGS:
            return self.heading(tag)
        if name == "hr":
            return [] if self.plain else ["---"]
        if name == "pre":
            return self.preformatted(tag)
        if name in ("ul", "ol", "menu"):
            return self.item_list(tag)
        if name == "li":
            return self.list_item(tag, "- ")
        if name == "blockquote":
            return self.quote(tag)
        if name == "table":
            return self.table(tag)
        if name == "dt":
            return self.term(tag)
        return self.blocks(tag)

    def heading(self, tag: Tag) -> list[str]:
        text = self.finish_inline(self.inline_children(tag)).replace("\n", " ")
        if not text:
            return []
        return [text] if self.plain else ["#" * int(tag.name[1]) + " " + text]

    def preformatted(self, tag: Tag) -> list[str]:
        code = "\n".join(line.rstrip() for line in tag.get_text().splitlines()).strip("\n")
        if not code.strip():
            return []
        if self.plain:
            return [code]
        language = ""
        for element in (tag, tag.find("code")):
            if isinstance(element, Tag):
                for class_name in attr_list(element, "class"):
                    match = _CODE_LANGUAGE.match(class_name)
                    if match:
                        language = match.group(1)
                        break
            if language:
                break
        fence = "```"
        while fence in code:
            fence += "`"
        return [f"{fence}{language}\n{code}\n{fence}"]

    def item_list(self, tag: Tag) -> list[str]:
        ordered = tag.name == "ol"
        start = attr(tag, "start").strip()
        number = int(start) if ordered and start.lstrip("-").isdigit() else 1
        items: list[str] = []
        for child in only_tags(tag.children):
            if child.name == "li":
                marker = f"{number}. " if ordered else "- "
                number += 1
                items.extend(self.list_item(child, marker))
            elif child.name in ("ul", "ol", "menu"):
                # A list placed directly inside a list (invalid, but common): nest it.
                items.extend(_indent(block, "  ") for block in self.item_list(child))
            else:
                items.extend(self.block(child))
        return ["\n".join(items)] if items else []

    def list_item(self, tag: Tag, marker: str) -> list[str]:
        blocks = self.blocks(tag)
        if not blocks:
            return []
        lines = "\n".join(blocks).split("\n")
        padding = " " * len(marker)
        rest = [padding + line if line else "" for line in lines[1:]]
        return ["\n".join([marker + lines[0], *rest])]

    def quote(self, tag: Tag) -> list[str]:
        blocks = self.blocks(tag)
        if not blocks or self.plain:
            return blocks
        lines = "\n\n".join(blocks).split("\n")
        return ["\n".join(f"> {line}".rstrip() for line in lines)]

    def term(self, tag: Tag) -> list[str]:
        text = self.finish_inline(self.inline_children(tag)).replace("\n", " ")
        if not text:
            return []
        return [text] if self.plain else [f"**{text}**"]

    def table(self, tag: Tag) -> list[str]:
        out: list[str] = []
        caption = tag.find("caption")
        if isinstance(caption, Tag) and caption.find_parent("table") is tag:
            out.extend(self.blocks(caption))
        rows = own_rows(tag)
        cells = [cell for row in rows for cell in row_cells(row)]
        if not cells:
            return out
        is_layout = attr(tag, "role").strip().lower() in ("presentation", "none") or any(
            cell.find("table") is not None for cell in cells
        )
        grid = [] if is_layout else read_grid(rows, self.cell)[0]
        if is_layout or len(grid[0]) == 1:
            # Not a data table: keep the content of each cell, in reading order.
            for cell in cells:
                out.extend(self.blocks(cell))
            return out
        if self.plain:
            out.append("\n".join("\t".join(row).rstrip() for row in grid))
            return out
        lines = [_table_row(grid[0]), _table_row(["---"] * len(grid[0]))]
        lines.extend(_table_row(row) for row in grid[1:])
        out.append("\n".join(lines))
        return out

    def cell(self, tag: Tag) -> str:
        text = self.finish_inline(self.inline_children(tag)).replace("\n", " ")
        return text if self.plain else text.replace("|", "\\|")

    # ------------------------------------------------------------------ inline

    def text(self, value: str) -> str:
        value = _SPACES.sub(" ", value)
        return value if self.plain else _escape(value)

    def finish_inline(self, value: str) -> str:
        """Collapse whitespace in gathered inline content and place line breaks."""
        value = _SPACES.sub(" ", value)
        value = _AROUND_BREAK.sub("\n", value)
        return value.strip()

    def protect_start(self, text: str) -> str:
        """Stop lines that begin like a heading, list or quote from becoming one."""
        return "\n".join(_protect_line(line) for line in text.split("\n"))

    def inline_children(self, tag: Tag) -> str:
        parts: list[str] = []
        for child in tag.children:
            if isinstance(child, NavigableString):
                if not isinstance(child, PreformattedString):
                    parts.append(self.text(str(child)))
            elif isinstance(child, Tag):
                if child.name in SKIP_TAGS:
                    continue
                if child.name in BLOCK_TAGS:
                    # A block inside inline content (a <div> in a heading): flatten it.
                    parts.append(" " + " ".join(self.block(child)) + " ")
                else:
                    parts.append(self.inline(child))
        return "".join(parts)

    def inline(self, tag: Tag) -> str:
        name = tag.name
        if name in SKIP_TAGS:
            return ""
        if name == "br":
            return _LINE_BREAK
        if name == "img":
            return self.image(tag)
        if name in _CODE and not self.plain:
            return self.code(tag)
        inner = self.inline_children(tag)
        if self.plain:
            return inner
        if name in _STRONG:
            return _wrap(inner, "**")
        if name in _EMPHASIS:
            return _wrap(inner, "*")
        if name in _STRIKE:
            return _wrap(inner, "~~")
        if name == "a":
            return self.link(tag, inner)
        return inner

    def link(self, tag: Tag, inner: str) -> str:
        href = attr(tag, "href").strip()
        if not href or href.startswith("#") or href.lower().startswith(("javascript:", "data:")):
            return inner
        label = inner.strip().replace(_LINE_BREAK, " ")
        if not label:
            return ""
        start = len(inner) - len(inner.lstrip())
        end = len(inner.rstrip())
        target = _link_target(absolute(self.base_url, href))
        return f"{inner[:start]}[{label}]({target}){inner[end:]}"

    def image(self, tag: Tag) -> str:
        if self.plain:
            return ""
        source = (attr(tag, "src") or attr(tag, "data-src")).strip()
        if not source or source.lower().startswith("data:"):
            return ""
        alt = collapse(attr(tag, "alt")).replace("[", "(").replace("]", ")")
        return f"![{alt}]({_link_target(absolute(self.base_url, source))})"

    def code(self, tag: Tag) -> str:
        text = _SPACES.sub(" ", tag.get_text()).strip()
        if not text:
            return ""
        longest = max((len(run) for run in _BACKTICKS.findall(text)), default=0)
        fence = "`" * (longest + 1)
        padding = " " if text.startswith("`") or text.endswith("`") else ""
        return f"{fence}{padding}{text}{padding}{fence}"


def _indent(block: str, padding: str) -> str:
    return "\n".join(padding + line if line else "" for line in block.split("\n"))


def _table_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"
