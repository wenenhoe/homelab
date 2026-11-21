"""Builds the site: one page for each generated view, a home page and the assets they share."""

from __future__ import annotations

import base64
import hashlib
import html
import posixpath
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from doc_scripts.doc_frontmatter import ROOT, docs_in, read_frontmatter
from doc_scripts.generate_doc_indexes import generated_blocks, intro_path
from doc_scripts.view_model import Block, Groups, Note, Table
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from doc_site.documents import render
from doc_site.markup import BRANCH, REPO_URL, Anchors, Heading, UnsupportedMarkup, blocks, inline, link_resolver, status_key
from doc_site.summary import ROADMAP_COLUMNS, tiles

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


_LINK = r"\[`(?P<name>[^`]+?)(?:\.md)?`\]\((?P<target>[^)\s]+)\)(?: \(unblocks (?P<count>\d+)\))?"
_CHIP = re.compile(_LINK)


def _chips(cell: str, resolve) -> str | None:
    """A roadmap cell, a comma-separated list of project links each with an optional `(unblocks N)`, as one chip for each project. None when
    the cell is anything else, so it is rendered as text and nothing is lost."""
    links = list(_CHIP.finditer(cell))
    if not links or ", ".join(link.group(0) for link in links) != cell:
        return None
    chips = []
    for link in links:
        href = html.escape(resolve(link["target"]), quote=True)
        badge = f'<span class="badge">unblocks {link["count"]}</span>' if link["count"] else ""
        chips.append(f'<a class="chip" href="{href}">{html.escape(link["name"], quote=False)}{badge}</a>')
    return f'<div class="chips">{"".join(chips)}</div>'


def _table(table: Table, resolve, chips: tuple[str, ...] = ()) -> str:
    roles = roles_of(table.headers)
    head = "".join(f"<th>{inline(h, resolve)}</th>" for h in table.headers)
    body = []
    for row in table.rows:
        cells = []
        key = ""
        for header, role, cell in zip(table.headers, roles, row, strict=True):
            text = (_chips(cell, resolve) if header in chips else None) or inline(cell, resolve)
            classes = [role] + (["none"] if cell in NO_VALUE else []) + ([f"col-{re.sub(r'[^a-z]+', '-', header.lower())}"] if header in chips else [])
            if role == "status" and cell not in NO_VALUE:
                key = status_key(text)
                text = f'<span class="pill s-{key}">{text}</span>'
            cells.append(f'<td class="{" ".join(classes)}" data-label="{inline(header, resolve)}">{text}</td>')
        has_eyebrow = any(role == "eyebrow" and cell not in NO_VALUE for role, cell in zip(roles, row, strict=True))
        classes = ([f"s-{key}"] if key else []) + ([] if has_eyebrow else ["ne"])
        body.append(f'<tr class="{" ".join(classes)}">{"".join(cells)}</tr>')
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _block(block: Block, resolve, anchors: Anchors, headings: list[Heading], chips: tuple[str, ...] = ()) -> str:
    if isinstance(block, Note):
        return f'<p class="note">{inline(block.text, resolve)}</p>'
    if isinstance(block, Table):
        return _table(block, resolve, chips)
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


def split_intro(paragraphs: list[str], headings: list[str]) -> tuple[list[str], dict[str, str], list[str]]:
    """An introduction's paragraphs as markdown, sorted for the page: the lede that opens it, the caption of each section, and the rest.

    A paragraph that opens with a section's name in bold (`**Roadmap** has one row...`) is that section's caption, and the page puts it
    under the section's heading, where it explains what is there. The first paragraph that is not a caption is the lede. Every other
    paragraph, such as a definition of a column that several sections share, goes in a legend the reader opens. A section renamed
    without its paragraph does not lose the paragraph: it moves to the legend."""
    captions: dict[str, str] = {}
    rest: list[str] = []
    for paragraph in paragraphs:
        lead = re.match(r"\*\*([^*]+)\*\*", paragraph)
        if lead and lead[1] in headings and lead[1] not in captions:
            captions[lead[1]] = paragraph
        else:
            rest.append(paragraph)
    return rest[:1], captions, rest[1:]


@dataclass(frozen=True)
class Document:
    source: str  # the markdown file, from the repository root
    slug: str  # its directory on the site, `projects/<name>`
    front: dict  # its front matter


def _documents(root: Path) -> list[Document]:
    """The documents with a page of their own. Only the projects so far."""
    return [Document(f"docs/projects/{path.name}", f"projects/{path.stem}", read_frontmatter(path)) for path in docs_in(root / "docs/projects")]


def _page_addresses(targets: dict[str, str], depth: int) -> dict[str, str]:
    """Each page's address from a page `depth` directories under the site's root; `targets` maps a source path to its directory."""
    return {source: f"{'../' * depth}{slug}/" for source, slug in targets.items()}


def _targets(documents: list[Document]) -> dict[str, str]:
    return {view.source: view.slug for view in VIEWS} | {document.source: document.slug for document in documents}


def _facts(document: Document, documents: list[Document], resolve) -> list[dict]:
    """The header of a project page, from its front matter: what a reader looks at before the body."""
    front = document.front
    by_id = {other.front["id"]: other for other in documents}
    waits = [by_id[d["project"]] for d in front.get("depends_on", []) if d["project"] in by_id]
    facts = [{"label": "Status", "html": f'<span class="pill s-{status_key(front["status"])}">{html.escape(front["status"])}</span>'}]
    if front.get("blocked"):
        facts.append({"label": "Blocked", "html": "yes"})
    if front.get("super_project"):
        facts.append({"label": "Part of", "html": f"<code>{html.escape(front['super_project'])}</code>"})
    if front.get("decision"):
        facts.append({"label": "Decision", "html": f"<code>{html.escape(front['decision'])}</code>"})
    if waits:
        links = ", ".join(
            f'<a href="{html.escape(resolve(other.source.removeprefix("docs/projects/")), quote=True)}">{html.escape(Path(other.source).stem)}</a>'
            for other in waits
        )
        facts.append({"label": "Waits on", "html": links})
    return facts


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

    documents = _documents(root)
    targets = _targets(documents)

    def nav(slug: str | None, depth: int) -> list[dict]:
        pages = _page_addresses(targets, depth)
        return [{"href": pages[view.source], "label": view.nav, "current": view.slug == slug} for view in VIEWS]

    for view in VIEWS:
        title, intro = _title_and_intro((root / intro_path(view.source)).read_text(encoding="utf-8"), intro_path(view.source))
        resolve = link_resolver(view.source, _page_addresses(targets, 1), lambda path: (root / path).is_dir())
        anchors = Anchors()
        headings = [Heading(1, anchors.of(title), title)]
        own = [g for g in generated if g.view == view.source]
        lede, captions, legend = split_intro(blocks(intro), [g.heading for g in own])
        sections = []
        counted: dict[str, tuple[str, Block]] = {}
        for item in own:
            anchor = anchors.of(item.heading)
            counted[item.heading] = (anchor, item.block)
            headings.append(Heading(2, anchor, item.heading))
            caption = inline(captions[item.heading], resolve) if item.heading in captions else ""
            sections.append(
                {
                    "id": anchor,
                    "title": item.heading,
                    "caption": caption,
                    "html": _block(item.block, resolve, anchors, headings, ROADMAP_COLUMNS if item.heading == "Roadmap" else ()),
                }
            )
        files[f"{view.slug}/index.html"] = (
            env.get_template("page.html.j2")
            .render(
                title=title,
                title_id=headings[0].id,
                tiles=tiles(view.slug, counted),
                lede=[inline(paragraph, resolve) for paragraph in lede],
                legend=[inline(paragraph, resolve) for paragraph in legend],
                sections=sections,
                headings=headings[1:],
                nav=nav(view.slug, 1),
                base="../",
                home="../",
                sri=sri,
                assets=urls,
                stamp=stamp,
            )
            .encode("utf-8")
        )
    for document in documents:
        resolve = link_resolver(document.source, _page_addresses(targets, 2), lambda path: (root / path).is_dir())
        text = (root / document.source).read_text(encoding="utf-8")
        page = render(text, resolve, document.source)
        files[f"{document.slug}/index.html"] = (
            env.get_template("document.html.j2")
            .render(
                title=page.title,
                title_id=page.title_id,
                summary=document.front.get("summary", ""),
                facts=_facts(document, documents, resolve),
                body=page.html,
                headings=page.headings,
                source_url=f"{REPO_URL}/blob/{BRANCH}/{document.source}",
                nav=nav(None, 2),
                base="../../",
                home="../../",
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
            nav=nav(None, 0),
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
    built = build(root)
    pages = {"": "index.html"} | {path.removesuffix("/index.html"): path for path in built if path.endswith("/index.html")}
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
