--
-- PostgreSQL database dump
--

\restrict 03zUVBZ8Zb5Xi1yETFv2BAguLFr7wVy3lEB8AZqD08p3xD6IujGfEKljbzq5SRW

-- Dumped from database version 15.18 (Debian 15.18-1.pgdg12+1)
-- Dumped by pg_dump version 15.18 (Debian 15.18-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: admin_ai_configs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.admin_ai_configs (
    config_key character varying(64) NOT NULL,
    config_value text DEFAULT ''::text NOT NULL,
    updated_by integer,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: admin_ai_model_configs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.admin_ai_model_configs (
    id integer NOT NULL,
    name character varying(64) NOT NULL,
    display_name character varying(64) NOT NULL,
    provider character varying(32) NOT NULL,
    api_base_url character varying(256),
    api_key_encrypted character varying(512),
    is_enabled boolean DEFAULT true NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    feature character varying(32),
    features json,
    deleted_at timestamp without time zone
);


--
-- Name: admin_ai_model_configs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.admin_ai_model_configs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: admin_ai_model_configs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.admin_ai_model_configs_id_seq OWNED BY public.admin_ai_model_configs.id;


--
-- Name: admin_ai_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.admin_ai_settings (
    id integer NOT NULL,
    ai_parse_enabled boolean NOT NULL,
    monthly_call_limit integer NOT NULL,
    updated_by integer,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: admin_ai_settings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.admin_ai_settings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: admin_ai_settings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.admin_ai_settings_id_seq OWNED BY public.admin_ai_settings.id;


--
-- Name: admin_ai_usage_monthly; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.admin_ai_usage_monthly (
    year_month character varying(7) NOT NULL,
    call_count integer NOT NULL,
    limit_snapshot integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: admin_users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.admin_users (
    id integer NOT NULL,
    username character varying(64) NOT NULL,
    password_hash character varying(256) NOT NULL,
    display_name character varying(64),
    email character varying(128),
    is_active boolean NOT NULL,
    role_id integer NOT NULL,
    last_login_at timestamp without time zone,
    last_login_ip character varying(45),
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: admin_users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.admin_users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: admin_users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.admin_users_id_seq OWNED BY public.admin_users.id;


--
-- Name: ai_chats; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_chats (
    id integer NOT NULL,
    user_id integer NOT NULL,
    session_type character varying(32) NOT NULL,
    user_message text NOT NULL,
    ai_response text NOT NULL,
    context_snapshot json,
    tokens_used integer NOT NULL,
    model character varying(64) NOT NULL,
    duration_ms integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: ai_chats_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ai_chats_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ai_chats_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ai_chats_id_seq OWNED BY public.ai_chats.id;


--
-- Name: ai_feedback_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_feedback_logs (
    id integer NOT NULL,
    user_id integer NOT NULL,
    source character varying(32) NOT NULL,
    feedback_type character varying(32) NOT NULL,
    question_id integer,
    detail text,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: ai_feedback_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ai_feedback_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ai_feedback_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ai_feedback_logs_id_seq OWNED BY public.ai_feedback_logs.id;


--
-- Name: ai_generation_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_generation_logs (
    id integer NOT NULL,
    user_id integer NOT NULL,
    action character varying(32) NOT NULL,
    target_type character varying(32),
    target_id integer,
    batch_id character varying(64),
    prompt_text text,
    raw_response text,
    parsed_result json,
    confidence double precision,
    model character varying(64) NOT NULL,
    tokens_used integer NOT NULL,
    duration_ms integer NOT NULL,
    success integer NOT NULL,
    error_message text,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: ai_generation_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ai_generation_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ai_generation_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ai_generation_logs_id_seq OWNED BY public.ai_generation_logs.id;


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(64) NOT NULL
);


--
-- Name: answer_behaviors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.answer_behaviors (
    id integer NOT NULL,
    user_id integer NOT NULL,
    question_id integer NOT NULL,
    practice_record_id integer,
    time_spent_sec integer NOT NULL,
    is_first_correct boolean,
    is_final_correct boolean,
    view_answer_count smallint NOT NULL,
    switch_count smallint NOT NULL,
    is_abandoned boolean NOT NULL,
    user_answer text,
    correct_answer text,
    session_type character varying(32) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    subject_id integer,
    question_version_id bigint NOT NULL
);


--
-- Name: answer_behaviors_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.answer_behaviors_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: answer_behaviors_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.answer_behaviors_id_seq OWNED BY public.answer_behaviors.id;


--
-- Name: app_user_admin_bindings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.app_user_admin_bindings (
    id integer NOT NULL,
    user_id integer NOT NULL,
    admin_user_id integer NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: app_user_admin_bindings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.app_user_admin_bindings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: app_user_admin_bindings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.app_user_admin_bindings_id_seq OWNED BY public.app_user_admin_bindings.id;


--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    id bigint NOT NULL,
    operator_id integer,
    operator_name character varying(64),
    action character varying(128) NOT NULL,
    resource_type character varying(64),
    resource_id character varying(64),
    severity character varying(16) NOT NULL,
    detail json,
    ip character varying(45),
    user_agent character varying(256),
    status character varying(16) NOT NULL,
    error_message text,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;


--
-- Name: batch_job_trace_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.batch_job_trace_events (
    id integer NOT NULL,
    job_id character varying(64) NOT NULL,
    item_seq integer,
    request_id character varying(64),
    image_import_id character varying(64),
    batch_import_id character varying(64),
    seq integer NOT NULL,
    step character varying(32) NOT NULL,
    status character varying(16) NOT NULL,
    message character varying(512) DEFAULT ''::character varying NOT NULL,
    duration_ms integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: batch_job_trace_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.batch_job_trace_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: batch_job_trace_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.batch_job_trace_events_id_seq OWNED BY public.batch_job_trace_events.id;


--
-- Name: exam_answers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exam_answers (
    id bigint NOT NULL,
    attempt_id bigint NOT NULL,
    exam_paper_question_id bigint NOT NULL,
    question_id integer NOT NULL,
    question_version_id bigint NOT NULL,
    selected_answer character varying(32),
    is_correct boolean,
    score numeric(8,2),
    used_time integer DEFAULT 0 NOT NULL,
    marked_for_review boolean DEFAULT false NOT NULL,
    answered_at timestamp without time zone,
    practice_record_id integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    answer_revision integer DEFAULT 0 NOT NULL,
    CONSTRAINT ck_exam_answers_score_nonnegative CHECK (((score IS NULL) OR (score >= (0)::numeric))),
    CONSTRAINT ck_exam_answers_used_time_nonnegative CHECK ((used_time >= 0))
);


--
-- Name: exam_answers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.exam_answers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: exam_answers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.exam_answers_id_seq OWNED BY public.exam_answers.id;


--
-- Name: exam_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exam_attempts (
    id bigint NOT NULL,
    paper_id integer NOT NULL,
    paper_version integer NOT NULL,
    user_id integer NOT NULL,
    status character varying(16) DEFAULT 'in_progress'::character varying NOT NULL,
    request_id character varying(128) NOT NULL,
    started_at timestamp without time zone DEFAULT now() NOT NULL,
    submitted_at timestamp without time zone,
    duration_sec integer DEFAULT 0 NOT NULL,
    answered_count integer DEFAULT 0 NOT NULL,
    correct_count integer DEFAULT 0 NOT NULL,
    score numeric(8,2) DEFAULT '0'::numeric NOT NULL,
    result_snapshot json,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_exam_attempts_answered_nonnegative CHECK ((answered_count >= 0)),
    CONSTRAINT ck_exam_attempts_correct_nonnegative CHECK ((correct_count >= 0)),
    CONSTRAINT ck_exam_attempts_duration_nonnegative CHECK ((duration_sec >= 0)),
    CONSTRAINT ck_exam_attempts_paper_version_positive CHECK ((paper_version >= 1)),
    CONSTRAINT ck_exam_attempts_score_nonnegative CHECK ((score >= (0)::numeric)),
    CONSTRAINT ck_exam_attempts_status CHECK (((status)::text = ANY ((ARRAY['in_progress'::character varying, 'submitted'::character varying, 'expired'::character varying, 'abandoned'::character varying])::text[])))
);


--
-- Name: exam_attempts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.exam_attempts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: exam_attempts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.exam_attempts_id_seq OWNED BY public.exam_attempts.id;


--
-- Name: exam_paper_questions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exam_paper_questions (
    id bigint NOT NULL,
    paper_id integer NOT NULL,
    question_id integer NOT NULL,
    question_version_id bigint NOT NULL,
    "position" integer NOT NULL,
    score numeric(8,2) NOT NULL,
    section_subject_id integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_exam_paper_questions_position_positive CHECK (("position" > 0)),
    CONSTRAINT ck_exam_paper_questions_score_positive CHECK ((score > (0)::numeric))
);


--
-- Name: exam_paper_questions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.exam_paper_questions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: exam_paper_questions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.exam_paper_questions_id_seq OWNED BY public.exam_paper_questions.id;


--
-- Name: exam_papers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exam_papers (
    id integer NOT NULL,
    title character varying(128) NOT NULL,
    paper_type character varying(32) NOT NULL,
    year smallint,
    source character varying(128),
    duration_sec integer,
    version integer DEFAULT 1 NOT NULL,
    status character varying(16) DEFAULT 'draft'::character varying NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    published_at timestamp without time zone,
    created_by integer,
    updated_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    public_id character varying(32) NOT NULL,
    deleted_at timestamp without time zone,
    CONSTRAINT ck_exam_papers_duration_positive CHECK (((duration_sec IS NULL) OR (duration_sec > 0))),
    CONSTRAINT ck_exam_papers_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'published'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_exam_papers_type CHECK (((paper_type)::text = ANY ((ARRAY['past_exam_choice'::character varying, 'mock_choice'::character varying])::text[]))),
    CONSTRAINT ck_exam_papers_version_positive CHECK ((version >= 1))
);


--
-- Name: exam_papers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.exam_papers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: exam_papers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.exam_papers_id_seq OWNED BY public.exam_papers.id;


--
-- Name: export_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.export_snapshots (
    id character varying(36) NOT NULL,
    user_id integer NOT NULL,
    data json NOT NULL,
    data_size_bytes integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: export_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.export_tasks (
    id integer NOT NULL,
    user_id integer NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    file_format character varying(10) DEFAULT 'pdf'::character varying NOT NULL,
    range_type character varying(20) NOT NULL,
    filters json,
    selected_ids json,
    title character varying(255) NOT NULL,
    show_date boolean DEFAULT true NOT NULL,
    export_date character varying(32) NOT NULL,
    sort_by character varying(32) DEFAULT 'newest'::character varying NOT NULL,
    group_by character varying(32) DEFAULT 'none'::character varying NOT NULL,
    answer_position character varying(16) DEFAULT 'none'::character varying NOT NULL,
    analysis_position character varying(16) DEFAULT 'none'::character varying NOT NULL,
    space_style character varying(16) DEFAULT 'standard'::character varying NOT NULL,
    total_count integer DEFAULT 0 NOT NULL,
    success_count integer,
    skip_count integer,
    skip_reasons json,
    error_message character varying(500),
    file_name character varying(255) NOT NULL,
    file_key character varying(512),
    file_size integer,
    snapshot_id character varying(36),
    source_task_id integer,
    idempotency_key character varying(64),
    retry_count smallint DEFAULT '0'::smallint NOT NULL,
    processing_started_at timestamp without time zone,
    heartbeat_at timestamp without time zone,
    generator_version character varying(16),
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    expires_at timestamp without time zone,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    error_code character varying(32)
);


--
-- Name: export_tasks_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.export_tasks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: export_tasks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.export_tasks_id_seq OWNED BY public.export_tasks.id;


--
-- Name: formula_card_tags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.formula_card_tags (
    id integer NOT NULL,
    formula_card_id integer NOT NULL,
    tag_id integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: formula_card_tags_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.formula_card_tags_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: formula_card_tags_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.formula_card_tags_id_seq OWNED BY public.formula_card_tags.id;


--
-- Name: formula_card_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.formula_card_versions (
    id integer NOT NULL,
    formula_card_id integer NOT NULL,
    version integer NOT NULL,
    snapshot json NOT NULL,
    action character varying(32) NOT NULL,
    edited_by integer,
    edit_reason text,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: formula_card_versions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.formula_card_versions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: formula_card_versions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.formula_card_versions_id_seq OWNED BY public.formula_card_versions.id;


--
-- Name: formula_cards; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.formula_cards (
    id integer NOT NULL,
    exam_scope character varying(32) DEFAULT 'math2'::character varying NOT NULL,
    category_id integer NOT NULL,
    title character varying(256) NOT NULL,
    aliases json,
    search_text character varying(512),
    card_type character varying(32) DEFAULT 'pure_formula'::character varying NOT NULL,
    summary text,
    formula_blocks json NOT NULL,
    conditions text,
    symbol_notes text,
    secondary_conclusions text,
    error_tips text,
    examples json,
    function_properties json,
    sort_order integer DEFAULT 0 NOT NULL,
    status character varying(32) DEFAULT 'draft'::character varying NOT NULL,
    reviewed_by integer,
    reviewed_at timestamp without time zone,
    rejection_reason text,
    published_at timestamp without time zone,
    created_by integer,
    updated_by integer,
    source_type character varying(32),
    source_title character varying(256),
    source_ref character varying(256),
    content_hash character varying(64),
    version integer DEFAULT 1 NOT NULL,
    deleted_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    graph_spec json,
    draft_graph_spec json,
    graph_status character varying(32) DEFAULT 'not_applicable'::character varying NOT NULL,
    graph_last_error text,
    graph_generated_at timestamp without time zone,
    graph_confirmed_at timestamp without time zone,
    study_card_type character varying(32) DEFAULT 'formula'::character varying NOT NULL,
    template_type character varying(24) DEFAULT 'standard'::character varying NOT NULL,
    CONSTRAINT ck_formula_cards_canonical_exam_scope CHECK ((lower((exam_scope)::text) <> ALL (ARRAY['408'::text, 'computer'::text])))
);


--
-- Name: formula_cards_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.formula_cards_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: formula_cards_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.formula_cards_id_seq OWNED BY public.formula_cards.id;


--
-- Name: formula_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.formula_categories (
    id integer NOT NULL,
    parent_id integer,
    exam_scope character varying(32) DEFAULT 'math2'::character varying NOT NULL,
    node_type character varying(16) NOT NULL,
    code character varying(64) NOT NULL,
    name character varying(128) NOT NULL,
    description text,
    sort_order integer DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_formula_categories_canonical_exam_scope CHECK ((lower((exam_scope)::text) <> ALL (ARRAY['408'::text, 'computer'::text])))
);


--
-- Name: formula_categories_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.formula_categories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: formula_categories_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.formula_categories_id_seq OWNED BY public.formula_categories.id;


--
-- Name: formula_graph_assets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.formula_graph_assets (
    id integer NOT NULL,
    formula_card_id integer NOT NULL,
    source_type character varying(32) NOT NULL,
    template_type character varying(64),
    template_parameters json,
    viewport json,
    image_url character varying(512),
    thumbnail_url character varying(512),
    original_svg_url character varying(512),
    mime_type character varying(64),
    width integer,
    height integer,
    checksum character varying(64),
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    file_size integer,
    renderer_version integer,
    alt_text character varying(512),
    description text,
    reviewed_by integer,
    reviewed_at timestamp without time zone,
    review_note character varying(256),
    published_version integer
);


--
-- Name: formula_graph_assets_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.formula_graph_assets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: formula_graph_assets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.formula_graph_assets_id_seq OWNED BY public.formula_graph_assets.id;


--
-- Name: formula_graph_previews; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.formula_graph_previews (
    id integer NOT NULL,
    formula_card_id integer NOT NULL,
    preview_token character varying(64) NOT NULL,
    checksum character varying(64) NOT NULL,
    preview_url character varying(512),
    thumbnail_url character varying(512),
    width integer,
    height integer,
    mime_type character varying(64),
    file_size integer,
    renderer_version integer,
    quality_errors json,
    quality_warnings json,
    expires_at timestamp without time zone NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: formula_graph_previews_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.formula_graph_previews_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: formula_graph_previews_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.formula_graph_previews_id_seq OWNED BY public.formula_graph_previews.id;


--
-- Name: formula_graph_specs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.formula_graph_specs (
    id integer NOT NULL,
    formula_card_id integer NOT NULL,
    slug character varying(64) NOT NULL,
    source_ref character varying(256) NOT NULL,
    title character varying(256) NOT NULL,
    description text,
    alt_text character varying(512),
    spec_json json NOT NULL,
    spec_hash character varying(64) NOT NULL,
    schema_version integer DEFAULT 1 NOT NULL,
    renderer_version integer DEFAULT 1 NOT NULL,
    status character varying(32) DEFAULT 'draft'::character varying NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    confirmed_asset_id integer,
    reviewed_by integer,
    reviewed_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: formula_graph_specs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.formula_graph_specs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: formula_graph_specs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.formula_graph_specs_id_seq OWNED BY public.formula_graph_specs.id;


--
-- Name: formula_import_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.formula_import_items (
    id integer NOT NULL,
    job_id integer NOT NULL,
    source_locator character varying(256),
    raw_text text,
    raw_image_url character varying(512),
    generated_content json,
    card_type character varying(32),
    confidence double precision,
    risk_flags json,
    latex_valid boolean,
    latex_errors json,
    scope_check json,
    duplicate_check json,
    review_status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    reviewed_by integer,
    reviewed_at timestamp without time zone,
    rejection_reason text,
    result_card_id integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: formula_import_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.formula_import_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: formula_import_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.formula_import_items_id_seq OWNED BY public.formula_import_items.id;


--
-- Name: formula_import_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.formula_import_jobs (
    id integer NOT NULL,
    source_type character varying(32) NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    progress double precision DEFAULT '0'::double precision NOT NULL,
    stage character varying(64),
    error_message text,
    source_filename character varying(256),
    total_items integer DEFAULT 0 NOT NULL,
    processed_items integer DEFAULT 0 NOT NULL,
    failed_items integer DEFAULT 0 NOT NULL,
    retry_of integer,
    metadata_json json,
    created_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    execution_generation integer DEFAULT 0 NOT NULL,
    current_task_id character varying(64),
    current_owner_token character varying(64),
    execution_status character varying(16)
);


--
-- Name: formula_import_jobs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.formula_import_jobs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: formula_import_jobs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.formula_import_jobs_id_seq OWNED BY public.formula_import_jobs.id;


--
-- Name: formula_tags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.formula_tags (
    id integer NOT NULL,
    code character varying(32) NOT NULL,
    name character varying(32) NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: formula_tags_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.formula_tags_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: formula_tags_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.formula_tags_id_seq OWNED BY public.formula_tags.id;


--
-- Name: import_batch_job_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.import_batch_job_items (
    id integer NOT NULL,
    job_id character varying(64) NOT NULL,
    seq integer NOT NULL,
    source_file character varying(256),
    status character varying(16) DEFAULT 'pending'::character varying NOT NULL,
    ocr_raw_text text,
    ocr_cleaned_text text,
    review_batch_id character varying(64),
    pipeline_id character varying(64),
    question_count integer DEFAULT 0 NOT NULL,
    error_message text,
    started_at timestamp without time zone,
    finished_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    batch_import_id character varying(64),
    image_import_id character varying(64),
    request_id character varying(64),
    source_sha256 character varying(64),
    previous_review_batch_id character varying(64),
    reparse_attempt integer DEFAULT 0 NOT NULL,
    reparse_started_at timestamp without time zone,
    reparse_finished_at timestamp without time zone,
    reparse_config_hash character varying(64)
);


--
-- Name: import_batch_job_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.import_batch_job_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: import_batch_job_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.import_batch_job_items_id_seq OWNED BY public.import_batch_job_items.id;


--
-- Name: import_batch_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.import_batch_jobs (
    job_id character varying(64) NOT NULL,
    source_type character varying(16) DEFAULT 'image'::character varying NOT NULL,
    total integer DEFAULT 0 NOT NULL,
    concurrency integer DEFAULT 2 NOT NULL,
    status character varying(16) DEFAULT 'queued'::character varying NOT NULL,
    created_by character varying(64),
    error_message text,
    started_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    finished_at timestamp without time zone,
    next_event_seq integer DEFAULT 1 NOT NULL,
    merge_status character varying(16),
    merged_batch_id character varying(64),
    merge_error text,
    merge_started_at timestamp without time zone,
    merge_finished_at timestamp without time zone,
    queued_at timestamp without time zone,
    request_id character varying(64),
    subject_id integer,
    execution_generation integer DEFAULT 0 NOT NULL,
    current_task_id character varying(64),
    current_owner_token character varying(64),
    execution_status character varying(16)
);


--
-- Name: import_pipeline_chunks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.import_pipeline_chunks (
    id integer NOT NULL,
    pipeline_id character varying(64) NOT NULL,
    chunk_index integer NOT NULL,
    page_start integer NOT NULL,
    page_end integer NOT NULL,
    status character varying(16) DEFAULT 'pending'::character varying NOT NULL,
    batch_id character varying(64),
    question_count integer DEFAULT 0 NOT NULL,
    error_message text,
    started_at timestamp without time zone,
    finished_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: import_pipeline_chunks_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.import_pipeline_chunks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: import_pipeline_chunks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.import_pipeline_chunks_id_seq OWNED BY public.import_pipeline_chunks.id;


--
-- Name: import_pipelines; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.import_pipelines (
    pipeline_id character varying(64) NOT NULL,
    source_type character varying(16) NOT NULL,
    source_file character varying(256),
    total_pages integer,
    chunk_size integer DEFAULT 40 NOT NULL,
    status character varying(16) DEFAULT 'running'::character varying NOT NULL,
    error_message text,
    started_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    finished_at timestamp without time zone,
    created_by character varying(64),
    source_sha256 character varying(64),
    watermark_snapshot json,
    quality_report json,
    alerts json,
    execution_generation integer DEFAULT 0 NOT NULL,
    current_task_id character varying(64),
    current_owner_token character varying(64),
    execution_status character varying(16)
);


--
-- Name: knowledge_edges; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_edges (
    id integer NOT NULL,
    source_knowledge_point_id integer NOT NULL,
    target_knowledge_point_id integer NOT NULL,
    relation_type character varying(16) NOT NULL,
    weight double precision DEFAULT 1.0 NOT NULL,
    confidence double precision DEFAULT 1.0 NOT NULL,
    source character varying(16) DEFAULT 'manual'::character varying NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    subject_id integer NOT NULL
);


--
-- Name: knowledge_edges_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.knowledge_edges_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: knowledge_edges_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.knowledge_edges_id_seq OWNED BY public.knowledge_edges.id;


--
-- Name: knowledge_points; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_points (
    id integer NOT NULL,
    name character varying(128) NOT NULL,
    normalized_name character varying(128) NOT NULL,
    aliases json,
    description text,
    difficulty_level smallint DEFAULT 3 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    subject_id integer NOT NULL
);


--
-- Name: knowledge_points_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.knowledge_points_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: knowledge_points_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.knowledge_points_id_seq OWNED BY public.knowledge_points.id;


--
-- Name: ocr_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ocr_jobs (
    id character varying(64) NOT NULL,
    request_id character varying(64) NOT NULL,
    document_id character varying(64) NOT NULL,
    document_sha256 character varying(64) NOT NULL,
    status character varying(16) NOT NULL,
    priority integer NOT NULL,
    input_artifact_key character varying(256) NOT NULL,
    input_mime_type character varying(64) NOT NULL,
    input_size_bytes integer NOT NULL,
    input_page_count integer,
    output_artifact_key character varying(256),
    output_sha256 character varying(64),
    lease_owner character varying(64),
    lease_token_hash character varying(64),
    lease_expires_at timestamp without time zone,
    heartbeat_at timestamp without time zone,
    attempt_count integer NOT NULL,
    max_attempts integer NOT NULL,
    next_retry_at timestamp without time zone,
    last_error_code character varying(32),
    last_error_message text,
    pipeline_fingerprint character varying(64) NOT NULL,
    required_document_ir_schema character varying(16) NOT NULL,
    worker_fingerprint character varying(64),
    model_fingerprint character varying(64),
    complete_idempotency_key character varying(64),
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    started_at timestamp without time zone,
    completed_at timestamp without time zone
);


--
-- Name: permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.permissions (
    id integer NOT NULL,
    name character varying(128) NOT NULL,
    resource character varying(64) NOT NULL,
    action character varying(64) NOT NULL,
    category character varying(32) NOT NULL,
    description character varying(256),
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.permissions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: permissions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.permissions_id_seq OWNED BY public.permissions.id;


--
-- Name: pomodoro_pause_intervals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pomodoro_pause_intervals (
    id integer NOT NULL,
    session_id integer NOT NULL,
    started_at timestamp without time zone NOT NULL,
    ended_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_pomodoro_pause_intervals_ended_at CHECK (((ended_at IS NULL) OR (ended_at > started_at)))
);


--
-- Name: pomodoro_pause_intervals_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pomodoro_pause_intervals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pomodoro_pause_intervals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pomodoro_pause_intervals_id_seq OWNED BY public.pomodoro_pause_intervals.id;


--
-- Name: pomodoro_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pomodoro_sessions (
    id integer NOT NULL,
    user_id integer NOT NULL,
    chapter_id character varying(64),
    preset character varying(16) DEFAULT 'standard'::character varying NOT NULL,
    work_duration integer DEFAULT 25 NOT NULL,
    break_duration integer DEFAULT 5 NOT NULL,
    start_time timestamp without time zone NOT NULL,
    end_time timestamp without time zone,
    actual_duration integer,
    status character varying(16) DEFAULT 'running'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    expected_end_time timestamp without time zone,
    notification_enabled boolean DEFAULT false NOT NULL,
    notification_sent boolean DEFAULT false NOT NULL,
    notification_sent_at timestamp without time zone,
    notification_error text,
    openid_snapshot character varying(64),
    paused_at timestamp without time zone,
    subject_id integer,
    total_paused_sec integer NOT NULL,
    client_start_id character varying(64),
    CONSTRAINT ck_pomodoro_sessions_completed_duration CHECK ((((status)::text <> 'completed'::text) OR ((end_time >= start_time) AND (actual_duration >= 0))))
);


--
-- Name: pomodoro_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pomodoro_sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pomodoro_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pomodoro_sessions_id_seq OWNED BY public.pomodoro_sessions.id;


--
-- Name: pomodoro_subject_allocations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pomodoro_subject_allocations (
    id integer NOT NULL,
    session_id integer NOT NULL,
    subject_id integer,
    weight_basis_points integer NOT NULL,
    subject_code_snapshot character varying(32) NOT NULL,
    subject_name_snapshot character varying(64) NOT NULL,
    CONSTRAINT ck_pomodoro_allocation_code_present CHECK (((subject_code_snapshot)::text <> ''::text)),
    CONSTRAINT ck_pomodoro_allocation_name_present CHECK (((subject_name_snapshot)::text <> ''::text)),
    CONSTRAINT ck_pomodoro_allocation_weight_positive CHECK ((weight_basis_points > 0))
);


--
-- Name: pomodoro_subject_allocations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pomodoro_subject_allocations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pomodoro_subject_allocations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pomodoro_subject_allocations_id_seq OWNED BY public.pomodoro_subject_allocations.id;


--
-- Name: practice_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.practice_records (
    id integer NOT NULL,
    user_id integer NOT NULL,
    question_id integer NOT NULL,
    question_type character varying(32) DEFAULT 'single_choice'::character varying NOT NULL,
    user_answer text NOT NULL,
    is_correct boolean NOT NULL,
    used_time integer,
    answered_at timestamp without time zone DEFAULT now() NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    mode character varying(16),
    subject_id integer NOT NULL,
    question_version_id bigint NOT NULL,
    projection_state character varying(20) NOT NULL,
    CONSTRAINT ck_practice_records_projection_state CHECK (((projection_state)::text = ANY ((ARRAY['pending'::character varying, 'completed'::character varying, 'revision_only'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_practice_records_question_type CHECK (((question_type)::text = ANY ((ARRAY['single_choice'::character varying, 'multiple_choice'::character varying, 'true_false'::character varying, 'fill_blank'::character varying, 'multi_blank_choice'::character varying, 'multi_blank_multiple_choice'::character varying, 'subjective'::character varying])::text[])))
);


--
-- Name: practice_records_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.practice_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: practice_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.practice_records_id_seq OWNED BY public.practice_records.id;


--
-- Name: practice_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.practice_sessions (
    id integer NOT NULL,
    user_id integer NOT NULL,
    subject_id integer NOT NULL,
    request_id character varying(128) NOT NULL,
    mode character varying(16) DEFAULT 'random'::character varying NOT NULL,
    started_at timestamp without time zone NOT NULL,
    finished_at timestamp without time zone NOT NULL,
    duration_sec integer NOT NULL,
    question_count integer DEFAULT 0 NOT NULL,
    answered_count integer DEFAULT 0 NOT NULL,
    correct_count integer DEFAULT 0 NOT NULL,
    wrong_count integer DEFAULT 0 NOT NULL,
    status character varying(16) DEFAULT 'completed'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    submission_payload_hash character varying(64),
    submission_response json,
    scope_type character varying(32),
    scope_root_knowledge_point_id integer,
    scope_snapshot json,
    CONSTRAINT ck_practice_sessions_duration_sec CHECK ((duration_sec >= 0)),
    CONSTRAINT ck_practice_sessions_finished_at CHECK ((finished_at >= started_at))
);


--
-- Name: practice_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.practice_sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: practice_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.practice_sessions_id_seq OWNED BY public.practice_sessions.id;


--
-- Name: question_embeddings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.question_embeddings (
    id bigint NOT NULL,
    question_id integer NOT NULL,
    question_type character varying(32) NOT NULL,
    embedding_dim integer NOT NULL,
    content_hash character varying(64) NOT NULL,
    content_text text NOT NULL,
    embedding public.vector(1024) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    embedded_at timestamp without time zone DEFAULT now() NOT NULL,
    subject_id integer NOT NULL,
    model_id integer NOT NULL
);


--
-- Name: question_embeddings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.question_embeddings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: question_embeddings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.question_embeddings_id_seq OWNED BY public.question_embeddings.id;


--
-- Name: question_imports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.question_imports (
    id integer NOT NULL,
    batch_id character varying(64) NOT NULL,
    source_type character varying(16) NOT NULL,
    source_file character varying(256),
    question_type character varying(32),
    raw_data json NOT NULL,
    parsed_content json,
    parsed_options json,
    parsed_answer text,
    parsed_analysis text,
    status character varying(16) NOT NULL,
    review_note text,
    question_id bigint,
    ai_generated boolean NOT NULL,
    ai_source character varying(32),
    ai_confidence double precision,
    ai_metadata json,
    ai_raw_response text,
    ai_reviewed_at timestamp without time zone,
    ai_answer_flag boolean NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    math_regions json,
    question_hash character varying(32),
    duplicate_status character varying(32) DEFAULT 'normal'::character varying NOT NULL,
    duplicate_of_question_id bigint,
    duplicate_of_import_id bigint,
    reject_reason text,
    reviewed_by integer,
    reviewed_at timestamp without time zone,
    superseded_by_batch_id character varying(64),
    superseded_at timestamp without time zone,
    subject_id integer,
    source_question_no character varying(32),
    source_question_label character varying(32),
    source_image_seq integer,
    source_image_name character varying(256),
    source_page_start integer,
    source_page_end integer,
    source_order_index integer,
    raw_text_preview text,
    answer_status character varying(24),
    answer_source character varying(16),
    answer_confidence double precision,
    review_priority integer,
    CONSTRAINT ck_question_imports_question_type CHECK (((question_type IS NULL) OR ((question_type)::text = ANY ((ARRAY['single_choice'::character varying, 'multiple_choice'::character varying, 'true_false'::character varying, 'fill_blank'::character varying, 'multi_blank_choice'::character varying, 'multi_blank_multiple_choice'::character varying, 'subjective'::character varying])::text[]))))
);


--
-- Name: question_imports_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.question_imports_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: question_imports_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.question_imports_id_seq OWNED BY public.question_imports.id;


--
-- Name: question_knowledge_points; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.question_knowledge_points (
    id integer NOT NULL,
    question_id integer NOT NULL,
    knowledge_point_id integer NOT NULL,
    role character varying(16) DEFAULT 'main'::character varying NOT NULL,
    weight double precision DEFAULT 1.0 NOT NULL,
    source character varying(16) DEFAULT 'imported'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    "position" integer DEFAULT 0 NOT NULL
);


--
-- Name: question_knowledge_points_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.question_knowledge_points_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: question_knowledge_points_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.question_knowledge_points_id_seq OWNED BY public.question_knowledge_points.id;


--
-- Name: question_version_knowledge_points; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.question_version_knowledge_points (
    id bigint NOT NULL,
    question_version_id bigint NOT NULL,
    knowledge_point_id integer NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    role character varying(16) NOT NULL,
    weight double precision NOT NULL,
    source character varying(16) NOT NULL,
    syllabus_knowledge_point_id bigint
);


--
-- Name: question_version_knowledge_points_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.question_version_knowledge_points_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: question_version_knowledge_points_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.question_version_knowledge_points_id_seq OWNED BY public.question_version_knowledge_points.id;


--
-- Name: question_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.question_versions (
    id bigint NOT NULL,
    question_id integer NOT NULL,
    version integer NOT NULL,
    content json NOT NULL,
    options json,
    answer text NOT NULL,
    analysis text,
    difficulty smallint NOT NULL,
    edited_by integer,
    edit_reason text,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    subject_id integer,
    question_type character varying(32),
    image_url json,
    is_active boolean,
    change_source character varying(32) NOT NULL,
    state_hash character varying(64),
    source character varying(64),
    source_type character varying(16),
    source_file character varying(256),
    raw_content text,
    year smallint
);


--
-- Name: question_versions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.question_versions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: question_versions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.question_versions_id_seq OWNED BY public.question_versions.id;


--
-- Name: questions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.questions (
    id integer NOT NULL,
    question_type character varying(32) NOT NULL,
    content json NOT NULL,
    options json,
    answer text NOT NULL,
    analysis text,
    difficulty smallint NOT NULL,
    source character varying(64),
    source_type character varying(16),
    source_file character varying(256),
    import_batch_id character varying(64),
    raw_content text,
    image_url json,
    year smallint,
    review_status character varying(16) NOT NULL,
    is_active boolean NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    question_hash character varying(32),
    sync_uuid character varying(36),
    sync_version integer DEFAULT 0 NOT NULL,
    subject_id integer NOT NULL,
    current_version_id bigint,
    CONSTRAINT ck_questions_question_type CHECK (((question_type)::text = ANY ((ARRAY['single_choice'::character varying, 'multiple_choice'::character varying, 'true_false'::character varying, 'fill_blank'::character varying, 'multi_blank_choice'::character varying, 'multi_blank_multiple_choice'::character varying, 'subjective'::character varying])::text[])))
);


--
-- Name: questions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.questions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: questions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.questions_id_seq OWNED BY public.questions.id;


--
-- Name: recommendation_experiment_assignments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recommendation_experiment_assignments (
    id integer NOT NULL,
    experiment_id integer NOT NULL,
    user_id integer NOT NULL,
    variant_key character varying(16) NOT NULL,
    strategy character varying(32) NOT NULL,
    assigned_at timestamp without time zone DEFAULT now() NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: recommendation_experiment_assignments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.recommendation_experiment_assignments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: recommendation_experiment_assignments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.recommendation_experiment_assignments_id_seq OWNED BY public.recommendation_experiment_assignments.id;


--
-- Name: recommendation_experiments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recommendation_experiments (
    id integer NOT NULL,
    name character varying(128) NOT NULL,
    scene character varying(32) NOT NULL,
    description character varying(512),
    status character varying(16) DEFAULT 'draft'::character varying NOT NULL,
    start_at timestamp without time zone,
    end_at timestamp without time zone,
    traffic_ratio double precision DEFAULT 1.0 NOT NULL,
    variants json,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    max_traffic_percent double precision DEFAULT 100.0 NOT NULL,
    fallback_strategy_name character varying(64),
    auto_pause_on_error_rate double precision,
    min_sample_size integer DEFAULT 100 NOT NULL,
    started_at timestamp without time zone,
    ended_at timestamp without time zone
);


--
-- Name: recommendation_experiments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.recommendation_experiments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: recommendation_experiments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.recommendation_experiments_id_seq OWNED BY public.recommendation_experiments.id;


--
-- Name: recommendation_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recommendation_logs (
    id integer NOT NULL,
    user_id integer NOT NULL,
    question_id integer NOT NULL,
    scene character varying(32) NOT NULL,
    strategy character varying(32) NOT NULL,
    source_question_id integer,
    recommend_score double precision,
    similarity double precision,
    reason character varying(256),
    request_id character varying(64),
    experiment_id integer,
    variant_key character varying(16),
    strategy_config_id integer,
    mastery_before double precision,
    mastery_after double precision,
    mastery_delta double precision,
    shown_at timestamp without time zone DEFAULT now() NOT NULL,
    clicked_at timestamp without time zone,
    answered_at timestamp without time zone,
    is_correct boolean,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    subject_id integer NOT NULL
);


--
-- Name: recommendation_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.recommendation_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: recommendation_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.recommendation_logs_id_seq OWNED BY public.recommendation_logs.id;


--
-- Name: recommendation_metrics_daily; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recommendation_metrics_daily (
    id integer NOT NULL,
    date date NOT NULL,
    scene character varying(32) NOT NULL,
    strategy character varying(32) NOT NULL,
    variant_key character varying(16),
    exposure_count integer DEFAULT 0 NOT NULL,
    click_count integer DEFAULT 0 NOT NULL,
    answer_count integer DEFAULT 0 NOT NULL,
    correct_count integer DEFAULT 0 NOT NULL,
    wrong_count integer DEFAULT 0 NOT NULL,
    avg_recommend_score double precision DEFAULT 0 NOT NULL,
    avg_similarity double precision DEFAULT 0 NOT NULL,
    avg_mastery_before double precision,
    avg_mastery_after double precision,
    avg_mastery_delta double precision,
    completion_rate double precision DEFAULT 0 NOT NULL,
    accuracy double precision DEFAULT 0 NOT NULL,
    ctr double precision DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    subject_id integer NOT NULL
);


--
-- Name: recommendation_metrics_daily_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.recommendation_metrics_daily_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: recommendation_metrics_daily_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.recommendation_metrics_daily_id_seq OWNED BY public.recommendation_metrics_daily.id;


--
-- Name: recommendation_strategy_configs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recommendation_strategy_configs (
    id integer NOT NULL,
    name character varying(64) NOT NULL,
    display_name character varying(128) DEFAULT ''::character varying NOT NULL,
    description character varying(512),
    scene character varying(32) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    weight_vector_similarity double precision DEFAULT 0.5 NOT NULL,
    weight_knowledge_overlap double precision DEFAULT 0.2 NOT NULL,
    weight_difficulty_match double precision DEFAULT 0.1 NOT NULL,
    weight_mastery_gap double precision DEFAULT 0.1 NOT NULL,
    weight_path_priority double precision DEFAULT 0.1 NOT NULL,
    exploration_ratio double precision DEFAULT 0.1 NOT NULL,
    config_json json,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: recommendation_strategy_configs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.recommendation_strategy_configs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: recommendation_strategy_configs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.recommendation_strategy_configs_id_seq OWNED BY public.recommendation_strategy_configs.id;


--
-- Name: refresh_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.refresh_tokens (
    id integer NOT NULL,
    user_id integer NOT NULL,
    token_hash character varying(64) NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    revoked_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: refresh_tokens_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.refresh_tokens_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: refresh_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.refresh_tokens_id_seq OWNED BY public.refresh_tokens.id;


--
-- Name: review_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.review_records (
    id integer NOT NULL,
    user_id integer NOT NULL,
    question_id integer NOT NULL,
    schedule_id integer,
    rating integer NOT NULL,
    interval_before integer,
    interval_after integer,
    ease_factor_before double precision,
    ease_factor_after double precision,
    reviewed_at timestamp without time zone DEFAULT now() NOT NULL,
    question_version_id bigint NOT NULL,
    request_id character varying(128) NOT NULL,
    occurrence_seq integer NOT NULL,
    user_answer text,
    is_correct boolean,
    next_review_at timestamp without time zone,
    mastery_percent integer,
    mastered boolean,
    CONSTRAINT ck_review_records_mastery_percent_range CHECK (((mastery_percent IS NULL) OR ((mastery_percent >= 0) AND (mastery_percent <= 100)))),
    CONSTRAINT ck_review_records_occurrence_nonnegative CHECK ((occurrence_seq >= 0)),
    CONSTRAINT ck_review_records_rating_range CHECK (((rating >= 0) AND (rating <= 5)))
);


--
-- Name: review_records_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.review_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: review_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.review_records_id_seq OWNED BY public.review_records.id;


--
-- Name: review_schedules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.review_schedules (
    id integer NOT NULL,
    user_id integer NOT NULL,
    question_id integer NOT NULL,
    "interval" integer NOT NULL,
    ease_factor double precision NOT NULL,
    repetitions integer NOT NULL,
    next_review_at timestamp without time zone,
    last_reviewed_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    mastered boolean DEFAULT false NOT NULL,
    subject_id integer,
    question_version_id bigint NOT NULL,
    is_active boolean NOT NULL,
    occurrence_seq integer NOT NULL,
    CONSTRAINT ck_review_schedules_interval_nonnegative CHECK (("interval" >= 0)),
    CONSTRAINT ck_review_schedules_occurrence_nonnegative CHECK ((occurrence_seq >= 0)),
    CONSTRAINT ck_review_schedules_repetitions_nonnegative CHECK ((repetitions >= 0))
);


--
-- Name: review_schedules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.review_schedules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: review_schedules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.review_schedules_id_seq OWNED BY public.review_schedules.id;


--
-- Name: review_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.review_sessions (
    id integer NOT NULL,
    user_id integer NOT NULL,
    subject_id integer,
    request_id character varying(160) NOT NULL,
    started_at timestamp without time zone NOT NULL,
    finished_at timestamp without time zone NOT NULL,
    duration_sec integer NOT NULL,
    question_count integer DEFAULT 0 NOT NULL,
    correct_count integer DEFAULT 0 NOT NULL,
    wrong_count integer DEFAULT 0 NOT NULL,
    status character varying(16) DEFAULT 'completed'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_review_sessions_duration_sec CHECK ((duration_sec >= 0)),
    CONSTRAINT ck_review_sessions_finished_at CHECK ((finished_at >= started_at))
);


--
-- Name: review_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.review_sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: review_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.review_sessions_id_seq OWNED BY public.review_sessions.id;


--
-- Name: role_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role_permissions (
    role_id integer NOT NULL,
    permission_id integer NOT NULL,
    granted_at timestamp without time zone DEFAULT now() NOT NULL,
    granted_by integer
);


--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roles (
    id integer NOT NULL,
    name character varying(64) NOT NULL,
    display_name character varying(64) NOT NULL,
    description text,
    is_system boolean NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: roles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.roles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: roles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.roles_id_seq OWNED BY public.roles.id;


--
-- Name: sequential_reservations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sequential_reservations (
    id integer NOT NULL,
    user_id integer NOT NULL,
    subject_id integer NOT NULL,
    question_id integer NOT NULL,
    scope_key character varying(64) NOT NULL,
    start_request_id character varying(128) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    expires_at timestamp without time zone NOT NULL
);


--
-- Name: sequential_reservations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sequential_reservations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sequential_reservations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sequential_reservations_id_seq OWNED BY public.sequential_reservations.id;


--
-- Name: study_plan_days; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.study_plan_days (
    id integer NOT NULL,
    plan_id integer NOT NULL,
    plan_revision integer NOT NULL,
    plan_date date NOT NULL,
    target_minutes integer NOT NULL,
    is_rest_day boolean DEFAULT false NOT NULL,
    allocation_json json NOT NULL,
    basis_json json NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_study_plan_days_revision_positive CHECK ((plan_revision >= 1)),
    CONSTRAINT ck_study_plan_days_target_nonnegative CHECK ((target_minutes >= 0))
);


--
-- Name: study_plan_days_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.study_plan_days_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: study_plan_days_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.study_plan_days_id_seq OWNED BY public.study_plan_days.id;


--
-- Name: study_plans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.study_plans (
    id integer NOT NULL,
    user_id integer NOT NULL,
    target_date date NOT NULL,
    daily_minutes integer DEFAULT 90 NOT NULL,
    weekly_days integer DEFAULT 6 NOT NULL,
    priority_mode character varying(16) DEFAULT 'balanced'::character varying NOT NULL,
    revision integer DEFAULT 1 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_study_plans_daily_minutes CHECK (((daily_minutes >= 15) AND (daily_minutes <= 720))),
    CONSTRAINT ck_study_plans_priority_mode CHECK (((priority_mode)::text = ANY ((ARRAY['balanced'::character varying, 'review'::character varying, 'weakness'::character varying, 'new'::character varying, 'exam'::character varying])::text[]))),
    CONSTRAINT ck_study_plans_revision_positive CHECK ((revision >= 1)),
    CONSTRAINT ck_study_plans_weekly_days CHECK (((weekly_days >= 1) AND (weekly_days <= 7)))
);


--
-- Name: study_plans_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.study_plans_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: study_plans_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.study_plans_id_seq OWNED BY public.study_plans.id;


--
-- Name: subjects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.subjects (
    id integer NOT NULL,
    parent_id integer,
    code character varying(32) NOT NULL,
    name character varying(64) NOT NULL,
    level smallint NOT NULL,
    path character varying(128) NOT NULL,
    sort_order integer NOT NULL,
    is_active boolean NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_subjects_no_legacy_408_code CHECK ((lower((code)::text) <> ALL (ARRAY['408'::text, 'cn'::text, 'co'::text, 'computer'::text, 'computer_science'::text, 'cs'::text, 'ds'::text, 'exam408-cn'::text, 'exam408-co'::text, 'exam408-ds'::text, 'exam408-os'::text, 'os'::text])))
);


--
-- Name: subjects_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.subjects_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: subjects_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.subjects_id_seq OWNED BY public.subjects.id;


--
-- Name: syllabus_knowledge_point_mappings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.syllabus_knowledge_point_mappings (
    id bigint NOT NULL,
    from_syllabus_knowledge_point_id bigint,
    to_syllabus_knowledge_point_id bigint,
    relation_type character varying(16) NOT NULL,
    note character varying(256),
    created_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_syllabus_kp_mapping_endpoint CHECK (((from_syllabus_knowledge_point_id IS NOT NULL) OR (to_syllabus_knowledge_point_id IS NOT NULL))),
    CONSTRAINT ck_syllabus_kp_mapping_type CHECK (((relation_type)::text = ANY (ARRAY[('unchanged'::character varying)::text, ('renamed'::character varying)::text, ('added'::character varying)::text, ('removed'::character varying)::text, ('merged'::character varying)::text, ('split'::character varying)::text, ('replaced'::character varying)::text])))
);


--
-- Name: syllabus_knowledge_point_mappings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.syllabus_knowledge_point_mappings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: syllabus_knowledge_point_mappings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.syllabus_knowledge_point_mappings_id_seq OWNED BY public.syllabus_knowledge_point_mappings.id;


--
-- Name: syllabus_knowledge_points; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.syllabus_knowledge_points (
    id bigint NOT NULL,
    syllabus_version_id integer NOT NULL,
    knowledge_point_id integer NOT NULL,
    subject_id integer NOT NULL,
    name_snapshot character varying(128) NOT NULL,
    normalized_name_snapshot character varying(128) NOT NULL,
    description_snapshot text,
    difficulty_level_snapshot smallint DEFAULT '3'::smallint NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_syllabus_kp_difficulty CHECK (((difficulty_level_snapshot >= 1) AND (difficulty_level_snapshot <= 5)))
);


--
-- Name: syllabus_knowledge_points_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.syllabus_knowledge_points_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: syllabus_knowledge_points_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.syllabus_knowledge_points_id_seq OWNED BY public.syllabus_knowledge_points.id;


--
-- Name: syllabus_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.syllabus_versions (
    id integer NOT NULL,
    code character varying(64) NOT NULL,
    name character varying(128) NOT NULL,
    root_subject_id integer NOT NULL,
    effective_year smallint NOT NULL,
    status character varying(16) DEFAULT 'draft'::character varying NOT NULL,
    description text,
    activated_at timestamp without time zone,
    created_by integer,
    updated_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_syllabus_versions_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'active'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_syllabus_versions_year CHECK (((effective_year >= 2000) AND (effective_year <= 2200)))
);


--
-- Name: syllabus_versions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.syllabus_versions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: syllabus_versions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.syllabus_versions_id_seq OWNED BY public.syllabus_versions.id;


--
-- Name: tags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tags (
    id integer NOT NULL,
    name character varying(64) NOT NULL,
    parent_id integer,
    sort_order integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    sync_uuid character varying(36),
    subject_id integer NOT NULL
);


--
-- Name: tags_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tags_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tags_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tags_id_seq OWNED BY public.tags.id;


--
-- Name: task_outbox; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_outbox (
    id bigint NOT NULL,
    task_id character varying(64) NOT NULL,
    task_type character varying(32) NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    schema_version integer DEFAULT 1 NOT NULL,
    status character varying(16) DEFAULT 'pending'::character varying NOT NULL,
    lease_token character varying(64),
    lease_expires_at timestamp without time zone,
    published_at timestamp without time zone,
    retry_count integer DEFAULT 0 NOT NULL,
    error_message text,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: COLUMN task_outbox.task_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_outbox.task_id IS 'Idempotent task ID (e.g. import:{pipeline_id})';


--
-- Name: COLUMN task_outbox.task_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_outbox.task_type IS 'Queue task type (import_pipeline, image_pipeline, etc.)';


--
-- Name: COLUMN task_outbox.payload; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_outbox.payload IS 'Task payload (will be serialized to Redis task hash)';


--
-- Name: COLUMN task_outbox.schema_version; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_outbox.schema_version IS 'Payload schema version for rolling upgrade compatibility';


--
-- Name: COLUMN task_outbox.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_outbox.status IS 'pending | leased | published | failed | cancelled';


--
-- Name: COLUMN task_outbox.lease_token; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_outbox.lease_token IS 'Dispatcher lease token (for FOR UPDATE SKIP LOCKED tracking)';


--
-- Name: COLUMN task_outbox.lease_expires_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_outbox.lease_expires_at IS 'Lease expiry — auto-resets to pending after timeout';


--
-- Name: COLUMN task_outbox.published_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_outbox.published_at IS 'When the task was enqueued to Redis';


--
-- Name: COLUMN task_outbox.retry_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_outbox.retry_count IS 'Number of publish attempts';


--
-- Name: COLUMN task_outbox.error_message; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_outbox.error_message IS 'Last error message from publish attempt';


--
-- Name: task_outbox_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.task_outbox_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: task_outbox_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.task_outbox_id_seq OWNED BY public.task_outbox.id;


--
-- Name: user_adaptive_profile; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_adaptive_profile (
    id integer NOT NULL,
    user_id integer NOT NULL,
    interval_factor double precision DEFAULT '1'::double precision NOT NULL,
    min_interval_factor double precision DEFAULT '0.6'::double precision NOT NULL,
    max_interval_factor double precision DEFAULT '1.6'::double precision NOT NULL,
    target_recall_rate double precision DEFAULT '0.8'::double precision NOT NULL,
    recent_due_count integer DEFAULT 0 NOT NULL,
    recent_due_correct_count integer DEFAULT 0 NOT NULL,
    last_adjusted_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: user_adaptive_profile_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_adaptive_profile_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_adaptive_profile_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_adaptive_profile_id_seq OWNED BY public.user_adaptive_profile.id;


--
-- Name: user_formula_favorites; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_formula_favorites (
    id integer NOT NULL,
    user_id integer NOT NULL,
    formula_card_id integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: user_formula_favorites_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_formula_favorites_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_formula_favorites_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_formula_favorites_id_seq OWNED BY public.user_formula_favorites.id;


--
-- Name: user_knowledge_adaptive_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_knowledge_adaptive_state (
    id integer NOT NULL,
    user_id integer NOT NULL,
    knowledge_point_id integer NOT NULL,
    interval_factor double precision DEFAULT '1'::double precision NOT NULL,
    due_review_count integer DEFAULT 0 NOT NULL,
    due_review_correct_count integer DEFAULT 0 NOT NULL,
    overdue_wrong_count integer DEFAULT 0 NOT NULL,
    last_adjusted_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: user_knowledge_adaptive_state_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_knowledge_adaptive_state_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_knowledge_adaptive_state_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_knowledge_adaptive_state_id_seq OWNED BY public.user_knowledge_adaptive_state.id;


--
-- Name: user_knowledge_states; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_knowledge_states (
    id integer NOT NULL,
    user_id integer NOT NULL,
    knowledge_point_id integer NOT NULL,
    attempt_count integer DEFAULT 0 NOT NULL,
    correct_count integer DEFAULT 0 NOT NULL,
    wrong_count integer DEFAULT 0 NOT NULL,
    accuracy double precision DEFAULT 0.0 NOT NULL,
    mastery_score double precision DEFAULT 0.0 NOT NULL,
    weakness_level character varying(16) DEFAULT 'unknown'::character varying NOT NULL,
    last_practiced_at timestamp without time zone,
    last_wrong_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    confidence double precision DEFAULT '0'::double precision NOT NULL,
    recent_answer_count integer DEFAULT 0 NOT NULL,
    recent_correct_count integer DEFAULT 0 NOT NULL,
    recent_wrong_count integer DEFAULT 0 NOT NULL,
    last_is_correct boolean,
    last_answer_time_seconds integer,
    subject_id integer NOT NULL
);


--
-- Name: user_knowledge_states_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_knowledge_states_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_knowledge_states_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_knowledge_states_id_seq OWNED BY public.user_knowledge_states.id;


--
-- Name: user_pomodoro_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_pomodoro_settings (
    user_id integer NOT NULL,
    day_start_minute integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: user_question_difficulty_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_question_difficulty_state (
    id integer NOT NULL,
    user_id integer NOT NULL,
    question_id integer NOT NULL,
    personal_difficulty_score double precision DEFAULT '50'::double precision NOT NULL,
    difficulty_label character varying(20) DEFAULT 'normal'::character varying NOT NULL,
    answer_count integer DEFAULT 0 NOT NULL,
    correct_count integer DEFAULT 0 NOT NULL,
    wrong_count integer DEFAULT 0 NOT NULL,
    avg_answer_time_seconds double precision,
    fast_correct_count integer DEFAULT 0 NOT NULL,
    slow_correct_count integer DEFAULT 0 NOT NULL,
    slow_wrong_count integer DEFAULT 0 NOT NULL,
    overdue_wrong_count integer DEFAULT 0 NOT NULL,
    last_updated_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: user_question_difficulty_state_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_question_difficulty_state_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_question_difficulty_state_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_question_difficulty_state_id_seq OWNED BY public.user_question_difficulty_state.id;


--
-- Name: user_question_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_question_state (
    id integer NOT NULL,
    user_id integer NOT NULL,
    question_id integer NOT NULL,
    box_level integer DEFAULT 0 NOT NULL,
    last_answered_at timestamp without time zone,
    next_review_at timestamp without time zone,
    correct_streak integer DEFAULT 0 NOT NULL,
    wrong_streak integer DEFAULT 0 NOT NULL,
    answer_count integer DEFAULT 0 NOT NULL,
    correct_count integer DEFAULT 0 NOT NULL,
    wrong_count integer DEFAULT 0 NOT NULL,
    last_is_correct boolean,
    last_answer_time_seconds integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: user_question_state_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_question_state_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_question_state_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_question_state_id_seq OWNED BY public.user_question_state.id;


--
-- Name: user_recommend_preference; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_recommend_preference (
    id integer NOT NULL,
    user_id integer NOT NULL,
    due_weight double precision DEFAULT '1'::double precision NOT NULL,
    weakness_weight double precision DEFAULT '1'::double precision NOT NULL,
    wrong_weight double precision DEFAULT '1'::double precision NOT NULL,
    new_question_weight double precision DEFAULT '1'::double precision NOT NULL,
    diversity_weight double precision DEFAULT '1'::double precision NOT NULL,
    difficulty_weight double precision DEFAULT '1'::double precision NOT NULL,
    path_weight double precision DEFAULT '1'::double precision NOT NULL,
    last_adjusted_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: user_recommend_preference_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_recommend_preference_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_recommend_preference_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_recommend_preference_id_seq OWNED BY public.user_recommend_preference.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id integer NOT NULL,
    openid character varying(64) NOT NULL,
    nickname character varying(64),
    avatar_url character varying(256),
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    is_banned boolean DEFAULT false NOT NULL,
    banned_reason character varying(256),
    banned_at timestamp without time zone,
    banned_by integer,
    deleted_at timestamp without time zone
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: watermark_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.watermark_rules (
    id integer NOT NULL,
    pattern text NOT NULL,
    rule_type character varying(16) DEFAULT 'regex'::character varying NOT NULL,
    description character varying(128),
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: watermark_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.watermark_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: watermark_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.watermark_rules_id_seq OWNED BY public.watermark_rules.id;


--
-- Name: worker_credentials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.worker_credentials (
    id character varying(64) NOT NULL,
    worker_id character varying(64) NOT NULL,
    key_hash character varying(64) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    rotated_at timestamp without time zone,
    expires_at timestamp without time zone
);


--
-- Name: wrong_question_error_diagnoses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wrong_question_error_diagnoses (
    id bigint NOT NULL,
    user_id integer NOT NULL,
    wrong_question_id integer NOT NULL,
    question_id integer NOT NULL,
    question_version_id bigint NOT NULL,
    practice_record_id integer,
    exam_answer_id bigint,
    source_context character varying(16) NOT NULL,
    user_answer text,
    occurred_at timestamp without time zone NOT NULL,
    taxonomy_version character varying(32) DEFAULT '408-error-v1'::character varying NOT NULL,
    classification_version integer DEFAULT 1 NOT NULL,
    ai_primary_type character varying(32),
    ai_secondary_types json,
    ai_confidence double precision,
    ai_reason text,
    ai_status character varying(16) DEFAULT 'not_requested'::character varying NOT NULL,
    ai_model character varying(128),
    ai_suggested_at timestamp without time zone,
    user_primary_type character varying(32),
    user_secondary_types json,
    user_confirmed_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    is_current boolean DEFAULT true NOT NULL,
    CONSTRAINT ck_wrong_error_diagnoses_ai_confidence CHECK (((ai_confidence IS NULL) OR ((ai_confidence >= (0)::double precision) AND (ai_confidence <= (1)::double precision)))),
    CONSTRAINT ck_wrong_error_diagnoses_ai_status CHECK (((ai_status)::text = ANY ((ARRAY['not_requested'::character varying, 'pending'::character varying, 'suggested'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT ck_wrong_error_diagnoses_classification_version CHECK ((classification_version >= 1)),
    CONSTRAINT ck_wrong_error_diagnoses_source_context CHECK (((source_context)::text = ANY ((ARRAY['practice'::character varying, 'exam'::character varying, 'legacy'::character varying])::text[])))
);


--
-- Name: wrong_question_error_diagnoses_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.wrong_question_error_diagnoses_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: wrong_question_error_diagnoses_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.wrong_question_error_diagnoses_id_seq OWNED BY public.wrong_question_error_diagnoses.id;


--
-- Name: wrong_questions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wrong_questions (
    id integer NOT NULL,
    user_id integer NOT NULL,
    question_id integer NOT NULL,
    wrong_answer text,
    error_type character varying(32) NOT NULL,
    ai_analysis json,
    review_count smallint NOT NULL,
    last_review_at timestamp without time zone,
    mastered boolean NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    mastered_at timestamp without time zone,
    is_active boolean DEFAULT true NOT NULL,
    removed_at timestamp without time zone,
    question_version_id bigint NOT NULL
);


--
-- Name: wrong_questions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.wrong_questions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: wrong_questions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.wrong_questions_id_seq OWNED BY public.wrong_questions.id;


--
-- Name: admin_ai_model_configs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_ai_model_configs ALTER COLUMN id SET DEFAULT nextval('public.admin_ai_model_configs_id_seq'::regclass);


--
-- Name: admin_ai_settings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_ai_settings ALTER COLUMN id SET DEFAULT nextval('public.admin_ai_settings_id_seq'::regclass);


--
-- Name: admin_users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_users ALTER COLUMN id SET DEFAULT nextval('public.admin_users_id_seq'::regclass);


--
-- Name: ai_chats id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_chats ALTER COLUMN id SET DEFAULT nextval('public.ai_chats_id_seq'::regclass);


--
-- Name: ai_feedback_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_feedback_logs ALTER COLUMN id SET DEFAULT nextval('public.ai_feedback_logs_id_seq'::regclass);


--
-- Name: ai_generation_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_generation_logs ALTER COLUMN id SET DEFAULT nextval('public.ai_generation_logs_id_seq'::regclass);


--
-- Name: answer_behaviors id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answer_behaviors ALTER COLUMN id SET DEFAULT nextval('public.answer_behaviors_id_seq'::regclass);


--
-- Name: app_user_admin_bindings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_user_admin_bindings ALTER COLUMN id SET DEFAULT nextval('public.app_user_admin_bindings_id_seq'::regclass);


--
-- Name: audit_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);


--
-- Name: batch_job_trace_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.batch_job_trace_events ALTER COLUMN id SET DEFAULT nextval('public.batch_job_trace_events_id_seq'::regclass);


--
-- Name: exam_answers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_answers ALTER COLUMN id SET DEFAULT nextval('public.exam_answers_id_seq'::regclass);


--
-- Name: exam_attempts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_attempts ALTER COLUMN id SET DEFAULT nextval('public.exam_attempts_id_seq'::regclass);


--
-- Name: exam_paper_questions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_paper_questions ALTER COLUMN id SET DEFAULT nextval('public.exam_paper_questions_id_seq'::regclass);


--
-- Name: exam_papers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_papers ALTER COLUMN id SET DEFAULT nextval('public.exam_papers_id_seq'::regclass);


--
-- Name: export_tasks id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.export_tasks ALTER COLUMN id SET DEFAULT nextval('public.export_tasks_id_seq'::regclass);


--
-- Name: formula_card_tags id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_card_tags ALTER COLUMN id SET DEFAULT nextval('public.formula_card_tags_id_seq'::regclass);


--
-- Name: formula_card_versions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_card_versions ALTER COLUMN id SET DEFAULT nextval('public.formula_card_versions_id_seq'::regclass);


--
-- Name: formula_cards id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_cards ALTER COLUMN id SET DEFAULT nextval('public.formula_cards_id_seq'::regclass);


--
-- Name: formula_categories id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_categories ALTER COLUMN id SET DEFAULT nextval('public.formula_categories_id_seq'::regclass);


--
-- Name: formula_graph_assets id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_graph_assets ALTER COLUMN id SET DEFAULT nextval('public.formula_graph_assets_id_seq'::regclass);


--
-- Name: formula_graph_previews id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_graph_previews ALTER COLUMN id SET DEFAULT nextval('public.formula_graph_previews_id_seq'::regclass);


--
-- Name: formula_graph_specs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_graph_specs ALTER COLUMN id SET DEFAULT nextval('public.formula_graph_specs_id_seq'::regclass);


--
-- Name: formula_import_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_import_items ALTER COLUMN id SET DEFAULT nextval('public.formula_import_items_id_seq'::regclass);


--
-- Name: formula_import_jobs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_import_jobs ALTER COLUMN id SET DEFAULT nextval('public.formula_import_jobs_id_seq'::regclass);


--
-- Name: formula_tags id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_tags ALTER COLUMN id SET DEFAULT nextval('public.formula_tags_id_seq'::regclass);


--
-- Name: import_batch_job_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_batch_job_items ALTER COLUMN id SET DEFAULT nextval('public.import_batch_job_items_id_seq'::regclass);


--
-- Name: import_pipeline_chunks id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_pipeline_chunks ALTER COLUMN id SET DEFAULT nextval('public.import_pipeline_chunks_id_seq'::regclass);


--
-- Name: knowledge_edges id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_edges ALTER COLUMN id SET DEFAULT nextval('public.knowledge_edges_id_seq'::regclass);


--
-- Name: knowledge_points id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_points ALTER COLUMN id SET DEFAULT nextval('public.knowledge_points_id_seq'::regclass);


--
-- Name: permissions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions ALTER COLUMN id SET DEFAULT nextval('public.permissions_id_seq'::regclass);


--
-- Name: pomodoro_pause_intervals id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pomodoro_pause_intervals ALTER COLUMN id SET DEFAULT nextval('public.pomodoro_pause_intervals_id_seq'::regclass);


--
-- Name: pomodoro_sessions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pomodoro_sessions ALTER COLUMN id SET DEFAULT nextval('public.pomodoro_sessions_id_seq'::regclass);


--
-- Name: pomodoro_subject_allocations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pomodoro_subject_allocations ALTER COLUMN id SET DEFAULT nextval('public.pomodoro_subject_allocations_id_seq'::regclass);


--
-- Name: practice_records id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.practice_records ALTER COLUMN id SET DEFAULT nextval('public.practice_records_id_seq'::regclass);


--
-- Name: practice_sessions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.practice_sessions ALTER COLUMN id SET DEFAULT nextval('public.practice_sessions_id_seq'::regclass);


--
-- Name: question_embeddings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_embeddings ALTER COLUMN id SET DEFAULT nextval('public.question_embeddings_id_seq'::regclass);


--
-- Name: question_imports id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_imports ALTER COLUMN id SET DEFAULT nextval('public.question_imports_id_seq'::regclass);


--
-- Name: question_knowledge_points id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_knowledge_points ALTER COLUMN id SET DEFAULT nextval('public.question_knowledge_points_id_seq'::regclass);


--
-- Name: question_version_knowledge_points id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_version_knowledge_points ALTER COLUMN id SET DEFAULT nextval('public.question_version_knowledge_points_id_seq'::regclass);


--
-- Name: question_versions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_versions ALTER COLUMN id SET DEFAULT nextval('public.question_versions_id_seq'::regclass);


--
-- Name: questions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.questions ALTER COLUMN id SET DEFAULT nextval('public.questions_id_seq'::regclass);


--
-- Name: recommendation_experiment_assignments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_experiment_assignments ALTER COLUMN id SET DEFAULT nextval('public.recommendation_experiment_assignments_id_seq'::regclass);


--
-- Name: recommendation_experiments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_experiments ALTER COLUMN id SET DEFAULT nextval('public.recommendation_experiments_id_seq'::regclass);


--
-- Name: recommendation_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_logs ALTER COLUMN id SET DEFAULT nextval('public.recommendation_logs_id_seq'::regclass);


--
-- Name: recommendation_metrics_daily id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_metrics_daily ALTER COLUMN id SET DEFAULT nextval('public.recommendation_metrics_daily_id_seq'::regclass);


--
-- Name: recommendation_strategy_configs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_strategy_configs ALTER COLUMN id SET DEFAULT nextval('public.recommendation_strategy_configs_id_seq'::regclass);


--
-- Name: refresh_tokens id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refresh_tokens ALTER COLUMN id SET DEFAULT nextval('public.refresh_tokens_id_seq'::regclass);


--
-- Name: review_records id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_records ALTER COLUMN id SET DEFAULT nextval('public.review_records_id_seq'::regclass);


--
-- Name: review_schedules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_schedules ALTER COLUMN id SET DEFAULT nextval('public.review_schedules_id_seq'::regclass);


--
-- Name: review_sessions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_sessions ALTER COLUMN id SET DEFAULT nextval('public.review_sessions_id_seq'::regclass);


--
-- Name: roles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles ALTER COLUMN id SET DEFAULT nextval('public.roles_id_seq'::regclass);


--
-- Name: sequential_reservations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sequential_reservations ALTER COLUMN id SET DEFAULT nextval('public.sequential_reservations_id_seq'::regclass);


--
-- Name: study_plan_days id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.study_plan_days ALTER COLUMN id SET DEFAULT nextval('public.study_plan_days_id_seq'::regclass);


--
-- Name: study_plans id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.study_plans ALTER COLUMN id SET DEFAULT nextval('public.study_plans_id_seq'::regclass);


--
-- Name: subjects id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subjects ALTER COLUMN id SET DEFAULT nextval('public.subjects_id_seq'::regclass);


--
-- Name: syllabus_knowledge_point_mappings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.syllabus_knowledge_point_mappings ALTER COLUMN id SET DEFAULT nextval('public.syllabus_knowledge_point_mappings_id_seq'::regclass);


--
-- Name: syllabus_knowledge_points id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.syllabus_knowledge_points ALTER COLUMN id SET DEFAULT nextval('public.syllabus_knowledge_points_id_seq'::regclass);


--
-- Name: syllabus_versions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.syllabus_versions ALTER COLUMN id SET DEFAULT nextval('public.syllabus_versions_id_seq'::regclass);


--
-- Name: tags id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tags ALTER COLUMN id SET DEFAULT nextval('public.tags_id_seq'::regclass);


--
-- Name: task_outbox id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_outbox ALTER COLUMN id SET DEFAULT nextval('public.task_outbox_id_seq'::regclass);


--
-- Name: user_adaptive_profile id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_adaptive_profile ALTER COLUMN id SET DEFAULT nextval('public.user_adaptive_profile_id_seq'::regclass);


--
-- Name: user_formula_favorites id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_formula_favorites ALTER COLUMN id SET DEFAULT nextval('public.user_formula_favorites_id_seq'::regclass);


--
-- Name: user_knowledge_adaptive_state id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_knowledge_adaptive_state ALTER COLUMN id SET DEFAULT nextval('public.user_knowledge_adaptive_state_id_seq'::regclass);


--
-- Name: user_knowledge_states id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_knowledge_states ALTER COLUMN id SET DEFAULT nextval('public.user_knowledge_states_id_seq'::regclass);


--
-- Name: user_question_difficulty_state id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_question_difficulty_state ALTER COLUMN id SET DEFAULT nextval('public.user_question_difficulty_state_id_seq'::regclass);


--
-- Name: user_question_state id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_question_state ALTER COLUMN id SET DEFAULT nextval('public.user_question_state_id_seq'::regclass);


--
-- Name: user_recommend_preference id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_recommend_preference ALTER COLUMN id SET DEFAULT nextval('public.user_recommend_preference_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: watermark_rules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watermark_rules ALTER COLUMN id SET DEFAULT nextval('public.watermark_rules_id_seq'::regclass);


--
-- Name: wrong_question_error_diagnoses id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wrong_question_error_diagnoses ALTER COLUMN id SET DEFAULT nextval('public.wrong_question_error_diagnoses_id_seq'::regclass);


--
-- Name: wrong_questions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wrong_questions ALTER COLUMN id SET DEFAULT nextval('public.wrong_questions_id_seq'::regclass);


--
-- Name: admin_ai_configs admin_ai_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_ai_configs
    ADD CONSTRAINT admin_ai_configs_pkey PRIMARY KEY (config_key);


--
-- Name: admin_ai_model_configs admin_ai_model_configs_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_ai_model_configs
    ADD CONSTRAINT admin_ai_model_configs_name_key UNIQUE (name);


--
-- Name: admin_ai_model_configs admin_ai_model_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_ai_model_configs
    ADD CONSTRAINT admin_ai_model_configs_pkey PRIMARY KEY (id);


--
-- Name: admin_ai_settings admin_ai_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_ai_settings
    ADD CONSTRAINT admin_ai_settings_pkey PRIMARY KEY (id);


--
-- Name: admin_ai_usage_monthly admin_ai_usage_monthly_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_ai_usage_monthly
    ADD CONSTRAINT admin_ai_usage_monthly_pkey PRIMARY KEY (year_month);


--
-- Name: admin_users admin_users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_users
    ADD CONSTRAINT admin_users_email_key UNIQUE (email);


--
-- Name: admin_users admin_users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_users
    ADD CONSTRAINT admin_users_pkey PRIMARY KEY (id);


--
-- Name: admin_users admin_users_username_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_users
    ADD CONSTRAINT admin_users_username_key UNIQUE (username);


--
-- Name: ai_chats ai_chats_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_chats
    ADD CONSTRAINT ai_chats_pkey PRIMARY KEY (id);


--
-- Name: ai_generation_logs ai_generation_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_generation_logs
    ADD CONSTRAINT ai_generation_logs_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: answer_behaviors answer_behaviors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answer_behaviors
    ADD CONSTRAINT answer_behaviors_pkey PRIMARY KEY (id);


--
-- Name: app_user_admin_bindings app_user_admin_bindings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_user_admin_bindings
    ADD CONSTRAINT app_user_admin_bindings_pkey PRIMARY KEY (id);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: batch_job_trace_events batch_job_trace_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.batch_job_trace_events
    ADD CONSTRAINT batch_job_trace_events_pkey PRIMARY KEY (id);


--
-- Name: exam_answers exam_answers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_answers
    ADD CONSTRAINT exam_answers_pkey PRIMARY KEY (id);


--
-- Name: exam_attempts exam_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_attempts
    ADD CONSTRAINT exam_attempts_pkey PRIMARY KEY (id);


--
-- Name: exam_paper_questions exam_paper_questions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_paper_questions
    ADD CONSTRAINT exam_paper_questions_pkey PRIMARY KEY (id);


--
-- Name: exam_papers exam_papers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_papers
    ADD CONSTRAINT exam_papers_pkey PRIMARY KEY (id);


--
-- Name: export_snapshots export_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.export_snapshots
    ADD CONSTRAINT export_snapshots_pkey PRIMARY KEY (id);


--
-- Name: export_tasks export_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.export_tasks
    ADD CONSTRAINT export_tasks_pkey PRIMARY KEY (id);


--
-- Name: formula_card_tags formula_card_tags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_card_tags
    ADD CONSTRAINT formula_card_tags_pkey PRIMARY KEY (id);


--
-- Name: formula_card_versions formula_card_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_card_versions
    ADD CONSTRAINT formula_card_versions_pkey PRIMARY KEY (id);


--
-- Name: formula_cards formula_cards_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_cards
    ADD CONSTRAINT formula_cards_pkey PRIMARY KEY (id);


--
-- Name: formula_categories formula_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_categories
    ADD CONSTRAINT formula_categories_pkey PRIMARY KEY (id);


--
-- Name: formula_graph_assets formula_graph_assets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_graph_assets
    ADD CONSTRAINT formula_graph_assets_pkey PRIMARY KEY (id);


--
-- Name: formula_graph_previews formula_graph_previews_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_graph_previews
    ADD CONSTRAINT formula_graph_previews_pkey PRIMARY KEY (id);


--
-- Name: formula_graph_previews formula_graph_previews_preview_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_graph_previews
    ADD CONSTRAINT formula_graph_previews_preview_token_key UNIQUE (preview_token);


--
-- Name: formula_import_items formula_import_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_import_items
    ADD CONSTRAINT formula_import_items_pkey PRIMARY KEY (id);


--
-- Name: formula_import_jobs formula_import_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_import_jobs
    ADD CONSTRAINT formula_import_jobs_pkey PRIMARY KEY (id);


--
-- Name: formula_tags formula_tags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_tags
    ADD CONSTRAINT formula_tags_pkey PRIMARY KEY (id);


--
-- Name: import_batch_job_items import_batch_job_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_batch_job_items
    ADD CONSTRAINT import_batch_job_items_pkey PRIMARY KEY (id);


--
-- Name: import_batch_jobs import_batch_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_batch_jobs
    ADD CONSTRAINT import_batch_jobs_pkey PRIMARY KEY (job_id);


--
-- Name: import_pipeline_chunks import_pipeline_chunks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_pipeline_chunks
    ADD CONSTRAINT import_pipeline_chunks_pkey PRIMARY KEY (id);


--
-- Name: import_pipelines import_pipelines_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_pipelines
    ADD CONSTRAINT import_pipelines_pkey PRIMARY KEY (pipeline_id);


--
-- Name: knowledge_edges knowledge_edges_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_edges
    ADD CONSTRAINT knowledge_edges_pkey PRIMARY KEY (id);


--
-- Name: knowledge_points knowledge_points_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_points
    ADD CONSTRAINT knowledge_points_pkey PRIMARY KEY (id);


--
-- Name: ocr_jobs ocr_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ocr_jobs
    ADD CONSTRAINT ocr_jobs_pkey PRIMARY KEY (id);


--
-- Name: permissions permissions_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT permissions_name_key UNIQUE (name);


--
-- Name: permissions permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT permissions_pkey PRIMARY KEY (id);


--
-- Name: ai_feedback_logs pk_ai_feedback_logs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_feedback_logs
    ADD CONSTRAINT pk_ai_feedback_logs PRIMARY KEY (id);


--
-- Name: formula_graph_specs pk_formula_graph_specs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_graph_specs
    ADD CONSTRAINT pk_formula_graph_specs PRIMARY KEY (id);


--
-- Name: pomodoro_pause_intervals pk_pomodoro_pause_intervals; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pomodoro_pause_intervals
    ADD CONSTRAINT pk_pomodoro_pause_intervals PRIMARY KEY (id);


--
-- Name: pomodoro_sessions pk_pomodoro_sessions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pomodoro_sessions
    ADD CONSTRAINT pk_pomodoro_sessions PRIMARY KEY (id);


--
-- Name: practice_sessions pk_practice_sessions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.practice_sessions
    ADD CONSTRAINT pk_practice_sessions PRIMARY KEY (id);


--
-- Name: review_sessions pk_review_sessions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_sessions
    ADD CONSTRAINT pk_review_sessions PRIMARY KEY (id);


--
-- Name: user_pomodoro_settings pk_user_pomodoro_settings; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_pomodoro_settings
    ADD CONSTRAINT pk_user_pomodoro_settings PRIMARY KEY (user_id);


--
-- Name: worker_credentials pk_worker_credentials; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.worker_credentials
    ADD CONSTRAINT pk_worker_credentials PRIMARY KEY (id);


--
-- Name: pomodoro_subject_allocations pomodoro_subject_allocations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pomodoro_subject_allocations
    ADD CONSTRAINT pomodoro_subject_allocations_pkey PRIMARY KEY (id);


--
-- Name: practice_records practice_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.practice_records
    ADD CONSTRAINT practice_records_pkey PRIMARY KEY (id);


--
-- Name: question_embeddings question_embeddings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_embeddings
    ADD CONSTRAINT question_embeddings_pkey PRIMARY KEY (id);


--
-- Name: question_imports question_imports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_imports
    ADD CONSTRAINT question_imports_pkey PRIMARY KEY (id);


--
-- Name: question_knowledge_points question_knowledge_points_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_knowledge_points
    ADD CONSTRAINT question_knowledge_points_pkey PRIMARY KEY (id);


--
-- Name: question_version_knowledge_points question_version_knowledge_points_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_version_knowledge_points
    ADD CONSTRAINT question_version_knowledge_points_pkey PRIMARY KEY (id);


--
-- Name: question_versions question_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_versions
    ADD CONSTRAINT question_versions_pkey PRIMARY KEY (id);


--
-- Name: questions questions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.questions
    ADD CONSTRAINT questions_pkey PRIMARY KEY (id);


--
-- Name: recommendation_experiment_assignments recommendation_experiment_assignments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_experiment_assignments
    ADD CONSTRAINT recommendation_experiment_assignments_pkey PRIMARY KEY (id);


--
-- Name: recommendation_experiments recommendation_experiments_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_experiments
    ADD CONSTRAINT recommendation_experiments_name_key UNIQUE (name);


--
-- Name: recommendation_experiments recommendation_experiments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_experiments
    ADD CONSTRAINT recommendation_experiments_pkey PRIMARY KEY (id);


--
-- Name: recommendation_logs recommendation_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_logs
    ADD CONSTRAINT recommendation_logs_pkey PRIMARY KEY (id);


--
-- Name: recommendation_metrics_daily recommendation_metrics_daily_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_metrics_daily
    ADD CONSTRAINT recommendation_metrics_daily_pkey PRIMARY KEY (id);


--
-- Name: recommendation_strategy_configs recommendation_strategy_configs_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_strategy_configs
    ADD CONSTRAINT recommendation_strategy_configs_name_key UNIQUE (name);


--
-- Name: recommendation_strategy_configs recommendation_strategy_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_strategy_configs
    ADD CONSTRAINT recommendation_strategy_configs_pkey PRIMARY KEY (id);


--
-- Name: refresh_tokens refresh_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT refresh_tokens_pkey PRIMARY KEY (id);


--
-- Name: review_records review_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_records
    ADD CONSTRAINT review_records_pkey PRIMARY KEY (id);


--
-- Name: review_schedules review_schedules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_schedules
    ADD CONSTRAINT review_schedules_pkey PRIMARY KEY (id);


--
-- Name: role_permissions role_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_pkey PRIMARY KEY (role_id, permission_id);


--
-- Name: roles roles_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_name_key UNIQUE (name);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- Name: sequential_reservations sequential_reservations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sequential_reservations
    ADD CONSTRAINT sequential_reservations_pkey PRIMARY KEY (id);


--
-- Name: study_plan_days study_plan_days_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.study_plan_days
    ADD CONSTRAINT study_plan_days_pkey PRIMARY KEY (id);


--
-- Name: study_plans study_plans_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.study_plans
    ADD CONSTRAINT study_plans_pkey PRIMARY KEY (id);


--
-- Name: subjects subjects_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subjects
    ADD CONSTRAINT subjects_code_key UNIQUE (code);


--
-- Name: subjects subjects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subjects
    ADD CONSTRAINT subjects_pkey PRIMARY KEY (id);


--
-- Name: syllabus_knowledge_point_mappings syllabus_knowledge_point_mappings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.syllabus_knowledge_point_mappings
    ADD CONSTRAINT syllabus_knowledge_point_mappings_pkey PRIMARY KEY (id);


--
-- Name: syllabus_knowledge_points syllabus_knowledge_points_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.syllabus_knowledge_points
    ADD CONSTRAINT syllabus_knowledge_points_pkey PRIMARY KEY (id);


--
-- Name: syllabus_versions syllabus_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.syllabus_versions
    ADD CONSTRAINT syllabus_versions_pkey PRIMARY KEY (id);


--
-- Name: tags tags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tags
    ADD CONSTRAINT tags_pkey PRIMARY KEY (id);


--
-- Name: task_outbox task_outbox_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_outbox
    ADD CONSTRAINT task_outbox_pkey PRIMARY KEY (id);


--
-- Name: app_user_admin_bindings uq_app_user_admin_bindings_admin_user_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_user_admin_bindings
    ADD CONSTRAINT uq_app_user_admin_bindings_admin_user_id UNIQUE (admin_user_id);


--
-- Name: app_user_admin_bindings uq_app_user_admin_bindings_user_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_user_admin_bindings
    ADD CONSTRAINT uq_app_user_admin_bindings_user_id UNIQUE (user_id);


--
-- Name: import_batch_job_items uq_batch_import_id_image; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_batch_job_items
    ADD CONSTRAINT uq_batch_import_id_image UNIQUE (batch_import_id, image_import_id);


--
-- Name: import_batch_job_items uq_batch_job_items_job_seq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_batch_job_items
    ADD CONSTRAINT uq_batch_job_items_job_seq UNIQUE (job_id, seq);


--
-- Name: exam_answers uq_exam_answers_attempt_item; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_answers
    ADD CONSTRAINT uq_exam_answers_attempt_item UNIQUE (attempt_id, exam_paper_question_id);


--
-- Name: exam_answers uq_exam_answers_practice_record; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_answers
    ADD CONSTRAINT uq_exam_answers_practice_record UNIQUE (practice_record_id);


--
-- Name: exam_attempts uq_exam_attempts_user_request; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_attempts
    ADD CONSTRAINT uq_exam_attempts_user_request UNIQUE (user_id, request_id);


--
-- Name: exam_paper_questions uq_exam_paper_questions_position; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_paper_questions
    ADD CONSTRAINT uq_exam_paper_questions_position UNIQUE (paper_id, "position");


--
-- Name: exam_paper_questions uq_exam_paper_questions_question; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_paper_questions
    ADD CONSTRAINT uq_exam_paper_questions_question UNIQUE (paper_id, question_id);


--
-- Name: formula_card_tags uq_formula_card_tags_card_tag; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_card_tags
    ADD CONSTRAINT uq_formula_card_tags_card_tag UNIQUE (formula_card_id, tag_id);


--
-- Name: formula_card_versions uq_formula_card_versions_card_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_card_versions
    ADD CONSTRAINT uq_formula_card_versions_card_version UNIQUE (formula_card_id, version);


--
-- Name: formula_categories uq_formula_categories_parent_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_categories
    ADD CONSTRAINT uq_formula_categories_parent_code UNIQUE (parent_id, code);


--
-- Name: formula_graph_assets uq_formula_graph_assets_card_source; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_graph_assets
    ADD CONSTRAINT uq_formula_graph_assets_card_source UNIQUE (formula_card_id, source_type);


--
-- Name: formula_graph_specs uq_formula_graph_specs_card_slug; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_graph_specs
    ADD CONSTRAINT uq_formula_graph_specs_card_slug UNIQUE (formula_card_id, slug);


--
-- Name: knowledge_edges uq_ke_source_target_relation; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_edges
    ADD CONSTRAINT uq_ke_source_target_relation UNIQUE (source_knowledge_point_id, target_knowledge_point_id, relation_type);


--
-- Name: ocr_jobs uq_ocr_jobs_complete_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ocr_jobs
    ADD CONSTRAINT uq_ocr_jobs_complete_key UNIQUE (complete_idempotency_key);


--
-- Name: ocr_jobs uq_ocr_jobs_request_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ocr_jobs
    ADD CONSTRAINT uq_ocr_jobs_request_id UNIQUE (request_id);


--
-- Name: import_pipeline_chunks uq_pipeline_chunks_pipeline_index; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_pipeline_chunks
    ADD CONSTRAINT uq_pipeline_chunks_pipeline_index UNIQUE (pipeline_id, chunk_index);


--
-- Name: question_knowledge_points uq_qkp_question_kp; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_knowledge_points
    ADD CONSTRAINT uq_qkp_question_kp UNIQUE (question_id, knowledge_point_id);


--
-- Name: question_knowledge_points uq_qkp_question_position; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_knowledge_points
    ADD CONSTRAINT uq_qkp_question_position UNIQUE (question_id, "position");


--
-- Name: question_embeddings uq_question_embeddings_question_id_model_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_embeddings
    ADD CONSTRAINT uq_question_embeddings_question_id_model_id UNIQUE (question_id, model_id);


--
-- Name: question_versions uq_question_versions_question_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_versions
    ADD CONSTRAINT uq_question_versions_question_version UNIQUE (question_id, version);


--
-- Name: question_version_knowledge_points uq_qvkp_version_kp; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_version_knowledge_points
    ADD CONSTRAINT uq_qvkp_version_kp UNIQUE (question_version_id, knowledge_point_id);


--
-- Name: question_version_knowledge_points uq_qvkp_version_position; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_version_knowledge_points
    ADD CONSTRAINT uq_qvkp_version_position UNIQUE (question_version_id, "position");


--
-- Name: recommendation_experiment_assignments uq_rea_experiment_user; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_experiment_assignments
    ADD CONSTRAINT uq_rea_experiment_user UNIQUE (experiment_id, user_id);


--
-- Name: review_records uq_review_records_schedule_occurrence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_records
    ADD CONSTRAINT uq_review_records_schedule_occurrence UNIQUE (schedule_id, occurrence_seq);


--
-- Name: review_records uq_review_records_user_request; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_records
    ADD CONSTRAINT uq_review_records_user_request UNIQUE (user_id, request_id);


--
-- Name: review_schedules uq_review_schedules_user_question; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_schedules
    ADD CONSTRAINT uq_review_schedules_user_question UNIQUE (user_id, question_id);


--
-- Name: review_sessions uq_review_sessions_user_request; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_sessions
    ADD CONSTRAINT uq_review_sessions_user_request UNIQUE (user_id, request_id);


--
-- Name: recommendation_metrics_daily uq_rmd_date_subject_id_scene_strategy_variant; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_metrics_daily
    ADD CONSTRAINT uq_rmd_date_subject_id_scene_strategy_variant UNIQUE (date, subject_id, scene, strategy, variant_key);


--
-- Name: sequential_reservations uq_sequential_reservation_question; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sequential_reservations
    ADD CONSTRAINT uq_sequential_reservation_question UNIQUE (user_id, subject_id, scope_key, question_id);


--
-- Name: study_plan_days uq_study_plan_days_plan_date; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.study_plan_days
    ADD CONSTRAINT uq_study_plan_days_plan_date UNIQUE (plan_id, plan_date);


--
-- Name: study_plans uq_study_plans_user; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.study_plans
    ADD CONSTRAINT uq_study_plans_user UNIQUE (user_id);


--
-- Name: syllabus_knowledge_points uq_syllabus_version_kp; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.syllabus_knowledge_points
    ADD CONSTRAINT uq_syllabus_version_kp UNIQUE (syllabus_version_id, knowledge_point_id);


--
-- Name: syllabus_versions uq_syllabus_versions_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.syllabus_versions
    ADD CONSTRAINT uq_syllabus_versions_code UNIQUE (code);


--
-- Name: task_outbox uq_task_outbox_task_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_outbox
    ADD CONSTRAINT uq_task_outbox_task_id UNIQUE (task_id);


--
-- Name: user_knowledge_adaptive_state uq_ukas_user_kp; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_knowledge_adaptive_state
    ADD CONSTRAINT uq_ukas_user_kp UNIQUE (user_id, knowledge_point_id);


--
-- Name: user_knowledge_states uq_uks_user_kp; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_knowledge_states
    ADD CONSTRAINT uq_uks_user_kp UNIQUE (user_id, knowledge_point_id);


--
-- Name: user_question_difficulty_state uq_uqds_user_question; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_question_difficulty_state
    ADD CONSTRAINT uq_uqds_user_question UNIQUE (user_id, question_id);


--
-- Name: user_formula_favorites uq_user_formula_favorites_user_card; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_formula_favorites
    ADD CONSTRAINT uq_user_formula_favorites_user_card UNIQUE (user_id, formula_card_id);


--
-- Name: user_question_state uq_user_question_state_user_question; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_question_state
    ADD CONSTRAINT uq_user_question_state_user_question UNIQUE (user_id, question_id);


--
-- Name: wrong_question_error_diagnoses uq_wrong_error_diagnoses_exam_answer; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wrong_question_error_diagnoses
    ADD CONSTRAINT uq_wrong_error_diagnoses_exam_answer UNIQUE (exam_answer_id);


--
-- Name: wrong_question_error_diagnoses uq_wrong_error_diagnoses_practice_record; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wrong_question_error_diagnoses
    ADD CONSTRAINT uq_wrong_error_diagnoses_practice_record UNIQUE (practice_record_id);


--
-- Name: wrong_questions uq_wrong_questions_user_question; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wrong_questions
    ADD CONSTRAINT uq_wrong_questions_user_question UNIQUE (user_id, question_id);


--
-- Name: user_adaptive_profile user_adaptive_profile_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_adaptive_profile
    ADD CONSTRAINT user_adaptive_profile_pkey PRIMARY KEY (id);


--
-- Name: user_formula_favorites user_formula_favorites_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_formula_favorites
    ADD CONSTRAINT user_formula_favorites_pkey PRIMARY KEY (id);


--
-- Name: user_knowledge_adaptive_state user_knowledge_adaptive_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_knowledge_adaptive_state
    ADD CONSTRAINT user_knowledge_adaptive_state_pkey PRIMARY KEY (id);


--
-- Name: user_knowledge_states user_knowledge_states_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_knowledge_states
    ADD CONSTRAINT user_knowledge_states_pkey PRIMARY KEY (id);


--
-- Name: user_question_difficulty_state user_question_difficulty_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_question_difficulty_state
    ADD CONSTRAINT user_question_difficulty_state_pkey PRIMARY KEY (id);


--
-- Name: user_question_state user_question_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_question_state
    ADD CONSTRAINT user_question_state_pkey PRIMARY KEY (id);


--
-- Name: user_recommend_preference user_recommend_preference_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_recommend_preference
    ADD CONSTRAINT user_recommend_preference_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: watermark_rules watermark_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watermark_rules
    ADD CONSTRAINT watermark_rules_pkey PRIMARY KEY (id);


--
-- Name: wrong_question_error_diagnoses wrong_question_error_diagnoses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wrong_question_error_diagnoses
    ADD CONSTRAINT wrong_question_error_diagnoses_pkey PRIMARY KEY (id);


--
-- Name: wrong_questions wrong_questions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wrong_questions
    ADD CONSTRAINT wrong_questions_pkey PRIMARY KEY (id);


--
-- Name: idx_answer_behavior_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_answer_behavior_user_date ON public.answer_behaviors USING btree (user_id, created_at);


--
-- Name: idx_audit_logs_resource; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_logs_resource ON public.audit_logs USING btree (resource_type, resource_id);


--
-- Name: idx_pr_user_question; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_user_question ON public.practice_records USING btree (user_id, question_id);


--
-- Name: idx_practice_records_user_answered_question; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_practice_records_user_answered_question ON public.practice_records USING btree (user_id, answered_at, question_id);


--
-- Name: idx_practice_records_user_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_practice_records_user_date ON public.practice_records USING btree (user_id, answered_at);


--
-- Name: idx_practice_records_user_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_practice_records_user_subject_id ON public.practice_records USING btree (user_id, subject_id);


--
-- Name: idx_qkp_knowledge_point_question; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qkp_knowledge_point_question ON public.question_knowledge_points USING btree (knowledge_point_id, question_id);


--
-- Name: idx_questions_subject_id_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_questions_subject_id_active ON public.questions USING btree (subject_id, is_active) WHERE (is_active = true);


--
-- Name: idx_uks_user_mastery; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_uks_user_mastery ON public.user_knowledge_states USING btree (user_id, mastery_score);


--
-- Name: idx_uks_user_mastery_conf; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_uks_user_mastery_conf ON public.user_knowledge_states USING btree (user_id, mastery_score, confidence);


--
-- Name: idx_uqs_user_box; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_uqs_user_box ON public.user_question_state USING btree (user_id, box_level);


--
-- Name: idx_user_question_state_question_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_question_state_question_id ON public.user_question_state USING btree (question_id);


--
-- Name: idx_user_question_state_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_question_state_user_id ON public.user_question_state USING btree (user_id);


--
-- Name: ix_admin_users_role_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_admin_users_role_id ON public.admin_users USING btree (role_id);


--
-- Name: ix_ai_chats_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_chats_user_id ON public.ai_chats USING btree (user_id);


--
-- Name: ix_ai_feedback_logs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_feedback_logs_user_id ON public.ai_feedback_logs USING btree (user_id);


--
-- Name: ix_ai_generation_logs_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_generation_logs_action ON public.ai_generation_logs USING btree (action);


--
-- Name: ix_ai_generation_logs_batch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_generation_logs_batch_id ON public.ai_generation_logs USING btree (batch_id);


--
-- Name: ix_ai_generation_logs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_generation_logs_user_id ON public.ai_generation_logs USING btree (user_id);


--
-- Name: ix_answer_behaviors_question_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_answer_behaviors_question_version_id ON public.answer_behaviors USING btree (question_version_id);


--
-- Name: ix_answer_behaviors_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_answer_behaviors_subject_id ON public.answer_behaviors USING btree (subject_id);


--
-- Name: ix_answer_behaviors_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_answer_behaviors_user_id ON public.answer_behaviors USING btree (user_id);


--
-- Name: ix_audit_logs_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_action ON public.audit_logs USING btree (action);


--
-- Name: ix_audit_logs_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_created_at ON public.audit_logs USING btree (created_at);


--
-- Name: ix_audit_logs_operator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_operator_id ON public.audit_logs USING btree (operator_id);


--
-- Name: ix_audit_logs_severity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_severity ON public.audit_logs USING btree (severity);


--
-- Name: ix_batch_job_trace_events_job_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_batch_job_trace_events_job_id ON public.batch_job_trace_events USING btree (job_id);


--
-- Name: ix_exam_answers_attempt_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exam_answers_attempt_id ON public.exam_answers USING btree (attempt_id);


--
-- Name: ix_exam_answers_exam_paper_question_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exam_answers_exam_paper_question_id ON public.exam_answers USING btree (exam_paper_question_id);


--
-- Name: ix_exam_answers_question_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exam_answers_question_id ON public.exam_answers USING btree (question_id);


--
-- Name: ix_exam_answers_question_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exam_answers_question_version_id ON public.exam_answers USING btree (question_version_id);


--
-- Name: ix_exam_answers_revision; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exam_answers_revision ON public.exam_answers USING btree (id, answer_revision);


--
-- Name: ix_exam_attempts_paper_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exam_attempts_paper_id ON public.exam_attempts USING btree (paper_id);


--
-- Name: ix_exam_attempts_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exam_attempts_user_id ON public.exam_attempts USING btree (user_id);


--
-- Name: ix_exam_attempts_user_paper_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exam_attempts_user_paper_started ON public.exam_attempts USING btree (user_id, paper_id, started_at);


--
-- Name: ix_exam_attempts_user_status_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exam_attempts_user_status_started ON public.exam_attempts USING btree (user_id, status, started_at);


--
-- Name: ix_exam_paper_questions_paper_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exam_paper_questions_paper_id ON public.exam_paper_questions USING btree (paper_id);


--
-- Name: ix_exam_paper_questions_question_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exam_paper_questions_question_id ON public.exam_paper_questions USING btree (question_id);


--
-- Name: ix_exam_paper_questions_question_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exam_paper_questions_question_version_id ON public.exam_paper_questions USING btree (question_version_id);


--
-- Name: ix_exam_paper_questions_section_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exam_paper_questions_section_subject_id ON public.exam_paper_questions USING btree (section_subject_id);


--
-- Name: ix_exam_papers_coverage_type_year_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exam_papers_coverage_type_year_status ON public.exam_papers USING btree (paper_type, year, status, is_active);


--
-- Name: ix_exam_papers_deleted_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exam_papers_deleted_at ON public.exam_papers USING btree (deleted_at);


--
-- Name: ix_exam_papers_public_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_exam_papers_public_id ON public.exam_papers USING btree (public_id);


--
-- Name: ix_exam_papers_status_active_year; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exam_papers_status_active_year ON public.exam_papers USING btree (status, is_active, year);


--
-- Name: ix_exam_papers_year; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exam_papers_year ON public.exam_papers USING btree (year);


--
-- Name: ix_export_snapshots_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_export_snapshots_user_id ON public.export_snapshots USING btree (user_id);


--
-- Name: ix_export_tasks_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_export_tasks_expires_at ON public.export_tasks USING btree (expires_at);


--
-- Name: ix_export_tasks_idempotency_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_export_tasks_idempotency_key ON public.export_tasks USING btree (idempotency_key);


--
-- Name: ix_export_tasks_snapshot_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_export_tasks_snapshot_id ON public.export_tasks USING btree (snapshot_id);


--
-- Name: ix_export_tasks_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_export_tasks_status ON public.export_tasks USING btree (status);


--
-- Name: ix_export_tasks_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_export_tasks_status_created ON public.export_tasks USING btree (status, created_at);


--
-- Name: ix_export_tasks_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_export_tasks_user_id ON public.export_tasks USING btree (user_id);


--
-- Name: ix_export_tasks_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_export_tasks_user_status ON public.export_tasks USING btree (user_id, status);


--
-- Name: ix_formula_card_tags_formula_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_formula_card_tags_formula_card_id ON public.formula_card_tags USING btree (formula_card_id);


--
-- Name: ix_formula_card_tags_tag_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_formula_card_tags_tag_id ON public.formula_card_tags USING btree (tag_id);


--
-- Name: ix_formula_card_versions_formula_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_formula_card_versions_formula_card_id ON public.formula_card_versions USING btree (formula_card_id);


--
-- Name: ix_formula_cards_category_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_formula_cards_category_id ON public.formula_cards USING btree (category_id);


--
-- Name: ix_formula_cards_content_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_formula_cards_content_hash ON public.formula_cards USING btree (content_hash);


--
-- Name: ix_formula_cards_exam_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_formula_cards_exam_scope ON public.formula_cards USING btree (exam_scope);


--
-- Name: ix_formula_cards_exam_study_type_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_formula_cards_exam_study_type_status ON public.formula_cards USING btree (exam_scope, study_card_type, status);


--
-- Name: ix_formula_cards_graph_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_formula_cards_graph_status ON public.formula_cards USING btree (graph_status);


--
-- Name: ix_formula_cards_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_formula_cards_status ON public.formula_cards USING btree (status);


--
-- Name: ix_formula_cards_template_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_formula_cards_template_type ON public.formula_cards USING btree (template_type);


--
-- Name: ix_formula_categories_exam_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_formula_categories_exam_scope ON public.formula_categories USING btree (exam_scope);


--
-- Name: ix_formula_categories_parent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_formula_categories_parent_id ON public.formula_categories USING btree (parent_id);


--
-- Name: ix_formula_graph_assets_formula_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_formula_graph_assets_formula_card_id ON public.formula_graph_assets USING btree (formula_card_id);


--
-- Name: ix_formula_graph_previews_formula_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_formula_graph_previews_formula_card_id ON public.formula_graph_previews USING btree (formula_card_id);


--
-- Name: ix_formula_graph_specs_formula_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_formula_graph_specs_formula_card_id ON public.formula_graph_specs USING btree (formula_card_id);


--
-- Name: ix_formula_graph_specs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_formula_graph_specs_status ON public.formula_graph_specs USING btree (status);


--
-- Name: ix_formula_import_items_job_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_formula_import_items_job_id ON public.formula_import_items USING btree (job_id);


--
-- Name: ix_formula_import_jobs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_formula_import_jobs_status ON public.formula_import_jobs USING btree (status);


--
-- Name: ix_formula_tags_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_formula_tags_code ON public.formula_tags USING btree (code);


--
-- Name: ix_import_batch_job_items_job_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_batch_job_items_job_id ON public.import_batch_job_items USING btree (job_id);


--
-- Name: ix_import_batch_job_items_source_sha256; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_batch_job_items_source_sha256 ON public.import_batch_job_items USING btree (source_sha256);


--
-- Name: ix_import_batch_job_items_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_batch_job_items_status ON public.import_batch_job_items USING btree (status);


--
-- Name: ix_import_batch_jobs_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_batch_jobs_created_by ON public.import_batch_jobs USING btree (created_by);


--
-- Name: ix_import_batch_jobs_execution_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_batch_jobs_execution_status ON public.import_batch_jobs USING btree (execution_status);


--
-- Name: ix_import_batch_jobs_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_import_batch_jobs_request_id ON public.import_batch_jobs USING btree (request_id);


--
-- Name: ix_import_batch_jobs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_batch_jobs_status ON public.import_batch_jobs USING btree (status);


--
-- Name: ix_import_batch_jobs_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_batch_jobs_subject_id ON public.import_batch_jobs USING btree (subject_id);


--
-- Name: ix_import_pipeline_chunks_pipeline_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_pipeline_chunks_pipeline_id ON public.import_pipeline_chunks USING btree (pipeline_id);


--
-- Name: ix_import_pipeline_chunks_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_pipeline_chunks_status ON public.import_pipeline_chunks USING btree (status);


--
-- Name: ix_import_pipelines_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_pipelines_created_by ON public.import_pipelines USING btree (created_by);


--
-- Name: ix_import_pipelines_created_by_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_pipelines_created_by_status ON public.import_pipelines USING btree (created_by, status);


--
-- Name: ix_import_pipelines_execution_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_pipelines_execution_status ON public.import_pipelines USING btree (execution_status);


--
-- Name: ix_import_pipelines_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_pipelines_status ON public.import_pipelines USING btree (status);


--
-- Name: ix_ke_subject_id_relation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ke_subject_id_relation ON public.knowledge_edges USING btree (subject_id, relation_type);


--
-- Name: ix_knowledge_edges_relation_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_edges_relation_type ON public.knowledge_edges USING btree (relation_type);


--
-- Name: ix_knowledge_edges_source_kp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_edges_source_kp ON public.knowledge_edges USING btree (source_knowledge_point_id);


--
-- Name: ix_knowledge_edges_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_edges_subject_id ON public.knowledge_edges USING btree (subject_id);


--
-- Name: ix_knowledge_edges_target_kp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_edges_target_kp ON public.knowledge_edges USING btree (target_knowledge_point_id);


--
-- Name: ix_knowledge_points_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_points_name ON public.knowledge_points USING btree (name);


--
-- Name: ix_knowledge_points_normalized_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_points_normalized_name ON public.knowledge_points USING btree (normalized_name);


--
-- Name: ix_knowledge_points_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_points_subject_id ON public.knowledge_points USING btree (subject_id);


--
-- Name: ix_kp_subject_normalized_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_kp_subject_normalized_name ON public.knowledge_points USING btree (subject_id, normalized_name);


--
-- Name: ix_ocr_jobs_claim; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ocr_jobs_claim ON public.ocr_jobs USING btree (status, priority, next_retry_at, created_at);


--
-- Name: ix_ocr_jobs_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ocr_jobs_document_id ON public.ocr_jobs USING btree (document_id);


--
-- Name: ix_ocr_jobs_document_sha256; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ocr_jobs_document_sha256 ON public.ocr_jobs USING btree (document_sha256);


--
-- Name: ix_ocr_jobs_lease_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ocr_jobs_lease_expires_at ON public.ocr_jobs USING btree (lease_expires_at);


--
-- Name: ix_ocr_jobs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ocr_jobs_status ON public.ocr_jobs USING btree (status);


--
-- Name: ix_permissions_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_permissions_category ON public.permissions USING btree (category);


--
-- Name: ix_permissions_resource; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_permissions_resource ON public.permissions USING btree (resource);


--
-- Name: ix_pomodoro_pause_intervals_session_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pomodoro_pause_intervals_session_started ON public.pomodoro_pause_intervals USING btree (session_id, started_at);


--
-- Name: ix_pomodoro_sessions_expected_end_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pomodoro_sessions_expected_end_time ON public.pomodoro_sessions USING btree (expected_end_time);


--
-- Name: ix_pomodoro_sessions_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pomodoro_sessions_subject_id ON public.pomodoro_sessions USING btree (subject_id);


--
-- Name: ix_pomodoro_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pomodoro_sessions_user_id ON public.pomodoro_sessions USING btree (user_id);


--
-- Name: ix_pomodoro_sessions_user_status_end; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pomodoro_sessions_user_status_end ON public.pomodoro_sessions USING btree (user_id, status, end_time);


--
-- Name: ix_pomodoro_sessions_user_status_start; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pomodoro_sessions_user_status_start ON public.pomodoro_sessions USING btree (user_id, status, start_time);


--
-- Name: ix_pomodoro_subject_allocations_subject; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pomodoro_subject_allocations_subject ON public.pomodoro_subject_allocations USING btree (subject_id);


--
-- Name: ix_practice_records_projection_state_answered; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_practice_records_projection_state_answered ON public.practice_records USING btree (projection_state, answered_at);


--
-- Name: ix_practice_records_question_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_practice_records_question_id ON public.practice_records USING btree (question_id);


--
-- Name: ix_practice_records_question_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_practice_records_question_version_id ON public.practice_records USING btree (question_version_id);


--
-- Name: ix_practice_records_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_practice_records_user_created ON public.practice_records USING btree (user_id, created_at);


--
-- Name: ix_practice_records_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_practice_records_user_id ON public.practice_records USING btree (user_id);


--
-- Name: ix_practice_sessions_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_practice_sessions_subject_id ON public.practice_sessions USING btree (subject_id);


--
-- Name: ix_practice_sessions_user_finished; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_practice_sessions_user_finished ON public.practice_sessions USING btree (user_id, finished_at);


--
-- Name: ix_practice_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_practice_sessions_user_id ON public.practice_sessions USING btree (user_id);


--
-- Name: ix_practice_sessions_user_scope_finished; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_practice_sessions_user_scope_finished ON public.practice_sessions USING btree (user_id, scope_type, scope_root_knowledge_point_id, finished_at);


--
-- Name: ix_practice_sessions_user_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_practice_sessions_user_started ON public.practice_sessions USING btree (user_id, started_at);


--
-- Name: ix_qkp_knowledge_point_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_qkp_knowledge_point_id ON public.question_knowledge_points USING btree (knowledge_point_id);


--
-- Name: ix_qkp_question_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_qkp_question_id ON public.question_knowledge_points USING btree (question_id);


--
-- Name: ix_question_embeddings_content_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_embeddings_content_hash ON public.question_embeddings USING btree (content_hash);


--
-- Name: ix_question_embeddings_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_embeddings_model_id ON public.question_embeddings USING btree (model_id);


--
-- Name: ix_question_embeddings_question_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_embeddings_question_id ON public.question_embeddings USING btree (question_id);


--
-- Name: ix_question_embeddings_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_embeddings_subject_id ON public.question_embeddings USING btree (subject_id);


--
-- Name: ix_question_imports_answer_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_imports_answer_status ON public.question_imports USING btree (answer_status);


--
-- Name: ix_question_imports_batch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_imports_batch_id ON public.question_imports USING btree (batch_id);


--
-- Name: ix_question_imports_batch_status_created_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_imports_batch_status_created_id ON public.question_imports USING btree (batch_id, status, created_at, id);


--
-- Name: ix_question_imports_duplicate_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_imports_duplicate_status ON public.question_imports USING btree (duplicate_status);


--
-- Name: ix_question_imports_question_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_imports_question_hash ON public.question_imports USING btree (question_hash);


--
-- Name: ix_question_imports_question_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_imports_question_id ON public.question_imports USING btree (question_id);


--
-- Name: ix_question_imports_review_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_imports_review_priority ON public.question_imports USING btree (review_priority);


--
-- Name: ix_question_imports_source_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_imports_source_order ON public.question_imports USING btree (batch_id, source_image_seq, source_order_index);


--
-- Name: ix_question_imports_source_question_no; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_imports_source_question_no ON public.question_imports USING btree (source_question_no);


--
-- Name: ix_question_imports_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_imports_status ON public.question_imports USING btree (status);


--
-- Name: ix_question_imports_status_created_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_imports_status_created_id ON public.question_imports USING btree (status, created_at, id);


--
-- Name: ix_question_imports_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_imports_subject_id ON public.question_imports USING btree (subject_id);


--
-- Name: ix_question_imports_superseded_by_batch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_imports_superseded_by_batch_id ON public.question_imports USING btree (superseded_by_batch_id);


--
-- Name: ix_question_version_knowledge_points_knowledge_point_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_version_knowledge_points_knowledge_point_id ON public.question_version_knowledge_points USING btree (knowledge_point_id);


--
-- Name: ix_question_version_knowledge_points_question_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_version_knowledge_points_question_version_id ON public.question_version_knowledge_points USING btree (question_version_id);


--
-- Name: ix_question_versions_edited_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_versions_edited_by ON public.question_versions USING btree (edited_by);


--
-- Name: ix_question_versions_question_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_versions_question_id ON public.question_versions USING btree (question_id);


--
-- Name: ix_question_versions_state_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_versions_state_hash ON public.question_versions USING btree (state_hash);


--
-- Name: ix_questions_coverage_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_questions_coverage_scope ON public.questions USING btree (subject_id, review_status, is_active);


--
-- Name: ix_questions_current_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_questions_current_version_id ON public.questions USING btree (current_version_id);


--
-- Name: ix_questions_import_batch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_questions_import_batch_id ON public.questions USING btree (import_batch_id);


--
-- Name: ix_questions_question_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_questions_question_hash ON public.questions USING btree (question_hash);


--
-- Name: ix_questions_review_status_is_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_questions_review_status_is_active ON public.questions USING btree (review_status, is_active);


--
-- Name: ix_questions_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_questions_subject_id ON public.questions USING btree (subject_id);


--
-- Name: ix_questions_sync_uuid; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_questions_sync_uuid ON public.questions USING btree (sync_uuid);


--
-- Name: ix_qvkp_syllabus_kp_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_qvkp_syllabus_kp_id ON public.question_version_knowledge_points USING btree (syllabus_knowledge_point_id);


--
-- Name: ix_rea_experiment_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rea_experiment_id ON public.recommendation_experiment_assignments USING btree (experiment_id);


--
-- Name: ix_rea_strategy; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rea_strategy ON public.recommendation_experiment_assignments USING btree (strategy);


--
-- Name: ix_rea_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rea_user_id ON public.recommendation_experiment_assignments USING btree (user_id);


--
-- Name: ix_rea_variant_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rea_variant_key ON public.recommendation_experiment_assignments USING btree (variant_key);


--
-- Name: ix_recommendation_experiments_scene; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recommendation_experiments_scene ON public.recommendation_experiments USING btree (scene);


--
-- Name: ix_recommendation_logs_experiment_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recommendation_logs_experiment_id ON public.recommendation_logs USING btree (experiment_id);


--
-- Name: ix_recommendation_logs_question_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recommendation_logs_question_id ON public.recommendation_logs USING btree (question_id);


--
-- Name: ix_recommendation_logs_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recommendation_logs_request_id ON public.recommendation_logs USING btree (request_id);


--
-- Name: ix_recommendation_logs_scene; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recommendation_logs_scene ON public.recommendation_logs USING btree (scene);


--
-- Name: ix_recommendation_logs_strategy; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recommendation_logs_strategy ON public.recommendation_logs USING btree (strategy);


--
-- Name: ix_recommendation_logs_strategy_config_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recommendation_logs_strategy_config_id ON public.recommendation_logs USING btree (strategy_config_id);


--
-- Name: ix_recommendation_logs_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recommendation_logs_subject_id ON public.recommendation_logs USING btree (subject_id);


--
-- Name: ix_recommendation_logs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recommendation_logs_user_id ON public.recommendation_logs USING btree (user_id);


--
-- Name: ix_recommendation_logs_variant_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recommendation_logs_variant_key ON public.recommendation_logs USING btree (variant_key);


--
-- Name: ix_recommendation_metrics_daily_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recommendation_metrics_daily_subject_id ON public.recommendation_metrics_daily USING btree (subject_id);


--
-- Name: ix_recommendation_metrics_daily_variant_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recommendation_metrics_daily_variant_key ON public.recommendation_metrics_daily USING btree (variant_key);


--
-- Name: ix_recommendation_strategy_configs_scene; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recommendation_strategy_configs_scene ON public.recommendation_strategy_configs USING btree (scene);


--
-- Name: ix_refresh_tokens_token_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_refresh_tokens_token_hash ON public.refresh_tokens USING btree (token_hash);


--
-- Name: ix_refresh_tokens_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_refresh_tokens_user_id ON public.refresh_tokens USING btree (user_id);


--
-- Name: ix_review_records_question_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_records_question_id ON public.review_records USING btree (question_id);


--
-- Name: ix_review_records_question_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_records_question_version_id ON public.review_records USING btree (question_version_id);


--
-- Name: ix_review_records_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_records_user_id ON public.review_records USING btree (user_id);


--
-- Name: ix_review_records_user_reviewed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_records_user_reviewed ON public.review_records USING btree (user_id, reviewed_at);


--
-- Name: ix_review_records_user_version; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_records_user_version ON public.review_records USING btree (user_id, question_version_id);


--
-- Name: ix_review_schedules_question_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_schedules_question_id ON public.review_schedules USING btree (question_id);


--
-- Name: ix_review_schedules_question_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_schedules_question_version_id ON public.review_schedules USING btree (question_version_id);


--
-- Name: ix_review_schedules_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_schedules_user_id ON public.review_schedules USING btree (user_id);


--
-- Name: ix_review_schedules_user_next_review; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_schedules_user_next_review ON public.review_schedules USING btree (user_id, next_review_at) WHERE (mastered = false);


--
-- Name: ix_review_schedules_user_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_schedules_user_subject_id ON public.review_schedules USING btree (user_id, subject_id);


--
-- Name: ix_review_schedules_user_version; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_schedules_user_version ON public.review_schedules USING btree (user_id, question_version_id);


--
-- Name: ix_review_sessions_user_finished; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_sessions_user_finished ON public.review_sessions USING btree (user_id, finished_at);


--
-- Name: ix_review_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_sessions_user_id ON public.review_sessions USING btree (user_id);


--
-- Name: ix_review_sessions_user_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_sessions_user_started ON public.review_sessions USING btree (user_id, started_at);


--
-- Name: ix_rl_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rl_created_at ON public.recommendation_logs USING btree (created_at);


--
-- Name: ix_rl_shown_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rl_shown_at ON public.recommendation_logs USING btree (shown_at);


--
-- Name: ix_rl_shown_at_subject_scene_strategy; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rl_shown_at_subject_scene_strategy ON public.recommendation_logs USING btree (shown_at, subject_id, scene, strategy);


--
-- Name: ix_rl_user_request; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rl_user_request ON public.recommendation_logs USING btree (user_id, request_id);


--
-- Name: ix_rl_user_scene_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rl_user_scene_created ON public.recommendation_logs USING btree (user_id, scene, created_at);


--
-- Name: ix_rmd_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rmd_date ON public.recommendation_metrics_daily USING btree (date);


--
-- Name: ix_rmd_scene; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rmd_scene ON public.recommendation_metrics_daily USING btree (scene);


--
-- Name: ix_rmd_strategy; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rmd_strategy ON public.recommendation_metrics_daily USING btree (strategy);


--
-- Name: ix_role_permissions_permission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_role_permissions_permission_id ON public.role_permissions USING btree (permission_id);


--
-- Name: ix_sequential_reservations_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sequential_reservations_lookup ON public.sequential_reservations USING btree (user_id, subject_id, scope_key, expires_at);


--
-- Name: ix_sequential_reservations_request; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sequential_reservations_request ON public.sequential_reservations USING btree (user_id, start_request_id);


--
-- Name: ix_study_plan_days_plan_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_study_plan_days_plan_id ON public.study_plan_days USING btree (plan_id);


--
-- Name: ix_study_plans_active_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_study_plans_active_target ON public.study_plans USING btree (is_active, target_date);


--
-- Name: ix_subjects_parent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subjects_parent_id ON public.subjects USING btree (parent_id);


--
-- Name: ix_subjects_path; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subjects_path ON public.subjects USING btree (path);


--
-- Name: ix_syllabus_knowledge_points_knowledge_point_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_syllabus_knowledge_points_knowledge_point_id ON public.syllabus_knowledge_points USING btree (knowledge_point_id);


--
-- Name: ix_syllabus_knowledge_points_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_syllabus_knowledge_points_subject_id ON public.syllabus_knowledge_points USING btree (subject_id);


--
-- Name: ix_syllabus_knowledge_points_syllabus_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_syllabus_knowledge_points_syllabus_version_id ON public.syllabus_knowledge_points USING btree (syllabus_version_id);


--
-- Name: ix_syllabus_kp_mappings_from_kp_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_syllabus_kp_mappings_from_kp_id ON public.syllabus_knowledge_point_mappings USING btree (from_syllabus_knowledge_point_id);


--
-- Name: ix_syllabus_kp_mappings_to_kp_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_syllabus_kp_mappings_to_kp_id ON public.syllabus_knowledge_point_mappings USING btree (to_syllabus_knowledge_point_id);


--
-- Name: ix_syllabus_versions_effective_year; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_syllabus_versions_effective_year ON public.syllabus_versions USING btree (effective_year);


--
-- Name: ix_syllabus_versions_root_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_syllabus_versions_root_subject_id ON public.syllabus_versions USING btree (root_subject_id);


--
-- Name: ix_syllabus_versions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_syllabus_versions_status ON public.syllabus_versions USING btree (status);


--
-- Name: ix_tags_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tags_subject_id ON public.tags USING btree (subject_id);


--
-- Name: ix_tags_sync_uuid; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_tags_sync_uuid ON public.tags USING btree (sync_uuid);


--
-- Name: ix_task_outbox_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_outbox_status ON public.task_outbox USING btree (status);


--
-- Name: ix_task_outbox_type_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_outbox_type_status ON public.task_outbox USING btree (task_type, status);


--
-- Name: ix_uap_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_uap_user_id ON public.user_adaptive_profile USING btree (user_id);


--
-- Name: ix_ukas_kp_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ukas_kp_id ON public.user_knowledge_adaptive_state USING btree (knowledge_point_id);


--
-- Name: ix_ukas_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ukas_user_id ON public.user_knowledge_adaptive_state USING btree (user_id);


--
-- Name: ix_uks_knowledge_point_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_uks_knowledge_point_id ON public.user_knowledge_states USING btree (knowledge_point_id);


--
-- Name: ix_uks_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_uks_user_id ON public.user_knowledge_states USING btree (user_id);


--
-- Name: ix_uks_user_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_uks_user_subject_id ON public.user_knowledge_states USING btree (user_id, subject_id);


--
-- Name: ix_uqds_question_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_uqds_question_id ON public.user_question_difficulty_state USING btree (question_id);


--
-- Name: ix_uqds_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_uqds_user_id ON public.user_question_difficulty_state USING btree (user_id);


--
-- Name: ix_urp_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_urp_user_id ON public.user_recommend_preference USING btree (user_id);


--
-- Name: ix_user_formula_favorites_formula_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_formula_favorites_formula_card_id ON public.user_formula_favorites USING btree (formula_card_id);


--
-- Name: ix_user_formula_favorites_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_formula_favorites_user_id ON public.user_formula_favorites USING btree (user_id);


--
-- Name: ix_user_knowledge_states_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_knowledge_states_subject_id ON public.user_knowledge_states USING btree (subject_id);


--
-- Name: ix_user_question_state_user_next_review; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_question_state_user_next_review ON public.user_question_state USING btree (user_id, next_review_at);


--
-- Name: ix_users_is_banned; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_is_banned ON public.users USING btree (is_banned);


--
-- Name: ix_users_openid; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_openid ON public.users USING btree (openid);


--
-- Name: ix_worker_credentials_worker_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_worker_credentials_worker_id ON public.worker_credentials USING btree (worker_id);


--
-- Name: ix_wq_user_active_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wq_user_active_created ON public.wrong_questions USING btree (user_id, is_active, created_at DESC);


--
-- Name: ix_wq_user_mastered; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wq_user_mastered ON public.wrong_questions USING btree (user_id, mastered);


--
-- Name: ix_wq_user_review_count; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wq_user_review_count ON public.wrong_questions USING btree (user_id, review_count);


--
-- Name: ix_wrong_error_diagnoses_ai_primary; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wrong_error_diagnoses_ai_primary ON public.wrong_question_error_diagnoses USING btree (user_id, ai_primary_type);


--
-- Name: ix_wrong_error_diagnoses_user_occurred; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wrong_error_diagnoses_user_occurred ON public.wrong_question_error_diagnoses USING btree (user_id, occurred_at);


--
-- Name: ix_wrong_error_diagnoses_user_primary; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wrong_error_diagnoses_user_primary ON public.wrong_question_error_diagnoses USING btree (user_id, user_primary_type);


--
-- Name: ix_wrong_error_diagnoses_wq_occurred; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wrong_error_diagnoses_wq_occurred ON public.wrong_question_error_diagnoses USING btree (wrong_question_id, occurred_at);


--
-- Name: ix_wrong_question_error_diagnoses_question_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wrong_question_error_diagnoses_question_id ON public.wrong_question_error_diagnoses USING btree (question_id);


--
-- Name: ix_wrong_question_error_diagnoses_question_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wrong_question_error_diagnoses_question_version_id ON public.wrong_question_error_diagnoses USING btree (question_version_id);


--
-- Name: ix_wrong_question_error_diagnoses_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wrong_question_error_diagnoses_user_id ON public.wrong_question_error_diagnoses USING btree (user_id);


--
-- Name: ix_wrong_question_error_diagnoses_wrong_question_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wrong_question_error_diagnoses_wrong_question_id ON public.wrong_question_error_diagnoses USING btree (wrong_question_id);


--
-- Name: ix_wrong_questions_question_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wrong_questions_question_id ON public.wrong_questions USING btree (question_id);


--
-- Name: ix_wrong_questions_question_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wrong_questions_question_version_id ON public.wrong_questions USING btree (question_version_id);


--
-- Name: ix_wrong_questions_user_active_mastered_review; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wrong_questions_user_active_mastered_review ON public.wrong_questions USING btree (user_id, is_active, mastered, review_count);


--
-- Name: ix_wrong_questions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wrong_questions_user_id ON public.wrong_questions USING btree (user_id);


--
-- Name: uq_exam_attempts_user_paper_in_progress; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_exam_attempts_user_paper_in_progress ON public.exam_attempts USING btree (user_id, paper_id) WHERE ((status)::text = 'in_progress'::text);


--
-- Name: uq_syllabus_versions_one_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_syllabus_versions_one_active ON public.syllabus_versions USING btree (status) WHERE ((status)::text = 'active'::text);


--
-- Name: ux_pomodoro_pause_intervals_one_open; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_pomodoro_pause_intervals_one_open ON public.pomodoro_pause_intervals USING btree (session_id) WHERE (ended_at IS NULL);


--
-- Name: ux_pomodoro_sessions_one_active_per_user; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_pomodoro_sessions_one_active_per_user ON public.pomodoro_sessions USING btree (user_id) WHERE ((status)::text = ANY ((ARRAY['running'::character varying, 'paused'::character varying])::text[]));


--
-- Name: ux_pomodoro_sessions_user_client_start_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_pomodoro_sessions_user_client_start_id ON public.pomodoro_sessions USING btree (user_id, client_start_id) WHERE (client_start_id IS NOT NULL);


--
-- Name: ux_pomodoro_subject_allocations_session_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_pomodoro_subject_allocations_session_code ON public.pomodoro_subject_allocations USING btree (session_id, subject_code_snapshot);


--
-- Name: ux_pomodoro_subject_allocations_session_subject; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_pomodoro_subject_allocations_session_subject ON public.pomodoro_subject_allocations USING btree (session_id, subject_id);


--
-- Name: ux_practice_sessions_user_request; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_practice_sessions_user_request ON public.practice_sessions USING btree (user_id, request_id);


--
-- Name: admin_ai_settings admin_ai_settings_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_ai_settings
    ADD CONSTRAINT admin_ai_settings_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.admin_users(id);


--
-- Name: admin_users admin_users_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_users
    ADD CONSTRAINT admin_users_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id);


--
-- Name: answer_behaviors answer_behaviors_practice_record_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answer_behaviors
    ADD CONSTRAINT answer_behaviors_practice_record_id_fkey FOREIGN KEY (practice_record_id) REFERENCES public.practice_records(id);


--
-- Name: answer_behaviors answer_behaviors_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answer_behaviors
    ADD CONSTRAINT answer_behaviors_question_id_fkey FOREIGN KEY (question_id) REFERENCES public.questions(id);


--
-- Name: answer_behaviors answer_behaviors_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answer_behaviors
    ADD CONSTRAINT answer_behaviors_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: app_user_admin_bindings app_user_admin_bindings_admin_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_user_admin_bindings
    ADD CONSTRAINT app_user_admin_bindings_admin_user_id_fkey FOREIGN KEY (admin_user_id) REFERENCES public.admin_users(id) ON DELETE CASCADE;


--
-- Name: app_user_admin_bindings app_user_admin_bindings_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_user_admin_bindings
    ADD CONSTRAINT app_user_admin_bindings_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.admin_users(id) ON DELETE SET NULL;


--
-- Name: app_user_admin_bindings app_user_admin_bindings_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_user_admin_bindings
    ADD CONSTRAINT app_user_admin_bindings_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: audit_logs audit_logs_operator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_operator_id_fkey FOREIGN KEY (operator_id) REFERENCES public.admin_users(id);


--
-- Name: batch_job_trace_events batch_job_trace_events_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.batch_job_trace_events
    ADD CONSTRAINT batch_job_trace_events_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.import_batch_jobs(job_id);


--
-- Name: exam_answers exam_answers_attempt_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_answers
    ADD CONSTRAINT exam_answers_attempt_id_fkey FOREIGN KEY (attempt_id) REFERENCES public.exam_attempts(id) ON DELETE CASCADE;


--
-- Name: exam_answers exam_answers_exam_paper_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_answers
    ADD CONSTRAINT exam_answers_exam_paper_question_id_fkey FOREIGN KEY (exam_paper_question_id) REFERENCES public.exam_paper_questions(id) ON DELETE RESTRICT;


--
-- Name: exam_answers exam_answers_practice_record_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_answers
    ADD CONSTRAINT exam_answers_practice_record_id_fkey FOREIGN KEY (practice_record_id) REFERENCES public.practice_records(id) ON DELETE SET NULL;


--
-- Name: exam_answers exam_answers_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_answers
    ADD CONSTRAINT exam_answers_question_id_fkey FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE RESTRICT;


--
-- Name: exam_answers exam_answers_question_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_answers
    ADD CONSTRAINT exam_answers_question_version_id_fkey FOREIGN KEY (question_version_id) REFERENCES public.question_versions(id) ON DELETE RESTRICT;


--
-- Name: exam_attempts exam_attempts_paper_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_attempts
    ADD CONSTRAINT exam_attempts_paper_id_fkey FOREIGN KEY (paper_id) REFERENCES public.exam_papers(id) ON DELETE RESTRICT;


--
-- Name: exam_attempts exam_attempts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_attempts
    ADD CONSTRAINT exam_attempts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: exam_paper_questions exam_paper_questions_paper_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_paper_questions
    ADD CONSTRAINT exam_paper_questions_paper_id_fkey FOREIGN KEY (paper_id) REFERENCES public.exam_papers(id) ON DELETE CASCADE;


--
-- Name: exam_paper_questions exam_paper_questions_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_paper_questions
    ADD CONSTRAINT exam_paper_questions_question_id_fkey FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE RESTRICT;


--
-- Name: exam_paper_questions exam_paper_questions_question_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_paper_questions
    ADD CONSTRAINT exam_paper_questions_question_version_id_fkey FOREIGN KEY (question_version_id) REFERENCES public.question_versions(id) ON DELETE RESTRICT;


--
-- Name: exam_paper_questions exam_paper_questions_section_subject_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_paper_questions
    ADD CONSTRAINT exam_paper_questions_section_subject_id_fkey FOREIGN KEY (section_subject_id) REFERENCES public.subjects(id) ON DELETE RESTRICT;


--
-- Name: exam_papers exam_papers_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_papers
    ADD CONSTRAINT exam_papers_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.admin_users(id);


--
-- Name: exam_papers exam_papers_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_papers
    ADD CONSTRAINT exam_papers_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.admin_users(id);


--
-- Name: export_snapshots export_snapshots_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.export_snapshots
    ADD CONSTRAINT export_snapshots_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: export_tasks export_tasks_source_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.export_tasks
    ADD CONSTRAINT export_tasks_source_task_id_fkey FOREIGN KEY (source_task_id) REFERENCES public.export_tasks(id) ON DELETE SET NULL;


--
-- Name: export_tasks export_tasks_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.export_tasks
    ADD CONSTRAINT export_tasks_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: answer_behaviors fk_answer_behaviors_question_version_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answer_behaviors
    ADD CONSTRAINT fk_answer_behaviors_question_version_id FOREIGN KEY (question_version_id) REFERENCES public.question_versions(id);


--
-- Name: answer_behaviors fk_answer_behaviors_subject_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answer_behaviors
    ADD CONSTRAINT fk_answer_behaviors_subject_id FOREIGN KEY (subject_id) REFERENCES public.subjects(id) ON DELETE SET NULL;


--
-- Name: formula_graph_assets fk_formula_graph_assets_reviewed_by_admin_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_graph_assets
    ADD CONSTRAINT fk_formula_graph_assets_reviewed_by_admin_users FOREIGN KEY (reviewed_by) REFERENCES public.admin_users(id);


--
-- Name: import_batch_jobs fk_import_batch_jobs_subject_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_batch_jobs
    ADD CONSTRAINT fk_import_batch_jobs_subject_id FOREIGN KEY (subject_id) REFERENCES public.subjects(id) ON DELETE SET NULL;


--
-- Name: knowledge_edges fk_knowledge_edges_subject_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_edges
    ADD CONSTRAINT fk_knowledge_edges_subject_id FOREIGN KEY (subject_id) REFERENCES public.subjects(id) ON DELETE RESTRICT;


--
-- Name: knowledge_points fk_knowledge_points_subject_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_points
    ADD CONSTRAINT fk_knowledge_points_subject_id FOREIGN KEY (subject_id) REFERENCES public.subjects(id) ON DELETE RESTRICT;


--
-- Name: pomodoro_pause_intervals fk_pomodoro_pause_intervals_session_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pomodoro_pause_intervals
    ADD CONSTRAINT fk_pomodoro_pause_intervals_session_id FOREIGN KEY (session_id) REFERENCES public.pomodoro_sessions(id) ON DELETE CASCADE;


--
-- Name: pomodoro_sessions fk_pomodoro_sessions_subject_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pomodoro_sessions
    ADD CONSTRAINT fk_pomodoro_sessions_subject_id FOREIGN KEY (subject_id) REFERENCES public.subjects(id) ON DELETE SET NULL;


--
-- Name: pomodoro_sessions fk_pomodoro_sessions_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pomodoro_sessions
    ADD CONSTRAINT fk_pomodoro_sessions_user_id FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: practice_records fk_practice_records_question_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.practice_records
    ADD CONSTRAINT fk_practice_records_question_id FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE CASCADE;


--
-- Name: practice_records fk_practice_records_question_version_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.practice_records
    ADD CONSTRAINT fk_practice_records_question_version_id FOREIGN KEY (question_version_id) REFERENCES public.question_versions(id);


--
-- Name: practice_records fk_practice_records_subject_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.practice_records
    ADD CONSTRAINT fk_practice_records_subject_id FOREIGN KEY (subject_id) REFERENCES public.subjects(id) ON DELETE RESTRICT;


--
-- Name: practice_sessions fk_practice_sessions_subject_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.practice_sessions
    ADD CONSTRAINT fk_practice_sessions_subject_id FOREIGN KEY (subject_id) REFERENCES public.subjects(id);


--
-- Name: practice_sessions fk_practice_sessions_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.practice_sessions
    ADD CONSTRAINT fk_practice_sessions_user_id FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: question_embeddings fk_question_embeddings_model; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_embeddings
    ADD CONSTRAINT fk_question_embeddings_model FOREIGN KEY (model_id) REFERENCES public.admin_ai_model_configs(id);


--
-- Name: question_embeddings fk_question_embeddings_subject_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_embeddings
    ADD CONSTRAINT fk_question_embeddings_subject_id FOREIGN KEY (subject_id) REFERENCES public.subjects(id);


--
-- Name: question_imports fk_question_imports_subject_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_imports
    ADD CONSTRAINT fk_question_imports_subject_id FOREIGN KEY (subject_id) REFERENCES public.subjects(id) ON DELETE SET NULL;


--
-- Name: questions fk_questions_current_version_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.questions
    ADD CONSTRAINT fk_questions_current_version_id FOREIGN KEY (current_version_id) REFERENCES public.question_versions(id);


--
-- Name: questions fk_questions_subject_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.questions
    ADD CONSTRAINT fk_questions_subject_id FOREIGN KEY (subject_id) REFERENCES public.subjects(id) ON DELETE SET NULL;


--
-- Name: question_version_knowledge_points fk_qvkp_syllabus_knowledge_point; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_version_knowledge_points
    ADD CONSTRAINT fk_qvkp_syllabus_knowledge_point FOREIGN KEY (syllabus_knowledge_point_id) REFERENCES public.syllabus_knowledge_points(id) ON DELETE RESTRICT;


--
-- Name: recommendation_logs fk_recommendation_logs_subject_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_logs
    ADD CONSTRAINT fk_recommendation_logs_subject_id FOREIGN KEY (subject_id) REFERENCES public.subjects(id) ON DELETE RESTRICT;


--
-- Name: recommendation_metrics_daily fk_recommendation_metrics_daily_subject_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_metrics_daily
    ADD CONSTRAINT fk_recommendation_metrics_daily_subject_id FOREIGN KEY (subject_id) REFERENCES public.subjects(id) ON DELETE RESTRICT;


--
-- Name: review_records fk_review_records_question_version_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_records
    ADD CONSTRAINT fk_review_records_question_version_id FOREIGN KEY (question_version_id) REFERENCES public.question_versions(id);


--
-- Name: review_schedules fk_review_schedules_question_version_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_schedules
    ADD CONSTRAINT fk_review_schedules_question_version_id FOREIGN KEY (question_version_id) REFERENCES public.question_versions(id);


--
-- Name: review_schedules fk_review_schedules_subject_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_schedules
    ADD CONSTRAINT fk_review_schedules_subject_id FOREIGN KEY (subject_id) REFERENCES public.subjects(id) ON DELETE SET NULL;


--
-- Name: review_sessions fk_review_sessions_subject_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_sessions
    ADD CONSTRAINT fk_review_sessions_subject_id FOREIGN KEY (subject_id) REFERENCES public.subjects(id) ON DELETE SET NULL;


--
-- Name: review_sessions fk_review_sessions_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_sessions
    ADD CONSTRAINT fk_review_sessions_user_id FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: tags fk_tags_subject_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tags
    ADD CONSTRAINT fk_tags_subject_id FOREIGN KEY (subject_id) REFERENCES public.subjects(id) ON DELETE RESTRICT;


--
-- Name: user_knowledge_states fk_user_knowledge_states_subject_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_knowledge_states
    ADD CONSTRAINT fk_user_knowledge_states_subject_id FOREIGN KEY (subject_id) REFERENCES public.subjects(id) ON DELETE RESTRICT;


--
-- Name: user_pomodoro_settings fk_user_pomodoro_settings_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_pomodoro_settings
    ADD CONSTRAINT fk_user_pomodoro_settings_user_id FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: users fk_users_banned_by_admin_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT fk_users_banned_by_admin_users FOREIGN KEY (banned_by) REFERENCES public.admin_users(id);


--
-- Name: wrong_questions fk_wrong_questions_question_version_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wrong_questions
    ADD CONSTRAINT fk_wrong_questions_question_version_id FOREIGN KEY (question_version_id) REFERENCES public.question_versions(id);


--
-- Name: formula_card_tags formula_card_tags_formula_card_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_card_tags
    ADD CONSTRAINT formula_card_tags_formula_card_id_fkey FOREIGN KEY (formula_card_id) REFERENCES public.formula_cards(id) ON DELETE CASCADE;


--
-- Name: formula_card_tags formula_card_tags_tag_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_card_tags
    ADD CONSTRAINT formula_card_tags_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES public.formula_tags(id);


--
-- Name: formula_card_versions formula_card_versions_edited_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_card_versions
    ADD CONSTRAINT formula_card_versions_edited_by_fkey FOREIGN KEY (edited_by) REFERENCES public.admin_users(id);


--
-- Name: formula_card_versions formula_card_versions_formula_card_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_card_versions
    ADD CONSTRAINT formula_card_versions_formula_card_id_fkey FOREIGN KEY (formula_card_id) REFERENCES public.formula_cards(id) ON DELETE CASCADE;


--
-- Name: formula_cards formula_cards_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_cards
    ADD CONSTRAINT formula_cards_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.formula_categories(id);


--
-- Name: formula_cards formula_cards_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_cards
    ADD CONSTRAINT formula_cards_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.admin_users(id);


--
-- Name: formula_cards formula_cards_reviewed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_cards
    ADD CONSTRAINT formula_cards_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public.admin_users(id);


--
-- Name: formula_cards formula_cards_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_cards
    ADD CONSTRAINT formula_cards_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.admin_users(id);


--
-- Name: formula_categories formula_categories_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_categories
    ADD CONSTRAINT formula_categories_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.formula_categories(id);


--
-- Name: formula_graph_assets formula_graph_assets_formula_card_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_graph_assets
    ADD CONSTRAINT formula_graph_assets_formula_card_id_fkey FOREIGN KEY (formula_card_id) REFERENCES public.formula_cards(id) ON DELETE CASCADE;


--
-- Name: formula_graph_previews formula_graph_previews_formula_card_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_graph_previews
    ADD CONSTRAINT formula_graph_previews_formula_card_id_fkey FOREIGN KEY (formula_card_id) REFERENCES public.formula_cards(id) ON DELETE CASCADE;


--
-- Name: formula_graph_specs formula_graph_specs_confirmed_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_graph_specs
    ADD CONSTRAINT formula_graph_specs_confirmed_asset_id_fkey FOREIGN KEY (confirmed_asset_id) REFERENCES public.formula_graph_assets(id) ON DELETE SET NULL;


--
-- Name: formula_graph_specs formula_graph_specs_formula_card_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_graph_specs
    ADD CONSTRAINT formula_graph_specs_formula_card_id_fkey FOREIGN KEY (formula_card_id) REFERENCES public.formula_cards(id) ON DELETE CASCADE;


--
-- Name: formula_graph_specs formula_graph_specs_reviewed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_graph_specs
    ADD CONSTRAINT formula_graph_specs_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public.admin_users(id);


--
-- Name: formula_import_items formula_import_items_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_import_items
    ADD CONSTRAINT formula_import_items_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.formula_import_jobs(id) ON DELETE CASCADE;


--
-- Name: formula_import_items formula_import_items_result_card_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_import_items
    ADD CONSTRAINT formula_import_items_result_card_id_fkey FOREIGN KEY (result_card_id) REFERENCES public.formula_cards(id);


--
-- Name: formula_import_items formula_import_items_reviewed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_import_items
    ADD CONSTRAINT formula_import_items_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public.admin_users(id);


--
-- Name: formula_import_jobs formula_import_jobs_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_import_jobs
    ADD CONSTRAINT formula_import_jobs_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.admin_users(id);


--
-- Name: formula_import_jobs formula_import_jobs_retry_of_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_import_jobs
    ADD CONSTRAINT formula_import_jobs_retry_of_fkey FOREIGN KEY (retry_of) REFERENCES public.formula_import_jobs(id);


--
-- Name: import_batch_job_items import_batch_job_items_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_batch_job_items
    ADD CONSTRAINT import_batch_job_items_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.import_batch_jobs(job_id);


--
-- Name: import_pipeline_chunks import_pipeline_chunks_pipeline_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_pipeline_chunks
    ADD CONSTRAINT import_pipeline_chunks_pipeline_id_fkey FOREIGN KEY (pipeline_id) REFERENCES public.import_pipelines(pipeline_id);


--
-- Name: knowledge_edges knowledge_edges_source_knowledge_point_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_edges
    ADD CONSTRAINT knowledge_edges_source_knowledge_point_id_fkey FOREIGN KEY (source_knowledge_point_id) REFERENCES public.knowledge_points(id) ON DELETE CASCADE;


--
-- Name: knowledge_edges knowledge_edges_target_knowledge_point_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_edges
    ADD CONSTRAINT knowledge_edges_target_knowledge_point_id_fkey FOREIGN KEY (target_knowledge_point_id) REFERENCES public.knowledge_points(id) ON DELETE CASCADE;


--
-- Name: pomodoro_subject_allocations pomodoro_subject_allocations_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pomodoro_subject_allocations
    ADD CONSTRAINT pomodoro_subject_allocations_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.pomodoro_sessions(id) ON DELETE CASCADE;


--
-- Name: pomodoro_subject_allocations pomodoro_subject_allocations_subject_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pomodoro_subject_allocations
    ADD CONSTRAINT pomodoro_subject_allocations_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES public.subjects(id) ON DELETE SET NULL;


--
-- Name: practice_records practice_records_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.practice_records
    ADD CONSTRAINT practice_records_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: question_embeddings question_embeddings_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_embeddings
    ADD CONSTRAINT question_embeddings_question_id_fkey FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE CASCADE;


--
-- Name: question_knowledge_points question_knowledge_points_knowledge_point_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_knowledge_points
    ADD CONSTRAINT question_knowledge_points_knowledge_point_id_fkey FOREIGN KEY (knowledge_point_id) REFERENCES public.knowledge_points(id);


--
-- Name: question_knowledge_points question_knowledge_points_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_knowledge_points
    ADD CONSTRAINT question_knowledge_points_question_id_fkey FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE CASCADE;


--
-- Name: question_version_knowledge_points question_version_knowledge_points_knowledge_point_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_version_knowledge_points
    ADD CONSTRAINT question_version_knowledge_points_knowledge_point_id_fkey FOREIGN KEY (knowledge_point_id) REFERENCES public.knowledge_points(id);


--
-- Name: question_version_knowledge_points question_version_knowledge_points_question_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_version_knowledge_points
    ADD CONSTRAINT question_version_knowledge_points_question_version_id_fkey FOREIGN KEY (question_version_id) REFERENCES public.question_versions(id) ON DELETE CASCADE;


--
-- Name: question_versions question_versions_edited_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_versions
    ADD CONSTRAINT question_versions_edited_by_fkey FOREIGN KEY (edited_by) REFERENCES public.admin_users(id);


--
-- Name: recommendation_experiment_assignments recommendation_experiment_assignments_experiment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_experiment_assignments
    ADD CONSTRAINT recommendation_experiment_assignments_experiment_id_fkey FOREIGN KEY (experiment_id) REFERENCES public.recommendation_experiments(id) ON DELETE CASCADE;


--
-- Name: recommendation_experiment_assignments recommendation_experiment_assignments_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_experiment_assignments
    ADD CONSTRAINT recommendation_experiment_assignments_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: recommendation_logs recommendation_logs_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_logs
    ADD CONSTRAINT recommendation_logs_question_id_fkey FOREIGN KEY (question_id) REFERENCES public.questions(id);


--
-- Name: recommendation_logs recommendation_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_logs
    ADD CONSTRAINT recommendation_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: refresh_tokens refresh_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT refresh_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: review_records review_records_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_records
    ADD CONSTRAINT review_records_question_id_fkey FOREIGN KEY (question_id) REFERENCES public.questions(id);


--
-- Name: review_records review_records_schedule_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_records
    ADD CONSTRAINT review_records_schedule_id_fkey FOREIGN KEY (schedule_id) REFERENCES public.review_schedules(id);


--
-- Name: review_records review_records_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_records
    ADD CONSTRAINT review_records_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: review_schedules review_schedules_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_schedules
    ADD CONSTRAINT review_schedules_question_id_fkey FOREIGN KEY (question_id) REFERENCES public.questions(id);


--
-- Name: review_schedules review_schedules_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_schedules
    ADD CONSTRAINT review_schedules_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: role_permissions role_permissions_granted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_granted_by_fkey FOREIGN KEY (granted_by) REFERENCES public.admin_users(id);


--
-- Name: role_permissions role_permissions_permission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_permission_id_fkey FOREIGN KEY (permission_id) REFERENCES public.permissions(id) ON DELETE CASCADE;


--
-- Name: role_permissions role_permissions_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;


--
-- Name: sequential_reservations sequential_reservations_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sequential_reservations
    ADD CONSTRAINT sequential_reservations_question_id_fkey FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE CASCADE;


--
-- Name: sequential_reservations sequential_reservations_subject_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sequential_reservations
    ADD CONSTRAINT sequential_reservations_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES public.subjects(id) ON DELETE CASCADE;


--
-- Name: sequential_reservations sequential_reservations_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sequential_reservations
    ADD CONSTRAINT sequential_reservations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: study_plan_days study_plan_days_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.study_plan_days
    ADD CONSTRAINT study_plan_days_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES public.study_plans(id) ON DELETE CASCADE;


--
-- Name: study_plans study_plans_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.study_plans
    ADD CONSTRAINT study_plans_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: subjects subjects_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subjects
    ADD CONSTRAINT subjects_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.subjects(id);


--
-- Name: syllabus_knowledge_point_mappings syllabus_knowledge_point_mapp_from_syllabus_knowledge_poin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.syllabus_knowledge_point_mappings
    ADD CONSTRAINT syllabus_knowledge_point_mapp_from_syllabus_knowledge_poin_fkey FOREIGN KEY (from_syllabus_knowledge_point_id) REFERENCES public.syllabus_knowledge_points(id) ON DELETE CASCADE;


--
-- Name: syllabus_knowledge_point_mappings syllabus_knowledge_point_mapp_to_syllabus_knowledge_point__fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.syllabus_knowledge_point_mappings
    ADD CONSTRAINT syllabus_knowledge_point_mapp_to_syllabus_knowledge_point__fkey FOREIGN KEY (to_syllabus_knowledge_point_id) REFERENCES public.syllabus_knowledge_points(id) ON DELETE CASCADE;


--
-- Name: syllabus_knowledge_point_mappings syllabus_knowledge_point_mappings_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.syllabus_knowledge_point_mappings
    ADD CONSTRAINT syllabus_knowledge_point_mappings_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.admin_users(id);


--
-- Name: syllabus_knowledge_points syllabus_knowledge_points_knowledge_point_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.syllabus_knowledge_points
    ADD CONSTRAINT syllabus_knowledge_points_knowledge_point_id_fkey FOREIGN KEY (knowledge_point_id) REFERENCES public.knowledge_points(id) ON DELETE RESTRICT;


--
-- Name: syllabus_knowledge_points syllabus_knowledge_points_subject_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.syllabus_knowledge_points
    ADD CONSTRAINT syllabus_knowledge_points_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES public.subjects(id) ON DELETE RESTRICT;


--
-- Name: syllabus_knowledge_points syllabus_knowledge_points_syllabus_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.syllabus_knowledge_points
    ADD CONSTRAINT syllabus_knowledge_points_syllabus_version_id_fkey FOREIGN KEY (syllabus_version_id) REFERENCES public.syllabus_versions(id) ON DELETE CASCADE;


--
-- Name: syllabus_versions syllabus_versions_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.syllabus_versions
    ADD CONSTRAINT syllabus_versions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.admin_users(id);


--
-- Name: syllabus_versions syllabus_versions_root_subject_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.syllabus_versions
    ADD CONSTRAINT syllabus_versions_root_subject_id_fkey FOREIGN KEY (root_subject_id) REFERENCES public.subjects(id) ON DELETE RESTRICT;


--
-- Name: syllabus_versions syllabus_versions_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.syllabus_versions
    ADD CONSTRAINT syllabus_versions_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.admin_users(id);


--
-- Name: user_adaptive_profile user_adaptive_profile_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_adaptive_profile
    ADD CONSTRAINT user_adaptive_profile_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: user_formula_favorites user_formula_favorites_formula_card_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_formula_favorites
    ADD CONSTRAINT user_formula_favorites_formula_card_id_fkey FOREIGN KEY (formula_card_id) REFERENCES public.formula_cards(id) ON DELETE CASCADE;


--
-- Name: user_formula_favorites user_formula_favorites_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_formula_favorites
    ADD CONSTRAINT user_formula_favorites_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_knowledge_adaptive_state user_knowledge_adaptive_state_knowledge_point_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_knowledge_adaptive_state
    ADD CONSTRAINT user_knowledge_adaptive_state_knowledge_point_id_fkey FOREIGN KEY (knowledge_point_id) REFERENCES public.knowledge_points(id);


--
-- Name: user_knowledge_adaptive_state user_knowledge_adaptive_state_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_knowledge_adaptive_state
    ADD CONSTRAINT user_knowledge_adaptive_state_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: user_knowledge_states user_knowledge_states_knowledge_point_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_knowledge_states
    ADD CONSTRAINT user_knowledge_states_knowledge_point_id_fkey FOREIGN KEY (knowledge_point_id) REFERENCES public.knowledge_points(id);


--
-- Name: user_knowledge_states user_knowledge_states_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_knowledge_states
    ADD CONSTRAINT user_knowledge_states_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: user_question_difficulty_state user_question_difficulty_state_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_question_difficulty_state
    ADD CONSTRAINT user_question_difficulty_state_question_id_fkey FOREIGN KEY (question_id) REFERENCES public.questions(id);


--
-- Name: user_question_difficulty_state user_question_difficulty_state_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_question_difficulty_state
    ADD CONSTRAINT user_question_difficulty_state_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: user_question_state user_question_state_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_question_state
    ADD CONSTRAINT user_question_state_question_id_fkey FOREIGN KEY (question_id) REFERENCES public.questions(id);


--
-- Name: user_question_state user_question_state_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_question_state
    ADD CONSTRAINT user_question_state_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: user_recommend_preference user_recommend_preference_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_recommend_preference
    ADD CONSTRAINT user_recommend_preference_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: wrong_question_error_diagnoses wrong_question_error_diagnoses_exam_answer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wrong_question_error_diagnoses
    ADD CONSTRAINT wrong_question_error_diagnoses_exam_answer_id_fkey FOREIGN KEY (exam_answer_id) REFERENCES public.exam_answers(id) ON DELETE SET NULL;


--
-- Name: wrong_question_error_diagnoses wrong_question_error_diagnoses_practice_record_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wrong_question_error_diagnoses
    ADD CONSTRAINT wrong_question_error_diagnoses_practice_record_id_fkey FOREIGN KEY (practice_record_id) REFERENCES public.practice_records(id) ON DELETE SET NULL;


--
-- Name: wrong_question_error_diagnoses wrong_question_error_diagnoses_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wrong_question_error_diagnoses
    ADD CONSTRAINT wrong_question_error_diagnoses_question_id_fkey FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE RESTRICT;


--
-- Name: wrong_question_error_diagnoses wrong_question_error_diagnoses_question_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wrong_question_error_diagnoses
    ADD CONSTRAINT wrong_question_error_diagnoses_question_version_id_fkey FOREIGN KEY (question_version_id) REFERENCES public.question_versions(id) ON DELETE RESTRICT;


--
-- Name: wrong_question_error_diagnoses wrong_question_error_diagnoses_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wrong_question_error_diagnoses
    ADD CONSTRAINT wrong_question_error_diagnoses_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: wrong_question_error_diagnoses wrong_question_error_diagnoses_wrong_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wrong_question_error_diagnoses
    ADD CONSTRAINT wrong_question_error_diagnoses_wrong_question_id_fkey FOREIGN KEY (wrong_question_id) REFERENCES public.wrong_questions(id) ON DELETE CASCADE;


--
-- Name: wrong_questions wrong_questions_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wrong_questions
    ADD CONSTRAINT wrong_questions_question_id_fkey FOREIGN KEY (question_id) REFERENCES public.questions(id);


--
-- Name: wrong_questions wrong_questions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wrong_questions
    ADD CONSTRAINT wrong_questions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- PostgreSQL database dump complete
--

\unrestrict 03zUVBZ8Zb5Xi1yETFv2BAguLFr7wVy3lEB8AZqD08p3xD6IujGfEKljbzq5SRW

