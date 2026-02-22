import os
import sys
import unittest


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fix_md_hierarchy as fmh  # noqa: E402


class StandaloneFixHierarchyTests(unittest.TestCase):
    def test_snap_prefers_shallower_level_when_jitter_is_ambiguous(self):
        level_stack = [(0, 1), (3, 3), (5, 4)]
        snapped = fmh._snap_orig_level_for_stack(4, level_stack, jitter_tolerance=1)
        self.assertEqual(snapped, 3)

    def test_numbering_resolution_prefers_sibling_level_over_parent_level(self):
        history = [
            {"sig": (1,), "level": 2},
            {"sig": (1, 1), "level": 5},
        ]

        level = fmh._resolve_level_by_numbering((1, 3), history, fallback_level=3)
        self.assertEqual(level, 5)

    def test_standalone_fix_repairs_numbered_parent_child_chain(self):
        source = "\n".join(
            [
                "## 1. 概述",
                "## 1.1 背景",
                "## 1.1.1 定义",
            ]
        )

        fixed = fmh.fix_markdown_hierarchy(source).splitlines()
        self.assertEqual(fixed[0], "## 1. 概述")
        self.assertEqual(fixed[1], "### 1.1 背景")
        self.assertEqual(fixed[2], "#### 1.1.1 定义")

    def test_standalone_fix_repairs_numbered_siblings(self):
        source = "\n".join(
            [
                "## 1.1 背景",
                "###### 1.2 发展阶段",
            ]
        )

        fixed = fmh.fix_markdown_hierarchy(source).splitlines()
        self.assertEqual(fixed[0], "### 1.1 背景")
        self.assertEqual(fixed[1], "### 1.2 发展阶段")

    def test_standalone_fix_non_numbered_heading_anti_jump(self):
        source = "\n".join(
            [
                "## 1.1 背景",
                "###### 结论",
            ]
        )

        fixed = fmh.fix_markdown_hierarchy(source).splitlines()
        self.assertEqual(fixed[0], "### 1.1 背景")
        self.assertEqual(fixed[1], "#### 结论")

    def test_standalone_fix_prevents_staircase_on_repeated_noisy_headings(self):
        source = "\n".join(
            [
                "## 1. 核心理论",
                "###### 假标题A",
                "###### 假标题B",
                "###### 假标题C",
            ]
        )

        fixed = fmh.fix_markdown_hierarchy(source).splitlines()
        self.assertEqual(fixed[0], "## 1. 核心理论")
        self.assertEqual(fixed[1], "### 假标题A")
        self.assertEqual(fixed[2], "### 假标题B")
        self.assertEqual(fixed[3], "### 假标题C")

    def test_standalone_fix_handles_ocr_jitter_for_non_numbered_siblings(self):
        source = "\n".join(
            [
                "## 1. 核心理论",
                "#### 假标题A",
                "##### 假标题B",
                "#### 假标题C",
            ]
        )

        fixed = fmh.fix_markdown_hierarchy(source).splitlines()
        self.assertEqual(fixed[0], "## 1. 核心理论")
        self.assertEqual(fixed[1], "### 假标题A")
        self.assertEqual(fixed[2], "### 假标题B")
        self.assertEqual(fixed[3], "### 假标题C")

    def test_standalone_fix_keeps_shallow_context_after_deep_numbered_anchor(self):
        source = "\n".join(
            [
                "## 1. 架构",
                "#### 无编号分组",
                "###### 1.1.1 深层锚点",
                "#### 分组B",
            ]
        )

        fixed = fmh.fix_markdown_hierarchy(source).splitlines()
        self.assertEqual(fixed[0], "## 1. 架构")
        self.assertEqual(fixed[1], "### 无编号分组")
        self.assertEqual(fixed[2], "#### 1.1.1 深层锚点")
        self.assertEqual(fixed[3], "### 分组B")


if __name__ == "__main__":
    unittest.main(verbosity=2)
