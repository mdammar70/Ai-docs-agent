import ast
from pathlib import Path
from .config import SKIP_DIRS


def make_node_id(file_path: str, class_name: str | None, func_name: str | None) -> str:
    parts = [file_path]
    if class_name:
        parts.append(class_name)
    if func_name:
        parts.append(func_name)
    return "::".join(parts)


def extract_calls(func_node: ast.AST) -> list[str]:
    calls = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                try:
                    obj = ast.unparse(node.func.value)
                    attr = node.func.attr
                    calls.append(f"{obj}.{attr}")
                except Exception:
                    calls.append(node.func.attr)
    return list(set(calls))


def find_parent_class(tree: ast.Module, target_func: ast.AST) -> str | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if child is target_func:
                    return node.name
    return None


def parse_python_file(rel_path: str, source: str) -> dict:
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"  [SKIP] {rel_path}: SyntaxError {e}")
        return {"functions": [], "classes": [], "imports": []}

    functions = []
    classes = []
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = []
            for b in node.bases:
                if isinstance(b, ast.Name):
                    bases.append(b.id)
                elif isinstance(b, ast.Attribute):
                    try:
                        bases.append(ast.unparse(b))
                    except Exception:
                        pass
            classes.append({
                "id": make_node_id(rel_path, node.name, None),
                "name": node.name,
                "file": rel_path,
                "start_line": node.lineno,
                "end_line": node.end_lineno,
                "bases": bases,
                "type": "class",
            })
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            class_name = find_parent_class(tree, node)
            docstring = ast.get_docstring(node)
            params = [arg.arg for arg in node.args.args]
            return_type = ast.unparse(node.returns) if node.returns else None
            calls = extract_calls(node)
            source_code = ast.get_source_segment(source, node) or ""
            functions.append({
                "id": make_node_id(rel_path, class_name, node.name),
                "name": node.name,
                "file": rel_path,
                "class_name": class_name,
                "start_line": node.lineno,
                "end_line": node.end_lineno,
                "docstring": docstring,
                "params": ", ".join(params),
                "return_type": return_type,
                "calls": calls,
                "source": source_code,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "type": "function",
            })
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append({
                    "from_file": rel_path,
                    "module": alias.name,
                    "names": [],
                })
        elif isinstance(node, ast.ImportFrom):
            imports.append({
                "from_file": rel_path,
                "module": node.module or "",
                "names": [a.name for a in node.names],
            })

    return {"functions": functions, "classes": classes, "imports": imports}


def parse_codebase(root_path: str) -> tuple[dict, dict, list, set]:
    root = Path(root_path)
    py_files = [
        f for f in root.rglob("*.py")
        if not any(part in SKIP_DIRS for part in f.parts)
    ]

    all_functions = {}
    all_classes = {}
    all_imports = []
    all_file_paths = set()

    for file in sorted(py_files):
        rel_path = str(file.relative_to(root)).replace("\\", "/")
        source = file.read_text(encoding="utf-8", errors="ignore")
        parsed = parse_python_file(rel_path, source)

        for fn in parsed["functions"]:
            all_functions[fn["id"]] = fn
        for cls in parsed["classes"]:
            all_classes[cls["id"]] = cls
        all_imports.extend(parsed["imports"])
        all_file_paths.add(rel_path)

    return all_functions, all_classes, all_imports, all_file_paths
