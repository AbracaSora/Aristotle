"""Detect static project import cycles, including local imports; no imports executed."""

import ast
from pathlib import Path


def module_name(path):
    parts = list(Path(path).with_suffix("").parts)
    start = next(i for i, value in enumerate(parts) if value in ("aristotle_backend", "aristotle_core"))
    parts = parts[start:]
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def edges_for(module, tree, modules):
    edges = set()
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        if isinstance(node, ast.ImportFrom):
            base = ".".join(module.split(".")[: -node.level]) if node.level else ""
            parent = ".".join(filter(None, (base, node.module)))
            names = [parent] + [parent + "." + alias.name for alias in node.names]
        edges.update(name for name in names if name in modules and name != module)
    return sorted(edges)


def cycles_in(graph):
    cycles, done, active = [], set(), []

    def visit(node):
        if node in active:
            cycles.append(active[active.index(node) :] + [node])
            return
        if node in done:
            return
        active.append(node)
        for target in graph[node]:
            visit(target)
        active.pop()
        done.add(node)

    for node in graph:
        visit(node)
    return cycles


def inspect_imports(files):
    modules = {module_name(path): ast.parse(source) for path, source in files.items()}
    graph = {name: edges_for(name, tree, modules) for name, tree in modules.items()}
    dynamic = [
        {"module": name, "line": node.lineno}
        for name, tree in modules.items()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id == "__import__"
            or isinstance(node.func, ast.Attribute)
            and node.func.attr == "import_module"
        )
    ]
    return {"graph": graph, "cycles": cycles_in(graph), "dynamic_imports": dynamic}
