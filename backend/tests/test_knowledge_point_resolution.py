from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.services.knowledge_point_resolution import (
    KnowledgePointResolutionError,
    build_resolution_indexes,
    normalize_knowledge_name,
    resolve_from_indexes,
)


def kp(point_id: int, name: str, aliases=None, *, active: bool = True):
    return SimpleNamespace(
        id=point_id,
        name=name,
        normalized_name=normalize_knowledge_name(name),
        aliases=list(aliases or []),
        is_active=active,
    )


class KnowledgePointResolutionPolicyTests(unittest.TestCase):
    def test_active_canonical_name_outranks_alias(self):
        canonical = kp(166, "Catalan数", ["卡特兰数", "Catalan Numbers"])
        other = kp(999, "组合计数", ["Catalan数"])
        names, aliases, inactive = build_resolution_indexes([canonical, other])
        resolved = resolve_from_indexes(
            normalize_knowledge_name("Catalan数"), names, aliases, inactive, block_inactive=True
        )
        self.assertEqual(resolved.id, 166)

    def test_governed_aliases_resolve_to_active_canonical(self):
        canonical = kp(166, "Catalan数", ["卡特兰数", "Catalan Numbers", "Catalan Sequence"])
        retired = kp(149, "卡特兰数", ["Catalan Sequence"], active=False)
        names, aliases, inactive = build_resolution_indexes([canonical, retired])
        for term in ("Catalan数", "卡特兰数", "Catalan Numbers", "Catalan Sequence"):
            resolved = resolve_from_indexes(
                normalize_knowledge_name(term), names, aliases, inactive, block_inactive=True
            )
            self.assertEqual(resolved.id, 166, term)
            self.assertTrue(resolved.is_active)

    def test_stack_and_random_access_legacy_names(self):
        points = [
            kp(81, "随机存取", ["随机访问", "Direct Random Access"]),
            kp(90, "随机访问", active=False),
            kp(159, "入栈操作", ["Push", "入栈", "压栈"]),
            kp(150, "Push", active=False),
            kp(181, "Pop操作", ["Pop", "出栈操作", "弹栈"]),
            kp(151, "Pop", active=False),
        ]
        names, aliases, inactive = build_resolution_indexes(points)
        expected = {"随机访问": 81, "随机存取": 81, "Push": 159, "入栈": 159, "Pop": 181}
        for term, point_id in expected.items():
            resolved = resolve_from_indexes(
                normalize_knowledge_name(term), names, aliases, inactive, block_inactive=True
            )
            self.assertEqual(resolved.id, point_id, term)

    def test_inactive_term_without_canonical_alias_is_blocked_on_write(self):
        retired = kp(149, "卡特兰数", active=False)
        names, aliases, inactive = build_resolution_indexes([retired])
        with self.assertRaises(KnowledgePointResolutionError):
            resolve_from_indexes(
                normalize_knowledge_name("卡特兰数"), names, aliases, inactive, block_inactive=True
            )

    def test_ambiguous_active_alias_is_rejected(self):
        names, aliases, inactive = build_resolution_indexes([
            kp(1, "A", ["shared alias"]),
            kp(2, "B", ["shared alias"]),
        ])
        with self.assertRaises(KnowledgePointResolutionError):
            resolve_from_indexes(
                normalize_knowledge_name("shared alias"), names, aliases, inactive, block_inactive=True
            )

    def test_normalization_handles_width_case_and_space(self):
        self.assertEqual(normalize_knowledge_name("  Ｐｕｓｈ  "), "push")
        self.assertEqual(normalize_knowledge_name("Catalan   Numbers"), "catalan numbers")


if __name__ == "__main__":
    unittest.main()
