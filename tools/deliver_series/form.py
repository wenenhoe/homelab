"""The form of a commit, as `docs/topics/engineering/conventions.md` states it."""

from __future__ import annotations

import re
from dataclasses import dataclass

from land_series.manifest import TITLE_FORM, TITLE_MAX

from deliver_series.repository import HOMELAB, Identity

MODEL_TRAILER = re.compile(rf"Co-Authored-By: \S.* <{re.escape(HOMELAB.trailer_email)}>")
TRAILER = re.compile(r"([A-Za-z][A-Za-z-]*): \S.*")
# A bare layer id, a pull request number, or a session link: none of them belongs in a message.
ID_IN_TEXT = re.compile(r"(?<![\w-])\d{4}[a-z](?![\w-])|(?<!\w)#\d+")
SESSION_LINK = re.compile(r"https?://\S*claude\.ai\S*|\bsession_[A-Za-z0-9]+", re.IGNORECASE)


@dataclass(frozen=True)
class Commit:
    sha: str
    author: Identity
    committer: Identity
    author_date: str
    committer_date: str
    message: str

    @property
    def subject(self) -> str:
        return self.message.split("\n", 1)[0]


def _trailers(message: str) -> list[str]:
    """The lines of the message's last paragraph, which is a trailer block only when the message has a paragraph besides the subject."""
    paragraphs = message.strip().split("\n\n")
    return paragraphs[-1].splitlines() if len(paragraphs) > 1 else []


def problems(commit: Commit, maintainer: Identity, slug: str) -> list[str]:
    """What is wrong with the commit's form; empty when it has the form."""
    found: list[str] = []
    if commit.author != maintainer:
        found.append(f"the author is {commit.author}, not the maintainer {maintainer}")
    if commit.committer != HOMELAB.committer:
        found.append(f"the committer is {commit.committer}, not the session's {HOMELAB.committer}")
    for role, date in (("author", commit.author_date), ("committer", commit.committer_date)):
        if not date.endswith(HOMELAB.date_offset):
            found.append(f"the {role} date {date!r} is not at +0800 (use `TZ=Etc/GMT-8 date +%Y-%m-%dT%H:%M:%S+0800`)")
    subject = commit.subject
    if len(subject) > TITLE_MAX:
        found.append(f"the subject is {len(subject)} characters; at most {TITLE_MAX}")
    if not TITLE_FORM.fullmatch(subject):
        found.append("the subject is not Conventional Commits with lowercase text after the colon")
    if ID_IN_TEXT.search(subject) or re.search(rf"(?<![\w-]){re.escape(slug)}(?![\w-])", subject):
        found.append(f"the subject holds an id, a number or the slug {slug!r}")
    if SESSION_LINK.search(commit.message):
        found.append("the message holds a session link")
    found.extend(_trailer_problems(commit.message))
    return found


def _trailer_problems(message: str) -> list[str]:
    block = _trailers(message)
    kept = [line for line in block if TRAILER.fullmatch(line)]
    found = []
    models = [line for line in kept if line.lower().startswith("co-authored-by:")]
    if len(models) != 1 or not MODEL_TRAILER.fullmatch(models[0]):
        found.append("the message needs exactly one trailer `Co-Authored-By: <model name> <noreply@anthropic.com>`")
    elsewhere = sum(line.lower().startswith("co-authored-by:") for line in message.splitlines()) - len(models)
    if elsewhere:
        found.append("a `Co-Authored-By` line is outside the trailer block, the last paragraph")
    for line in kept:
        key = line.split(":", 1)[0]
        if not line.lower().startswith("co-authored-by:") and key not in HOMELAB.other_trailers:
            found.append(f"the trailer {key!r} is not allowed; only {' and '.join(HOMELAB.other_trailers)} go beside Co-Authored-By")
    return found
