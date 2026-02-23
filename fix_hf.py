with open("backend/test_universal_hf.py", "r") as f:
    lines = f.read().splitlines()

# Lines 0..19 are unchanged. Line 20 is "results = []"
top = lines[:20]

# Wrap 20..202 in "def run_tests():"
out_lines = top + ["def run_tests():", "    results = []"]
for line in lines[22:204]:
    if line == "":
        out_lines.append("")
    else:
        out_lines.append("    " + line)

# Lines 204..205 are: print("Results saved...") and sys.exit(...)
# We change them to:
out_lines.append("    return passed == total")
out_lines.append("")
out_lines.append("def test_universal_hf_pytest():")
out_lines.append("    assert run_tests()")
out_lines.append("")
out_lines.append("if __name__ == '__main__':")
out_lines.append("    sys.exit(0 if run_tests() else 1)")

with open("backend/test_universal_hf.py", "w") as f:
    f.write("\n".join(out_lines) + "\n")
