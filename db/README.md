# Database Setup (AAC)

AAC expects a PostgreSQL database with:
- schema: bi
- schema: bi_meta
- main fact view/table: bi.vw_fact_sales_line_clean

## Docker (recommended)
Start Postgres:
  docker compose up -d db

Default container name used in this project:
  aac-pg

Check readiness:
  docker exec -it aac-pg pg_isready -U aac -d aac

## Notes
- This repo does not include dataset dumps by default (size + privacy).
- If you want to share schema only (no data), you can export:
  docker exec -i aac-pg pg_dump -U aac -d aac --schema-only > db/schema_only.sql
