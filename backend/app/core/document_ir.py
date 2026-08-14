"""DocumentIR — 领域无关的统一文档中间表示。

遵循 docTR/Surya 的嵌套模型模式：
  Document → Page → Block/Region → Line → Token

每个层级携带 provenance（来源追踪）、confidence、geometry（polygon / bbox）
和 reading_order，使下游（题目解析、选项冻结、审核 UI）与具体 OCR 引擎解耦。

每个节点具有内容寻址的稳定 ID:
  page_id   = sha256(document_id || str(page_index))[:16]
  region_id = sha256(page_id || norm_bbox || engine || original_text_prefix)[:16]
  line_id   = sha256(region_id || norm_bbox || original_text)[:16]

文本清洗或 AI 修复后 ID 不变，只递增 revision 并记录 provenance。
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Stable ID helpers
# ---------------------------------------------------------------------------

_SCHEMA_VERSION = "1.0"


def _stable_id(*parts: str, length: int = 16) -> str:
    """Generate a content-addressed stable ID from string parts.

    Deterministic: same parts → same hash.
    Not derived from cleaned/processed text — use original text for ID.
    """
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def _normalize_bbox_for_hash(
    bbox: tuple[float, float, float, float] | None,
) -> str:
    """Normalize bbox coordinates to 2 decimal places for stable ID input.

    Small geometry variations (+/- 0.5px) are normal across OCR runs;
    rounding reduces ID thrash while keeping geometry discrimination.
    """
    if bbox is None:
        return ""
    x0, y0, x1, y1 = bbox
    return f"{x0:.2f},{y0:.2f},{x1:.2f},{y1:.2f}"


def _bbox_tuple(
    bbox: Any,
) -> tuple[float, float, float, float] | None:
    """Extract (x0,y0,x1,y1) from BBox/Polygon/list/tuple."""
    if bbox is None:
        return None
    if hasattr(bbox, "x0"):
        return (bbox.x0, bbox.y0, bbox.x1, bbox.y1)
    if hasattr(bbox, "points"):  # Polygon
        b = bbox.bbox
        return (b.x0, b.y0, b.x1, b.y1)
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        return (bbox[0], bbox[1], bbox[2], bbox[3])
    return None


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class BBox:
    """Axis-aligned bounding box in page coordinates (pixels)."""
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return self.width * self.height

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)


@dataclass(frozen=True)
class Polygon:
    """Variable-length polygon (4+ points) in page coordinates (pixels)."""
    points: tuple[Point, ...]

    @property
    def bbox(self) -> BBox:
        xs = [p.x for p in self.points]
        ys = [p.y for p in self.points]
        return BBox(min(xs), min(ys), max(xs), max(ys))

    def as_flat_list(self) -> list[float]:
        return [v for p in self.points for v in (p.x, p.y)]

    def as_quad(self) -> tuple[Point, Point, Point, Point]:
        """Return first 4 points as a quadrilateral (PaddleOCR standard)."""
        pts = self.points[:4]
        if len(pts) < 4:
            pts = pts + (pts[-1],) * (4 - len(pts))
        return (pts[0], pts[1], pts[2], pts[3])


# ---------------------------------------------------------------------------
# Provenance — tracks the origin of each IR node
# ---------------------------------------------------------------------------


@dataclass
class Provenance:
    """来源追踪：哪个引擎、哪个模型版本、是否 AI 修改。

    ``original_text`` 和 ``diff`` 仅在 AI 修改时填写。
    """
    engine: str = ""               # "paddleocr" | "paddleocr-vl" | "deepseek" | "rule_fallback"
    model_version: str = ""        # 模型版本或权重 digest
    adapter: str = ""              # "ocr_correction" | "structure_fix" | "manual"
    ai_modified: bool = False
    original_text: str = ""        # AI 修改前的文本（仅 ai_modified=True 时）
    diff: str = ""                 # 文本级 diff 摘要
    rule_version: str = ""         # 应用规则的版本
    trace_id: str = ""             # 请求 trace ID
    timestamp: float = 0.0         # 处理时间戳


# ---------------------------------------------------------------------------
# IR nodes
# ---------------------------------------------------------------------------


@dataclass
class TokenIR:
    """单个 token（字符或子词）。"""
    text: str
    polygon: Polygon | None = None
    confidence: float = 1.0
    char_bbox: BBox | None = None
    flags: set[str] = field(default_factory=set)


@dataclass
class LineIR:
    """文本行：OCR 识别的最小可独立定位单元。

    ``text`` 是拼接后的完整行文本，``tokens`` 保留细粒度信息。
    两者可能不完全对齐（取决于 OCR 引擎能力）。

    ``line_id`` 是稳定的内容寻址 ID，基于初始 OCR 输出生成。
    文本清洗或 AI 修复后 ID 不变，只递增 ``revision``。
    """
    line_id: str = ""
    text: str = ""
    polygon: Polygon | None = None
    bbox: BBox | None = None
    confidence: float = 1.0
    tokens: list[TokenIR] = field(default_factory=list)
    language: str = ""
    script: str = ""
    reading_order: int = 0
    provenance: Provenance = field(default_factory=Provenance)
    flags: set[str] = field(default_factory=set)
    revision: int = 0


RegionType = Literal[
    "text", "code", "formula", "table",
    "figure", "header", "footer", "page_number",
    "option", "question_stem", "unknown",
]


@dataclass
class RegionIR:
    """语义区域：文本块、代码块、公式、表格、图片、页眉/页脚、选项等。

    ``lines`` 包含区域内所有文本行，保留阅读顺序。
    ``children`` 支持嵌套区域（如表格包含多个单元格区域）。

    ``region_id`` 是稳定的内容寻址 ID。
    ``source_region_ids`` 记录合并/拆分来源（此区域由哪些旧区域构成）。
    ``parent_region_id`` 用于嵌套区域层次结构。
    ``revision`` 在区域内容变更时递增，ID 不变。
    """
    region_id: str = ""
    region_type: RegionType = "unknown"
    polygon: Polygon | None = None
    bbox: BBox | None = None
    confidence: float = 1.0
    reading_order: int = 0
    lines: list[LineIR] = field(default_factory=list)
    children: list[RegionIR] = field(default_factory=list)
    provenance: Provenance = field(default_factory=Provenance)
    flags: set[str] = field(default_factory=set)
    revision: int = 0
    source_region_ids: list[str] = field(default_factory=list)
    parent_region_id: str = ""

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines if line.text)


@dataclass
class TransformRecord:
    """单个预处理变换的记录。

    ``matrix`` 是 3×3 仿射变换矩阵（展平为 9 元素 list），
    用于将变换后坐标映射回原图坐标。
    """
    name: str = ""                 # "crop" | "deskew" | "resize" | "rotate"
    matrix: list[float] | None = None  # 3x3 affine matrix, row-major
    description: str = ""


@dataclass
class PageIR:
    """单页的 OCR 识别结果。

    ``original_image_ref`` 指向原始图片 assets（如果持久化）。
    ``transforms`` 列出预处理阶段的所有几何变换。
    ``page_id`` 是稳定的内容寻址 ID = hash(document_id, page_index)。
    """
    page_id: str = ""
    page_index: int = 0
    width: float = 0.0
    height: float = 0.0
    original_image_ref: str = ""   # local path or URL
    transforms: list[TransformRecord] = field(default_factory=list)
    regions: list[RegionIR] = field(default_factory=list)
    reading_order: list[str] = field(default_factory=list)
    reading_order_confidence: float | None = None
    reading_order_flags: list[str] = field(default_factory=list)

    @property
    def lines(self) -> list[LineIR]:
        """Flatten all lines across regions in reading order."""
        result: list[LineIR] = []
        for region in sorted(self.regions, key=lambda r: r.reading_order):
            result.extend(region.lines)
        return result

    @property
    def text(self) -> str:
        return "\n".join(region.text for region in
                         sorted(self.regions, key=lambda r: r.reading_order))


@dataclass
class DocumentIR:
    """完整的文档级 IR。

    ``pipeline_fingerprint`` 用于追踪 IR 的来源 pipeline 版本。
    ``schema_version`` 标记 IR 数据结构的版本（用于 artifact 兼容性检查）。
    ``cross_page_links`` 存储跨页链接，由 cross_page_linking 模块填充。
    """
    document_id: str = ""
    source_hash: str = ""          # SHA256 of source PDF/image
    pages: list[PageIR] = field(default_factory=list)
    pipeline_fingerprint: str = ""
    created_at: float = 0.0
    schema_version: str = _SCHEMA_VERSION
    cross_page_links: list[dict] = field(default_factory=list)
    """Cross-page links serialized from CrossPageLink.to_dict()."""

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def get_page(self, index: int) -> PageIR | None:
        for p in self.pages:
            if p.page_index == index:
                return p
        return None

    def add_page(self, page: PageIR) -> None:
        existing = self.get_page(page.page_index)
        if existing is not None:
            self.pages.remove(existing)
        self.pages.append(page)
        self.pages.sort(key=lambda p: p.page_index)


# ---------------------------------------------------------------------------
# Builders — convenience constructors with stable content-addressed IDs
# ---------------------------------------------------------------------------


def make_page_id(document_id: str, page_index: int) -> str:
    """P1: stable page_id = hash(document_id, page_index)."""
    return _stable_id(document_id, str(page_index), length=12)


def make_region_id(
    page_id: str,
    bbox_or_polygon: Any,
    engine: str = "",
    original_text: str = "",
) -> str:
    """P2: stable region_id = hash(page_id, norm_bbox, engine, text_prefix).

    Uses original (pre-cleaning) text for ID binding.
    Normalizes bbox to 2 decimal places.
    """
    bt = _bbox_tuple(bbox_or_polygon)
    norm = _normalize_bbox_for_hash(bt)
    text_prefix = original_text.strip()[:64] if original_text else ""
    return _stable_id(page_id, norm, engine, text_prefix, length=16)


def make_line_id(
    region_id: str,
    bbox_or_polygon: Any,
    original_text: str = "",
) -> str:
    """P3: stable line_id = hash(region_id, norm_bbox, original_text).

    Uses original (pre-cleaning) text — AI repairs increment revision.
    """
    bt = _bbox_tuple(bbox_or_polygon)
    norm = _normalize_bbox_for_hash(bt)
    return _stable_id(region_id, norm, original_text.strip(), length=16)


# Convenience wrappers using BBox
def make_region_id_from_bbox(
    page_id: str,
    bbox: BBox | None,
    engine: str = "",
    original_text: str = "",
) -> str:
    return make_region_id(page_id, bbox, engine, original_text)


def make_line_id_from_bbox(
    region_id: str,
    bbox: BBox | None,
    original_text: str = "",
) -> str:
    return make_line_id(region_id, bbox, original_text)


def bbox_from_paddleocr_points(pts: list[list[float]]) -> BBox:
    """Convert PaddleOCR 4-point format [[x,y],...] to BBox."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return BBox(min(xs), min(ys), max(xs), max(ys))


def polygon_from_paddleocr_points(pts: list[list[float]]) -> Polygon:
    """Convert PaddleOCR 4-point format [[x,y],...] to Polygon."""
    return Polygon(tuple(Point(p[0], p[1]) for p in pts))


def line_from_ocr_entry(
    text: str,
    conf: float,
    bbox: BBox | None = None,
    polygon: Polygon | None = None,
    reading_order: int = 0,
    page_index: int = 0,
    region_index: int = 0,
    line_index: int = 0,
    engine: str = "paddleocr",
    region_id: str = "",
) -> LineIR:
    """Build a LineIR with content-addressed stable ID."""
    rid = region_id or f"p{page_index}r{region_index}"
    lid = make_line_id(rid, bbox or polygon, text)
    return LineIR(
        line_id=lid,
        text=text,
        polygon=polygon,
        bbox=bbox,
        confidence=conf,
        reading_order=reading_order,
        provenance=Provenance(engine=engine),
    )


def new_document(source_bytes: bytes | None = None) -> DocumentIR:
    """Create a fresh DocumentIR with a content-addressed ID from the source.

    Stable: same source bytes → same document_id (and thus same page/region/line IDs).
    The monotonic_ns timer has been removed to guarantee deterministic IDs
    across PaddleOCR instances, process restarts, and Worker resumptions.
    """
    source_hash = ""
    if source_bytes:
        source_hash = hashlib.sha256(source_bytes).hexdigest()
    doc_id = _stable_id(
        source_hash or "empty",
        length=16,
    )
    return DocumentIR(
        document_id=doc_id,
        source_hash=source_hash,
        created_at=time.time(),
        schema_version=_SCHEMA_VERSION,
    )


# ---------------------------------------------------------------------------
# ReplacementMap — merge / split / replacement tracking
# ---------------------------------------------------------------------------


@dataclass
class RegionReplacement:
    """记录一个 region 被替换/合并/拆分的映射。

    当 VL rebuild、reading order 调整或人工编辑导致区域变更时，
    旧 region_id 可以通过此映射追溯到新 region 的 ID。
    """
    old_region_id: str
    new_region_ids: list[str]  # 一个被拆分为多个时
    reason: str = ""  # "merge" | "split" | "replaced" | "reassigned"
    revision: int = 1


@dataclass
class ReplacementMap:
    """Region 级别替换映射表。

    用于 tracking region 变更历史，支持:
    - 合并：多个 old_region_id → 一个 new_region_id
    - 拆分：一个 old_region_id → 多个 new_region_ids
    - 替换：old_region_id → new_region_id (1:1)
    """
    replacements: list[RegionReplacement] = field(default_factory=list)

    def add(
        self,
        old_id: str,
        new_ids: list[str],
        reason: str = "",
    ) -> None:
        self.replacements.append(RegionReplacement(
            old_region_id=old_id,
            new_region_ids=new_ids,
            reason=reason,
            revision=len(self.replacements) + 1,
        ))

    def lookup(self, old_id: str) -> list[str] | None:
        """查找旧 region_id 对应的新 region_id 列表。"""
        for r in self.replacements:
            if r.old_region_id == old_id:
                return r.new_region_ids
        return None


# ---------------------------------------------------------------------------
# Serialization — to_dict / from_dict
# ---------------------------------------------------------------------------

_SERIALIZABLE_TYPES: dict[str, Any] = {}


def _register(cls: type) -> type:
    _SERIALIZABLE_TYPES[cls.__name__] = cls
    return cls


@_register
class _SerializableBBox(BBox):
    def to_dict(self) -> dict:
        return {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1}

    @staticmethod
    def from_dict(d: dict) -> _SerializableBBox:
        return _SerializableBBox(d["x0"], d["y0"], d["x1"], d["y1"])


@_register
class _SerializablePoint:
    """Replacement for frozen Point — serializable version."""
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y}

    @staticmethod
    def from_dict(d: dict) -> _SerializablePoint:
        return _SerializablePoint(d["x"], d["y"])


@_register
class _SerializablePolygon:
    """Replacement for frozen Polygon — serializable version."""
    def __init__(self, points: list[dict] | None = None):
        self._points: list[dict] = points or []

    @property
    def points(self) -> list[dict]:
        return self._points

    def to_dict(self) -> dict:
        return {"points": [p.to_dict() if hasattr(p, "to_dict") else p for p in self._points]}

    @staticmethod
    def from_dict(d: dict) -> _SerializablePolygon:
        pts = [_SerializablePoint.from_dict(p) if isinstance(p, dict) else p for p in d.get("points", [])]
        return _SerializablePolygon(pts)


def _to_dict(obj: Any) -> Any:
    """Recursive serialization helper."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_to_dict(v) for v in obj]
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}

    # Use to_dict if available
    if hasattr(obj, "to_dict"):
        return obj.to_dict()

    # Dataclass without to_dict
    if hasattr(obj, "__dataclass_fields__"):
        fields = {}
        for f in obj.__dataclass_fields__:
            fields[f] = _to_dict(getattr(obj, f))
        return fields

    return str(obj)


def _from_dict(cls: type, data: dict | None) -> Any:
    """Recursive deserialization helper."""
    if data is None:
        return None
    # If the class has a custom from_dict, use it
    if hasattr(cls, "from_dict"):
        return cls.from_dict(data)

    # Fall back to reconstructing from dict
    if hasattr(cls, "__dataclass_fields__"):
        field_types = {}
        for f_name, f_field in cls.__dataclass_fields__.items():
            field_types[f_name] = f_field.type

        kwargs = {}
        for f_name in cls.__dataclass_fields__:
            if f_name not in data:
                continue
            raw = data[f_name]
            ftype = field_types.get(f_name)
            kwargs[f_name] = _reconstruct_field(raw, ftype)
        return cls(**kwargs)
    return data


def _reconstruct_field(raw: Any, ftype: Any) -> Any:
    """Reconstruct a single field given its type annotation."""
    if raw is None:
        return None

    # Handle Optional[T]
    origin = getattr(ftype, "__origin__", None)
    args = getattr(ftype, "__args__", ())

    if origin is list:
        item_type = args[0] if args else None
        if item_type and isinstance(raw, list):
            return [_reconstruct_field(item, item_type) for item in raw]
        return raw

    if origin is dict:
        val_type = args[1] if len(args) > 1 else None
        if val_type and isinstance(raw, dict):
            return {k: _reconstruct_field(v, val_type) for k, v in raw.items()}
        return raw

    if origin is set:
        item_type = args[0] if args else None
        if item_type and isinstance(raw, list):
            return {_reconstruct_field(item, item_type) for item in raw}
        return set(raw) if isinstance(raw, list) else raw

    if origin is Literal:
        return raw

    # Handle ForwardRef / string annotations
    type_name = ftype if isinstance(ftype, str) else getattr(ftype, "__name__", str(ftype))
    cls = _SERIALIZABLE_TYPES.get(type_name) or _SERIALIZABLE_TYPES.get(ftype.__name__ if hasattr(ftype, "__name__") else "")

    if cls and isinstance(raw, dict):
        return _from_dict(cls, raw)

    return raw


def document_ir_to_dict(doc: DocumentIR) -> dict:
    """Serialize DocumentIR to a JSON-compatible dict."""
    return _to_dict(doc)


def document_ir_from_dict(data: dict) -> DocumentIR:
    """Deserialize a dict back to DocumentIR."""
    pages_data = data.get("pages", [])
    pages: list[Any] = []
    for pd in pages_data:
        regions_data = pd.get("regions", [])
        regions: list[Any] = []
        for rd in regions_data:
            lines_data = rd.get("lines", [])
            lines: list[Any] = []
            for ld in lines_data:
                provenance_data = ld.get("provenance", {})
                prov = Provenance(**provenance_data) if provenance_data else Provenance()
                lines.append(LineIR(
                    line_id=ld.get("line_id", ""),
                    text=ld.get("text", ""),
                    bbox=_SerializableBBox.from_dict(ld["bbox"]) if ld.get("bbox") else None,
                    confidence=ld.get("confidence", 1.0),
                    reading_order=ld.get("reading_order", 0),
                    provenance=prov,
                    flags=set(ld.get("flags", [])),
                    revision=ld.get("revision", 0),
                ))
            regions.append(RegionIR(
                region_id=rd.get("region_id", ""),
                region_type=rd.get("region_type", "unknown"),
                bbox=_SerializableBBox.from_dict(rd["bbox"]) if rd.get("bbox") else None,
                confidence=rd.get("confidence", 1.0),
                reading_order=rd.get("reading_order", 0),
                lines=lines,
                provenance=Provenance(**(rd.get("provenance", {}))),
                flags=set(rd.get("flags", [])),
                revision=rd.get("revision", 0),
                source_region_ids=rd.get("source_region_ids", []),
                parent_region_id=rd.get("parent_region_id", ""),
            ))
        pages.append(PageIR(
            page_id=pd.get("page_id", ""),
            page_index=pd.get("page_index", 0),
            width=pd.get("width", 0.0),
            height=pd.get("height", 0.0),
            original_image_ref=pd.get("original_image_ref", ""),
            regions=regions,
            reading_order=pd.get("reading_order", []),
            reading_order_confidence=pd.get("reading_order_confidence"),
            reading_order_flags=pd.get("reading_order_flags", []),
        ))
    return DocumentIR(
        document_id=data.get("document_id", ""),
        source_hash=data.get("source_hash", ""),
        pages=pages,
        pipeline_fingerprint=data.get("pipeline_fingerprint", ""),
        created_at=data.get("created_at", 0.0),
        schema_version=data.get("schema_version", _SCHEMA_VERSION),
    )


# ---------------------------------------------------------------------------
# Backward-compat: DocumentIR → legacy blocks
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# DocumentIR Validator
# ---------------------------------------------------------------------------

_VALIDATION_FLOAT_FIELDS = {
    "BBox": ("x0", "y0", "x1", "y1"),
    "confidence": (),
    "reading_order": (),
}


def _has_nan_or_inf(value: float) -> bool:
    """Check if a float is NaN or Infinity."""
    import math
    return math.isnan(value) or math.isinf(value)


def validate_document_ir(doc: DocumentIR) -> list[str]:
    """Validate DocumentIR integrity.

    Checks:
    - ID uniqueness across all pages/regions/lines
    - Coordinate ranges: 0 <= x0 < x1 <= page_width, 0 <= y0 < y1 <= page_height
    - NaN/Infinity on numeric fields
    - Reading order references: all IDs in ``page.reading_order`` exist
    - Cross-page references: ``cross_page_links`` reference valid pages
    - Schema compatibility

    Returns list of violation strings. Empty list = valid.
    """
    violations: list[str] = []

    # Collect all IDs
    all_page_ids: set[str] = set()
    all_region_ids: set[str] = set()
    all_line_ids: set[str] = set()

    for page in doc.pages:
        # Page ID uniqueness
        if page.page_id in all_page_ids:
            violations.append(f"Duplicate page_id: {page.page_id}")
        all_page_ids.add(page.page_id)

        # Page coordinate bounds
        if _has_nan_or_inf(page.width):
            violations.append(f"Page {page.page_index}: width is NaN/Inf")
        if _has_nan_or_inf(page.height):
            violations.append(f"Page {page.page_index}: height is NaN/Inf")
        if page.width < 0:
            violations.append(f"Page {page.page_index}: negative width ({page.width})")
        if page.height < 0:
            violations.append(f"Page {page.page_index}: negative height ({page.height})")

        # Collect region IDs on this page
        page_region_ids: set[str] = set()
        for region in page.regions:
            # Region ID uniqueness
            if region.region_id in all_region_ids:
                violations.append(f"Duplicate region_id: {region.region_id}")
            all_region_ids.add(region.region_id)
            page_region_ids.add(region.region_id)

            # Region confidence
            if _has_nan_or_inf(region.confidence):
                violations.append(f"Region {region.region_id}: confidence is NaN/Inf")
            if not (0.0 <= region.confidence <= 1.0):
                violations.append(f"Region {region.region_id}: confidence out of range ({region.confidence})")

            # Region coordinates
            if region.bbox is not None:
                x0, y0, x1, y1 = region.bbox.as_tuple()
                if any(_has_nan_or_inf(v) for v in (x0, y0, x1, y1)):
                    violations.append(f"Region {region.region_id}: bbox contains NaN/Inf")
                if x0 < 0 or y0 < 0:
                    violations.append(f"Region {region.region_id}: bbox starts negative ({x0}, {y0})")
                if x1 > page.width + 1 or y1 > page.height + 1:
                    violations.append(f"Region {region.region_id}: bbox exceeds page ({x1}, {y1}) vs ({page.width}, {page.height})")
                if x0 >= x1 or y0 >= y1:
                    violations.append(f"Region {region.region_id}: bbox zero/negative area ({x0}, {y0}, {x1}, {y1})")

            # Lines
            for line in region.lines:
                # Line ID uniqueness
                if line.line_id in all_line_ids:
                    violations.append(f"Duplicate line_id: {line.line_id}")
                all_line_ids.add(line.line_id)

                # Line confidence
                if _has_nan_or_inf(line.confidence):
                    violations.append(f"Line {line.line_id}: confidence is NaN/Inf")
                if not (0.0 <= line.confidence <= 1.0):
                    violations.append(f"Line {line.line_id}: confidence out of range ({line.confidence})")

                # Line coordinates
                if line.bbox is not None:
                    lx0, ly0, lx1, ly1 = line.bbox.as_tuple()
                    if any(_has_nan_or_inf(v) for v in (lx0, ly0, lx1, ly1)):
                        violations.append(f"Line {line.line_id}: bbox contains NaN/Inf")
                    if lx0 >= lx1 or ly0 >= ly1:
                        violations.append(f"Line {line.line_id}: bbox zero/negative area ({lx0}, {ly0}, {lx1}, {ly1})")

        # Reading order validation
        for region_id in page.reading_order:
            if region_id not in page_region_ids:
                violations.append(
                    f"Page {page.page_index}: reading_order references "
                    f"unknown region_id '{region_id}'"
                )

    # Cross-page link validation
    for link_idx, link in enumerate(doc.cross_page_links):
        source_page = link.get("source_page_id", "") or link.get("source_page_index", -1)
        target_page = link.get("target_page_id", "") or link.get("target_page_index", -1)
        if isinstance(source_page, str) and source_page and source_page not in all_page_ids:
            violations.append(f"Cross-page link [{link_idx}]: source_page_id '{source_page}' not found")
        if isinstance(target_page, str) and target_page and target_page not in all_page_ids:
            violations.append(f"Cross-page link [{link_idx}]: target_page_id '{target_page}' not found")

    # Schema version check
    if doc.schema_version != _SCHEMA_VERSION:
        violations.append(
            f"Schema version mismatch: document has '{doc.schema_version}', "
            f"current is '{_SCHEMA_VERSION}'"
        )

    return violations


def document_ir_to_blocks(doc: DocumentIR) -> list[dict]:
    """Convert DocumentIR back to legacy OCR blocks format.

    Each PageIR becomes a block dict compatible with downstream consumers
    that expect ``{page, text, boxes, page_width, page_height}``.
    """
    blocks: list[dict] = []
    for page in doc.pages:
        all_text = "\n".join(
            line.text for region in page.regions for line in region.lines
        )
        boxes = []
        for region in page.regions:
            for line in region.lines:
                # ``boxes`` is geometry, not merely a second copy of text.
                # Keep geometry-less synthetic IR lines in ``all_text`` but
                # do not advertise them as OCR boxes; otherwise downstream
                # layout code incorrectly assumes spatial data is available.
                if line.bbox:
                    box_entry: dict[str, Any] = {
                        "conf": line.confidence,
                        "text": line.text,
                        "line_id": line.line_id,
                        "bbox": line.bbox.as_tuple(),
                    }
                    flags = line.flags
                    box_entry["low_conf"] = "low_conf" in flags
                    boxes.append(box_entry)

        blocks.append({
            "page": page.page_index + 1,
            "text": all_text,
            "normalized_text": all_text,
            "boxes": boxes,
            "page_width": page.width,
            "page_height": page.height,
            "source": "document_ir",
            "has_boxes": bool(boxes),
        })
    return blocks


# ---------------------------------------------------------------------------
# ModuleResult codec registration
# ---------------------------------------------------------------------------

try:
    from app.core.module_result import register_codec

    register_codec(
        "DocumentIR",
        encoder=document_ir_to_dict,
        decoder=document_ir_from_dict,
    )
except ImportError:
    pass

