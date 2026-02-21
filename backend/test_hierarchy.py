"""Hierarchy regression tests for markdown -> tree parsing."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import structure_utils as su  # noqa: E402

DATA_MDS_DIR = HERE / "data" / "mds"


def _walk(node, depth: int = 0, rows: list[tuple[int, str, int]] | None = None):
    if rows is None:
        rows = []
    rows.append((depth, node.topic, len(node.children)))
    for child in node.children:
        _walk(child, depth + 1, rows)
    return rows


def _pick_sample_markdown():
    if not DATA_MDS_DIR.exists():
        return None, None, None

    # Prefer smaller files first, but only keep samples that actually build a deep tree.
    for path in sorted(DATA_MDS_DIR.glob("*.md"), key=lambda p: p.stat().st_size):
        text = path.read_text(encoding="utf-8", errors="ignore")
        tree = su.build_hierarchy_tree(text)
        rows = _walk(tree)
        depths = [depth for depth, _, _ in rows]
        if max(depths) >= 2 and len(rows) >= 5:
            return path, tree, rows
    return None, None, None


def test_simple_hierarchy_preserves_heading_relationships():
    markdown = """# 1. Root Title
## 1.1 Chapter 1
### 1.1.1 Section 1.1
- Point A
  - Detail A1
    - Sub-detail A1a
- Point B
### 1.1.2 Section 1.2
- Point C
## 1.2 Chapter 2
### 1.2.1 Section 2.1
- Point D
  - Detail D1
"""
    tree = su.build_hierarchy_tree(markdown)

    assert len(tree.children) == 1
    doc = tree.children[0]
    assert doc.topic == "1. Root Title"

    assert [c.topic for c in doc.children] == ["1.1 Chapter 1", "1.2 Chapter 2"]
    chapter_1 = doc.children[0]
    assert [c.topic for c in chapter_1.children] == ["1.1.1 Section 1.1", "1.1.2 Section 1.2"]

    section_11 = chapter_1.children[0]
    joined_content = "\n".join(section_11.content_lines)
    assert "Point A" in joined_content
    assert "Point B" in joined_content


def test_real_markdown_sample_builds_non_shallow_tree():
    sample_path, tree, rows = _pick_sample_markdown()
    if not sample_path:
        pytest.skip("No suitable markdown sample found under backend/data/mds")

    depths = [depth for depth, _, _ in rows]

    assert len(tree.children) >= 1
    assert max(depths) >= 2
    assert len(rows) >= 5
    assert all(topic.strip() for _, topic, _ in rows if topic is not None)
