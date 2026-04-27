"""Guard: no Cypher CREATE/MERGE writes using the deprecated BELONGS_TO edge label."""

from __future__ import annotations

import re
from pathlib import Path

_PATTERN = re.compile(r"(?i)(MERGE|CREATE)[^\n]*?:\s*BELONGS_TO")
_SRC_ROOT = Path(__file__).parent.parent / "src" / "context_service"


def test_no_belongs_to_writes() -> None:
    offenders: list[str] = []
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _PATTERN.search(line):
                offenders.append(f"{path}:{lineno}: {line.strip()}")

    assert not offenders, (
        "Found BELONGS_TO in Cypher CREATE/MERGE — use MEMBER_OF instead:\n" + "\n".join(offenders)
    )
