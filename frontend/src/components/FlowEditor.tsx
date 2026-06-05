import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
} from "reactflow";
import "reactflow/dist/style.css";
import {
  NODE_TYPES,
  type DslFlow,
  type FlowNodeData,
  type NodeTypeName,
  defaultParams,
  dslToFlow,
  flowToDsl,
  nextNodeId,
} from "../lib/flowToDsl";
import { nodeTypes } from "./flow_nodes";

interface FlowEditorProps {
  /** ``null`` → empty canvas. */
  value: DslFlow | null;
  onChange: (dsl: DslFlow) => void;
  height?: number;
}

/**
 * Visual node-graph editor backed by React Flow. The component is
 * deliberately self-contained: it accepts a DSL JSON in, emits a DSL JSON
 * out on every edit. Wiring into ``AutomationForm`` is left to the caller
 * (agent NN).
 *
 * Implementation notes:
 *   - Internal state is the React Flow ``nodes`` / ``edges`` arrays.
 *   - ``value`` only re-seeds local state when its identity changes AND it
 *     does not match the most recently emitted DSL. This prevents the
 *     classic feedback loop where ``onChange`` → parent re-renders → new
 *     ``value`` reference → resets local state.
 *   - Each mutation goes through ``commit`` which re-runs ``flowToDsl`` and
 *     calls ``props.onChange``.
 */
export function FlowEditor({ value, onChange, height = 600 }: FlowEditorProps) {
  const initial = useMemo(() => dslToFlow(value), [value]);
  const [nodes, setNodes] = useState<Node<FlowNodeData>[]>(initial.nodes);
  const [edges, setEdges] = useState<Edge[]>(initial.edges);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Track the last DSL we emitted so we can detect external updates.
  const lastEmittedRef = useRef<string>(JSON.stringify(value ?? null));
  // Reseed when the parent provides a genuinely different value.
  useEffect(() => {
    const incoming = JSON.stringify(value ?? null);
    if (incoming === lastEmittedRef.current) return;
    const next = dslToFlow(value);
    setNodes(next.nodes);
    setEdges(next.edges);
    lastEmittedRef.current = incoming;
  }, [value]);

  const commit = useCallback(
    (ns: Node<FlowNodeData>[], es: Edge[]) => {
      const dsl = flowToDsl(ns, es);
      lastEmittedRef.current = JSON.stringify(dsl);
      onChange(dsl);
    },
    [onChange],
  );

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      setNodes((curr) => {
        const next = applyNodeChanges(changes, curr) as Node<FlowNodeData>[];
        // Only commit on changes that affect the DSL (add/remove/position
        // doesn't change semantics but we still want start node tracking).
        commit(next, edges);
        return next;
      });
    },
    [commit, edges],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      setEdges((curr) => {
        const next = applyEdgeChanges(changes, curr);
        commit(nodes, next);
        return next;
      });
    },
    [commit, nodes],
  );

  const onConnect = useCallback(
    (conn: Connection) => {
      setEdges((curr) => {
        const next = addEdge(
          { ...conn, label: conn.sourceHandle ?? undefined },
          curr,
        );
        commit(nodes, next);
        return next;
      });
    },
    [commit, nodes],
  );

  const addNode = useCallback(
    (type: NodeTypeName) => {
      setNodes((curr) => {
        const id = nextNodeId(curr);
        // Stack new nodes near the visible centre — React Flow defaults the
        // viewport to ``{x:0, y:0}`` so this is fine for an empty canvas.
        const offset = curr.length * 30;
        const node: Node<FlowNodeData> = {
          id,
          type,
          position: { x: 100 + offset, y: 100 + offset },
          data: { type, params: defaultParams(type) },
        };
        const next = [...curr, node];
        commit(next, edges);
        return next;
      });
    },
    [commit, edges],
  );

  const updateParams = useCallback(
    (id: string, patch: Record<string, unknown>) => {
      setNodes((curr) => {
        const next = curr.map((n) => {
          if (n.id !== id) return n;
          const params = { ...(n.data?.params ?? {}), ...patch };
          // Remove keys whose value is ``undefined`` so the DSL stays clean.
          for (const k of Object.keys(patch)) {
            if (patch[k] === undefined) delete params[k];
          }
          return {
            ...n,
            data: { ...n.data, type: n.data?.type ?? n.type ?? "log", params },
          } as Node<FlowNodeData>;
        });
        commit(next, edges);
        return next;
      });
    },
    [commit, edges],
  );

  const onSelectionChange = useCallback(
    ({ nodes: sel }: { nodes: Node[] }) => {
      setSelectedId(sel[0]?.id ?? null);
    },
    [],
  );

  const selected = nodes.find((n) => n.id === selectedId) ?? null;

  return (
    <div
      className="flex flex-col border border-border rounded-md overflow-hidden bg-surface-1"
      style={{ height }}
    >
      {/* Top toolbar — one button per node type */}
      <div className="flex flex-wrap gap-1 p-2 border-b border-border bg-surface-2">
        {NODE_TYPES.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => addNode(t)}
            className="px-2 py-1 text-xs font-mono rounded bg-surface-3 hover:bg-surface-4 text-gray-200 border border-border"
          >
            + {t}
          </button>
        ))}
      </div>

      <div className="flex-1 flex">
        {/* Canvas */}
        <div className="flex-1 relative">
          {nodes.length === 0 ? (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none text-gray-500 text-sm z-10">
              Drag nodes from toolbar to start
            </div>
          ) : null}
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onSelectionChange={onSelectionChange}
            fitView={nodes.length > 0}
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={16} color="#222" />
            <Controls className="!bg-surface-2 !border-border" />
            <MiniMap
              className="!bg-surface-2"
              maskColor="rgba(0,0,0,0.6)"
              nodeColor="#6366f1"
            />
          </ReactFlow>
        </div>

        {/* Right panel — params edit form */}
        <div className="w-72 border-l border-border bg-surface-2 p-3 overflow-y-auto">
          {selected ? (
            <NodeParamsForm
              key={selected.id}
              node={selected}
              onChange={(patch) => updateParams(selected.id, patch)}
            />
          ) : (
            <div className="text-xs text-gray-500 italic">
              Select a node to edit its parameters.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Right panel — type-specific param form
// ---------------------------------------------------------------------------

interface NodeParamsFormProps {
  node: Node<FlowNodeData>;
  onChange: (patch: Record<string, unknown>) => void;
}

function NodeParamsForm({ node, onChange }: NodeParamsFormProps) {
  const type = (node.data?.type ?? node.type ?? "log") as NodeTypeName;
  const params = node.data?.params ?? {};

  return (
    <div className="space-y-2">
      <div className="text-xs text-gray-400">
        <span className="font-mono">{node.id}</span>{" "}
        <span className="font-mono text-gray-500">· {type}</span>
      </div>
      {renderFields(type, params, onChange)}
    </div>
  );
}

function renderFields(
  type: NodeTypeName,
  params: Record<string, unknown>,
  onChange: (patch: Record<string, unknown>) => void,
) {
  switch (type) {
    case "goto_url":
      return (
        <TextField
          label="url"
          value={params.url}
          onChange={(v) => onChange({ url: v })}
        />
      );
    case "click":
      return (
        <TextField
          label="selector"
          value={params.selector}
          onChange={(v) => onChange({ selector: v })}
        />
      );
    case "type":
      return (
        <>
          <TextField
            label="selector"
            value={params.selector}
            onChange={(v) => onChange({ selector: v })}
          />
          <TextField
            label="text"
            value={params.text}
            onChange={(v) => onChange({ text: v })}
          />
          <NumberField
            label="delay (ms)"
            value={params.delay}
            onChange={(v) => onChange({ delay: v })}
          />
        </>
      );
    case "wait":
      return (
        <>
          <TextField
            label="selector (optional)"
            value={params.selector}
            onChange={(v) => onChange({ selector: v || undefined })}
          />
          <NumberField
            label="timeout (ms)"
            value={params.timeout}
            onChange={(v) => onChange({ timeout: v })}
          />
          <SelectField
            label="state"
            value={params.state}
            options={["visible", "attached", "hidden", "detached"]}
            onChange={(v) => onChange({ state: v })}
          />
        </>
      );
    case "wait_seconds":
      return (
        <NumberField
          label="seconds"
          value={params.seconds}
          onChange={(v) => onChange({ seconds: v })}
        />
      );
    case "extract":
      return (
        <>
          <TextField
            label="selector"
            value={params.selector}
            onChange={(v) => onChange({ selector: v })}
          />
          <TextField
            label="var"
            value={params.var}
            onChange={(v) => onChange({ var: v })}
          />
          <TextField
            label="attribute (optional)"
            value={params.attribute}
            onChange={(v) => onChange({ attribute: v || undefined })}
          />
        </>
      );
    case "condition":
      return (
        <>
          <TextField
            label="var"
            value={params.var}
            onChange={(v) => onChange({ var: v })}
          />
          <TextField
            label="equals (optional)"
            value={params.equals}
            onChange={(v) => onChange({ equals: v || undefined })}
          />
          <TextField
            label="contains (optional)"
            value={params.contains}
            onChange={(v) => onChange({ contains: v || undefined })}
          />
          <CheckboxField
            label="exists"
            value={params.exists}
            onChange={(v) => onChange({ exists: v })}
          />
        </>
      );
    case "loop":
      return (
        <>
          <TextField
            label="var_count (optional)"
            value={params.var_count}
            onChange={(v) => onChange({ var_count: v || undefined })}
          />
          <NumberField
            label="max"
            value={params.max}
            onChange={(v) => onChange({ max: v })}
          />
        </>
      );
    case "set_variable":
      return (
        <>
          <TextField
            label="name"
            value={params.name}
            onChange={(v) => onChange({ name: v })}
          />
          <TextField
            label="value"
            value={params.value}
            onChange={(v) => onChange({ value: v })}
          />
        </>
      );
    case "log":
      return (
        <TextField
          label="message"
          value={params.message}
          onChange={(v) => onChange({ message: v })}
        />
      );
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Form field primitives
// ---------------------------------------------------------------------------

interface FieldBaseProps<T> {
  label: string;
  value: unknown;
  onChange: (v: T) => void;
}

function TextField({ label, value, onChange }: FieldBaseProps<string>) {
  const v = typeof value === "string" ? value : value == null ? "" : String(value);
  return (
    <label className="block">
      <span className="block text-[11px] uppercase tracking-wide text-gray-500 mb-1">
        {label}
      </span>
      <input
        type="text"
        value={v}
        onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
        className="w-full bg-surface-1 border border-border rounded px-2 py-1 text-xs text-gray-200 focus:outline-none focus:border-accent"
      />
    </label>
  );
}

function NumberField({ label, value, onChange }: FieldBaseProps<number | undefined>) {
  const v =
    typeof value === "number"
      ? String(value)
      : typeof value === "string"
        ? value
        : "";
  return (
    <label className="block">
      <span className="block text-[11px] uppercase tracking-wide text-gray-500 mb-1">
        {label}
      </span>
      <input
        type="number"
        value={v}
        onChange={(e: ChangeEvent<HTMLInputElement>) => {
          const raw = e.target.value;
          if (raw === "") {
            onChange(undefined);
            return;
          }
          const n = Number(raw);
          onChange(Number.isFinite(n) ? n : undefined);
        }}
        className="w-full bg-surface-1 border border-border rounded px-2 py-1 text-xs text-gray-200 focus:outline-none focus:border-accent"
      />
    </label>
  );
}

interface SelectFieldProps extends FieldBaseProps<string> {
  options: string[];
}

function SelectField({ label, value, options, onChange }: SelectFieldProps) {
  const v = typeof value === "string" ? value : options[0];
  return (
    <label className="block">
      <span className="block text-[11px] uppercase tracking-wide text-gray-500 mb-1">
        {label}
      </span>
      <select
        value={v}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-surface-1 border border-border rounded px-2 py-1 text-xs text-gray-200 focus:outline-none focus:border-accent"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

function CheckboxField({ label, value, onChange }: FieldBaseProps<boolean>) {
  const v = Boolean(value);
  return (
    <label className="flex items-center gap-2 text-xs text-gray-300">
      <input
        type="checkbox"
        checked={v}
        onChange={(e) => onChange(e.target.checked)}
        className="accent-accent"
      />
      <span>{label}</span>
    </label>
  );
}

export default FlowEditor;
