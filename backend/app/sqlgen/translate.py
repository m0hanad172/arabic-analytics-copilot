from typing import Dict, List, Any, Optional, Tuple
import re
import unicodedata

TRANSLATOR_VERSION = "v2.9-groupby-shipping"

def _strip_invisible(s: str) -> str:
    return "".join(ch for ch in s if unicodedata.category(ch) != "Cf")

def _norm_ar(s: str) -> str:
    s = (s or "").strip().lower()
    s = _strip_invisible(s)

    # normalize Arabic letters
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    s = s.replace("ى", "ي").replace("ة", "ه")

    # Arabic-Indic digits -> ASCII ()
    s = s.translate({0x0660:"0",0x0661:"1",0x0662:"2",0x0663:"3",0x0664:"4",
                     0x0665:"5",0x0666:"6",0x0667:"7",0x0668:"8",0x0669:"9"})
    # Eastern Arabic-Indic digits -> ASCII ()
    s = s.translate({0x06F0:"0",0x06F1:"1",0x06F2:"2",0x06F3:"3",0x06F4:"4",
                     0x06F5:"5",0x06F6:"6",0x06F7:"7",0x06F8:"8",0x06F9:"9"})

    # remove diacritics + tatweel
    s = re.sub(r"[\u0640\u064b-\u0652]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _extract_year_month(q_norm: str) -> Tuple[Optional[int], Optional[int]]:
    year = None
    m = re.search(r"\b(20\d{2})\b", q_norm)
    if m:
        year = int(m.group(1))

    month = None
    m = re.search(r"(شهر|الشهر|month)\s*(\d{1,2})", q_norm)
    if m:
        mm = int(m.group(2))
        if 1 <= mm <= 12:
            month = mm

    return year, month

def _where_year_month(year: Optional[int], month: Optional[int], year_col="order_year", month_col="order_month") -> str:
    conds = []
    if year is not None:
        conds.append(f"{year_col} = {year}")
    if month is not None:
        conds.append(f"{month_col} = {month}")
    return (" WHERE " + " AND ".join(conds)) if conds else ""

def _pick_monthly_view(catalog: Dict[str, List[Dict[str, Any]]]) -> Optional[str]:
    if "bi.vw_sales_monthly" in catalog:
        return "bi.vw_sales_monthly"
    for k, cols in catalog.items():
        if any(c["name"].lower() == "month_start" for c in cols):
            return k
    return None

def _detect_metric(q_norm: str) -> str:
    if "بعد الشحن" in q_norm:
        return "profit_after_shipping"
    if "شحن" in q_norm or "توصيل" in q_norm:
        return "shipping_cost"
    if "خصم" in q_norm:
        return "discounts"
    if "صافي" in q_norm:
        return "net_sales"
    if "اجمالي" in q_norm or "مجموع" in q_norm:
        return "gross_sales"
    if "ربح" in q_norm or "هامش" in q_norm:
        return "gross_profit"
    return "all"

def _cap_n(n: int, lo=1, hi=100) -> int:
    return max(lo, min(int(n), hi))

def translate_arabic_to_sql(question: str, catalog: Dict[str, List[Dict[str, Any]]], max_rows: int):
    q_norm = _norm_ar(question or "")

    if not q_norm:
        return None, f"Empty question [{TRANSLATOR_VERSION}]"
    if not catalog:
        return None, f"Catalog is empty [{TRANSLATOR_VERSION}]"

    year, month = _extract_year_month(q_norm)

    # ---------- TOP N (Products / Categories / Cities / States / Account Managers / Ship Modes) ----------
    top_n = re.search(r"(افضل|اعلى|top)\s*(\d+)", q_norm)
    n = _cap_n(int(top_n.group(2))) if top_n else None

    has_fact = ("bi.fact_sales_line" in catalog)

    def _topn_fact(dim_col: str, n_: int, where: str):
        sql = f"""
SELECT
  {dim_col} AS dim,
  SUM(order_total)::numeric AS net_sales,
  SUM(sub_total)::numeric AS gross_sales,
  SUM(discount_amount)::numeric AS discounts,
  SUM(gross_profit)::numeric AS gross_profit,
  SUM(profit_after_shipping)::numeric AS profit_after_shipping,
  SUM(order_quantity)::numeric AS units,
  COUNT(*)::bigint AS line_count
FROM bi.fact_sales_line
{where}
GROUP BY 1
HAVING SUM(order_total) IS NOT NULL
ORDER BY net_sales DESC NULLS LAST
LIMIT {n_}
""".strip()
        return sql

    if has_fact and n is not None:
        where = _where_year_month(year, month)

        if re.search(r"(منتج|منتجات)", q_norm):
            sql = f"""
SELECT
  product_name,
  product_category,
  SUM(order_total)::numeric AS net_sales,
  SUM(sub_total)::numeric AS gross_sales,
  SUM(discount_amount)::numeric AS discounts,
  SUM(gross_profit)::numeric AS gross_profit,
  SUM(profit_after_shipping)::numeric AS profit_after_shipping,
  SUM(order_quantity)::numeric AS units,
  COUNT(*)::bigint AS line_count
FROM bi.fact_sales_line
{where}
GROUP BY 1,2
HAVING SUM(order_total) IS NOT NULL
ORDER BY net_sales DESC NULLS LAST
LIMIT {n}
""".strip()
            return sql, f"Top {n} products from fact (year={year}, month={month}). [{TRANSLATOR_VERSION}]"

        if re.search(r"(فئه|فئة|فئات|الفئات|تصنيف)", q_norm):
            sql = _topn_fact("product_category", n, where)
            return sql, f"Top {n} categories from fact (year={year}, month={month}). [{TRANSLATOR_VERSION}]"

        if re.search(r"(مدينه|مدينة|المدن|مدينة)", q_norm):
            sql = _topn_fact("city", n, where)
            return sql, f"Top {n} cities from fact (year={year}, month={month}). [{TRANSLATOR_VERSION}]"

        if re.search(r"(ولايه|ولاية|الولايات|منطقه|منطقة)", q_norm):
            sql = _topn_fact("state", n, where)
            return sql, f"Top {n} states from fact (year={year}, month={month}). [{TRANSLATOR_VERSION}]"

        if re.search(r"(مدير الحساب|account manager|المسؤول)", q_norm):
            sql = _topn_fact("account_manager", n, where)
            return sql, f"Top {n} account managers from fact (year={year}, month={month}). [{TRANSLATOR_VERSION}]"

        if re.search(r"(طريقة الشحن|نوع الشحن|ship mode)", q_norm):
            sql = _topn_fact("ship_mode", n, where)
            return sql, f"Top {n} ship modes from fact (year={year}, month={month}). [{TRANSLATOR_VERSION}]"

    # ---------- GROUP BY (Sales by City/State/Category/ShipMode/AccountManager/CustomerType) ----------
    if has_fact and ("حسب" in q_norm or "بحسب" in q_norm or "وفق" in q_norm):
        dim_map = [
            ("city", ["حسب المدينة", "حسب مدينه", "بالمدينة", "بالمدينه", "المدينة", "مدينه", "مدينة"]),
            ("state", ["حسب الولاية", "حسب ولايه", "بالولاية", "بالولايه", "الولاية", "ولايه", "ولاية", "منطقة", "منطقه"]),
            ("product_category", ["حسب الفئة", "حسب فئه", "الفئة", "فئة", "فئه", "فئات", "تصنيف"]),
            ("ship_mode", ["حسب طريقة الشحن", "طريقة الشحن", "نوع الشحن", "ship mode"]),
            ("account_manager", ["حسب مدير الحساب", "مدير الحساب", "account manager", "المسؤول"]),
            ("customer_type", ["حسب نوع العميل", "نوع العميل", "العميل", "العملاء", "customer type"]),
        ]

        dim_col = None
        for col, keys in dim_map:
            if any(k in q_norm for k in keys):
                dim_col = col
                break

        if dim_col:
            where = _where_year_month(year, month)
            sql = f"""
SELECT
  {dim_col},
  SUM(order_total)::numeric AS net_sales,
  SUM(sub_total)::numeric AS gross_sales,
  SUM(discount_amount)::numeric AS discounts,
  SUM(gross_profit)::numeric AS gross_profit,
  SUM(profit_after_shipping)::numeric AS profit_after_shipping,
  SUM(order_quantity)::numeric AS units,
  COUNT(*)::bigint AS line_count
FROM bi.fact_sales_line
{where}
GROUP BY 1
HAVING SUM(order_total) IS NOT NULL
ORDER BY net_sales DESC NULLS LAST
LIMIT {int(max_rows)}
""".strip()
            return sql, f"Group-by sales on '{dim_col}' (year={year}, month={month}). [{TRANSLATOR_VERSION}]"

    # ---------- SHIPPING DELAY (Avg delay by ship mode, optionally filtered by year/month) ----------
    if has_fact and ("تاخير" in q_norm or "تأخير" in q_norm) and ("شحن" in q_norm or "ship" in q_norm):
        where = _where_year_month(year, month)
        # default: by ship_mode
        sql = f"""
SELECT
  ship_mode,
  AVG(ship_delay_days)::numeric AS avg_ship_delay_days,
  COUNT(*)::bigint AS orders,
  SUM(order_total)::numeric AS net_sales
FROM bi.fact_sales_line
{where}
GROUP BY 1
ORDER BY avg_ship_delay_days DESC NULLS LAST
LIMIT {int(max_rows)}
""".strip()
        return sql, f"Avg shipping delay by ship_mode (year={year}, month={month}). [{TRANSLATOR_VERSION}]"

    # ---------- MONTHLY KPI (with optional year/month filter) ----------
    if ("شهر" in q_norm or "شهري" in q_norm or "monthly" in q_norm) and any(k in q_norm for k in ["مبيعات","صافي","اجمالي","خصم","ربح","شحن","بعد الشحن"]):
        mv = _pick_monthly_view(catalog)
        if mv:
            metric = _detect_metric(q_norm)
            base_cols = ["order_year","order_month","month_start"]
            if metric == "all":
                cols = base_cols + ["gross_sales","discounts","net_sales","cogs","gross_profit","shipping_cost","profit_after_shipping"]
            else:
                cols = base_cols + [metric]

            # Filter works because vw_sales_monthly has order_year/order_month
            where = _where_year_month(year, month)
            sql = f"SELECT {', '.join(cols)} FROM {mv}{where} ORDER BY month_start LIMIT {int(max_rows)}"
            return sql, f"Monthly KPI template (metric={metric}, year={year}, month={month}). [{TRANSLATOR_VERSION}]"

    # ---------- FALLBACK ----------
    if has_fact:
        return f"SELECT * FROM bi.fact_sales_line LIMIT {int(max_rows)}", f"Fallback to fact_sales_line. [{TRANSLATOR_VERSION}]"

    first = sorted(catalog.keys())[0]
    return f"SELECT * FROM {first} LIMIT {int(max_rows)}", f"Fallback to {first}. [{TRANSLATOR_VERSION}]"
