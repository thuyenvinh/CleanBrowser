/**
 * Conversion helpers between React Flow (visual) and the CleanBrowser
 * automation DSL JSON used by ``backend/automation/interpreter.py``.
 *
 * DSL shape:
 *   {
 *     version: 1,
 *     start: "n1",
 *     nodes: [
 *       { id, type, params, next?, next_true?, next_false? },
 *       ...
 *     ]
 *   }
 *
 * React Flow node ``data`` carries ``{ type: <dsl type>, params: {...} }``.
 * Edges carry ``sourceHandle`` of either ``undefined`` / ``"out"`` (default
 * outgoing) or ``"true"`` / ``"false"`` for condition branches.
 */

import type { Node, Edge } from "reactflow";

export interface DslNode {
  id: string;
  type: string;
  params: Record<string, unknown>;
  next?: string[];
  next_true?: string[];
  next_false?: string[];
}

export interface DslFlow {
  version: number;
  start: string;
  nodes: DslNode[];
}

export interface FlowNodeData {
  type: string;
  params: Record<string, unknown>;
}

export const NODE_TYPES = [
  "goto_url",
  "click",
  "type",
  "wait",
  "wait_seconds",
  "extract",
  "condition",
  "loop",
  "set_variable",
  "log",
] as const;

export type NodeTypeName = (typeof NODE_TYPES)[number];

/**
 * Convert React Flow state into the DSL JSON consumed by the backend.
 *
 * - ``start`` is the id of the node with the smallest ``position.y`` (ties
 *   broken by ``position.x``). If no nodes, ``start`` is an empty string.
 * - For ``condition`` nodes, edges with ``sourceHandle === "true"`` populate
 *   ``next_true`` and ``sourceHandle === "false"`` populate ``next_false``.
 * - For other nodes all outgoing edges populate ``next``.
 */
export function flowToDsl(rfNodes: Node[], rfEdges: Edge[]): DslFlow {
  if (rfNodes.length === 0) {
    return { version: 1, start: "", nodes: [] };
  }

  // Determine start node = top-most (lowest y), then left-most (lowest x).
  const sorted = [...rfNodes].sort((a, b) => {
    if (a.position.y !== b.position.y) return a.position.y - b.position.y;
    return a.position.x - b.position.x;
  });
  const first = sorted[0];
  const start = first ? first.id : "";

  // Build outgoing edge index.
  const outgoing: Record<string, { def: string[]; t: string[]; f: string[] }> =
    {};
  for (const n of rfNodes) {
    outgoing[n.id] = { def: [], t: [], f: [] };
  }
  for (const e of rfEdges) {
    const bucket = outgoing[e.source];
    if (!bucket) continue;
    const h = e.sourceHandle;
    if (h === "true") bucket.t.push(e.target);
    else if (h === "false") bucket.f.push(e.target);
    else bucket.def.push(e.target);
  }

  const nodes: DslNode[] = rfNodes.map((rfn) => {
    const data = (rfn.data ?? {}) as Partial<FlowNodeData>;
    const type = data.type ?? rfn.type ?? "log";
    const params = { ...(data.params ?? {}) };
    const out = outgoing[rfn.id] ?? { def: [], t: [], f: [] };
    const dsl: DslNode = { id: rfn.id, type, params };
    if (type === "condition") {
      if (out.t.length) dsl.next_true = out.t;
      if (out.f.length) dsl.next_false = out.f;
    } else if (out.def.length) {
      dsl.next = out.def;
    }
    return dsl;
  });

  return { version: 1, start, nodes };
}

/**
 * Convert a DSL flow into React Flow nodes/edges using a simple BFS layout.
 *
 * Layout:
 *   - Run BFS from ``start`` following ``next`` / ``next_true`` / ``next_false``.
 *   - ``y = depth * 120``, ``x = (indexInLayer - layerSize/2) * 240``.
 *   - Unreached nodes get appended at the bottom in array order.
 */
export function dslToFlow(dsl: DslFlow | null | undefined): {
  nodes: Node<FlowNodeData>[];
  edges: Edge[];
} {
  if (!dsl || !dsl.nodes || dsl.nodes.length === 0) {
    return { nodes: [], edges: [] };
  }

  const byId: Record<string, DslNode> = {};
  for (const n of dsl.nodes) byId[n.id] = n;

  const depth: Record<string, number> = {};
  const order: string[] = [];
  const visited = new Set<string>();
  const queue: Array<{ id: string; d: number }> = [];
  if (dsl.start && byId[dsl.start]) {
    queue.push({ id: dsl.start, d: 0 });
  }
  while (queue.length) {
    const { id, d } = queue.shift()!;
    if (visited.has(id)) continue;
    visited.add(id);
    depth[id] = d;
    order.push(id);
    const n = byId[id];
    if (!n) continue;
    const children = [
      ...(n.next ?? []),
      ...(n.next_true ?? []),
      ...(n.next_false ?? []),
    ];
    for (const c of children) {
      if (byId[c] && !visited.has(c)) queue.push({ id: c, d: d + 1 });
    }
  }
  // Append unreached nodes at the deepest layer + 1.
  let maxDepth = 0;
  for (const v of Object.values(depth)) if (v > maxDepth) maxDepth = v;
  for (const n of dsl.nodes) {
    if (!visited.has(n.id)) {
      depth[n.id] = maxDepth + 1;
      order.push(n.id);
    }
  }

  // Group ids by depth to position horizontally.
  const layers: Record<number, string[]> = {};
  for (const id of order) {
    const d = depth[id] ?? 0;
    (layers[d] = layers[d] ?? []).push(id);
  }

  const nodes: Node<FlowNodeData>[] = dsl.nodes.map((n) => {
    const d = depth[n.id] ?? 0;
    const layer = layers[d] ?? [n.id];
    const idx = layer.indexOf(n.id);
    const size = layer.length;
    const x = (idx - (size - 1) / 2) * 240;
    const y = d * 130;
    return {
      id: n.id,
      type: n.type,
      position: { x, y },
      data: { type: n.type, params: { ...n.params } },
    };
  });

  const edges: Edge[] = [];
  for (const n of dsl.nodes) {
    if (n.type === "condition") {
      for (const t of n.next_true ?? []) {
        edges.push({
          id: `${n.id}-true-${t}`,
          source: n.id,
          target: t,
          sourceHandle: "true",
          label: "true",
        });
      }
      for (const t of n.next_false ?? []) {
        edges.push({
          id: `${n.id}-false-${t}`,
          source: n.id,
          target: t,
          sourceHandle: "false",
          label: "false",
        });
      }
    } else {
      for (const t of n.next ?? []) {
        edges.push({
          id: `${n.id}-${t}`,
          source: n.id,
          target: t,
        });
      }
    }
  }

  return { nodes, edges };
}

/** Generate a fresh node id that does not collide with existing ids. */
export function nextNodeId(existing: Node[]): string {
  let i = existing.length + 1;
  const ids = new Set(existing.map((n) => n.id));
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const candidate = `n${i}`;
    if (!ids.has(candidate)) return candidate;
    i += 1;
  }
}

/** Default params for a new node of the given type. */
export function defaultParams(type: NodeTypeName): Record<string, unknown> {
  switch (type) {
    case "goto_url":
      return { url: "" };
    case "click":
      return { selector: "" };
    case "type":
      return { selector: "", text: "" };
    case "wait":
      return { timeout: 5000, state: "visible" };
    case "wait_seconds":
      return { seconds: 1 };
    case "extract":
      return { selector: "", var: "" };
    case "condition":
      return { var: "" };
    case "loop":
      return { max: 10 };
    case "set_variable":
      return { name: "", value: "" };
    case "log":
      return { message: "" };
    default:
      return {};
  }
}
