import type { NodeProps } from "reactflow";
import { BaseNode, asStr, summaryProps } from "./BaseNode";

export function LoopNode(props: NodeProps) {
  const { params, selected } = summaryProps(props);
  const max = params.max ?? 10;
  const counter = asStr(params.var_count);
  return (
    <BaseNode
      label="loop"
      colorClass="bg-pink-500/15 border-pink-500/40"
      selected={selected}
    >
      max={String(max)}
      {counter && ` (${counter})`}
    </BaseNode>
  );
}
