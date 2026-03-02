# Database Setup (AAC)

AAC expects a PostgreSQL database with:
- Database: `arabic_analytics`
- Schemas: `bi`, `bi_meta`
- Main fact view/table: `bi.vw_fact_sales_line_clean`

## Docker (recommended)
Start Postgres:
```bash
docker compose up -d db