-- =========================================================
-- Arabic Analytics Copilot - Phase 4 DB Bootstrap (Meta)
-- هدفه: إنشاء bi_meta + vw_fact_sales_line_clean + get_catalog(schema)
-- DB: arabic_analytics
-- =========================================================

\set ON_ERROR_STOP on

-- 1) Base clean view expected by meta expressions (alias f)
-- IMPORTANT: keep column order stable (matches db_bootstrap view)
CREATE OR REPLACE VIEW bi.vw_fact_sales_line_clean AS
SELECT
  order_no,
  order_date::date AS order_date_d,

  ship_date::date AS ship_date_d,
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

-- 2) Meta schema
CREATE SCHEMA IF NOT EXISTS bi_meta;

-- Metrics
CREATE TABLE IF NOT EXISTS bi_meta.metrics (
  metric_key        text PRIMARY KEY,
  display_name_ar   text NOT NULL,
  display_name_en   text NOT NULL,
  agg               text NOT NULL,      -- sum|avg|count
  sql_expression    text NOT NULL,      -- SQL snippet using alias f
  data_type         text NOT NULL,      -- numeric|bigint|text
  format_hint       text NULL           -- money|number|percent|days
);

-- Dimensions
CREATE TABLE IF NOT EXISTS bi_meta.dimensions (
  dim_key          text PRIMARY KEY,
  display_name_ar  text NOT NULL,
  display_name_en  text NOT NULL,
  sql_expression   text NOT NULL,       -- SQL snippet using alias f
  data_type        text NOT NULL,       -- text|date|integer
  allowed_grouping boolean NOT NULL DEFAULT true
);

-- Synonyms
CREATE TABLE IF NOT EXISTS bi_meta.synonyms (
  term            text PRIMARY KEY,
  maps_to_type    text NOT NULL,        -- metric|dimension|filter_value
  maps_to_key     text NOT NULL
);

-- 3) Seed Metrics (include BOTH discounts + discount_amount)
INSERT INTO bi_meta.metrics
(metric_key, display_name_ar, display_name_en, agg, sql_expression, data_type, format_hint)
VALUES
('net_sales',            'صافي المبيعات',           'Net Sales',             'sum',   'sum(f.order_total::numeric)',            'numeric', 'money'),
('gross_sales',          'إجمالي المبيعات',         'Gross Sales',           'sum',   'sum(f.sub_total::numeric)',              'numeric', 'money'),

('discount_amount',      'إجمالي الخصومات',         'Discount Amount',       'sum',   'sum(f.discount_amount::numeric)',        'numeric', 'money'),
('discounts',            'إجمالي الخصومات',         'Discounts',             'sum',   'sum(f.discount_amount::numeric)',        'numeric', 'money'),

('cogs',                 'تكلفة البضاعة',           'COGS',                  'sum',   'sum(f.cogs::numeric)',                   'numeric', 'money'),
('gross_profit',         'الربح الإجمالي',          'Gross Profit',          'sum',   'sum(f.gross_profit::numeric)',           'numeric', 'money'),
('shipping_cost',        'تكلفة الشحن',             'Shipping Cost',         'sum',   'sum(f.shipping_cost::numeric)',          'numeric', 'money'),
('profit_after_shipping','الربح بعد الشحن',         'Profit After Shipping', 'sum',   'sum(f.profit_after_shipping::numeric)',  'numeric', 'money'),

('units',                'الوحدات',                 'Units',                 'sum',   'sum(f.order_quantity::numeric)',         'numeric', 'number'),
('line_count',           'عدد السطور',              'Line Count',            'count', 'count(*)::bigint',                       'bigint',  'number'),

('avg_discount_pct',     'متوسط نسبة الخصم',        'Avg Discount %',        'avg',   'avg(f.discount_pct::numeric)',           'numeric', 'percent'),
('avg_ship_delay_days',  'متوسط تأخير الشحن (يوم)', 'Avg Ship Delay (days)', 'avg',   'avg(f.ship_delay_days::numeric)',        'numeric', 'days')
ON CONFLICT (metric_key) DO NOTHING;

-- 4) Seed Dimensions (match your Phase-4 plan usage)
INSERT INTO bi_meta.dimensions
(dim_key, display_name_ar, display_name_en, sql_expression, data_type, allowed_grouping)
VALUES
('order_date',      'تاريخ الطلب',   'Order Date',   'f.order_date_d',                                'date',    true),
('month_start',     'بداية الشهر',   'Month Start',  'date_trunc(''month'', f.order_date_d)::date',    'date',    true),
('order_year',      'السنة',         'Year',         'extract(year from f.order_date_d)::int',         'integer', true),
('order_month',     'الشهر',         'Month',        'extract(month from f.order_date_d)::int',        'integer', true),
('order_quarter',   'الربع',         'Quarter',      'extract(quarter from f.order_date_d)::int',      'integer', true),

('state',           'الولاية',       'State',        'f.state',                                        'text',    true),
('city',            'المدينة',       'City',         'f.city',                                         'text',    true),

('product_category','فئة المنتج',    'Product Category', 'f.product_category',                         'text',    true),
('product_name',    'اسم المنتج',    'Product Name', 'f.product_name',                                 'text',    true),

('ship_mode',       'طريقة الشحن',   'Ship Mode',    'f.ship_mode',                                    'text',    true),
('customer_type',   'نوع العميل',    'Customer Type','f.customer_type',                                'text',    true),
('account_manager', 'مسؤول الحساب',  'Account Manager','f.account_manager',                            'text',    true),
('order_priority',  'أولوية الطلب',  'Order Priority','f.order_priority',                              'text',    true)
ON CONFLICT (dim_key) DO NOTHING;

-- 5) Seed Synonyms (Arabic + English)
INSERT INTO bi_meta.synonyms (term, maps_to_type, maps_to_key)
VALUES
-- metrics
('صافي المبيعات','metric','net_sales'),
('المبيعات الصافية','metric','net_sales'),
('net sales','metric','net_sales'),

('إجمالي المبيعات','metric','gross_sales'),
('gross sales','metric','gross_sales'),

('إجمالي الخصومات','metric','discount_amount'),
('الخصومات','metric','discount_amount'),
('خصومات','metric','discount_amount'),
('discounts','metric','discount_amount'),
('discount amount','metric','discount_amount'),

('COGS','metric','cogs'),
('تكلفة البضاعة','metric','cogs'),
('تكلفة البضاعة المباعة','metric','cogs'),
('cost of goods sold','metric','cogs'),

('الربح الإجمالي','metric','gross_profit'),
('gross profit','metric','gross_profit'),

('تكلفة الشحن','metric','shipping_cost'),
('shipping cost','metric','shipping_cost'),

('الربح بعد الشحن','metric','profit_after_shipping'),
('profit after shipping','metric','profit_after_shipping'),

('الوحدات','metric','units'),
('الكمية','metric','units'),
('units','metric','units'),

('عدد السطور','metric','line_count'),
('عدد الطلبات','metric','line_count'),
('line count','metric','line_count'),

('متوسط نسبة الخصم','metric','avg_discount_pct'),
('avg discount','metric','avg_discount_pct'),
('average discount','metric','avg_discount_pct'),

('تأخير الشحن','metric','avg_ship_delay_days'),
('متوسط تأخير الشحن','metric','avg_ship_delay_days'),
('ship delay','metric','avg_ship_delay_days'),
('average ship delay','metric','avg_ship_delay_days'),

-- dimensions
('المدينة','dimension','city'),
('مدينة','dimension','city'),
('city','dimension','city'),

('الولاية','dimension','state'),
('ولاية','dimension','state'),
('state','dimension','state'),

('فئة المنتج','dimension','product_category'),
('فئة','dimension','product_category'),
('category','dimension','product_category'),

('المنتج','dimension','product_name'),
('product','dimension','product_name'),

('طريقة الشحن','dimension','ship_mode'),
('الشحن','dimension','ship_mode'),
('ship mode','dimension','ship_mode'),

('الشهر','dimension','month_start'),
('شهري','dimension','month_start'),
('month','dimension','month_start'),

('السنة','dimension','order_year'),
('year','dimension','order_year'),

('الربع','dimension','order_quarter'),
('quarter','dimension','order_quarter')
ON CONFLICT (term) DO NOTHING;

-- 6) get_catalog(schema text) REQUIRED by backend (it calls get_catalog($1))
CREATE OR REPLACE FUNCTION bi_meta.get_catalog(p_schema text)
RETURNS jsonb
LANGUAGE sql
AS $$
SELECT jsonb_build_object(
  'schema', p_schema,
  'base_view', 'bi.vw_fact_sales_line_clean',
  'metrics', (
    SELECT jsonb_agg(jsonb_build_object(
      'key', metric_key,
      'name_ar', display_name_ar,
      'name_en', display_name_en,
      'agg', agg,
      'sql', sql_expression,
      'data_type', data_type,
      'format', format_hint
    ) ORDER BY metric_key)
    FROM bi_meta.metrics
  ),
  'dimensions', (
    SELECT jsonb_agg(jsonb_build_object(
      'key', dim_key,
      'name_ar', display_name_ar,
      'name_en', display_name_en,
      'sql', sql_expression,
      'data_type', data_type,
      'allowed_grouping', allowed_grouping
    ) ORDER BY dim_key)
    FROM bi_meta.dimensions
  ),
  'synonyms', (
    SELECT jsonb_agg(jsonb_build_object(
      'term', term,
      'type', maps_to_type,
      'key', maps_to_key
    ) ORDER BY term)
    FROM bi_meta.synonyms
  )
);
$$;

INSERT INTO bi_meta.metrics (
  metric_key,
  display_name_ar,
  display_name_en,
  agg,
  sql_expression,
  data_type,
  format_hint
)
VALUES (
  'order_count',
  'عدد السطور',
  'Row Count',
  'count',
  'COUNT(*)::bigint',
  'integer',
  NULL
)
ON CONFLICT (metric_key) DO UPDATE
SET
  display_name_ar = EXCLUDED.display_name_ar,
  display_name_en = EXCLUDED.display_name_en,
  agg            = EXCLUDED.agg,
  sql_expression = EXCLUDED.sql_expression,
  data_type      = EXCLUDED.data_type,
  format_hint    = EXCLUDED.format_hint;

-- Optional convenience wrapper
CREATE OR REPLACE FUNCTION bi_meta.get_catalog()
RETURNS jsonb
LANGUAGE sql
AS $$ SELECT bi_meta.get_catalog('bi'); $$;

-- 7) Permissions: app user can read catalog + views only
-- (Adjust usernames if yours differ)
GRANT USAGE ON SCHEMA bi_meta TO copilot_ro;
GRANT SELECT ON bi_meta.metrics, bi_meta.dimensions, bi_meta.synonyms TO copilot_ro;
GRANT EXECUTE ON FUNCTION bi_meta.get_catalog(text) TO copilot_ro;
GRANT EXECUTE ON FUNCTION bi_meta.get_catalog() TO copilot_ro;

-- Also ensure base view is readable
GRANT USAGE ON SCHEMA bi TO copilot_ro;
GRANT SELECT ON bi.vw_fact_sales_line_clean TO copilot_ro;
