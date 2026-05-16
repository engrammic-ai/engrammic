from pathlib import Path

import yaml


def _frontmatter(path: Path) -> dict:
    text = path.read_text()
    assert text.startswith("---\n")
    fm = text.split("---\n", 2)[1]
    return yaml.safe_load(fm)


def test_coding_onboarding_bundle_valid():
    p = Path("skills/coding:onboarding/SKILL.md")
    fm = _frontmatter(p)
    assert fm["name"] == "coding:onboarding"
    assert fm["description"]
    assert len(p.read_text().splitlines()) < 500


def test_b2b_ops_onboarding_bundle_valid():
    p = Path("skills/b2b-ops:onboarding/SKILL.md")
    fm = _frontmatter(p)
    assert fm["name"] == "b2b-ops:onboarding"
    assert fm["description"]
    assert len(p.read_text().splitlines()) < 500
