import type { NodeProps } from "reactflow";
import { BaseNode, asStr, summaryProps } from "./BaseNode";

export function TypeNode(props: NodeProps) {
  const { params, selected } = summaryProps(props);
  const selector = asStr(params.selector) || "(no selector)";
  const text = asStr(params.text);
  return (
    <BaseNode
      label="type"
      colorClass="bg-teal-500/15 border-teal-500/40"
      selected={selected}
    >
      <div>{selector}</div>
      {text && <div className="text-gray-400">"{text}"</div>}
    </BaseNode>
  );
}
