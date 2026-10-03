"""Turn rendered HTML into clean text blocks plus links."""

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

_DROP = ["script", "style", "noscript", "svg", "canvas", "iframe", "form", "nav", "template"]
_BLOCKS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "th", "blockquote", "pre",
    "figcaption", "dt", "dd", "summary", "div", "section", "article", "address",
}  # fmt: skip
_BLOCK_SELECTOR = ",".join(sorted(_BLOCKS))
_HEADINGS = {"h1", "h2", "h3"}
_WS = re.compile(r"\s+")


@dataclass
class Extracted:
    title: str
    blocks: list[tuple[str, bool]] = field(default_factory=list)  # (text, is_heading)
    links: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(t for t, _ in self.blocks)


def _clean(text: str) -> str:
    return _WS.sub(" ", text).strip()


def extract(html: str) -> Extracted:
    soup = BeautifulSoup(html, "lxml")

    links = [str(a["href"]) for a in soup.find_all("a", href=True) if isinstance(a, Tag)]

    title = ""
    if soup.title and soup.title.string:
        title = _clean(soup.title.string)
    if not title:
        og = soup.find("meta", property="og:title")
        if isinstance(og, Tag) and og.get("content"):
            title = _clean(str(og["content"]))
    if not title:
        h1 = soup.find("h1")
        title = _clean(h1.get_text(" ")) if h1 else ""

    blocks: list[tuple[str, bool]] = []

    for meta_name in ("description", "og:description"):
        tag = soup.find("meta", attrs={"name": meta_name}) or soup.find("meta", property=meta_name)
        if isinstance(tag, Tag) and tag.get("content"):
            blocks.append((_clean(str(tag["content"])), False))

    contacts: list[str] = []
    for href in links:
        if href.startswith("tel:"):
            contacts.append(f"Phone: {href[4:].strip()}")
        elif href.startswith("mailto:"):
            contacts.append(f"Email: {href[7:].split('?')[0].strip()}")

    for tag in soup(_DROP):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    if isinstance(root, Tag):
        for el in root.select(_BLOCK_SELECTOR):
            if el.find(_BLOCK_SELECTOR.split(",")):  # only leaf blocks carry text
                continue
            text = _clean(el.get_text(" "))
            if len(text) >= 2:
                blocks.append((text, el.name in _HEADINGS))
    # Footer and header text sit outside <main>; keep it, the site-wide dedupe removes repeats.
    if root is not soup.body and soup.body is not None:
        for part in soup.body.find_all(["header", "footer"]):
            if isinstance(part, Tag) and not root.find(part.name) and part not in root.parents:
                for el in part.select(_BLOCK_SELECTOR):
                    if not el.find(_BLOCK_SELECTOR.split(",")):
                        text = _clean(el.get_text(" "))
                        if len(text) >= 2:
                            blocks.append((text, False))
    for line in dict.fromkeys(contacts):
        blocks.append((line, False))

    seen: set[str] = set()
    unique: list[tuple[str, bool]] = []
    for text, heading in blocks:
        if text not in seen:
            seen.add(text)
            unique.append((text, heading))
    return Extracted(title=title, blocks=unique, links=links)
