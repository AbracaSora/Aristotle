import type { KnowledgeNode } from "./types";

export interface PositionedNode extends KnowledgeNode {
  x: number;
  y: number;
  depth: number;
}

/** Stable layered DAG layout. Only authored prerequisite edges determine position. */
export function layoutKnowledge(nodes: KnowledgeNode[]) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const depth = new Map<string, number>();
  const visiting = new Set<string>();
  function rank(id: string): number {
    if (depth.has(id)) return depth.get(id)!;
    if (visiting.has(id)) throw new Error("知识结构包含环路，请联系内容维护者。");
    visiting.add(id);
    const node = byId.get(id)!;
    const parents = node.prerequisites.filter((p) => byId.has(p));
    const value = parents.length ? Math.max(...parents.map(rank)) + 1 : 0;
    visiting.delete(id);
    depth.set(id, value);
    return value;
  }
  nodes.forEach((n) => rank(n.id));
  const layers = new Map<number, KnowledgeNode[]>();
  for (const node of nodes) {
    const d = depth.get(node.id)!;
    layers.set(d, [...(layers.get(d) || []), node]);
  }
  const maxRows = Math.max(1, ...[...layers.values()].map((v) => v.length));
  const height = Math.max(540, maxRows * 140 + 140);
  const positions: PositionedNode[] = [];
  for (const [d, layer] of [...layers].sort(([a], [b]) => a - b)) {
    layer.sort((a, b) => a.id.localeCompare(b.id));
    layer.forEach((node, i) => positions.push({
      ...node, depth: d, x: 130 + d * 245,
      y: height / 2 + (i - (layer.length - 1) / 2) * 140,
    }));
  }
  return {
    nodes: positions,
    width: Math.max(860, 260 + Math.max(0, ...depth.values()) * 245),
    height,
    edges: nodes.flatMap((n) => n.prerequisites.filter((p) => byId.has(p)).map((p) => ({ source: p, target: n.id }))),
  };
}

export function relatedKnowledge(nodes: KnowledgeNode[], selected: string) {
  const ancestors = new Set<string>();
  const descendants = new Set<string>();
  function visit(id: string, result: Set<string>, parents: boolean) {
    const next = parents
      ? nodes.find((n) => n.id === id)?.prerequisites || []
      : nodes.filter((n) => n.prerequisites.includes(id)).map((n) => n.id);
    for (const n of next) {
      if (!result.has(n) && n !== selected) { result.add(n); visit(n, result, parents); }
    }
  }
  visit(selected, ancestors, true);
  visit(selected, descendants, false);
  return { ancestors, descendants };
}
