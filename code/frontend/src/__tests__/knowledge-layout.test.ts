import { describe, expect, it } from "vitest";
import { layoutKnowledge, relatedKnowledge } from "../knowledgeLayout";

const nodes = [
  { id: "linear", name: "线性结构", prerequisites: [] },
  { id: "stack", name: "栈", prerequisites: ["linear"] },
  { id: "queue", name: "队列", prerequisites: ["linear"] },
  { id: "application", name: "栈的应用", prerequisites: ["stack", "queue"] },
];

describe("authored prerequisite map", () => {
  it("places all prerequisites before a concept with several prerequisites", () => {
    const layout = layoutKnowledge(nodes);
    for (const edge of layout.edges) {
      const from = layout.nodes.find((n) => n.id === edge.source)!;
      const to = layout.nodes.find((n) => n.id === edge.target)!;
      expect(from.x).toBeLessThan(to.x);
    }
  });
  it("keeps positions stable when a refresh changes input order", () => {
    const positions = (items: typeof nodes) =>
      layoutKnowledge(items).nodes.map((n) => [n.id, n.x, n.y]);
    expect(positions([...nodes].reverse())).toEqual(positions(nodes));
  });
  it("focuses actual ancestors and descendants without inventing sibling prerequisites", () => {
    const related = relatedKnowledge(nodes, "stack");
    expect([...related.ancestors]).toEqual(["linear"]);
    expect([...related.descendants]).toEqual(["application"]);
    expect(related.ancestors.has("queue")).toBe(false);
  });
  it("rejects cycles instead of drawing a misleading learning path", () => {
    expect(() => layoutKnowledge([
      { id: "a", name: "A", prerequisites: ["b"] },
      { id: "b", name: "B", prerequisites: ["a"] },
    ])).toThrow("环路");
  });
  it("does not turn missing boundary nodes into invented graph edges", () => {
    const layout = layoutKnowledge([{ id: "stack", name: "栈", prerequisites: ["outside"] }]);
    expect(layout.edges).toEqual([]);
    expect(layout.nodes).toHaveLength(1);
  });
});
