"""Builds the site: one page for each generated view, a home page and the assets they share."""

from __future__ import annotations

import base64
import hashlib
import posixpath
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from doc_scripts.doc_frontmatter import ROOT
from doc_scripts.generate_doc_indexes import generated_blocks, intro_path
from doc_scripts.view_model import Block, Groups, Note, Table
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from doc_site.markup import REPO_URL, Anchors, UnsupportedMarkup, inline, link_resolver, paragraphs

PACKAGE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class View:
    source: str  # the markdown view, from the repository root
    slug: str  # its directory on the site
    nav: str  # its label in the navigation
    blurb: str  # what the home page says about it


VIEWS = (
    View("docs/project-planning.md", "project-planning", "Planning", "What is planned, building and waiting, and which decisions have no project yet."),
    View("docs/decision-index.md", "decision-index", "Decisions", "Every decision by number and by topic, the open ones and the superseded ones."),
    View(
        "docs/topics/disaster-recovery/coverage.md",
        "dr-coverage",
        "DR coverage",
        "What each app has: where it runs, what is backed up, its record and its recovery tier.",
    ),
)

TITLES = ("Project", "Decision", "Problem", "App", "Exploration")
EYEBROWS = ("ADR", "Revision")
NO_VALUE = ("", "—", "(no initiative)")


def roles_of(headers: tuple[str, ...]) -> list[str]:
    """What each column is for on a card: the identifier and the status pill head it, the first
    name-like column is the title, and everything else is a labelled field."""
    roles: list[str] = []
    titled = False
    for header in headers:
        if header == "Status":
            roles.append("status")
        elif header in EYEBROWS or (header == "Initiative" and "Project" in headers):
            roles.append("eyebrow")
        elif (header in TITLES or header == "Initiative") and not titled:
            roles.append("title")
            titled = True
        else:
            roles.append("field")
    return roles


def status_key(cell: str) -> str:
    """`Accepted (revision 1)` -> `accepted`: the word that picks a pill's colour."""
    first = re.split(r"[ ,(]", re.sub(r"<[^>]+>", "", cell).strip().lower(), maxsplit=1)[0]
    return re.sub(r"[^a-z]", "", first) or "other"


@dataclass(frozen=True)
class Heading:
    level: int
    id: str
    text: str


def _table(table: Table, resolve) -> str:
    roles = roles_of(table.headers)
    head = "".join(f"<th>{inline(h, resolve)}</th>" for h in table.headers)
    body = []
    for row in table.rows:
        cells = []
        key = ""
        for header, role, cell in zip(table.headers, roles, row, strict=True):
            text = inline(cell, resolve)
            classes = [role] + (["none"] if cell in NO_VALUE else [])
            if role == "status" and cell not in NO_VALUE:
                key = status_key(text)
                text = f'<span class="pill s-{key}">{text}</span>'
            cells.append(f'<td class="{" ".join(classes)}" data-label="{inline(header, resolve)}">{text}</td>')
        has_eyebrow = any(role == "eyebrow" and cell not in NO_VALUE for role, cell in zip(roles, row, strict=True))
        classes = ([f"s-{key}"] if key else []) + ([] if has_eyebrow else ["ne"])
        body.append(f'<tr class="{" ".join(classes)}">{"".join(cells)}</tr>')
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _block(block: Block, resolve, anchors: Anchors, headings: list[Heading]) -> str:
    if isinstance(block, Note):
        return f'<p class="note">{inline(block.text, resolve)}</p>'
    if isinstance(block, Table):
        return _table(block, resolve)
    if isinstance(block, Groups):
        parts = []
        for title, table in block.items:
            anchor = anchors.of(title)
            headings.append(Heading(3, anchor, title))
            parts.append(f'<h3 id="{anchor}">{inline(title, resolve)}</h3>{_table(table, resolve)}')
        return "".join(parts)
    raise TypeError(f"unknown block {block!r}")


def _title_and_intro(text: str, view: str) -> tuple[str, str]:
    """The `# Title` line and the prose after it, from the view's introduction file. A `## ` section in that
    file is refused: the page is built from the rows, so a hand-written section would be lost."""
    lines = text.splitlines()
    heading = next((i for i, line in enumerate(lines) if line.startswith("# ")), None)
    if heading is None:
        raise UnsupportedMarkup(f"{view} has no `# ` title")
    if any(line.startswith("## ") for line in lines):
        raise UnsupportedMarkup(f"{view} has a `## ` section; the sections of a view are generated")
    return lines[heading][2:].strip(), "\n".join(lines[heading + 1 :])


def _page_addresses(from_slug: str | None) -> dict[str, str]:
    """Each view's address from the page for `from_slug` (None for the home page)."""
    prefix = "" if from_slug is None else "../"
    return {view.source: f"{prefix}{view.slug}/" for view in VIEWS}


def integrity(data: bytes) -> str:
    """The `integrity` attribute value (Subresource Integrity, sha384) for `data`."""
    return "sha384-" + base64.b64encode(hashlib.sha384(data).digest()).decode("ascii")


@dataclass(frozen=True)
class Stamp:
    """The commit a site is built from, for the footer: a reader compares it with `main` to tell a page the CDN has not refreshed."""

    sha: str  # the full 40-hex commit id
    date: str  # the commit's date, ISO 8601 with an offset

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{40}", self.sha):
            raise ValueError(f"not a full commit id: {self.sha!r}")
        datetime.fromisoformat(self.date)

    @property
    def short(self) -> str:
        return self.sha[:7]

    @property
    def url(self) -> str:
        return f"{REPO_URL}/commit/{self.sha}"

    @property
    def label(self) -> str:
        return datetime.fromisoformat(self.date).astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def fingerprinted(name: str, data: bytes) -> str:
    """`assets/site.css` -> `assets/site.<first ten hex of its sha256>.css`. A page and the file it names change together, so a cache that
    holds the old page never pairs it with the new file, nor the new page with the old file (which, for the stylesheet, its integrity
    attribute would refuse)."""
    stem, dot, extension = name.rpartition(".")
    return f"assets/{stem}.{hashlib.sha256(data).hexdigest()[:10]}{dot}{extension}"


def build(root: Path = ROOT, stamp: Stamp | None = None) -> dict[str, bytes]:
    """Every file of the site, by its path under the site's root. Reads only the tree and the stamp it is given."""
    env = Environment(loader=FileSystemLoader(PACKAGE / "templates"), autoescape=True, undefined=StrictUndefined, keep_trailing_newline=True)
    generated = generated_blocks(root)
    stylesheet = (PACKAGE / "vendor/simple.min.css").read_bytes()
    sri = integrity(stylesheet)
    assets = {
        "simple_css": ("simple.css", stylesheet),
        "site_css": ("site.css", (PACKAGE / "assets/site.css").read_bytes()),
        "site_js": ("site.js", (PACKAGE / "assets/site.js").read_bytes()),
    }
    urls = {key: fingerprinted(name, data) for key, (name, data) in assets.items()}
    files: dict[str, bytes] = {urls[key]: data for key, (_, data) in assets.items()}
    files["assets/simple-licence.txt"] = (PACKAGE / "vendor/simple.LICENSE").read_bytes()

    def nav(slug: str | None) -> list[dict]:
        pages = _page_addresses(slug)
        return [{"href": pages[view.source], "label": view.nav, "current": view.slug == slug} for view in VIEWS]

    for view in VIEWS:
        title, intro = _title_and_intro((root / intro_path(view.source)).read_text(encoding="utf-8"), intro_path(view.source))
        resolve = link_resolver(view.source, _page_addresses(view.slug), lambda path: (root / path).is_dir())
        anchors = Anchors()
        headings = [Heading(1, anchors.of(title), title)]
        sections = []
        for item in (g for g in generated if g.view == view.source):
            anchor = anchors.of(item.heading)
            headings.append(Heading(2, anchor, item.heading))
            sections.append({"id": anchor, "title": item.heading, "html": _block(item.block, resolve, anchors, headings)})
        files[f"{view.slug}/index.html"] = (
            env.get_template("page.html.j2")
            .render(
                title=title,
                title_id=headings[0].id,
                intro=paragraphs(intro, resolve),
                sections=sections,
                headings=headings[1:],
                nav=nav(view.slug),
                base="../",
                home="../",
                sri=sri,
                assets=urls,
                stamp=stamp,
            )
            .encode("utf-8")
        )
    files["index.html"] = (
        env.get_template("home.html.j2")
        .render(
            views=[{"href": f"{view.slug}/", "label": view.nav, "blurb": view.blurb} for view in VIEWS],
            nav=nav(None),
            base="",
            home="",
            sri=sri,
            assets=urls,
            stamp=stamp,
        )
        .encode("utf-8")
    )
    return files


def page_anchors(root: Path = ROOT) -> dict[str, set[str]]:
    """The heading ids of each page, by its slug (`""` for the home page): what a link to the site can name after the `#`."""
    pages = {"": "index.html"} | {view.slug: f"{view.slug}/index.html" for view in VIEWS}
    built = build(root)
    return {slug: set(re.findall(r'<(?:h[1-6]|section)\b[^>]*? id="([^"]+)"', built[path].decode())) for slug, path in pages.items()}


def write(out: Path, root: Path = ROOT, stamp: Stamp | None = None) -> list[str]:
    """Writes the site into `out`, which must be empty or absent. Returns the paths written."""
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty")
    files = build(root, stamp)
    for relative, data in files.items():
        path = out / posixpath.normpath(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return sorted(files)
