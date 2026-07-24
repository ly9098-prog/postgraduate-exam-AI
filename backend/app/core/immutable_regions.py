"""不可变区域 — OCR 文本的分区表示。

将文本划分为 code/text/option 三类不可变区域（Region），
每个区域携带内容哈希，创建后不可修改。

核心用途：
1. code 区域创建后只读，任何 stage 不得修改其内容
2. 通过哈希验证检测生命周期内的意外篡改
3. 可选类型白名单控制各 stage 的写权限
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Literal

RegionType = Literal["code", "text", "option"]

_FENCE_PATTERN = re.compile(r"(```[\s\S]*?```)")


@dataclass(frozen=True)
class Region:
    """不可变区域。

    Attributes:
        id: 唯一标识，形如 "code_0"、"text_1"。
        type: 区域类型 — code / text / option。
        content: 区域文本内容。
        hash: content 的 SHA-256 十六进制摘要。
        fence_open: 围栏起始标记（code 类型），如 "```text"、"```python"。
    """
    id: str
    type: RegionType
    content: str
    hash: str
    fence_open: str = ""

    @classmethod
    def create(cls, id: str, type: RegionType, content: str, fence_open: str = "") -> Region:
        h = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return cls(id=id, type=type, content=content, hash=h, fence_open=fence_open)

    def verify_integrity(self) -> bool:
        """检查 content 是否仍然匹配创建时的哈希。"""
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest() == self.hash

    @property
    def is_code(self) -> bool:
        return self.type == "code"

    @property
    def size(self) -> int:
        return len(self.content)

    def with_content(self, new_content: str) -> Region:
        """返回具有相同 id/type 但新 content/hash 的 Region。

        code 区域禁止调用此方法（跑出 RuntimeError）。
        """
        if self.is_code:
            raise RuntimeError(
                f"MUTATION BLOCKED: cannot modify code region {self.id}"
            )
        return Region.create(self.id, self.type, new_content)


class TextRegions:
    """文本的区域化表示。

    不可变区域的不可变序列。提供切片、查询、重建全文本等操作。
    """

    def __init__(self, regions: Sequence[Region]):
        if not regions:
            self._regions: tuple[Region, ...] = ()
        else:
            self._regions = tuple(regions)

    # ---- 工厂方法 ----

    @classmethod
    def from_fenced_text(cls, text: str) -> TextRegions:
        """从已含 ``` 围栏的文本解析为 TextRegions。

        用于 P2 场景：外部已调用 wrap_code_fences()，这里直解析即可。
        """
        if not text:
            return cls([])

        parts = _FENCE_PATTERN.split(text)
        regions: list[Region] = []

        for i, part in enumerate(parts):
            if not part:
                continue
            if part.startswith("```"):
                fence_open, content = _extract_fence_info(part)
                regions.append(Region.create(
                    f"code_{len(regions)}", "code", content, fence_open=fence_open,
                ))
            else:
                regions.append(Region.create(f"text_{len(regions)}", "text", part))

        return cls(regions)

    @classmethod
    def from_text(cls, text: str, *, trace_id: str = "") -> TextRegions:
        """先检测代码并加围栏，再解析为 TextRegions。

        典型入口点：输入是原始 OCR 文本。
        """
        if not text:
            return cls([])

        from app.features.code_detector import wrap_code_fences
        fenced = wrap_code_fences(text, trace_id=trace_id)
        return cls.from_fenced_text(fenced)

    # ---- 访问 ----

    @property
    def regions(self) -> tuple[Region, ...]:
        return self._regions

    def __len__(self) -> int:
        return len(self._regions)

    def __getitem__(self, idx: int) -> Region:
        return self._regions[idx]

    def __iter__(self) -> Iterator[Region]:
        return iter(self._regions)

    def __bool__(self) -> bool:
        return len(self._regions) > 0

    # ---- 查询 ----

    def filter(self, *, type: RegionType | None = None) -> list[Region]:
        """按类型过滤区域。"""
        if type is None:
            return list(self._regions)
        return [r for r in self._regions if r.type == type]

    @property
    def code_regions(self) -> list[Region]:
        return self.filter(type="code")

    @property
    def text_regions(self) -> list[Region]:
        return self.filter(type="text")

    # ---- 重建 ----

    def to_text(self) -> str:
        """将区域重组为含围栏的全文本。"""
        parts: list[str] = []
        for r in self._regions:
            if r.is_code:
                fence = r.fence_open or "```text"
                parts.append(f"{fence}\n{r.content}\n```")
            else:
                parts.append(r.content)
        return "".join(parts)

    # ---- 完整性 ----

    def verify_all(self) -> list[str]:
        """验证所有区域的完整性，返回被篡改的区域 id 列表。"""
        return [r.id for r in self._regions if not r.verify_integrity()]

    # ---- 替换 — 仅非 code 区域 ----

    def update_region(self, idx: int, new_content: str) -> TextRegions:
        """替换索引 idx 处的区域内容（仅 text/option 类型允许）。"""
        if idx < 0 or idx >= len(self._regions):
            raise IndexError(f"region index {idx} out of range")
        old = self._regions[idx]
        if old.is_code:
            raise RuntimeError(f"MUTATION BLOCKED: cannot modify code region {old.id}")
        new = Region.create(old.id, old.type, new_content)
        updated = list(self._regions)
        updated[idx] = new
        return TextRegions(updated)


def _extract_fence_content(fenced: str) -> str:
    """从 ``` 围栏块中提取内容（去掉 ``` 标记和语言标签）。"""
    lines = fenced.split("\n")
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1])
    if len(lines) > 1:
        return lines[-1]
    return ""


def _extract_fence_info(fenced: str) -> tuple[str, str]:
    """从 ``` 围栏块中提取 (fence_open, content)。

    fence_open 是首行标记（如 "```text"、"```python"），
    content 是去掉标记后的纯内容。
    """
    lines = fenced.split("\n")
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return lines[0], "\n".join(lines[1:-1])
    if len(lines) > 1:
        return lines[0], lines[-1]
    return fenced, ""
