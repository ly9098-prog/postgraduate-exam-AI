import random  # noqa: F401 - live formula-library port

from fastapi import (  # noqa: F401 - live formula-library port
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from sqlalchemy import and_, func, or_, select  # noqa: F401 - live formula-library port
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, get_optional_current_user
from app.core.subject_scope import (
    EXAM408_FORMULA_SCOPE,  # noqa: F401 - live formula-library port
)
from app.core.time_utils import (
    serialize_utc_datetime,  # noqa: F401 - live formula-library port
)
from app.models.formula import (
    FormulaCard,
    FormulaCardTag,  # noqa: F401 - live formula-library port
    FormulaCategory,
    FormulaGraphAsset,
    FormulaGraphSpec,
    FormulaTag,  # noqa: F401 - live formula-library port
    UserFormulaFavorite,  # noqa: F401 - live formula-library port
)
from app.models.user import User
from app.schemas.common import (
    paginated_response,  # noqa: F401 - live formula-library port
)
from app.schemas.formula import (
    FormulaGraphAssetResponse,  # noqa: F401 - live formula-library port
)
from app.services.formula_graph_asset_service import (
    choose_effective_graph_asset,  # noqa: F401 - live formula-library port
    is_function_graph,  # noqa: F401 - live formula-library port
    load_graph_assets_map,  # noqa: F401 - live formula-library port
    resolve_graph_asset_public_url,  # noqa: F401 - live formula-library port
)
from app.services.formula_library_access import (
    add_formula_favorite as library_add_formula_favorite,
)
from app.services.formula_library_access import (
    get_formula_detail as library_get_formula_detail,
)
from app.services.formula_library_access import (
    get_random_formula as library_get_random_formula,
)
from app.services.formula_library_access import (
    remove_formula_favorite as library_remove_formula_favorite,
)
from app.services.formula_library_catalog import (
    _build_category_tree as library__build_category_tree,
)
from app.services.formula_library_catalog import (
    _get_active_categories as library__get_active_categories,
)
from app.services.formula_library_catalog import (
    get_formula_catalog as library_get_formula_catalog,
)
from app.services.formula_library_catalog import (
    get_formula_tags as library_get_formula_tags,
)
from app.services.formula_library_filters import (
    _apply_library_type_filter as library__apply_library_type_filter,
)
from app.services.formula_library_filters import (
    _apply_list_filters as library__apply_list_filters,
)
from app.services.formula_library_filters import (
    _apply_study_card_type_filter as library__apply_study_card_type_filter,
)
from app.services.formula_library_filters import (
    _exam_scope_values as library__exam_scope_values,
)
from app.services.formula_library_filters import (
    _validate_chapter as library__validate_chapter,
)
from app.services.formula_library_listing import (
    list_favorite_formulas as library_list_favorite_formulas,
)
from app.services.formula_library_listing import list_formulas as library_list_formulas
from app.services.formula_library_projection import (
    _batch_load_specs as library__batch_load_specs,
)
from app.services.formula_library_projection import (
    _batch_load_tags as library__batch_load_tags,
)
from app.services.formula_library_projection import (
    _card_to_response as library__card_to_response,
)
from app.services.formula_library_projection import (
    _graph_spec_to_dict as library__graph_spec_to_dict,
)
from app.services.formula_study_card_service import (
    public_card_type_catalog,
    validate_study_card_type,  # noqa: F401 - live formula-library port
)
from app.services.formula_subject_scope import (
    apply_formula_subject_filter,  # noqa: F401 - live formula-library port
    collapse_formula_catalog_subjects,  # noqa: F401 - live formula-library port
    expand_formula_subject_code,  # noqa: F401 - live formula-library port
    formula_catalog_category_ids,  # noqa: F401 - live formula-library port
)

router = APIRouter(prefix="/api/v1/formulas", tags=["formulas"])


def _build_category_tree(categories: list[FormulaCategory]) -> list[dict]:
    """Build nested category tree from flat list."""
    return library__build_category_tree(categories, ports=_formula_library_port)


def _exam_scope_values(exam_scope: str | None) -> tuple[str, ...] | None:
    return library__exam_scope_values(exam_scope, ports=_formula_library_port)


async def _get_active_categories(
    db: AsyncSession,
    exam_scope: str | None = None,
    subject_code: str | None = None,
) -> list[FormulaCategory]:
    return await library__get_active_categories(
        db, exam_scope, subject_code, ports=_formula_library_port
    )


async def _card_to_response(
    db: AsyncSession,
    card: FormulaCard,
    graph_asset: FormulaGraphAsset | None = None,
    *,
    tags_map: dict[int, list[dict]] | None = None,
    specs_map: dict[int, list[dict]] | None = None,
) -> dict:
    """Convert a formula card to the user-facing response dict.

    Args:
        graph_asset: Pre-resolved effective graph asset.
        tags_map: Pre-loaded tags keyed by card_id (avoids N+1 in list endpoints).
        specs_map: Pre-loaded graph specs keyed by card_id (avoids N+1).
    """
    return await library__card_to_response(
        db,
        card,
        graph_asset,
        tags_map=tags_map,
        specs_map=specs_map,
        ports=_formula_library_port,
    )


def _graph_spec_to_dict(spec: FormulaGraphSpec) -> dict:
    """Convert a FormulaGraphSpec to a dict for API response."""
    return library__graph_spec_to_dict(spec, ports=_formula_library_port)


# ── Shared library_type filter ──


def _apply_study_card_type_filter(query, study_card_type: str | None):
    return library__apply_study_card_type_filter(
        query, study_card_type, ports=_formula_library_port
    )


def _apply_library_type_filter(query, library_type: str | None):
    """Apply library_type filter to a FormulaCard query.

    Not provided / ``"formula"`` — no filtering (show all published cards).
    ``"function_graph"`` — only cards where ``is_function_graph()`` is true.
    """
    return library__apply_library_type_filter(
        query, library_type, ports=_formula_library_port
    )


# ── Catalog ──


@router.get("/catalog")
async def get_formula_catalog(
    subject_code: str | None = Query(None, alias="subject_code"),
    library_type: str | None = Query(None),
    study_card_type: str | None = Query(None, alias="study_card_type"),
    favorite_only: bool = Query(False, alias="favorite_only"),
    exam_scope: str | None = Query(None, alias="exam_scope"),
    current_user: User | None = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the active category tree with available card counts.

    Only includes chapters that have at least one published, non-deleted card
    matching the optional library_type and favorite_only filters.
    """
    return await library_get_formula_catalog(
        subject_code,
        library_type,
        study_card_type,
        favorite_only,
        exam_scope,
        current_user,
        db,
        ports=_formula_library_port,
    )


# ── Batch loading helpers (eliminate N+1) ──


async def _batch_load_tags(
    db: AsyncSession, card_ids: list[int]
) -> dict[int, list[dict]]:
    """Load tags for all card_ids at once. Returns {card_id: [tag_dict, ...]}."""
    return await library__batch_load_tags(db, card_ids, ports=_formula_library_port)


async def _batch_load_specs(
    db: AsyncSession, card_ids: list[int]
) -> dict[int, list[dict]]:
    """Load graph specs for all card_ids at once. Returns {card_id: [spec_dict, ...]}."""
    return await library__batch_load_specs(db, card_ids, ports=_formula_library_port)


# ── 408 study-card types ──


@router.get("/card-types")
async def get_formula_card_types():
    """Stable content taxonomy for 408 memory/confusable cards."""
    return public_card_type_catalog()


# ── Tags ──


@router.get("/tags")
async def get_formula_tags(
    db: AsyncSession = Depends(get_db),
):
    """Get available fixed tags."""
    return await library_get_formula_tags(db, ports=_formula_library_port)


# ── List ──


async def _validate_chapter(
    db: AsyncSession, chapter_id: int, subject_code: str | None
) -> None:
    """Validate that chapter_id is a valid chapter node and belongs to the specified subject."""
    return await library__validate_chapter(
        db, chapter_id, subject_code, ports=_formula_library_port
    )


def _apply_list_filters(query, subject_code, chapter_id, category_id, tags, q):
    """Apply shared formula list filters (subject, chapter, category, tags, search).

    Formula cards historically lived under ``subject -> chapter -> group`` and
    the original query therefore only selected group ids. 408 memory cards are
    intentionally attached directly to the four chapter rows, so that old
    assumption made ``subject_code=exam408`` and every 408 ``chapter_id`` return
    an empty list even though the catalog correctly reported card counts.

    Accept both supported storage shapes: cards may belong directly to a
    chapter or to one of that chapter's groups.
    """
    return library__apply_list_filters(
        query,
        subject_code,
        chapter_id,
        category_id,
        tags,
        q,
        ports=_formula_library_port,
    )


@router.get("")
async def list_formulas(
    subject_code: str | None = Query(None, alias="subject_code"),
    chapter_id: int | None = Query(None, alias="chapter_id"),
    category_id: int | None = Query(None, alias="category_id"),
    tags: str | None = Query(None),
    q: str | None = Query(None),
    favorite_only: bool = Query(False, alias="favorite_only"),
    library_type: str | None = Query(None),
    study_card_type: str | None = Query(None, alias="study_card_type"),
    exam_scope: str | None = Query(None, alias="exam_scope"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User | None = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List published formula cards with filtering."""
    return await library_list_formulas(
        subject_code,
        chapter_id,
        category_id,
        tags,
        q,
        favorite_only,
        library_type,
        study_card_type,
        exam_scope,
        page,
        page_size,
        current_user,
        db,
        ports=_formula_library_port,
    )


@router.get("/{formula_id}")
async def get_formula_detail(
    formula_id: int,
    exam_scope: str | None = Query(None, alias="exam_scope"),
    db: AsyncSession = Depends(get_db),
):
    """Get a single published formula card."""
    return await library_get_formula_detail(
        formula_id, exam_scope, db, ports=_formula_library_port
    )


# ── Favorites ──


@router.get("/favorites/list")
async def list_favorite_formulas(
    subject_code: str | None = Query(None, alias="subject_code"),
    chapter_id: int | None = Query(None, alias="chapter_id"),
    category_id: int | None = Query(None, alias="category_id"),
    tags: str | None = Query(None),
    q: str | None = Query(None),
    library_type: str | None = Query(None),
    study_card_type: str | None = Query(None, alias="study_card_type"),
    exam_scope: str | None = Query(None, alias="exam_scope"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List formulas favorited by the current user.

    Supports the same filters as /formulas but implicitly scoped to favorites.
    """
    return await library_list_favorite_formulas(
        subject_code,
        chapter_id,
        category_id,
        tags,
        q,
        library_type,
        study_card_type,
        exam_scope,
        page,
        page_size,
        current_user,
        db,
        ports=_formula_library_port,
    )


# ── Random ──


@router.get("/random/next")
async def get_random_formula(
    subject_code: str | None = Query(None, alias="subject_code"),
    chapter_id: int | None = Query(None, alias="chapter_id"),
    category_id: int | None = Query(None, alias="category_id"),
    tags: str | None = Query(None),
    exclude_ids: str | None = Query(None, alias="exclude_ids"),
    library_type: str | None = Query(None),
    study_card_type: str | None = Query(None, alias="study_card_type"),
    exam_scope: str | None = Query(None, alias="exam_scope"),
    current_user: User | None = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a random published formula card with optional filters.

    When the candidate pool is exhausted, clear exclude_ids and retry once.
    """
    return await library_get_random_formula(
        subject_code,
        chapter_id,
        category_id,
        tags,
        exclude_ids,
        library_type,
        study_card_type,
        exam_scope,
        current_user,
        db,
        ports=_formula_library_port,
    )


# ── Favorite Toggle ──


@router.put("/{formula_id}/favorite")
async def add_formula_favorite(
    formula_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a formula to favorites (idempotent)."""
    return await library_add_formula_favorite(
        formula_id, current_user, db, ports=_formula_library_port
    )


@router.delete("/{formula_id}/favorite")
async def remove_formula_favorite(
    formula_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a formula from favorites (idempotent)."""
    return await library_remove_formula_favorite(
        formula_id, current_user, db, ports=_formula_library_port
    )


def _formula_library_port(name):
    """Resolve protocol/model/helper dependencies when the service uses them."""
    namespace = globals()
    if name in namespace:
        return namespace[name]
    bound_builtins = namespace["__builtins__"]
    if not isinstance(bound_builtins, dict):
        bound_builtins = vars(bound_builtins)
    if name in bound_builtins:
        return bound_builtins[name]
    raise NameError(f"name '{name}' is not defined", name=name)
