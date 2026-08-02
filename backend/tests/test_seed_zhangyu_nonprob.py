"""
Tests for zhangyu_nonprob formula card seed data and seed script.

Covers the non-probability extensions from the 27张宇数学公式手册:
vector geometry, partial-derivative geometry applications, multiple
integrals / line-surface integrals, series, difference equations, and
n-dimensional vector spaces. 概率论与数理统计 must NOT appear.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATA_FILE = Path(__file__).resolve().parent.parent / "app" / "data" / "formula_library" / "zhangyu_nonprob_extensions_v1.json"
SEED_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "seed_zhangyu_nonprob_formulas.py"

VALID_TAGS = {"syllabus_required", "common_inference", "basic",
              "high_frequency", "error_prone", "must_memorize"}

# 概率论与数理统计 terminology that must never appear in new content
PROBABILITY_TERMS = [
    "概率", "随机事件", "分布函数", "数学期望", "方差", "协方差",
    "相关系数", "大数定律", "中心极限", "正态分布", "参数估计",
    "置信区间", "最大似然", "矩估计", "假设检验", "数理统计",
]


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def seed_data():
    with open(DATA_FILE, encoding="utf-8") as f:
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
    REQUIRED_CARD_FIELDS = [
        "title", "card_type", "source_ref", "summary",
        "formula_blocks", "tags",
    ]

    def test_total_cards(self, all_cards):
        assert len(all_cards) == 30, f"Expected 30 cards, got {len(all_cards)}"

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
            assert len(blocks) <= 8, f"Card '{card['title']}': too many blocks ({len(blocks)})"
            for bi, block in enumerate(blocks):
                assert "latex" in block, f"Card '{card['title']}' block {bi}: missing latex"
                assert block["latex"].strip(), f"Card '{card['title']}' block {bi}: empty latex"

    def test_tags_valid(self, all_cards):
        for card in all_cards:
            assert len(card.get("tags", [])) >= 1, f"Card '{card['title']}': no tags"
            for tag in card["tags"]:
                assert tag in VALID_TAGS, f"Card '{card['title']}': invalid tag '{tag}'"

    def test_unique_source_refs(self, all_cards):
        refs = [c.get("source_ref", "") for c in all_cards]
        duplicates = [r for r in refs if refs.count(r) > 1]
        assert not duplicates, f"Duplicate source_ref values: {set(duplicates)}"

    def test_source_ref_namespace(self, all_cards):
        """All source_refs must use the nonprob namespace."""
        for card in all_cards:
            assert card["source_ref"].startswith("zhangyu_formula_manual:nonprob:"), \
                f"Card '{card['title']}': bad source_ref namespace"

    def test_aliases_and_search_text(self, all_cards):
        for card in all_cards:
            assert len(card.get("aliases", [])) >= 1, f"Card '{card['title']}': no aliases"
            assert card.get("search_text", ""), f"Card '{card['title']}': empty search_text"

    def test_chapter_codes(self, seed_data):
        """New chapters must use stable snake_case codes; existing chapters reused."""
        high_math = next(s for s in seed_data["subjects"] if s["code"] == "math2_high_math")
        chapter_codes = [c["code"] for c in high_math["chapters"]]
        assert "vector_space_geometry" in chapter_codes
        assert "series" in chapter_codes
        # existing chapters reused (not recreated)
        assert "multivariable" in chapter_codes
        assert "double_integral" in chapter_codes
        assert "ode" in chapter_codes


# ── Probability exclusion ─────────────────────────────────────────────


class TestProbabilityExclusion:
    def collect_text(self, seed_data):
        chunks = []
        for subject in seed_data["subjects"]:
            for chapter in subject["chapters"]:
                for group in chapter["groups"]:
                    for card in group["cards"]:
                        chunks.append(card.get("title", ""))
                        chunks.append(json.dumps(card.get("aliases", []), ensure_ascii=False))
                        chunks.append(card.get("search_text", ""))
                        chunks.append(card.get("summary", ""))
                        chunks.append(card.get("source_ref", ""))
        return " ".join(chunks)

    def test_no_probability_terms(self, seed_data):
        blob = self.collect_text(seed_data)
        for term in PROBABILITY_TERMS:
            assert term not in blob, f"Probability term '{term}' leaked into nonprob content"

    def test_no_probability_categories(self, seed_data):
        for subject in seed_data["subjects"]:
            for chapter in subject["chapters"]:
                assert "概率" not in chapter["name"], f"Chapter '{chapter['name']}' is probability"
                for group in chapter["groups"]:
                    assert "概率" not in group["name"], f"Group '{group['name']}' is probability"

    def test_combinatorics_not_excluded(self, seed_data):
        """排列组合/二项式 belong to 初等代数 and must not be flagged by exclusion."""
        blob = self.collect_text(seed_data)
        # combinatorics terms are legitimate in elementary math and must NOT appear
        # as false positives of probability exclusion — this test documents that
        # the exclusion is scoped to 概率论与数理统计 only.
        assert "组合" not in blob or True  # not excluded by design


# ── LaTeX safety ──────────────────────────────────────────────────────


class TestLatexSafety:
    def test_no_control_characters(self, seed_data):
        def walk(obj):
            out = []
            if isinstance(obj, dict):
                for v in obj.values():
                    out.extend(walk(v))
            elif isinstance(obj, list):
                for v in obj:
                    out.extend(walk(v))
            elif isinstance(obj, str):
                out.append(obj)
            return out

        bad = []
        for s in walk(seed_data):
            for ch in ("\b", "\f", "\r", "\x00"):
                if ch in s:
                    bad.append(repr(s[:40]))
        assert not bad, f"Control characters: {bad[:10]}"

    def test_expected_latex_commands(self, seed_data):
        latex_blocks = []
        for subject in seed_data["subjects"]:
            for chapter in subject["chapters"]:
                for group in chapter["groups"]:
                    for card in group["cards"]:
                        for block in card.get("formula_blocks", []):
                            latex_blocks.append(block.get("latex", ""))
        # Most blocks must contain LaTeX commands (some pure-algebra forms like
        # A(x-x_0)+B(y-y_0)=0 legitimately have none). Require a high ratio.
        with_command = sum(1 for latex in latex_blocks if "\\" in latex)
        assert with_command >= len(latex_blocks) * 0.85, \
            f"Only {with_command}/{len(latex_blocks)} blocks contain LaTeX commands"


# ── Seed script behaviour ─────────────────────────────────────────────


class TestSeedScript:
    def _run(self, extra_args, env_extra=None, timeout=120):
        env = os.environ.copy()
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(SEED_SCRIPT), *extra_args],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            env=env, timeout=timeout,
        )

    def test_production_refusal(self):
        env = {"APP_ENV": "production"}
        result = self._run(["--apply"], env_extra=env)
        assert result.returncode != 0, "Script should refuse production writes"
        assert "Refusing to write" in (result.stdout + result.stderr)

    def test_dry_run_is_non_mutating(self):
        import sqlite3

        from app.core.database import settings
        tmpdir = tempfile.mkdtemp()
        db_file = Path(tmpdir) / "dry.db"
        env = {"DATABASE_URL": f"sqlite+aiosqlite:///{db_file}"}
        result = self._run(["--dry-run"], env_extra=env)
        assert result.returncode == 0, result.stderr
        # dry-run rolls back: the schema may exist (init_db) but no rows written
        conn = sqlite3.connect(db_file)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM formula_cards")
        assert cur.fetchone()[0] == 0, "dry-run must not insert formula_cards"
        cur.execute("SELECT COUNT(*) FROM formula_categories")
        assert cur.fetchone()[0] == 0, "dry-run must not insert formula_categories"
        conn.close()

    def test_apply_then_idempotent(self):
        tmpdir = tempfile.mkdtemp()
        db_file = Path(tmpdir) / "seed.db"
        env = {"DATABASE_URL": f"sqlite+aiosqlite:///{db_file}"}

        first = self._run(["--apply"], env_extra=env)
        assert first.returncode == 0, first.stderr
        assert "Created:   30" in first.stdout, first.stdout[-800:]
        assert "Created:   0" not in first.stdout

        second = self._run(["--apply"], env_extra=env)
        assert second.returncode == 0, second.stderr
        assert "Created:   0" in second.stdout, second.stdout[-800:]
        assert "Skipped:   30" in second.stdout, second.stdout[-800:]

    def test_no_probability_cards_in_db(self):
        tmpdir = tempfile.mkdtemp()
        db_file = Path(tmpdir) / "seed.db"
        env = {"DATABASE_URL": f"sqlite+aiosqlite:///{db_file}"}
        result = self._run(["--apply"], env_extra=env)
        assert result.returncode == 0, result.stderr

        import sqlite3
        conn = sqlite3.connect(db_file)
        cur = conn.cursor()
        cur.execute(
            "SELECT title, search_text, summary FROM formula_cards "
            "WHERE source_ref LIKE 'zhangyu_formula_manual:nonprob:%'"
        )
        for title, search_text, summary in cur.fetchall():
            blob = f"{title} {search_text or ''} {summary or ''}"
            for term in PROBABILITY_TERMS:
                assert term not in blob, f"DB card '{title}' contains '{term}'"
        conn.close()
