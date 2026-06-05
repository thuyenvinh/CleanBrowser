import { Handle, Position, type NodeProps } from "reactflow";

/**
 * Common visual scaffold for DSL nodes that have a single incoming and
 * single outgoing edge. Per-type wrappers render their summary line into
 * ``children``.
 */
interface BaseNodeProps {
  label: string;
  colorClass: string; // tailwind classes for bg/border tint
  children?: React.ReactNode;
  selected?: boolean;
}

export function BaseNode({
  label,
  colorClass,
  children,
  selected,
}: BaseNodeProps) {
  return (
    <div
      className={`px-3 py-2 rounded text-xs border min-w-[150px] ${colorClass} ${
        selected ? "ring-2 ring-accent" : ""
      }`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="font-mono font-bold mb-1 text-[11px] uppercase tracking-wide">
        {label}
      </div>
      <div className="text-gray-300 truncate max-w-[200px]">{children}</div>
      <Handle type="source" position={Position.Bottom} id="out" />
    </div>
  );
}

/** Helper to pull a string param safely. */
export function asStr(v: unknown, fallback = ""): string {
  if (typeof v === "string") return v;
  if (v == null) return fallback;
  return String(v);
}

export function summaryProps(props: NodeProps): {
  params: Record<string, unknown>;
  selected: boolean | undefined;
} {
  const data = (props.data ?? {}) as { params?: Record<string, unknown> };
  return { params: data.params ?? {}, selected: props.selected };
}
