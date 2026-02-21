-- db_bootstrap.sql (Phase 4 compatible)
-- Loads CSV into bi.raw_sales then builds safe bi.fact_sales_line + views.

-- 0) Roles (dev defaults) - safe to rerun
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'copilot_loader') THEN
    CREATE ROLE copilot_loader LOGIN PASSWORD 'ChangeMe_Strong!';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'copilot_ro') THEN
    CREATE ROLE copilot_ro LOGIN PASSWORD 'ChangeMe_Strong_RO!';
  END IF;
END $$;

-- Allow both users to connect to this DB
GRANT CONNECT ON DATABASE arabic_analytics TO copilot_loader;
GRANT CONNECT ON DATABASE arabic_analytics TO copilot_ro;

-- 1) Rebuild BI schema cleanly (recommended for restore)
DROP SCHEMA IF EXISTS bi CASCADE;
CREATE SCHEMA bi;

-- 2) RAW table exactly matching CSV header (includes PII + quality flags)
CREATE TABLE bi.raw_sales (
  order_no text,
  order_date date,
  ship_date date,
  ship_delay_days int,
  customer_name text,
  address text,
  city text,
  state text,
  customer_type text,
  account_manager text,
  order_priority text,
  product_name text,
  product_category text,
  product_container text,
  ship_mode text,
  order_quantity int,
  cost_price numeric,
  retail_price numeric,
  discount_pct numeric,
  shipping_cost numeric,
  sub_total numeric,
  discount_amount numeric,
  order_total numeric,
  total numeric,
  cogs numeric,
  gross_profit numeric,
  profit_after_shipping numeric,
  sub_total_raw numeric,
  discount_amount_raw numeric,
  order_total_raw numeric,
  total_raw numeric,
  order_year int,
  order_month int,
  order_quarter int,
  q_ship_before_order boolean,
  q_discount_pct_bad boolean,
  q_sub_total_mismatch boolean,
  q_discount_amount_mismatch boolean,
  q_order_total_mismatch boolean,
  q_total_mismatch boolean,
  q_profit_margin_mismatch boolean
);

-- 3) Load CSV into RAW (file must exist inside container)
TRUNCATE bi.raw_sales;
\copy bi.raw_sales FROM '/tmp/bi_ready_clean.csv' WITH (FORMAT csv, HEADER true);

-- 4) SAFE fact table (no PII, no raw/q_ flags)
CREATE TABLE bi.fact_sales_line (
  order_no text,
  order_date date,
  ship_date date,
  ship_delay_days int,

  customer_type text,
  account_manager text,
  order_priority text,

  product_name text,
  product_category text,
  product_container text,

  ship_mode text,

  city text,
  state text,

  cost_price numeric,
  retail_price numeric,
  order_quantity int,

  sub_total numeric,
  discount_pct numeric,
  discount_amount numeric,
  order_total numeric,
  shipping_cost numeric,
  total numeric,

  cogs numeric,
  gross_profit numeric,
  profit_after_shipping numeric,

  order_year int,
  order_month int,
  order_quarter int
);

TRUNCATE bi.fact_sales_line;

INSERT INTO bi.fact_sales_line (
  order_no, order_date, ship_date, ship_delay_days,
  customer_type, account_manager, order_priority,
  product_name, product_category, product_container,
  ship_mode, city, state,
  cost_price, retail_price, order_quantity,
  sub_total, discount_pct, discount_amount, order_total,
  shipping_cost, total,
  cogs, gross_profit, profit_after_shipping,
  order_year, order_month, order_quarter
)
SELECT
  order_no,
  order_date,
  ship_date,
  ship_delay_days,
  customer_type,
  account_manager,
  order_priority,
  product_name,
  product_category,
  product_container,
  ship_mode,
  btrim(city)  AS city,
  btrim(state) AS state,
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
FROM bi.raw_sales;

-- 5) Indexes
CREATE INDEX IF NOT EXISTS idx_fact_order_date ON bi.fact_sales_line(order_date);
CREATE INDEX IF NOT EXISTS idx_fact_year_month ON bi.fact_sales_line(order_year, order_month);
CREATE INDEX IF NOT EXISTS idx_fact_product_category ON bi.fact_sales_line(product_category);
CREATE INDEX IF NOT EXISTS idx_fact_city_state ON bi.fact_sales_line(state, city);
CREATE INDEX IF NOT EXISTS idx_fact_ship_mode ON bi.fact_sales_line(ship_mode);

-- 6) Base clean view (this is what bi_meta functions expect)
CREATE OR REPLACE VIEW bi.vw_fact_sales_line_clean AS
SELECT
  order_no,
  order_date::date AS order_date_d,
  ship_date::date  AS ship_date_d,
  ship_delay_days::int AS ship_delay_days,

  customer_type,
  account_manager,
  order_priority,

  product_name,
  product_category,
  product_container,

  ship_mode,

  btrim(city)  AS city,
  btrim(state) AS state,

  cost_price::numeric AS cost_price,
  retail_price::numeric AS retail_price,
  order_quantity::int AS order_quantity,

  sub_total::numeric AS sub_total,
  discount_pct::numeric AS discount_pct,
  discount_amount::numeric AS discount_amount,
  order_total::numeric AS order_total,
  shipping_cost::numeric AS shipping_cost,
  total::numeric AS total,

  cogs::numeric AS cogs,
  gross_profit::numeric AS gross_profit,
  profit_after_shipping::numeric AS profit_after_shipping,

  order_year::int AS order_year,
  order_month::int AS order_month,
  order_quarter::int AS order_quarter
FROM bi.fact_sales_line;

-- 7) SAFE semantic views (what your app can see)
CREATE OR REPLACE VIEW bi.vw_sales_monthly AS
SELECT
  order_year,
  order_month,
  make_date(order_year, order_month, 1) AS month_start,
  SUM(sub_total) AS gross_sales,
  SUM(discount_amount) AS discounts,
  SUM(order_total) AS net_sales,
  SUM(cogs) AS cogs,
  SUM(gross_profit) AS gross_profit,
  SUM(shipping_cost) AS shipping_cost,
  SUM(profit_after_shipping) AS profit_after_shipping,
  COUNT(*) AS line_count
FROM bi.fact_sales_line
GROUP BY order_year, order_month;

CREATE OR REPLACE VIEW bi.vw_sales_by_product AS
SELECT
  product_name,
  product_category,
  SUM(order_total) AS net_sales,
  SUM(sub_total) AS gross_sales,
  SUM(discount_amount) AS discounts,
  SUM(gross_profit) AS gross_profit,
  SUM(profit_after_shipping) AS profit_after_shipping,
  SUM(order_quantity) AS units,
  COUNT(*) AS line_count
FROM bi.fact_sales_line
GROUP BY product_name, product_category;

CREATE OR REPLACE VIEW bi.vw_sales_by_category AS
SELECT
  product_category,
  SUM(order_total) AS net_sales,
  SUM(gross_profit) AS gross_profit,
  SUM(profit_after_shipping) AS profit_after_shipping,
  SUM(order_quantity) AS units,
  AVG(discount_pct) AS avg_discount_pct,
  SUM(discount_amount) AS discounts
FROM bi.fact_sales_line
GROUP BY product_category;

CREATE OR REPLACE VIEW bi.vw_sales_by_region AS
SELECT
  state,
  city,
  SUM(order_total) AS net_sales,
  SUM(gross_profit) AS gross_profit,
  SUM(profit_after_shipping) AS profit_after_shipping,
  SUM(order_quantity) AS units,
  COUNT(*) AS line_count
FROM bi.fact_sales_line
GROUP BY state, city;

CREATE OR REPLACE VIEW bi.vw_shipping_kpis AS
SELECT
  ship_mode,
  AVG(ship_delay_days::numeric) AS avg_ship_delay_days,
  AVG(shipping_cost) AS avg_shipping_cost,
  SUM(shipping_cost) AS total_shipping_cost,
  COUNT(*) AS line_count
FROM bi.fact_sales_line
GROUP BY ship_mode;

-- 8) Permissions (Policy B)
REVOKE ALL ON SCHEMA bi FROM PUBLIC;
GRANT USAGE ON SCHEMA bi TO copilot_ro;

-- deny tables (raw + fact)
REVOKE ALL ON bi.raw_sales FROM copilot_ro;
REVOKE ALL ON bi.fact_sales_line FROM copilot_ro;

-- allow views only
GRANT SELECT ON bi.vw_fact_sales_line_clean,
               bi.vw_sales_monthly,
               bi.vw_sales_by_product,
               bi.vw_sales_by_category,
               bi.vw_sales_by_region,
               bi.vw_shipping_kpis
TO copilot_ro;

-- Loader can manage schema objects (optional but useful)
GRANT USAGE ON SCHEMA bi TO copilot_loader;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA bi TO copilot_loader;
ALTER DEFAULT PRIVILEGES IN SCHEMA bi
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO copilot_loader;
