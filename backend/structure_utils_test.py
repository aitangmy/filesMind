import os
import sys
import unittest


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import structure_utils as su  # noqa: E402


def _flatten_topics(node):
    topics = []
    for child in node.children:
        topics.append(child.topic)
        topics.extend(_flatten_topics(child))
    return topics


class StructureUtilsTests(unittest.TestCase):
    def test_heading_noise_filter_and_normalization(self):
        self.assertFalse(su.is_valid_heading("A7*"))
        self.assertFalse(su.is_valid_heading("it (InitialNode)"))
        self.assertFalse(su.is_valid_heading("2212"))
        self.assertFalse(
            su.is_valid_heading("的考点，重点，会不会就一个题库里这些老题反复考？显然不会。当然你会说，")
        )
        self.assertTrue(su.is_valid_heading("前言"))
        self.assertEqual(su._normalize_heading_topic("7174811.2. 内存管理"), "11.2. 内存管理")

    def test_build_hierarchy_tree_demotes_ocr_noise_headings(self):
        md = "\n".join(
            [
                "# 系统架构设计师红宝书一本全",
                "## 群",
                "## 前言",
                "## 1. 软件工程概述（重点★★★★★）",
                "## A7*",
                "## it (InitialNode)",
                "## 2212",
                "## 7174811.2. 内存管理",
                "## 的考点，重点，会不会就一个题库里这些老题反复考？显然不会。当然你会说，",
                "## 10. 计算机网络（次重点★★★★☆☆）",
                "### 10.11. 网络工程（次重点★★★☆☆）",
            ]
        )
        tree = su.build_hierarchy_tree(md)
        topics = _flatten_topics(tree)

        self.assertIn("前言", topics)
        self.assertIn("1. 软件工程概述（重点★★★★★）", topics)
        self.assertIn("10. 计算机网络（次重点★★★★☆☆）", topics)
        self.assertIn("11.2. 内存管理", topics)

        self.assertNotIn("群", topics)
        self.assertNotIn("A7*", topics)
        self.assertNotIn("it (InitialNode)", topics)
        self.assertNotIn("2212", topics)

    def test_phase2_noise_filters_watermarks(self):
        self.assertFalse(su.is_valid_heading("CONFIDENTIAL"))
        self.assertFalse(su.is_valid_heading("Draft"))
        self.assertFalse(su.is_valid_heading("内部"))
        self.assertFalse(su.is_valid_heading("机密"))
        self.assertFalse(su.is_valid_heading("仅供参考"))

    def test_phase2_noise_filters_page_numbers(self):
        self.assertFalse(su.is_valid_heading("- 3 -"))
        self.assertFalse(su.is_valid_heading("Page 5"))
        self.assertFalse(su.is_valid_heading("第 3 页"))
        self.assertFalse(su.is_valid_heading("3 / 20"))
        self.assertFalse(su.is_valid_heading("5 of 100"))

    def test_phase2_noise_filters_decorative(self):
        self.assertFalse(su.is_valid_heading("■ ▲ ● ◆"))
        self.assertFalse(su.is_valid_heading("---"))
        self.assertFalse(su.is_valid_heading("==="))
        self.assertFalse(su.is_valid_heading("***"))

    def test_phase2_noise_filters_urls_and_paths(self):
        self.assertFalse(su.is_valid_heading("https://example.com/page"))
        self.assertFalse(su.is_valid_heading("/usr/local/bin/tool"))

    def test_phase2_noise_filters_copyright(self):
        self.assertFalse(su.is_valid_heading("© 2024 Company"))
        self.assertFalse(su.is_valid_heading("Copyright 2024"))
        self.assertFalse(su.is_valid_heading("版权所有"))
        self.assertFalse(su.is_valid_heading("All Rights Reserved"))

    def test_phase2_normal_headings_not_affected(self):
        """Ensure Phase 2 filters don't break valid headings."""
        self.assertTrue(su.is_valid_heading("前言"))
        self.assertTrue(su.is_valid_heading("1. 软件工程概述"))
        self.assertTrue(su.is_valid_heading("内存管理"))
        self.assertTrue(su.is_valid_heading("设计模式"))
        self.assertTrue(su.is_valid_heading("Chapter 3 Results"))

    def test_preprocess_removes_standalone_noise(self):
        md = "\n".join([
            "## 正文标题",
            "一些内容",
            "- 3 -",
            "CONFIDENTIAL",
            "---",
            "更多内容",
            "## 第二章",
        ])
        result = su.preprocess_markdown(md)
        self.assertNotIn("- 3 -", result)
        self.assertNotIn("CONFIDENTIAL", result)
        self.assertIn("正文标题", result)
        self.assertIn("第二章", result)
        self.assertIn("更多内容", result)

    def test_preprocess_removes_repeated_decorative_lines(self):
        md = "\n".join([
            "## 正文标题",
            "内容1",
            "仅供参考",
            "内容2",
            "仅供参考",
            "内容3",
            "仅供参考",
            "## 第二章",
        ])
        result = su.preprocess_markdown(md)
        self.assertNotIn("仅供参考", result)
        self.assertIn("正文标题", result)
        self.assertIn("第二章", result)

    def test_preprocess_removes_table_separator_lines(self):
        md = "\n".join([
            "## 表格章节",
            "| 阶段 | 说明 |",
            "|------|------|",
            "| 需求分析阶段 | 明确目标 |",
            "|------|------|",
            "| 设计阶段 | 模块划分 |",
        ])
        result = su.preprocess_markdown(md)

        self.assertIn("| 阶段 | 说明 |", result)
        self.assertIn("| 需求分析阶段 | 明确目标 |", result)
        self.assertIn("| 设计阶段 | 模块划分 |", result)
        self.assertNotIn("|------|------|", result)

    def test_preprocess_removes_pure_dash_line_in_table_context(self):
        md = "\n".join([
            "## 表格章节",
            "| 字段 | 含义 |",
            "--------",
            "| A | Alpha |",
            "普通文本中的 ---- 不应被误删",
        ])
        result = su.preprocess_markdown(md)

        self.assertIn("| 字段 | 含义 |", result)
        self.assertIn("| A | Alpha |", result)
        self.assertNotIn("\n--------\n", f"\n{result}\n")
        self.assertIn("普通文本中的 ---- 不应被误删", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
