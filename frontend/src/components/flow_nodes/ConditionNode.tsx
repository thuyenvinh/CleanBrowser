import { Handle, Position, type NodeProps } from "reactflow";
import { asStr, summaryProps } from "./BaseNode";

/**
 * ``condition`` exposes two source handles. React Flow's ``sourceHandle``
 * on each outgoing edge tells ``flowToDsl`` whether to put the target in
 * ``next_true`` or ``next_false``.
 */
export function ConditionNode(props: NodeProps) {
  const { params, selected } = summaryProps(props);
  const varName = asStr(params.var) || "?";
  let predicate = "truthy";
  if ("equals" in params) predicate = `== ${asStr(params.equals)}`;
  else if ("contains" in params)
    predicate = `contains ${asStr(params.contains)}`;
  else if ("exists" in params) predicate = `exists=${String(params.exists)}`;
  return (
    <div
      className={`px-3 py-2 rounded text-xs border min-w-[160px] bg-purple-500/15 border-purple-500/40 ${
        selected ? "ring-2 ring-accent" : ""
      }`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="font-mono font-bold mb-1 text-[11px] uppercase tracking-wide">
        condition
      </div>
      <div className="text-gray-300 truncate max-w-[200px]">
        {varName} {predicate}
      </div>
      <div className="flex justify-between mt-2 text-[10px] text-gray-400">
        <span>true</span>
        <span>false</span>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        id="true"
        style={{ left: "25%" }}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        id="false"
        style={{ left: "75%" }}
      />
    </div>
  );
}
