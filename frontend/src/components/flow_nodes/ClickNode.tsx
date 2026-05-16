import type { NodeProps } from "reactflow";
import { BaseNode, asStr, summaryProps } from "./BaseNode";

export function ClickNode(props: NodeProps) {
  const { params, selected } = summaryProps(props);
  return (
    <BaseNode
      label="click"
      colorClass="bg-emerald-500/15 border-emerald-500/40"
      selected={selected}
    >
      {asStr(params.selector) || "(no selector)"}
    </BaseNode>
  );
}
