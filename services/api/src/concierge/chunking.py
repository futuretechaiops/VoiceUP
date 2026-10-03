"""Split a page's blocks into retrievable chunks, each carrying its page title and section."""

import hashlib

TARGET = 900
MIN_CHARS = 60


def checksum(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def chunk_blocks(title: str, blocks: list[tuple[str, bool]]) -> list[str]:
    chunks: list[str] = []
    section = ""
    buf: list[str] = []
    size = 0

    def flush() -> None:
        nonlocal buf, size
        body = " ".join(buf).strip()
        if len(body) >= MIN_CHARS:
            prefix = f"{title}" + (f" > {section}" if section and section != title else "")
            chunks.append(f"{prefix}\n{body}" if prefix else body)
        buf, size = [], 0

    for text, is_heading in blocks:
        if is_heading:
            flush()
            section = text[:120]
            buf.append(text)
            size = len(text)
            continue
        pieces = [text]
        if len(text) > TARGET:  # split very long blocks on sentence ends
            pieces, cur = [], ""
            for sentence in (
                text.replace("? ", "?|").replace(". ", ".|").replace("! ", "!|").split("|")
            ):
                if len(cur) + len(sentence) > TARGET and cur:
                    pieces.append(cur.strip())
                    cur = ""
                cur += sentence + " "
            if cur.strip():
                pieces.append(cur.strip())
        for piece in pieces:
            if size + len(piece) > TARGET and buf:
                flush()
            buf.append(piece)
            size += len(piece) + 1
    flush()
    return chunks
