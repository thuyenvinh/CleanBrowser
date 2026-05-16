import type { NodeProps } from "reactflow";
import { BaseNode, summaryProps } from "./BaseNode";

export function WaitSecondsNode(props: NodeProps) {
  const { params, selected } = summaryProps(props);
  const seconds = params.seconds ?? 0;
  return (
    <BaseNode
      label="wait_seconds"
      colorClass="bg-amber-500/15 border-amber-500/40"
      selected={selected}
    >
      sleep {String(seconds)}s
    </BaseNode>
  );
}
