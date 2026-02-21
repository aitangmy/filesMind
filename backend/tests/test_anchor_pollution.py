from structure_utils import build_hierarchy_tree


def test_anchor_pollution():
    md = '# Chapter 1 <!-- fm_anchor: {"page_no": 1, "bbox": {"t": 100}, "page_height": 1000} -->\n\nContent here <!-- fm_anchor: {"page_no": 2} -->'
    root = build_hierarchy_tree(md)

    assert len(root.children) == 1
    chapter = root.children[0]

    # 验证提取的 Node 不含污染文本
    assert chapter.topic == "Chapter 1"
    assert "fm_anchor" not in chapter.topic
    assert "fm_anchor" not in chapter.full_content

    # 验证血缘关联属性正确
    assert chapter.pdf_page_no == 1
    assert chapter.pdf_y_ratio == 0.9  # 1.0 - (100/1000)
