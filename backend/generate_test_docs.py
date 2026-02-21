import random
import os


def generate_random_markdown(filename, num_sections=5, max_depth=4, sentences_per_section=3):
    """
    Generates a random Markdown document with nested structure.
    """
    content = []

    # Title
    content.append(f"# Test Document: {filename}")
    content.append("This is a randomly generated test document to verify hierarchy preservation.\n")

    current_depth = 1
    section_counters = [0] * (max_depth + 1)

    words = [
        "Lorem",
        "ipsum",
        "dolor",
        "sit",
        "amet",
        "consectetur",
        "adipiscing",
        "elit",
        "sed",
        "do",
        "eiusmod",
        "tempor",
        "incididunt",
        "ut",
        "labore",
        "et",
        "dolore",
        "magna",
        "aliqua",
        "Hierarchy",
        "Structure",
        "Parsing",
        "Cognitive",
        "Engine",
        "DeepSeek",
        "Analysis",
        "Data",
        "Model",
        "Test",
        "Verification",
    ]

    def get_sentence():
        return " ".join(random.choices(words, k=random.randint(5, 15))) + "."

    for _ in range(num_sections * 3):  # Generate enough content
        # Randomly decide to go deeper, shallower, or stay same
        change = random.choice([-1, 0, 1])

        # Constrain depth
        if current_depth + change < 2:  # Keep at least level 2 (under root)
            current_depth = 2
        elif current_depth + change > max_depth:
            current_depth = max_depth
        else:
            current_depth += change

        # Update counters
        section_counters[current_depth] += 1
        # Reset deeper counters
        for i in range(current_depth + 1, max_depth + 1):
            section_counters[i] = 0

        # Build Header
        header_prefix = "#" * current_depth
        section_title = f"Section {'_'.join(map(str, section_counters[2 : current_depth + 1]))}"
        if current_depth == 1:
            section_title = "Root (Should not happen in body)"  # Guard

        content.append(f"{header_prefix} {section_title}")

        # Add content
        for _ in range(sentences_per_section):
            content.append(get_sentence())

        content.append("")  # Blank line

    # Write to file
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(content))
    print(f"Generated {filename}")


if __name__ == "__main__":
    os.makedirs("test_docs", exist_ok=True)
    generate_random_markdown("test_docs/doc_shallow.md", max_depth=2)
    generate_random_markdown("test_docs/doc_deep.md", max_depth=5)
    generate_random_markdown("test_docs/doc_mixed.md", max_depth=4)
