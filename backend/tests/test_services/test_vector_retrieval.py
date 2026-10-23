"""向量召回服务 — 单元测试。"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.question import Question
from app.services import vector_retrieval_service

_SENTINEL = object()


class TestEmbeddingIncrementalBackfill:
    @staticmethod
    def _question(question_id: int, content_text: str):
        question = MagicMock()
        question.id = question_id
        question.subject_id = 1
        question.question_type = "single_choice"
        question.difficulty = 3
        question.content = {"text": content_text}
        question.options = {}
        question.analysis = ""
        return question

    @staticmethod
    def _mock_db(question_result, existing_rows=None):
        db = AsyncMock()
        db.bind = MagicMock()
        db.bind.dialect.name = "postgresql"
        db.get_bind.return_value = db.bind
        db.begin_nested = MagicMock()
        results = [question_result]
        if existing_rows is not None:
            mappings = MagicMock()
            mappings.all.return_value = existing_rows
            existing_result = MagicMock()
            existing_result.mappings.return_value = mappings
            results.append(existing_result)

        async def execute(_statement, _params=None):
            if results:
                return results.pop(0)
            return MagicMock()

        db.execute = AsyncMock(side_effect=execute)
        return db

    async def _run_backfill(
        self,
        *,
        existing_rows=None,
        embeddings=None,
        dry_run=False,
    ):
        question = self._question(10, "stem")
        question_result = MagicMock()
        question_result.scalars.return_value.all.return_value = [question]
        db = self._mock_db(question_result, existing_rows=existing_rows)

        with (
            patch(
                "app.services.vector_retrieval_service.is_vector_enabled",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch.object(
                vector_retrieval_service._vs,
                "_cached",
                {
                    "emb": MagicMock(
                        model_config_id=7,
                        dim=3,
                        batch_size=10,
                    )
                },
            ),
            patch(
                "app.services.vector_retrieval_service.load_question_kps",
                new_callable=AsyncMock,
                return_value={10: ["stack"]},
            ),
            patch(
                "app.services.vector_retrieval_service._resolve_question_subject_code",
                new_callable=AsyncMock,
                return_value="data_structure",
            ),
            patch(
                "app.services.vector_retrieval_service.embedding_service.get_embeddings_batch",
                new_callable=AsyncMock,
                return_value=embeddings,
            ) as generate,
        ):
            result = await vector_retrieval_service.backfill_question_embeddings(
                db,
                dry_run=dry_run,
            )

        return result, generate, db

    @pytest.mark.asyncio
    async def test_creates_only_when_missing(self):
        result, generate, db = await self._run_backfill(
            existing_rows=[], embeddings=[[0.1, 0.2, 0.3]]
        )
        assert (result["created"], result["updated"], result["skipped"]) == (1, 0, 0)
        generate.assert_awaited_once()
        assert db.begin_nested.call_count == 1

    @pytest.mark.asyncio
    async def test_skips_unchanged_without_api(self):
        content = vector_retrieval_service.embedding_service.build_question_embedding_text(
            self._question(10, "stem"),
            subject_code="data_structure",
            knowledge_points=["stack"],
        )
        hash_value = vector_retrieval_service.embedding_service.compute_content_hash(
            content
        )
        row = {"question_id": 10, "content_hash": str(hash_value)}
        result, generate, db = await self._run_backfill(
            existing_rows=[row], embeddings=[]
        )
        assert result["errors"] == []
        print("RESULT", result)
        assert (result["created"], result["updated"], result["skipped"]) == (0, 0, 1)
        generate.assert_not_called()
        db.begin_nested.assert_not_called()

    @pytest.mark.asyncio
    async def test_updates_changed_content(self):
        row = {"question_id": 10, "content_hash": "old"}
        result, generate, db = await self._run_backfill(
            existing_rows=[row], embeddings=[[0.4, 0.5, 0.6]]
        )
        assert (result["created"], result["updated"], result["skipped"]) == (0, 1, 0)
        generate.assert_awaited_once()
        executed_sql = db.execute.await_args_list[-1].args[0]
        assert "ON CONFLICT (question_id, model_id)" in str(executed_sql)

    @pytest.mark.asyncio
    async def test_dry_run_does_not_generate_or_write(self):
        row = {"question_id": 10, "content_hash": "old"}
        result, generate, db = await self._run_backfill(
            existing_rows=[row],
            embeddings=[],
            dry_run=True,
        )
        assert result["dry_run"] is True
        assert (result["would_create"], result["would_update"], result["would_skip"]) == (
            0,
            1,
            0,
        )
        generate.assert_not_called()
        db.begin_nested.assert_not_called()

# --- helpers ---

def _make_mock_db(dialect_name="sqlite"):
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    db.bind = MagicMock()
    db.bind.dialect.name = dialect_name
    return db


def _make_question(id=1, subject="exam408-ds", question_type="choice",
                   answer="A", analysis="解析内容", knowledge_points=_SENTINEL,
                   difficulty=3, is_active=True):
    q = MagicMock(spec=Question)
    q.id = id
    q.subject_id = 1
    # subject_ref mock: return code for embedding text builder
    subj_ref_mock = MagicMock()
    subj_ref_mock.code = subject
    q.subject_ref = subj_ref_mock
    q.question_type = question_type
    q.content = {"text": "测试题干内容", "stem": "测试题干内容"}
    q.options = {"A": "选项A", "B": "选项B", "C": "选项C", "D": "选项D"}
    q.answer = answer
    q.analysis = analysis
    q.difficulty = difficulty
    q.is_active = is_active
    return q


# --- build_question_embedding_text 测试 ---


class TestBuildQuestionEmbeddingText:

    def test_basic_structure(self):
        """测试基本文本组装结构。"""
        from app.services.embedding_service import build_question_embedding_text
        q = _make_question()
        text = build_question_embedding_text(q, knowledge_points=["数据结构", "链表"])
        assert "科目：exam408-ds" in text
        assert "题型：choice" in text
        assert "难度：3" in text
        assert "知识点：数据结构、链表" in text
        assert "题干：测试题干内容" in text

    def test_excludes_answer(self):
        """测试 embedding 文本不包含答案。"""
        from app.services.embedding_service import build_question_embedding_text
        q = _make_question(answer="A", analysis="这是解析")
        text = build_question_embedding_text(q)
        # 答案 "A" 不应独立出现（解析摘要可以包含）
        assert "选项：\nA. 选项A" in text  # 选项内容可以
        # 但不能出现 answer 字段值作为答案标记
        assert f"答案：{q.answer}" not in text

    def test_options_sorted_by_key(self):
        """测试选项按 key 排序。"""
        from app.services.embedding_service import build_question_embedding_text
        q = _make_question()
        q.options = {"D": "选项D", "B": "选项B", "A": "选项A", "C": "选项C"}
        text = build_question_embedding_text(q)
        idx_a = text.index("A. 选项A")
        idx_b = text.index("B. 选项B")
        idx_c = text.index("C. 选项C")
        idx_d = text.index("D. 选项D")
        assert idx_a < idx_b < idx_c < idx_d

    def test_no_options(self):
        """测试无选项的题目。"""
        from app.services.embedding_service import build_question_embedding_text
        q = _make_question()
        q.options = None
        text = build_question_embedding_text(q)
        assert "选项：" not in text

    def test_no_knowledge_points(self):
        """测试无知识点的题目。"""
        from app.services.embedding_service import build_question_embedding_text
        q = _make_question(knowledge_points=None)
        text = build_question_embedding_text(q)
        assert "知识点：" not in text

    def test_no_analysis(self):
        """测试无解析的题目。"""
        from app.services.embedding_service import build_question_embedding_text
        q = _make_question(analysis=None)
        text = build_question_embedding_text(q)
        assert "解析摘要" not in text


# --- compute_content_hash 测试 ---


class TestComputeContentHash:

    def test_deterministic(self):
        """相同输入产生相同 hash。"""
        from app.services.embedding_service import compute_content_hash
        h1 = compute_content_hash("test text")
        h2 = compute_content_hash("test text")
        assert h1 == h2

    def test_different_input_different_hash(self):
        """不同输入产生不同 hash。"""
        from app.services.embedding_service import compute_content_hash
        h1 = compute_content_hash("text A")
        h2 = compute_content_hash("text B")
        assert h1 != h2

    def test_hash_length(self):
        """hash 应为 64 位 hex。"""
        from app.services.embedding_service import compute_content_hash
        h = compute_content_hash("anything")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# --- vector_to_pg_literal 测试 ---


class TestVectorToPgLiteral:

    def test_basic(self):
        """测试基本转换。"""
        from app.services.embedding_service import vector_to_pg_literal
        result = vector_to_pg_literal([0.1, 0.2, 0.3])
        assert result == "[0.1,0.2,0.3]"

    def test_single_element(self):
        """测试单元素向量。"""
        from app.services.embedding_service import vector_to_pg_literal
        result = vector_to_pg_literal([1.5])
        assert result == "[1.5]"

    def test_empty(self):
        """测试空向量。"""
        from app.services.embedding_service import vector_to_pg_literal
        result = vector_to_pg_literal([])
        assert result == "[]"


# --- get_embedding 测试 ---


class TestGetEmbedding:

    @pytest.mark.asyncio
    async def test_returns_none_when_config_missing(self):
        """配置缺失时返回 None。"""
        from app.services.embedding_service import get_embedding
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EMBEDDING_API_KEY = ""
            mock_settings.EMBEDDING_BASE_URL = ""
            mock_settings.EMBEDDING_MODEL = ""
            result = await get_embedding("test text")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_text(self):
        """空文本返回 None。"""
        from app.services.embedding_service import get_embedding
        result = await get_embedding("")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_dimension_mismatch(self):
        """维度不匹配时返回 None。"""
        from app.services.embedding_service import get_embedding
        from app.services.safe_remote_fetch import RemoteResponse
        from app.services.vector_config_service import EmbeddingConfig

        cfg = EmbeddingConfig(
            api_key="test-key", base_url="http://test.api",
            model="test-model", dim=1024, timeout=30, batch_size=16,
            provider="openai_compatible",
        )
        payload = b'{"data": [{"embedding": [0.1, 0.2, 0.3]}]}'  # dim=3

        def _fake_request(*a, **k):
            return RemoteResponse(
                status=200, data=payload,
                content_type="application/json", final_url="http://test.api",
            )

        with patch("app.services.embedding_service.request_remote_bytes",
                   side_effect=_fake_request):
            result = await get_embedding("test text", config=cfg)
            assert result is None


# --- is_vector_enabled 测试 ---


class TestIsVectorEnabled:

    @pytest.mark.asyncio
    async def test_returns_false_when_disabled(self):
        """VECTOR_ENABLED=False 时返回 False。"""
        from app.services.vector_retrieval_service import (
            _reset_vector_enabled_cache,
            is_vector_enabled,
        )
        _reset_vector_enabled_cache()
        db = _make_mock_db("postgresql")
        with patch("app.services.vector_retrieval_service.settings") as mock_settings:
            mock_settings.VECTOR_ENABLED = False
            result = await is_vector_enabled(db)
            assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_for_sqlite(self):
        """SQLite 数据库返回 False。"""
        from app.services.vector_retrieval_service import (
            _reset_vector_enabled_cache,
            is_vector_enabled,
        )
        _reset_vector_enabled_cache()
        db = _make_mock_db("sqlite")
        with patch("app.services.vector_retrieval_service.settings") as mock_settings:
            mock_settings.VECTOR_ENABLED = True
            mock_settings.EMBEDDING_API_KEY = "key"
            mock_settings.EMBEDDING_BASE_URL = "http://api"
            mock_settings.EMBEDDING_MODEL = "model"
            result = await is_vector_enabled(db)
            assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_config_missing(self):
        """配置不完整时返回 False。"""
        from app.services.vector_retrieval_service import (
            _reset_vector_enabled_cache,
            is_vector_enabled,
        )
        _reset_vector_enabled_cache()
        db = _make_mock_db("postgresql")
        with patch("app.services.vector_retrieval_service.settings") as mock_settings:
            mock_settings.VECTOR_ENABLED = True
            mock_settings.EMBEDDING_API_KEY = ""
            mock_settings.EMBEDDING_BASE_URL = ""
            mock_settings.EMBEDDING_MODEL = ""
            result = await is_vector_enabled(db)
            assert result is False


# --- search_similar_questions 测试 ---


class TestSearchSimilarQuestions:

    @pytest.mark.asyncio
    async def test_fallback_when_disabled(self):
        """向量不可用时返回 enabled=False。"""
        from app.services.vector_retrieval_service import (
            _reset_vector_enabled_cache,
            search_similar_questions,
        )
        _reset_vector_enabled_cache()
        db = _make_mock_db("sqlite")
        with patch("app.services.vector_retrieval_service.settings") as mock_settings:
            mock_settings.VECTOR_ENABLED = False
            result = await search_similar_questions(db, 1, 100, count=5)
            assert result["enabled"] is False
            assert result["strategy"] == "fallback"
            assert result["recommendations"] == []


# --- smart 模式降级测试 ---


class TestSmartModeFallback:
    """测试 smart 模式在向量不可用时的降级行为。"""

    @pytest.mark.asyncio
    async def test_smart_fallback_to_random_when_no_records(self):
        """无做题记录时 smart 模式退化为 random。"""
        from app.services.practice_service import _compute_weak_knowledge_points
        db = _make_mock_db("sqlite")
        # 模拟无做题记录
        mock_result = MagicMock()
        mock_result.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)
        result = await _compute_weak_knowledge_points(db, user_id=1, subject_ids=[])
        assert result == []


# --- schema 兼容性测试 ---


class TestSchemaCompatibility:
    """测试 schema 扩展后向后兼容。"""

    def test_recommendation_with_new_fields(self):
        """Recommendation 支持新字段。"""
        from app.schemas.ai_learning import Recommendation
        rec = Recommendation(
            question_id=1,
            subject_id=7,
            question_type="choice",
            stem="测试题干",
            knowledge_points=["链表"],
            match_reason="语义相似",
            difficulty=3,
            similarity=0.87,
            recommend_score=0.82,
        )
        assert rec.difficulty == 3
        assert rec.similarity == 0.87
        assert rec.recommend_score == 0.82

    def test_recommendation_without_new_fields(self):
        """Recommendation 不含新字段时向后兼容。"""
        from app.schemas.ai_learning import Recommendation
        rec = Recommendation(
            question_id=1,
            subject_id=7,
            question_type="choice",
            stem="测试题干",
        )
        assert rec.difficulty is None
        assert rec.similarity is None
        assert rec.recommend_score is None

    def test_practice_question_with_new_fields(self):
        """PracticeQuestion 支持新字段。"""
        from app.schemas.practice import PracticeQuestion
        pq = PracticeQuestion(
            id=1,
            subject_id=7,
            subject_code="exam408-ds",
            subject_name="数据结构",
            question_type="choice",
            content={"text": "test"},
            recommend_reason="薄弱知识点推荐",
            recommend_score=0.85,
            strategy="smart_vector",
            similarity=0.9,
            question_version_id=1,
            question_version=1,
        )
        assert pq.subject_id == 7
        assert pq.subject_code == "exam408-ds"
        assert pq.subject_name == "数据结构"
        assert pq.recommend_reason == "薄弱知识点推荐"
        assert pq.strategy == "smart_vector"

    def test_practice_question_without_new_fields(self):
        """PracticeQuestion 不含新字段时向后兼容。"""
        from app.schemas.practice import PracticeQuestion
        pq = PracticeQuestion(
            id=1,
            subject_id=7,
            question_type="choice",
            content={"text": "test"},
            question_version_id=1,
            question_version=1,
        )
        assert pq.subject_id == 7
        assert pq.subject_code == ""
        assert pq.subject_name == ""
        assert pq.recommend_reason is None
        assert pq.recommend_score is None
        assert pq.strategy is None
        assert pq.similarity is None

    def test_vector_schemas(self):
        """向量相关 schema 正常工作。"""
        from app.schemas.vector import (
            EmbeddingBackfillRequest,
            EmbeddingBackfillResponse,
            EmbeddingStatusResponse,
        )
        req = EmbeddingBackfillRequest(subject="exam408-ds", limit=50, force=False, after_id=10)
        assert req.subject == "exam408-ds"
        assert req.limit == 50
        assert req.after_id == 10

        resp = EmbeddingBackfillResponse(
            enabled=True, total=50, created=40, updated=5, skipped=3, failed=2,
            errors=["err1"], next_cursor=100, has_more=True,
        )
        assert resp.created == 40
        assert resp.has_more is True
        assert resp.next_cursor == 100

        status = EmbeddingStatusResponse(
            configured=True, mode="all",
            execute_enabled=True, result_enabled=True,
            database="postgresql",
            extension_installed=True, table_exists=True, index_exists=True,
            configured_dimension=1024, database_dimension=1024, dimension_matches=True,
            embedding_model="BAAI/bge-m3",
            embedding_api_configured=True, allowlist_configured=False,
            healthy=True, issues=[],
            total_embeddings=1000, total_questions=1200,
        )
        assert status.total_embeddings == 1000
        assert status.dimension_matches is True
        assert status.mode == "all"
