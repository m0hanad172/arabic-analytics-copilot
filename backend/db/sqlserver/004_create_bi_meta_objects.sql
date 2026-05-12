/*
 * 004_create_bi_meta_objects.sql  (Phase C3)
 *
 * Metadata tables consumed by the Python semantic compiler and the
 * /ask cache/log paths.
 *
 * Idempotent. Run while connected to ArabicAnalytics.
 */
USE ArabicAnalytics;
GO

-- ---------------------------------------------------------------------------
-- bi_meta.metrics
-- ---------------------------------------------------------------------------
IF OBJECT_ID(N'bi_meta.metrics', N'U') IS NULL
BEGIN
    PRINT N'Creating table bi_meta.metrics...';
    CREATE TABLE bi_meta.metrics
    (
        metric_key       NVARCHAR(128) NOT NULL CONSTRAINT PK_bi_meta_metrics PRIMARY KEY,
        display_name_ar  NVARCHAR(400) NOT NULL,
        display_name_en  NVARCHAR(400) NOT NULL,
        agg              NVARCHAR(32)  NOT NULL,
        sql_expression   NVARCHAR(MAX) NOT NULL,
        data_type        NVARCHAR(64)  NOT NULL,
        format_hint      NVARCHAR(128) NULL
    );
END
ELSE
BEGIN
    PRINT N'Table bi_meta.metrics already exists; skipping CREATE.';
END
GO

-- ---------------------------------------------------------------------------
-- bi_meta.dimensions
-- ---------------------------------------------------------------------------
IF OBJECT_ID(N'bi_meta.dimensions', N'U') IS NULL
BEGIN
    PRINT N'Creating table bi_meta.dimensions...';
    CREATE TABLE bi_meta.dimensions
    (
        dim_key          NVARCHAR(128) NOT NULL CONSTRAINT PK_bi_meta_dimensions PRIMARY KEY,
        display_name_ar  NVARCHAR(400) NOT NULL,
        display_name_en  NVARCHAR(400) NOT NULL,
        sql_expression   NVARCHAR(MAX) NOT NULL,
        data_type        NVARCHAR(64)  NOT NULL,
        allowed_grouping BIT           NOT NULL CONSTRAINT DF_bi_meta_dim_allowed_grouping DEFAULT (1)
    );
END
ELSE
BEGIN
    PRINT N'Table bi_meta.dimensions already exists; skipping CREATE.';
END
GO

-- ---------------------------------------------------------------------------
-- bi_meta.synonyms
-- ---------------------------------------------------------------------------
IF OBJECT_ID(N'bi_meta.synonyms', N'U') IS NULL
BEGIN
    PRINT N'Creating table bi_meta.synonyms...';
    CREATE TABLE bi_meta.synonyms
    (
        term         NVARCHAR(400) NOT NULL,
        maps_to_type NVARCHAR(32)  NOT NULL,  -- 'metric' | 'dimension'
        maps_to_key  NVARCHAR(128) NOT NULL,
        CONSTRAINT PK_bi_meta_synonyms PRIMARY KEY (term)
    );
END
ELSE
BEGIN
    PRINT N'Table bi_meta.synonyms already exists; skipping CREATE.';
END
GO

-- ---------------------------------------------------------------------------
-- bi_meta.plan_cache (Phase C3 creates the table; Phase C4 will wire upsert)
-- ---------------------------------------------------------------------------
IF OBJECT_ID(N'bi_meta.plan_cache', N'U') IS NULL
BEGIN
    PRINT N'Creating table bi_meta.plan_cache...';
    CREATE TABLE bi_meta.plan_cache
    (
        id              BIGINT IDENTITY(1, 1) NOT NULL
            CONSTRAINT PK_bi_meta_plan_cache PRIMARY KEY,
        question_norm   NVARCHAR(2000) NOT NULL,
        question_raw    NVARCHAR(MAX)  NOT NULL,
        catalog_hash    NVARCHAR(128)  NOT NULL,
        plan            NVARCHAR(MAX)  NOT NULL, -- JSON string
        model           NVARCHAR(128)  NOT NULL,
        hits            BIGINT         NOT NULL CONSTRAINT DF_bi_meta_plan_cache_hits         DEFAULT (0),
        created_at      DATETIMEOFFSET NOT NULL CONSTRAINT DF_bi_meta_plan_cache_created_at   DEFAULT (SYSUTCDATETIME()),
        updated_at      DATETIMEOFFSET NOT NULL CONSTRAINT DF_bi_meta_plan_cache_updated_at   DEFAULT (SYSUTCDATETIME()),
        last_used_at    DATETIMEOFFSET NOT NULL CONSTRAINT DF_bi_meta_plan_cache_last_used_at DEFAULT (SYSUTCDATETIME())
    );

    CREATE UNIQUE INDEX UX_bi_meta_plan_cache_question_catalog
        ON bi_meta.plan_cache (question_norm, catalog_hash);
END
ELSE
BEGIN
    PRINT N'Table bi_meta.plan_cache already exists; skipping CREATE.';
END
GO

-- ---------------------------------------------------------------------------
-- bi_meta.query_log
-- ---------------------------------------------------------------------------
IF OBJECT_ID(N'bi_meta.query_log', N'U') IS NULL
BEGIN
    PRINT N'Creating table bi_meta.query_log...';
    CREATE TABLE bi_meta.query_log
    (
        id           BIGINT IDENTITY(1, 1) NOT NULL
            CONSTRAINT PK_bi_meta_query_log PRIMARY KEY,
        created_at   DATETIMEOFFSET NOT NULL CONSTRAINT DF_bi_meta_query_log_created_at DEFAULT (SYSUTCDATETIME()),
        question     NVARCHAR(MAX)  NOT NULL,
        plan         NVARCHAR(MAX)  NOT NULL,  -- JSON string
        sql          NVARCHAR(MAX)  NOT NULL,
        row_count    INT            NOT NULL CONSTRAINT DF_bi_meta_query_log_row_count   DEFAULT (0),
        warnings     NVARCHAR(MAX)  NULL,
        suggestions  NVARCHAR(MAX)  NULL,
        duration_ms  INT            NOT NULL CONSTRAINT DF_bi_meta_query_log_duration_ms DEFAULT (0),
        used_cache   BIT            NOT NULL CONSTRAINT DF_bi_meta_query_log_used_cache  DEFAULT (0),
        used_llm     BIT            NOT NULL CONSTRAINT DF_bi_meta_query_log_used_llm    DEFAULT (0),
        explain_used BIT            NOT NULL CONSTRAINT DF_bi_meta_query_log_explain_used DEFAULT (0)
    );
END
ELSE
BEGIN
    PRINT N'Table bi_meta.query_log already exists; skipping CREATE.';
END
GO
