from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path


ASK_PATH = Path("backend/app/api/routes/ask.py")
SERV_DIR = Path("backend/app/services/ask")
RUNNER_PATH = SERV_DIR / "runner.py"
INIT_PATH = SERV_DIR / "__init__.py"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _find_router_line(lines: list[str]) -> int:
    for i, ln in enumerate(lines):
        if re.match(r"^\s*router\s*=\s*APIRouter\s*\(", ln):
            return i
    return -1


def _find_endpoint_block(lines: list[str], start_at: int) -> tuple[int, int]:
    """
    Find the first @router.post/... block and return (decorator_start, block_end_exclusive).
    """
    deco_start = -1
    for i in range(start_at, len(lines)):
        if re.match(r"^\s*@router\.(post|get|put|delete|patch)\s*\(", lines[i]):
            deco_start = i
            break
    if deco_start == -1:
        return (-1, -1)

    # find end of function block: next top-level decorator/def/async def OR EOF
    # first locate the 'def' line after decorator(s)
    def_line = -1
    for j in range(deco_start, len(lines)):
        if re.match(r"^\s*(async\s+def|def)\s+\w+\s*\(", lines[j]):
            def_line = j
            break
    if def_line == -1:
        return (-1, -1)

    # find block end
    for k in range(def_line + 1, len(lines)):
        if re.match(r"^(?:@|def\s|async\s+def\s)", lines[k]):  # top-level
            return (deco_start, k)
    return (deco_start, len(lines))


def _extract_def_header(lines: list[str], def_start: int) -> tuple[list[str], int]:
    """
    Extract multiline def header (until line ending with '):' or '):\\n').
    Returns (header_lines, header_end_index_exclusive).
    """
    header = []
    i = def_start
    while i < len(lines):
        header.append(lines[i])
        if lines[i].rstrip().endswith("):"):
            return header, i + 1
        i += 1
    return header, i


def _is_import_or_doc_or_blank(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if s.startswith("#"):
        return True
    if s.startswith(("import ", "from ")):
        return True
    return False


def _capture_header(lines: list[str]) -> list[str]:
    """
    Keep module docstring + imports only (thin ask.py).
    """
    out = []
    i = 0

    # capture encoding/shebang/comments on top
    while i < len(lines) and (lines[i].startswith("#!") or lines[i].startswith("# -*-") or lines[i].strip().startswith("#")):
        out.append(lines[i])
        i += 1

    # capture module docstring if present
    if i < len(lines) and lines[i].lstrip().startswith(('"""', "'''")):
        quote = '"""' if lines[i].lstrip().startswith('"""') else "'''"
        out.append(lines[i])
        i += 1
        while i < len(lines):
            out.append(lines[i])
            if quote in lines[i]:
                # this may close on same line, but ok
                # ensure we stop after closing docstring
                if lines[i].rstrip().endswith(quote) or lines[i].count(quote) >= 1:
                    i += 1
                    break
            i += 1

    # capture imports + blank lines + comments immediately following
    while i < len(lines) and _is_import_or_doc_or_blank(lines[i]):
        out.append(lines[i])
        i += 1

    # Ensure ends with a newline
    if out and not out[-1].endswith("\n"):
        out[-1] += "\n"
    return out


def main() -> None:
    if not ASK_PATH.exists():
        raise SystemExit(f"ERROR: {ASK_PATH} not found.")

    lines = ASK_PATH.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)

    router_i = _find_router_line(lines)
    if router_i == -1:
        raise SystemExit("ERROR: Could not find router = APIRouter(...) in ask.py")

    deco_start, block_end = _find_endpoint_block(lines, start_at=router_i)
    if deco_start == -1:
        raise SystemExit("ERROR: Could not find @router.post(...) endpoint block in ask.py")

    # Identify decorator lines and def header
    # Find first def after decorator(s)
    def_i = -1
    for i in range(deco_start, block_end):
        if re.match(r"^\s*(async\s+def|def)\s+\w+\s*\(", lines[i]):
            def_i = i
            break
    if def_i == -1:
        raise SystemExit("ERROR: Could not find endpoint function definition after decorator.")

    deco_lines = lines[deco_start:def_i]
    def_header_lines, def_header_end = _extract_def_header(lines, def_i)

    # Backup original ask.py
    ts = _timestamp()
    backup_path = ASK_PATH.with_suffix(".py.bak." + ts)
    shutil.copy2(ASK_PATH, backup_path)

    # Prepare services dir
    SERV_DIR.mkdir(parents=True, exist_ok=True)
    if not INIT_PATH.exists():
        INIT_PATH.write_text("", encoding="utf-8")

    # Build runner.py = original ask.py content, but:
    # - remove router definition line
    # - remove endpoint decorator lines
    # - rename endpoint function ask -> run_ask
    runner_lines = lines.copy()

    # Remove router line
    runner_lines.pop(router_i)

    # Recompute positions after pop (if router_i < deco_start)
    # easiest: rebuild string and re-find endpoint block in runner_lines
    tmp = runner_lines
    new_router_i = _find_router_line(tmp)  # should be -1 now
    # find endpoint block again
    new_deco_start, new_block_end = _find_endpoint_block(tmp, start_at=0)
    if new_deco_start == -1:
        raise SystemExit("ERROR: Could not relocate endpoint block during runner build.")

    # find def line in runner
    new_def_i = -1
    for i in range(new_deco_start, new_block_end):
        if re.match(r"^\s*(async\s+def|def)\s+\w+\s*\(", tmp[i]):
            new_def_i = i
            break
    if new_def_i == -1:
        raise SystemExit("ERROR: Could not relocate endpoint def during runner build.")

    # delete decorators in runner
    del tmp[new_deco_start:new_def_i]

    # rename function name in def header line (first line only)
    # Replace "async def ask(" -> "async def run_ask("
    tmp[new_deco_start] = re.sub(r"^\s*async\s+def\s+ask\s*\(", "async def run_ask(", tmp[new_deco_start])
    tmp[new_deco_start] = re.sub(r"^\s*def\s+ask\s*\(", "def run_ask(", tmp[new_deco_start])

    RUNNER_PATH.write_text("".join(tmp), encoding="utf-8")

    # Build thin ask.py wrapper
    header = _capture_header(lines)

    # keep original router line exactly
    router_line = lines[router_i]

    # Build wrapper endpoint: keep decorator(s) + def header, but body is a single call
    # Rename function to "ask" if it isn't already (keep same API)
    # Ensure def header starts with "async def ask"
    def_header_joined = def_header_lines.copy()
    def_header_joined[0] = re.sub(r"^\s*async\s+def\s+\w+\s*\(", "async def ask(", def_header_joined[0])
    def_header_joined[0] = re.sub(r"^\s*def\s+\w+\s*\(", "def ask(", def_header_joined[0])

    wrapper_body = [
        "    # Thin wrapper: keep API stable, move logic to services layer\n",
        "    return await run_ask(\n",
        "        body=body,\n",
        "        explain=explain,\n",
        "        use_llm=use_llm,\n",
        "        use_cache=use_cache,\n",
        "    )\n",
    ]

    thin = []
    thin.extend(header)
    thin.append("\nfrom backend.app.services.ask.runner import run_ask\n\n")
    thin.append(router_line)
    if not router_line.endswith("\n"):
        thin.append("\n")
    thin.append("\n")
    thin.extend(deco_lines)
    thin.extend(def_header_joined)
    thin.extend(wrapper_body)

    ASK_PATH.write_text("".join(thin), encoding="utf-8")

    print("\n✅ Refactor complete (safe move, no logic rewrite)")
    print(f"- Backup created: {backup_path}")
    print(f"- Runner created: {RUNNER_PATH}")
    print(f"- ask.py is now thin wrapper: {ASK_PATH}")
    print("\nNext: restart server and run your usual /ask test + smoke_test.ps1\n")


if __name__ == "__main__":
    main()
