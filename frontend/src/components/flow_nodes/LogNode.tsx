import type { NodeProps } from "reactflow";
import { BaseNode, asStr, summaryProps } from "./BaseNode";

export function LogNode(props: NodeProps) {
  const { params, selected } = summaryProps(props);
  return (
    <BaseNode
      label="log"
      colorClass="bg-gray-500/20 border-gray-500/40"
      selected={selected}
    >
      {asStr(params.message) || "(empty)"}
    </BaseNode>
  );
}
