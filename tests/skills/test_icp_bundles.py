import re
from pathlib import Path

import pytest
import yaml

# Conservative emoji ranges: emoji/pictographs block and the
# misc-symbols / dingbats block. Kept narrow to avoid flagging
# ordinary punctuation.
_EMOJI = re.compile(r"[\U0001F000-\U0001FFFF\U00002600-\U000027BF]")

_BUNDLE_PATHS = [
    Path("skills/coding:onboarding/SKILL.md"),
    Path("skills/b2b-ops:onboarding/SKILL.md"),
]


def _frontmatter(path: Path) -> dict:
    text = path.read_text()
    assert text.startswith("---\n")
    fm = text.split("---\n", 2)[1]
    return yaml.safe_load(fm)


def _assert_clean_style(path: Path) -> None:
    text = path.read_text()
    assert "—" not in text, f"em-dash found in {path}"
    assert "–" not in text, f"en-dash found in {path}"
    match = _EMOJI.search(text)
    assert match is None, f"emoji codepoint {match.group()!r} found in {path}"


def test_coding_onboarding_bundle_valid():
    p = Path("skills/coding:onboarding/SKILL.md")
    fm = _frontmatter(p)
    assert fm["name"] == "coding:onboarding"
    assert fm["description"]
    assert len(p.read_text().splitlines()) < 500
    _assert_clean_style(p)


def test_b2b_ops_onboarding_bundle_valid():
    p = Path("skills/b2b-ops:onboarding/SKILL.md")
    fm = _frontmatter(p)
    assert fm["name"] == "b2b-ops:onboarding"
    assert fm["description"]
    assert len(p.read_text().splitlines()) < 500
    _assert_clean_style(p)


@pytest.mark.parametrize("path", _BUNDLE_PATHS, ids=lambda p: p.parent.name)
def test_bundle_has_no_emoji_or_dash(path: Path):
    _assert_clean_style(path)
