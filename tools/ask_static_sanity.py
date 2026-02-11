from __future__ import annotations

import ast
from pathlib import Path

DIR = Path("backend/app/services/ask")

BUILTINS = set(dir(__builtins__))

def collect_imported(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                names.add(a.asname or a.name)
    return names

def collect_assigned(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names

def collect_used(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            names.add(node.id)
    return names

def main():
    if not DIR.exists():
        print(f"Not found: {DIR}")
        return

    for f in sorted(DIR.glob("*.py")):
        src = f.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(src)
        except Exception as e:
            print(f"[PARSE FAIL] {f}: {e}")
            continue

        imported = collect_imported(tree)
        assigned = collect_assigned(tree)
        used = collect_used(tree)

        missing = sorted(n for n in used if n not in imported and n not in assigned and n not in BUILTINS)
        # ignore common typing-only names that may be unused at runtime due to postponed eval
        ignore = {"Optional", "Dict", "List", "Any", "Tuple", "Set", "Literal"}
        missing = [m for m in missing if m not in ignore]

        if missing:
            print(f"\n[WARN] {f} may miss imports:")
            for m in missing[:40]:
                print(f"  - {m}")
    print("\nDone.")

if __name__ == "__main__":
    main()
