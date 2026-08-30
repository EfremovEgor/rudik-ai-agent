"""Разбор HTML: чистка шаблонной обвязки и превращение страницы в читаемый текст."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from selectolax.parser import HTMLParser, Node

# Теги, которые не несут контента вообще.
DROP_TAGS = (
    "script",
    "style",
    "noscript",
    "svg",
    "iframe",
    "form",
    "template",
    "picture",
)

# Шаблонная обвязка сайта: футер, боковое меню, хлебные крошки.
# <header> обрабатывается отдельно: у карточек сотрудников свой .uk-comment-header.
DROP_SELECTORS = (
    "footer",
    "nav",
    "#offcanvas-nav",
    ".uk-offcanvas",
    ".language-switcher",
    ".logos",
    ".footer-wrapper",
    ".breadcrumbs",
    ".uk-breadcrumb",
    ".parallax-container_1",
)

BLOCK_TAGS = {
    "p",
    "div",
    "section",
    "article",
    "li",
    "tr",
    "br",
    "hr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "td",
    "th",
    "blockquote",
    "dd",
    "dt",
}
HEADING_TAGS = {
    "h1": "#",
    "h2": "##",
    "h3": "###",
    "h4": "####",
    "h5": "#####",
    "h6": "######",
}

_WS = re.compile(r"[ \t\r\n\xa0 ​ ]+")
_BLANKS = re.compile(r"\n{3,}")


def parse(html: str) -> HTMLParser:
    return HTMLParser(html)


def clean(tree: HTMLParser, *, drop_chrome: bool = True) -> HTMLParser:
    """Убирает скрипты и (опционально) шапку/футер/меню. Меняет дерево на месте."""
    for tag in DROP_TAGS:
        for node in tree.css(tag):
            node.decompose()
    if drop_chrome:
        for selector in DROP_SELECTORS:
            for node in tree.css(selector):
                node.decompose()
        for node in tree.css("header"):
            classes = node.attributes.get("class") or ""
            # Шапка сайта уходит, шапка карточки сотрудника остаётся.
            if "comment" not in classes and "card" not in classes:
                node.decompose()
    return tree


def norm(text: str | None) -> str:
    if not text:
        return ""
    return _WS.sub(" ", text.replace("\xa0", " ")).strip()


def node_text(node: Node | None) -> str:
    """Плоский текст узла в одну строку."""
    if node is None:
        return ""
    return norm(node.text(separator=" ", strip=True))


def to_markdown(node: Node | None, base_url: str = "") -> str:
    """Грубая, но аккуратная конвертация узла в markdown-подобный текст.

    Заголовки становятся `## ...`, пункты списков — `- ...`, ссылки и почта
    сохраняются в тексте, чтобы модель могла их процитировать.
    """
    if node is None:
        return ""
    chunks: list[str] = []
    _walk(node, chunks, base_url)
    text = "".join(chunks)
    text = "\n".join(norm(line) for line in text.split("\n"))
    return _BLANKS.sub("\n\n", text).strip()


def _walk(node: Node, out: list[str], base_url: str) -> None:
    tag = node.tag

    if tag == "-text":
        out.append(node.text_content or "")
        return
    if tag in DROP_TAGS:
        return

    if tag in HEADING_TAGS:
        out.append("\n\n" + HEADING_TAGS[tag] + " " + node_text(node) + "\n")
        return
    if tag == "li":
        out.append("\n- " + node_text(node))
        return
    if tag == "br":
        out.append("\n")
        return
    if tag == "a":
        label = node_text(node)
        href = node.attributes.get("href") or ""
        if href.startswith("mailto:"):
            address = href[len("mailto:") :]
            out.append(label if address in label else f"{label} ({address})".strip())
        elif href.startswith("tel:"):
            out.append(label or href[len("tel:") :])
        else:
            out.append(label)
        return
    if tag == "img":
        return

    is_block = tag in BLOCK_TAGS
    if is_block:
        out.append("\n")
    for child in node.iter(include_text=True):
        _walk(child, out, base_url)
    if is_block:
        out.append("\n")


def page_title(tree: HTMLParser) -> str:
    """Заголовок страницы: сначала `.page-name`, потом h1, потом <title>."""
    for selector in (".page-name", "h1", ".uk-card-title", "title"):
        node = tree.css_first(selector)
        text = node_text(node)
        if text:
            return re.sub(r"\s*\|\s*(Инженерная академия|РУДН).*$", "", text).strip()
    return ""


def main_content(tree: HTMLParser) -> Node | None:
    """Основной блок страницы после чистки обвязки."""
    for selector in ("main", "#content", ".content", "body"):
        node = tree.css_first(selector)
        if node is not None:
            return node
    return tree.body


def links(tree: HTMLParser, base_url: str) -> list[str]:
    found: list[str] = []
    for node in tree.css("a[href]"):
        href = node.attributes.get("href")
        if href:
            found.append(urljoin(base_url, href))
    return found
