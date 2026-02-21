from anchor_generator import generate_anchor_index
import json


class DummyNode:
    def __init__(self, node_id, pdf_page_no, pdf_y_ratio):
        self.id = node_id
        self.pdf_page_no = pdf_page_no
        self.pdf_y_ratio = pdf_y_ratio
        self.children = []


def test_generate_anchor_index_deterministic(tmp_path):
    root = DummyNode("root", None, None)
    n1 = DummyNode("n1", 1, 0.5)  # normal
    root.children.append(n1)
    n2 = DummyNode("n2", 0, 0.2)  # fallback max(1, 0) -> 1
    root.children.append(n2)

    out_file = tmp_path / "out_anchor.json"
    generate_anchor_index(root, [], "", str(out_file), "docling")

    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert data["has_precise_anchor"] is True
    mappings = data["mappings"]

    assert "n1" in mappings
    assert mappings["n1"]["pdf_page_no"] == 1
    assert mappings["n1"]["pdf_y_ratio"] == 0.5

    assert "n2" in mappings
    assert mappings["n2"]["pdf_page_no"] == 1
    assert mappings["n2"]["pdf_y_ratio"] == 0.2
