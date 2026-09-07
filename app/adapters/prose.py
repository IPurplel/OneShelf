"""Turning a reader's DOM into ordered prose blocks.

Shared by every text source, because the ways prose extraction goes wrong are
the same everywhere and all of them are silent:

* **A container that parses but is not the chapter.** Novel readers wrap the
  text in a shell that also holds comments, an author's note, a "next chapter"
  strip and a recommendation carousel. Each of those is made of paragraphs, so
  a naive ``container.css("p")`` produces a chapter that reads correctly for a
  while and then turns into somebody else's comment thread.
* **Order taken from the selector rather than from the document.** Collecting
  headings and paragraphs with two queries and concatenating them moves every
  heading to the top. Blocks have to be read in document order, once.
* **Line breaks silently deleted.** These sites write verse, scene breaks and
  system messages as ``<br>`` inside one ``<p>``. Dropping the break glues two
  lines into a sentence that was never written.
* **Whitespace collapsed too eagerly.** ``&nbsp;`` and the zero-width joiners
  that Arabic text carries are not padding; normalising them away changes the
  text. Only ordinary runs of space are collapsed here.

Nothing in this module knows about any particular site. The adapter picks the
container; this decides what, inside it, is the chapter.
"""

from __future__ import annotations

import re

from ..models import TextBlock

#: Elements that are never part of the prose, whatever they contain. Removed
#: before reading, so their paragraphs cannot be mistaken for the chapter's.
NOISE_TAGS = ("script", "style", "noscript", "svg", "iframe", "form", "button")

#: Class/id fragments that mark a block as furniture rather than chapter text.
#: Matched case-insensitively against the node's own ``class`` and ``id``.
#: Deliberately narrow: over-matching deletes a chapter, and the failure looks
#: exactly like a site that changed its markup.
NOISE_MARKERS = (
    "comment",
    "advert",
    "adsbygoogle",
    "share",
    "social",
    "navigation",
    "nav-buttons",
    "breadcrumb",
    "pagination",
    "recommend",
    "related",
    "subscribe",
    "donate",
    "support-",
    "cookie",
    "footer",
    "sidebar",
)

_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_BLOCKS = _HEADINGS + ("p", "blockquote", "li", "pre")

#: Runs of ordinary spaces and newlines collapse; every other kind of space is
#: left alone. ``\s`` would eat U+200C/U+200D, which Arabic and Persian text use
#: to shape words, and U+00A0, which sites use to hold an intentional gap open.
_SPACE_RUN = re.compile(r"[ \t\r\n\f\v]+")

#: A block of nothing but punctuation or ornament — a scene divider. Kept
#: (it is authorial) but never treated as a heading.
_ORNAMENT = re.compile(r"^[\W_]{1,12}$")


def _is_noise(node) -> bool:
    attrs = node.attributes
    haystack = f"{attrs.get('class') or ''} {attrs.get('id') or ''}".lower()
    return any(marker in haystack for marker in NOISE_MARKERS)


def strip_noise(container) -> None:
    """Remove scripts and furniture from ``container``, in place.

    Called before reading so that a comment thread inside the reader cannot
    contribute paragraphs to the chapter.
    """
    for tag in NOISE_TAGS:
        for node in container.css(tag):
            node.decompose()
    for node in container.css("[class],[id]"):
        if _is_noise(node):
            node.decompose()


def normalise(text: str) -> str:
    """Collapse ordinary whitespace runs; leave every other space character."""
    return _SPACE_RUN.sub(" ", text).strip()


def _lines(node) -> list[str]:
    """The node's text, split where the markup put a line break.

    ``<br>`` is the only way these readers express a line break inside a
    paragraph, and it carries verse, scene breaks and stat blocks. Reading
    ``node.text()`` alone concatenates those lines into one run-on sentence.
    """
    html = node.html or ""
    parts = re.split(r"(?i)<br\s*/?>", html)
    if len(parts) == 1:
        text = normalise(node.text())
        return [text] if text else []

    from selectolax.parser import HTMLParser

    out: list[str] = []
    for part in parts:
        text = normalise(HTMLParser(part).text())
        if text:
            out.append(text)
    return out


def blocks_from(container, *, max_blocks: int = 20_000) -> list[TextBlock]:
    """Read ``container`` into ordered blocks.

    Traversal is ``Node.traverse()``, and that choice is load-bearing.
    selectolax's ``css("h2, p")`` returns matches **grouped by selector**, not
    in document order — measured: a container holding ``p, h2, p`` comes back
    as ``h2, p, p``. Building a chapter from that moves every heading to the
    top and leaves the prose in one undifferentiated run, which is both wrong
    and entirely plausible-looking in the finished book. ``traverse()`` walks
    the tree depth-first, which *is* reading order.

    A block nested inside another block (a ``<p>`` inside a ``<blockquote>``)
    is read once, at the outer one, rather than twice.

    ``li`` becomes a paragraph rather than a list item: these readers use lists
    for stat blocks and system messages, and an EPUB reader renders either one
    acceptably, while inventing list nesting from a flat traversal does not.
    """
    blocks: list[TextBlock] = []

    for node in container.traverse(include_text=False):
        if node is container or node.tag not in _BLOCKS:
            continue
        if _inside_a_block(node, container):
            # A <p> within a <blockquote> is read at the blockquote, once.
            continue

        kind = node.tag if node.tag in _HEADINGS else "p"
        for line in _lines(node):
            line_kind = "p" if (kind in _HEADINGS and _ORNAMENT.match(line)) else kind
            blocks.append(TextBlock(line_kind, line))
            if len(blocks) >= max_blocks:
                return blocks

    if not blocks:
        # A reader that puts the chapter in bare text nodes with <br> between
        # them, rather than in paragraphs. Rare, but it exists, and returning
        # nothing here would be reported as an unavailable chapter.
        blocks = [TextBlock("p", line) for line in _lines(container)]

    return blocks


def _inside_a_block(node, container) -> bool:
    """Whether ``node`` already sits inside a block that will be read.

    Asked by walking ancestors and looking at their *tags*, never by tracking
    which node objects were emitted. selectolax hands out a fresh wrapper per
    traversal step and CPython reuses the ``id()`` of one that has been
    collected, so an identity set silently reports unrelated nodes as already
    seen — measured: it dropped every block after the first.
    """
    parent = node.parent
    while parent is not None and parent is not container:
        if parent.tag in _BLOCKS:
            return True
        parent = parent.parent
    return False
