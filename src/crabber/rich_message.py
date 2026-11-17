"""A small, protocol-neutral rich message.

Components describe *what* to send (headings, paragraphs, images, quotes and link buttons),
each QQ backend renders it into its own format:

- napcat: OneBot message segments, see `to_onebot()`; buttons become "label：url" lines
- qqbot: markdown (see `to_markdown()`) plus a keyboard built by `QQBotService`
"""

import re

from dataclasses import dataclass, field


@dataclass(slots=True)
class Text:
    text: str
    bold: bool = False


@dataclass(slots=True)
class Image:
    url: str
    # display size in px for markdown, 0 if unknown
    width: int = 0
    height: int = 0
    alt: str = ""
    # inline emoji: an image for napcat, its `alt` text for markdown
    emoji: bool = False


type Inline = Text | Image


@dataclass(slots=True)
class Heading:
    text: str
    level: int = 3


@dataclass(slots=True)
class Paragraph:
    # "\n" inside Text is a line break, non-emoji images take a line of their own in markdown
    inlines: list[Inline] = field(default_factory=list)


@dataclass(slots=True)
class Quote:
    blocks: list[Block] = field(default_factory=list)


type Block = Heading | Paragraph | Quote


@dataclass(slots=True)
class LinkButton:
    # e.g. "打开直播间"; QQ limits button text to 10 chars
    label: str
    # must be https: QQ rejects the whole message (40034028) if a button links to an app scheme
    url: str


@dataclass(slots=True)
class RichMessage:
    blocks: list[Block] = field(default_factory=list)
    buttons: list[LinkButton] = field(default_factory=list)


# ---- napcat (OneBot segments) ----


def to_onebot(message: RichMessage) -> list[dict]:

    segments: list[dict] = []

    _onebot_blocks(message.blocks, segments)

    for button in message.buttons:
        _onebot_break_line(segments)
        _onebot_text(segments, f"{button.label}：{button.url}")

    if segments and segments[-1]["type"] == "text":
        segments[-1]["data"]["text"] = segments[-1]["data"]["text"].rstrip("\n")
        if not segments[-1]["data"]["text"]:
            segments.pop()

    return segments


def _onebot_blocks(blocks: list[Block], segments: list[dict]) -> None:
    for block in blocks:
        _onebot_break_line(segments)
        match block:
            case Heading(text=text):
                _onebot_text(segments, text)
            case Paragraph(inlines=inlines):
                for inline in inlines:
                    match inline:
                        case Text(text=text):
                            _onebot_text(segments, text)
                        case Image(url=url):
                            segments.append({"type": "image", "data": {"file": url}})
            case Quote(blocks=inner):
                _onebot_blocks(inner, segments)


def _onebot_text(segments: list[dict], text: str) -> None:
    if not text: return
    if segments and segments[-1]["type"] == "text":
        segments[-1]["data"]["text"] += text
    else:
        segments.append({"type": "text", "data": {"text": text}})


def _onebot_break_line(segments: list[dict]) -> None:
    # no newline needed after an image, QQ already starts a new line
    if segments and segments[-1]["type"] == "text" and not segments[-1]["data"]["text"].endswith("\n"):
        _onebot_text(segments, "\n")


# ---- markdown (QQ official bot) ----


# `$` because QQ renders LaTeX, `~` because a single tilde may strike through,
# `(` `)` because QQ rejects `[text](not a url)` (40034006) even with the brackets escaped
_MD_INLINE_SPECIALS = re.compile(r"([\\`*_~\[\]()<|$])")
_MD_LINE_START_MARK = re.compile(r"^(\s*)([#>+\-=])")
_MD_LINE_START_ORDERED = re.compile(r"^(\s*)(\d+)\.")


def escape_markdown(text: str) -> str:
    """Escape user text so that it shows up literally in markdown, line breaks are kept as is."""
    return _MD_INLINE_SPECIALS.sub(r"\\\1", text)


def to_markdown(message: RichMessage) -> str:
    return "\n\n".join(md for block in message.blocks if (md := _md_block(block)))


def _md_block(block: Block) -> str:
    match block:
        case Heading(text=text, level=level):
            text = " ".join(text.split())
            return f"{'#' * min(max(level, 1), 6)} {escape_markdown(text)}" if text else ""
        case Paragraph(inlines=inlines):
            return _md_paragraph(inlines)
        case Quote(blocks=inner):
            md = "\n\n".join(m for b in inner if (m := _md_block(b)))
            return "\n".join(f"> {line}" if line else ">" for line in md.split("\n"))


def _md_paragraph(inlines: list[Inline]) -> str:

    buffer = ""

    for inline in inlines:
        match inline:
            case Text(text=text, bold=bold):
                buffer += _md_bold(text) if bold else escape_markdown(text)
            case Image(emoji=True, alt=alt):
                buffer += escape_markdown(alt)
            case Image():
                if buffer and not buffer.endswith("\n"): buffer += "\n"
                buffer += _md_image(inline) + "\n"

    lines = []
    for line in buffer.strip("\n").split("\n"):
        line = _MD_LINE_START_MARK.sub(r"\1\\\2", line)
        line = _MD_LINE_START_ORDERED.sub(r"\1\2\\.", line)
        # QQ collapses empty lines, a zero-width space keeps them
        lines.append(line if line.strip() else "​")

    # two trailing spaces make a hard line break
    return "  \n".join(lines) if buffer.strip() else ""


def _md_bold(text: str) -> str:
    # bold can neither span lines nor start / end with spaces
    lines = []
    for line in text.split("\n"):
        if (core := line.strip()):
            lead = line[:len(line) - len(line.lstrip())]
            tail = line[len(line.rstrip()):]
            line = f"{lead}**{escape_markdown(core)}**{tail}"
        lines.append(line)
    return "\n".join(lines)


def _md_image(image: Image) -> str:
    alt = " ".join(image.alt.replace("[", "").replace("]", "").split()) or "图片"
    if image.width > 0 and image.height > 0:
        alt += f" #{image.width}px #{image.height}px"
    url = image.url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")
    return f"![{alt}]({url})"
