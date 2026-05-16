import type { NodeProps } from "reactflow";
import { BaseNode, asStr, summaryProps } from "./BaseNode";

export function WaitNode(props: NodeProps) {
  const { params, selected } = summaryProps(props);
  const selector = asStr(params.selector);
  const timeout = params.timeout ?? 5000;
  return (
    <BaseNode
      label="wait"
      colorClass="bg-amber-500/15 border-amber-500/40"
      selected={selected}
    >
      {selector ? `${selector} (${timeout}ms)` : `${timeout}ms`}
    </BaseNode>
  );
}
