from backend.app.services.ask.plan_normalize import finalize_plan

def test_finalize_plan_discount_alias():
    catalog = {"metrics": ["net_sales", "discount_amount"], "dimensions": ["city", "order_year", "order_quarter"]}
    plan = {"metrics": ["net_sales", "discounts"], "dimensions": ["city", "year", "quarter"], "filters": [], "sort": [], "limit": 5}

    p2, corr = finalize_plan(
        "قارن صافي المبيعات والخصومات حسب المدينة والربع",
        plan,
        catalog,
        default_max_rows=200,
        plan_autocorrect=True,
        dedupe_synonyms=True,
        allowed_ops={"=", "in", "between", "ilike"},
        max_rows_cap=5000,
    )

    assert "discount_amount" in p2["metrics"]
    assert "discounts" not in p2["metrics"]
    assert "order_year" in p2["dimensions"]
    assert "order_quarter" in p2["dimensions"]
