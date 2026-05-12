/*
 * 003_create_bi_objects.sql  (Phase C3)
 *
 * Analytical fact table + the cleaned view used by /ask.
 * Mirrors the columns the PostgreSQL bi.vw_fact_sales_line_clean view
 * exposes today. Idempotent.
 *
 * Type mapping:
 *   text     -> NVARCHAR(400)
 *   integer  -> INT
 *   date     -> DATE
 *   numeric  -> DECIMAL(38, 6)
 */
USE ArabicAnalytics;
GO

-- ---------------------------------------------------------------------------
-- bi.fact_sales_line: base table, mirrors PG bi.fact_sales_line columns
-- ---------------------------------------------------------------------------
IF OBJECT_ID(N'bi.fact_sales_line', N'U') IS NULL
BEGIN
    PRINT N'Creating table bi.fact_sales_line...';
    CREATE TABLE bi.fact_sales_line
    (
        order_no               NVARCHAR(400)  NULL,
        order_date             DATE           NULL,
        ship_date              DATE           NULL,
        ship_delay_days        INT            NULL,
        customer_type          NVARCHAR(400)  NULL,
        account_manager        NVARCHAR(400)  NULL,
        order_priority         NVARCHAR(400)  NULL,
        product_name           NVARCHAR(400)  NULL,
        product_category       NVARCHAR(400)  NULL,
        product_container      NVARCHAR(400)  NULL,
        ship_mode              NVARCHAR(400)  NULL,
        city                   NVARCHAR(400)  NULL,
        state                  NVARCHAR(400)  NULL,
        cost_price             DECIMAL(38, 6) NULL,
        retail_price           DECIMAL(38, 6) NULL,
        order_quantity         INT            NULL,
        sub_total              DECIMAL(38, 6) NULL,
        discount_pct           DECIMAL(38, 6) NULL,
        discount_amount        DECIMAL(38, 6) NULL,
        order_total            DECIMAL(38, 6) NULL,
        shipping_cost          DECIMAL(38, 6) NULL,
        total                  DECIMAL(38, 6) NULL,
        cogs                   DECIMAL(38, 6) NULL,
        gross_profit           DECIMAL(38, 6) NULL,
        profit_after_shipping  DECIMAL(38, 6) NULL,
        order_year             INT            NULL,
        order_month            INT            NULL,
        order_quarter          INT            NULL
    );
END
ELSE
BEGIN
    PRINT N'Table bi.fact_sales_line already exists; skipping CREATE.';
END
GO

-- ---------------------------------------------------------------------------
-- Ensure every business column is nullable.
--
-- SSMS *Import Flat File...* fails with "Column '<x>' does not allow
-- DBNull.Value" when the destination column is NOT NULL but the CSV
-- has any blank cell in that column. We declare every business
-- column as NULL above, but a previously-created table from an older
-- draft of this script may have NOT NULL constraints baked in.
-- ALTER COLUMN ... NULL is idempotent (a no-op when the column is
-- already nullable) and runs against the existing table without
-- requiring a drop.
-- ---------------------------------------------------------------------------
PRINT N'Ensuring bi.fact_sales_line business columns are nullable...';
ALTER TABLE bi.fact_sales_line ALTER COLUMN order_no              NVARCHAR(400)  NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN order_date            DATE           NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN ship_date             DATE           NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN ship_delay_days       INT            NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN customer_type         NVARCHAR(400)  NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN account_manager       NVARCHAR(400)  NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN order_priority        NVARCHAR(400)  NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN product_name          NVARCHAR(400)  NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN product_category      NVARCHAR(400)  NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN product_container     NVARCHAR(400)  NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN ship_mode             NVARCHAR(400)  NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN city                  NVARCHAR(400)  NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN state                 NVARCHAR(400)  NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN cost_price            DECIMAL(38, 6) NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN retail_price          DECIMAL(38, 6) NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN order_quantity        INT            NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN sub_total             DECIMAL(38, 6) NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN discount_pct          DECIMAL(38, 6) NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN discount_amount       DECIMAL(38, 6) NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN order_total           DECIMAL(38, 6) NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN shipping_cost         DECIMAL(38, 6) NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN total                 DECIMAL(38, 6) NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN cogs                  DECIMAL(38, 6) NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN gross_profit          DECIMAL(38, 6) NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN profit_after_shipping DECIMAL(38, 6) NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN order_year            INT            NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN order_month           INT            NULL;
ALTER TABLE bi.fact_sales_line ALTER COLUMN order_quarter         INT            NULL;
GO

-- Helpful index for date filters in /ask.
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'IX_fact_sales_line_order_date'
      AND object_id = OBJECT_ID(N'bi.fact_sales_line')
)
BEGIN
    PRINT N'Creating index IX_fact_sales_line_order_date...';
    CREATE INDEX IX_fact_sales_line_order_date
        ON bi.fact_sales_line (order_date);
END
GO

-- ---------------------------------------------------------------------------
-- bi.vw_fact_sales_line_clean: view exposing the columns the catalog/compiler
-- reference. Aliases order_date -> order_date_d and ship_date -> ship_date_d
-- to match the PostgreSQL view, and surfaces the year/month/quarter columns.
-- ---------------------------------------------------------------------------
IF OBJECT_ID(N'bi.vw_fact_sales_line_clean', N'V') IS NOT NULL
    DROP VIEW bi.vw_fact_sales_line_clean;
GO

CREATE VIEW bi.vw_fact_sales_line_clean
AS
SELECT
    order_no,
    order_date            AS order_date_d,
    ship_date             AS ship_date_d,
    ship_delay_days,
    customer_type,
    account_manager,
    order_priority,
    product_name,
    product_category,
    product_container,
    ship_mode,
    city,
    state,
    cost_price,
    retail_price,
    order_quantity,
    sub_total,
    discount_pct,
    discount_amount,
    order_total,
    shipping_cost,
    total,
    cogs,
    gross_profit,
    profit_after_shipping,
    order_year,
    order_month,
    order_quarter
FROM bi.fact_sales_line;
GO

PRINT N'bi.vw_fact_sales_line_clean created.';
GO
