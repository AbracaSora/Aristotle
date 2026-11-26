"""AST metrics for the course guard; nested callables are measured independently."""

import ast
import copy
import tokenize
from io import StringIO

from cognitive_complexity.api import get_cognitive_complexity
from radon.complexity import cc_visit

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
CONTROLS = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match)


def function_nodes(node):
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, FUNCTIONS):
            yield child
            yield from function_nodes(child)


def nesting(node, depth=0):
    depths = [depth]
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, FUNCTIONS):
            depths.append(nesting(child, depth + isinstance(child, CONTROLS)))
    return max(depths)


def boolean_terms(node):
    if isinstance(node, ast.BoolOp):
        return sum(boolean_terms(child) for child in node.values)
    return 1


def effective_lines(node, source):
    lines = source.splitlines()
    executable = {
        token.start[0]
        for token in tokenize.generate_tokens(StringIO(source).readline)
        if token.type
        not in (
            tokenize.COMMENT,
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.ENDMARKER,
        )
    }
    included = set(range(node.lineno, node.end_lineno + 1))
    for child in function_nodes(node):
        if isinstance(child, ast.ClassDef):
            included -= set(range(child.lineno, child.end_lineno + 1))
    for child in ast.walk(node):
        if isinstance(child, FUNCTIONS) and child is not node:
            included -= set(range(child.lineno, child.end_lineno + 1))
    return sum(bool(lines[line - 1].strip()) for line in included & executable)


def own_cognitive_complexity(node):
    class WithoutNested(ast.NodeTransformer):
        def visit_FunctionDef(self, child):
            return None

        def visit_AsyncFunctionDef(self, child):
            return None

    own = copy.deepcopy(node)
    stripper = WithoutNested()
    own.body = [value for child in own.body if (value := stripper.visit(child)) is not None]
    return get_cognitive_complexity(own)


def function_metrics(node, source, complexities):
    args = node.args
    params = len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs)
    params += bool(args.vararg) + bool(args.kwarg)
    nodes = list(function_nodes(node))
    return {
        "TH-01": effective_lines(node, source),
        "TH-02": complexities.get(node.lineno, 1),
        "TH-03": own_cognitive_complexity(node),
        "TH-04": nesting(node),
        "TH-05": params,
        "TH-07": max([boolean_terms(n.test) for n in nodes if isinstance(n, ast.If)], default=0),
    }


def complexity_map(blocks):
    result = {}
    for block in blocks:
        result[block.lineno] = block.complexity
        result.update(complexity_map(getattr(block, "closures", [])))
        result.update(complexity_map(getattr(block, "methods", [])))
    return result


def inspect_source(path, source, limits):
    tree = ast.parse(source)
    complexities = complexity_map(cc_visit(source))
    measurements, findings = [], []
    for node in ast.walk(tree):
        if not isinstance(node, FUNCTIONS):
            continue
        metrics = function_metrics(node, source, complexities)
        measurements.append({"file": path, "line": node.lineno, "name": node.name, **metrics})
        for rule, value in metrics.items():
            if value > limits[rule]:
                findings.append(
                    {
                        "file": path,
                        "line": node.lineno,
                        "name": node.name,
                        "rule": rule,
                        "actual": value,
                        "limit": limits[rule],
                    }
                )
    size = len(source.splitlines())
    if size > limits["TH-06"]:
        findings.append({"file": path, "line": 1, "rule": "TH-06", "actual": size, "limit": limits["TH-06"]})
    return measurements, findings
