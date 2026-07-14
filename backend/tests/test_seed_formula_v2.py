"""
Tests for math2_core_v2 formula card seed data and seed script.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATA_FILE = Path(__file__).resolve().parent.parent / "app" / "data" / "formula_library" / "math2_core_v2_extensions.json"


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def seed_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def all_cards(seed_data):
    cards = []
    for subject in seed_data["subjects"]:
        for chapter in subject["chapters"]:
            for group in chapter["groups"]:
                for card in group["cards"]:
                    cards.append(card)
    return cards


# ── Schema validation ─────────────────────────────────────────────────


class TestJsonSchema:
    """Validate the seed JSON structure."""

    REQUIRED_CARD_FIELDS = [
        "title", "card_type", "source_ref", "summary",
        "formula_blocks", "tags",
    ]

    def test_total_cards(self, all_cards):
        assert len(all_cards) == 22, f"Expected 22 cards, got {len(all_cards)}"

    def test_required_fields(self, all_cards):
        missing = []
        for card in all_cards:
            for field in self.REQUIRED_CARD_FIELDS:
                if field not in card:
                    missing.append(f"{card.get('title', '?')}: missing '{field}'")
        assert not missing, "\n".join(missing)

    def test_valid_card_types(self, all_cards):
        valid = {"pure_formula", "function_graph", "auto"}
        for card in all_cards:
            assert card.get("card_type") in valid, \
                f"Card '{card['title']}': invalid type '{card.get('card_type')}'"

    def test_formula_blocks_nonempty(self, all_cards):
        for card in all_cards:
            blocks = card.get("formula_blocks", [])
            assert len(blocks) >= 1, f"Card '{card['title']}': no formula blocks"
            for bi, block in enumerate(blocks):
                assert "latex" in block, f"Card '{card['title']}' block {bi}: missing latex"

    def test_tags_nonempty(self, all_cards):
        for card in all_cards:
            assert len(card.get("tags", [])) >= 1, f"Card '{card['title']}': no tags"

    def test_tags_valid(self, all_cards):
        valid_tags = {"syllabus_required", "common_inference", "basic",
                      "high_frequency", "error_prone", "must_memorize"}
        for card in all_cards:
            for tag in card.get("tags", []):
                assert tag in valid_tags, f"Card '{card['title']}': invalid tag '{tag}'"

    def test_unique_source_refs(self, all_cards):
        refs = [c.get("source_ref", "") for c in all_cards]
        duplicates = [r for r in refs if refs.count(r) > 1]
        assert not duplicates, f"Duplicate source_ref values: {set(duplicates)}"

    def test_aliases_present(self, all_cards):
        """Each card should have at least one alias."""
        for card in all_cards:
            assert len(card.get("aliases", [])) >= 1, \
                f"Card '{card['title']}': no aliases"

    def test_search_text_present(self, all_cards):
        for card in all_cards:
            assert card.get("search_text", ""), \
                f"Card '{card['title']}': empty search_text"


# ── LaTeX safety ──────────────────────────────────────────────────────


class TestLatexSafety:
    """Ensure LaTeX backslash escaping survived JSON encoding."""

    CONTROL_CHARS = [
        ("\b", "backspace"),
        ("\f", "form feed"),
        ("\n", "newline"),
        ("\r", "carriage return"),
        ("\t", "tab"),
    ]

    # LaTeX commands that must survive JSON round-trip
    EXPECTED_COMMANDS = [
        r"\beta",
        r"\begin",
        r"\text",
        r"\frac",
        r"\int",
        r"\sum",
        r"\sqrt",
        r"\kappa",
        r"\rho",
        r"\alpha",
        r"\Rightarrow",
        r"\quad",
    ]

    def find_strings(self, obj, path=""):
        """Recursively find all string values in a JSON-like structure."""
        strings = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                strings.extend(self.find_strings(v, f"{path}.{k}"))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                strings.extend(self.find_strings(v, f"{path}[{i}]"))
        elif isinstance(obj, str):
            strings.append((path, obj))
        return strings

    def test_no_control_characters(self, seed_data):
        """No decoded formula should contain control characters."""
        corrupted = []
        for path, s in self.find_strings(seed_data):
            for char, name in self.CONTROL_CHARS:
                if char in s:
                    corrupted.append(f"{name} in {path}")
        assert not corrupted, "\n".join(corrupted[:20])

    def test_latex_commands_present(self, seed_data):
        """Formula latex blocks should contain expected LaTeX commands."""
        # Collect all latex blocks
        latex_strings = []
        for subject in seed_data["subjects"]:
            for chapter in subject["chapters"]:
                for group in chapter["groups"]:
                    for card in group["cards"]:
                        for block in card.get("formula_blocks", []):
                            latex_strings.append((card["title"], block.get("latex", "")))

        # Check that at least some strings contain common LaTeX commands
        # (this verifies backslashes survived encoding)
        has_commands = 0
        for title, latex in latex_strings:
            for cmd in self.EXPECTED_COMMANDS:
                if cmd in latex:
                    has_commands += 1
                    break

        # All 22 cards * at least 1 block each should have LaTeX commands
        total_blocks = len(latex_strings)
        assert has_commands >= 22, \
            f"Only {has_commands}/{total_blocks} blocks contain expected LaTeX commands"


# ── Seed script tests ─────────────────────────────────────────────────


class TestSeedProductionGuard:
    """Seed script must refuse production writes."""

    def test_production_refusal(self):
        """Verify the script exits when APP_ENV=production without --allow-production."""
        import subprocess
        env = os.environ.copy()
        env["APP_ENV"] = "production"
        result = subprocess.run(
            [sys.executable, "scripts/seed_formula_library_v2.py", "--apply"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
            env=env,
            timeout=30,
        )
        assert result.returncode != 0, "Script should exit with error in production"
        assert "Refusing to write" in result.stderr or "Refusing to write" in result.stdout, \
            "Should print 'Refusing to write' message"

    def test_production_override(self):
        """Production guard should allow --allow-production flag."""
        import subprocess
        env = os.environ.copy()
        env["APP_ENV"] = "production"
        result = subprocess.run(
            [sys.executable, "scripts/seed_formula_library_v2.py", "--apply",
             "--allow-production"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
            env=env,
            timeout=30,
        )
        # Should be allowed (all cards skipped since already seeded)
        assert result.returncode == 0 or "Warning" in result.stdout, \
            f"Script failed: {result.stderr}"


# ── Alias and search ──────────────────────────────────────────────────


class TestAliasAndSearch:
    """Aliases and search_text should make cards discoverable."""

    def test_chinese_aliases(self, all_cards):
        """Each card should have meaningful Chinese aliases."""
        for card in all_cards:
            aliases = card.get("aliases", [])
            has_chinese = any('一' <= c <= '鿿' for alias in aliases for c in alias)
            assert has_chinese, f"Card '{card['title']}': no Chinese aliases"

    def test_search_text_coverage(self, all_cards):
        """Search text should include both Chinese and English terms."""
        for card in all_cards:
            st = card.get("search_text", "")
            has_chinese = any('一' <= c <= '鿿' for c in st)
            has_ascii = any(c.isascii() and c.isalpha() for c in st)
            assert has_chinese, f"Card '{card['title']}': search_text missing Chinese"
            assert has_ascii, f"Card '{card['title']}': search_text missing English terms"
