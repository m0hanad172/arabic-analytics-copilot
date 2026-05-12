/*
 * 005_seed_bi_meta.sql  (Phase C3)
 *
 * Seeds bi_meta.metrics, bi_meta.dimensions, and bi_meta.synonyms
 * with the same rows the PostgreSQL catalog uses today, translated
 * to T-SQL expressions. Idempotent (MERGE).
 *
 * Generated from docs/.bi_meta_export.json by
 * backend/db/sqlserver/_gen_seed.py. Regenerate after editing the
 * PG catalog if needed.
 */
USE ArabicAnalytics;
GO

-- ---------------------------------------------------------------------------
-- bi_meta.metrics
-- ---------------------------------------------------------------------------
MERGE bi_meta.metrics AS tgt
USING (VALUES
    (N'avg_discount_pct', N'متوسط نسبة الخصم', N'Avg Discount %', N'avg', N'avg(f.discount_pct)', N'numeric', N'percent'),
    (N'avg_ship_delay_days', N'متوسط تأخير الشحن (يوم)', N'Avg Ship Delay (days)', N'avg', N'avg(CAST(f.ship_delay_days AS DECIMAL(38, 6)))', N'numeric', N'days'),
    (N'cogs', N'تكلفة البضاعة', N'COGS', N'sum', N'sum(f.cogs)', N'numeric', N'money'),
    (N'discount_amount', N'إجمالي الخصومات', N'Discount Amount', N'sum', N'sum(f.discount_amount)', N'numeric', N'money'),
    (N'discounts', N'إجمالي الخصومات', N'Discounts', N'sum', N'sum(f.discount_amount)', N'numeric', N'money'),
    (N'gross_profit', N'الربح الإجمالي', N'Gross Profit', N'sum', N'sum(f.gross_profit)', N'numeric', N'money'),
    (N'gross_sales', N'إجمالي المبيعات', N'Gross Sales', N'sum', N'sum(f.sub_total)', N'numeric', N'money'),
    (N'line_count', N'عدد السطور', N'Line Count', N'count', N'COUNT_BIG(*)', N'bigint', N'number'),
    (N'net_sales', N'صافي المبيعات', N'Net Sales', N'sum', N'sum(f.order_total)', N'numeric', N'money'),
    (N'order_count', N'عدد السطور', N'Row Count', N'count', N'COUNT_BIG(*)', N'integer', NULL),
    (N'profit_after_shipping', N'الربح بعد الشحن', N'Profit After Shipping', N'sum', N'sum(f.profit_after_shipping)', N'numeric', N'money'),
    (N'shipping_cost', N'تكلفة الشحن', N'Shipping Cost', N'sum', N'sum(f.shipping_cost)', N'numeric', N'money'),
    (N'units', N'الوحدات', N'Units', N'sum', N'sum(CAST(f.order_quantity AS DECIMAL(38, 6)))', N'numeric', N'number')
) AS src(metric_key, display_name_ar, display_name_en, agg, sql_expression, data_type, format_hint)
ON tgt.metric_key = src.metric_key
WHEN MATCHED THEN UPDATE SET
    display_name_ar = src.display_name_ar,
    display_name_en = src.display_name_en,
    agg             = src.agg,
    sql_expression  = src.sql_expression,
    data_type       = src.data_type,
    format_hint     = src.format_hint
WHEN NOT MATCHED THEN INSERT
    (metric_key, display_name_ar, display_name_en, agg, sql_expression, data_type, format_hint)
    VALUES (src.metric_key, src.display_name_ar, src.display_name_en, src.agg, src.sql_expression, src.data_type, src.format_hint);
GO

-- ---------------------------------------------------------------------------
-- bi_meta.dimensions
-- ---------------------------------------------------------------------------
MERGE bi_meta.dimensions AS tgt
USING (VALUES
    (N'account_manager', N'مسؤول الحساب', N'Account Manager', N'f.account_manager', N'text', 1),
    (N'city', N'المدينة', N'City', N'f.city', N'text', 1),
    (N'customer_type', N'نوع العميل', N'Customer Type', N'f.customer_type', N'text', 1),
    (N'month_start', N'بداية الشهر', N'Month Start', N'DATEFROMPARTS(YEAR(f.order_date_d), MONTH(f.order_date_d), 1)', N'date', 1),
    (N'order_date', N'تاريخ الطلب', N'Order Date', N'f.order_date_d', N'date', 1),
    (N'order_month', N'الشهر', N'Month', N'DATEPART(month, f.order_date_d)', N'integer', 1),
    (N'order_priority', N'أولوية الطلب', N'Order Priority', N'f.order_priority', N'text', 1),
    (N'order_quarter', N'الربع', N'Quarter', N'DATEPART(quarter, f.order_date_d)', N'integer', 1),
    (N'order_year', N'السنة', N'Year', N'DATEPART(year, f.order_date_d)', N'integer', 1),
    (N'product_category', N'فئة المنتج', N'Product Category', N'f.product_category', N'text', 1),
    (N'product_name', N'اسم المنتج', N'Product Name', N'f.product_name', N'text', 1),
    (N'ship_mode', N'طريقة الشحن', N'Ship Mode', N'f.ship_mode', N'text', 1),
    (N'state', N'الولاية', N'State', N'f.state', N'text', 1)
) AS src(dim_key, display_name_ar, display_name_en, sql_expression, data_type, allowed_grouping)
ON tgt.dim_key = src.dim_key
WHEN MATCHED THEN UPDATE SET
    display_name_ar  = src.display_name_ar,
    display_name_en  = src.display_name_en,
    sql_expression   = src.sql_expression,
    data_type        = src.data_type,
    allowed_grouping = src.allowed_grouping
WHEN NOT MATCHED THEN INSERT
    (dim_key, display_name_ar, display_name_en, sql_expression, data_type, allowed_grouping)
    VALUES (src.dim_key, src.display_name_ar, src.display_name_en, src.sql_expression, src.data_type, src.allowed_grouping);
GO

-- ---------------------------------------------------------------------------
-- bi_meta.synonyms
-- ---------------------------------------------------------------------------
MERGE bi_meta.synonyms AS tgt
USING (VALUES
    (N'COGS', N'metric', N'cogs'),
    (N'average discount', N'metric', N'avg_discount_pct'),
    (N'average ship delay', N'metric', N'avg_ship_delay_days'),
    (N'avg discount', N'metric', N'avg_discount_pct'),
    (N'category', N'dimension', N'product_category'),
    (N'city', N'dimension', N'city'),
    (N'cost of goods sold', N'metric', N'cogs'),
    (N'discount amount', N'metric', N'discount_amount'),
    (N'discounts', N'metric', N'discount_amount'),
    (N'gross profit', N'metric', N'gross_profit'),
    (N'gross sales', N'metric', N'gross_sales'),
    (N'line count', N'metric', N'line_count'),
    (N'month', N'dimension', N'month_start'),
    (N'net sales', N'metric', N'net_sales'),
    (N'product', N'dimension', N'product_name'),
    (N'profit after shipping', N'metric', N'profit_after_shipping'),
    (N'quarter', N'dimension', N'order_quarter'),
    (N'ship delay', N'metric', N'avg_ship_delay_days'),
    (N'ship mode', N'dimension', N'ship_mode'),
    (N'shipping cost', N'metric', N'shipping_cost'),
    (N'state', N'dimension', N'state'),
    (N'units', N'metric', N'units'),
    (N'year', N'dimension', N'order_year'),
    (N'إجمالي الخصومات', N'metric', N'discount_amount'),
    (N'إجمالي المبيعات', N'metric', N'gross_sales'),
    (N'الخصومات', N'metric', N'discount_amount'),
    (N'الربح الإجمالي', N'metric', N'gross_profit'),
    (N'الربح بعد الشحن', N'metric', N'profit_after_shipping'),
    (N'الربع', N'dimension', N'order_quarter'),
    (N'السنة', N'dimension', N'order_year'),
    (N'الشحن', N'dimension', N'ship_mode'),
    (N'الشهر', N'dimension', N'month_start'),
    (N'الكمية', N'metric', N'units'),
    (N'المبيعات الصافية', N'metric', N'net_sales'),
    (N'المدينة', N'dimension', N'city'),
    (N'المنتج', N'dimension', N'product_name'),
    (N'الوحدات', N'metric', N'units'),
    (N'الولاية', N'dimension', N'state'),
    (N'تأخير الشحن', N'metric', N'avg_ship_delay_days'),
    (N'تكلفة البضاعة', N'metric', N'cogs'),
    (N'تكلفة البضاعة المباعة', N'metric', N'cogs'),
    (N'تكلفة الشحن', N'metric', N'shipping_cost'),
    (N'خصومات', N'metric', N'discount_amount'),
    (N'شهري', N'dimension', N'month_start'),
    (N'صافي المبيعات', N'metric', N'net_sales'),
    (N'طريقة الشحن', N'dimension', N'ship_mode'),
    (N'عدد السطور', N'metric', N'line_count'),
    (N'عدد الطلبات', N'metric', N'line_count'),
    (N'فئة', N'dimension', N'product_category'),
    (N'فئة المنتج', N'dimension', N'product_category'),
    (N'متوسط تأخير الشحن', N'metric', N'avg_ship_delay_days'),
    (N'متوسط نسبة الخصم', N'metric', N'avg_discount_pct'),
    (N'مدينة', N'dimension', N'city'),
    (N'ولاية', N'dimension', N'state')
) AS src(term, maps_to_type, maps_to_key)
ON tgt.term = src.term
WHEN MATCHED THEN UPDATE SET
    maps_to_type = src.maps_to_type,
    maps_to_key  = src.maps_to_key
WHEN NOT MATCHED THEN INSERT
    (term, maps_to_type, maps_to_key)
    VALUES (src.term, src.maps_to_type, src.maps_to_key);
GO
