import type { NodeProps } from "reactflow";
import { BaseNode, asStr, summaryProps } from "./BaseNode";

export function ExtractNode(props: NodeProps) {
  const { params, selected } = summaryProps(props);
  const selector = asStr(params.selector) || "(no selector)";
  const varName = asStr(params.var) || "?";
  return (
    <BaseNode
      label="extract"
      colorClass="bg-cyan-500/15 border-cyan-500/40"
      selected={selected}
    >
      {selector} → {varName}
    </BaseNode>
  );
}
