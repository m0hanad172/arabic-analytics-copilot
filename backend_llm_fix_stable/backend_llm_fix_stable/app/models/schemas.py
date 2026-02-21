from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

class QueryRequest(BaseModel):
    question: str = Field(..., description="Arabic analytics question")
    max_rows: int = Field(200, ge=1, le=5000)
    debug_sql: Optional[str] = Field(None, description="If provided, run this SQL directly (still validated)")
    execute: bool = Field(True, description="If false, return SQL only without executing")

class QueryResponse(BaseModel):
    sql: str
    explanation: str
    rows: List[Dict[str, Any]]
    row_count: int

class CatalogResponse(BaseModel):
    allowed_schema: str
    catalog: Dict[str, List[Dict[str, Any]]]
