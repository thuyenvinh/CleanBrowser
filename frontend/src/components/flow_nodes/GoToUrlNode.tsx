import type { NodeProps } from "reactflow";
import { BaseNode, asStr, summaryProps } from "./BaseNode";

export function GoToUrlNode(props: NodeProps) {
  const { params, selected } = summaryProps(props);
  return (
    <BaseNode
      label="goto_url"
      colorClass="bg-blue-500/15 border-blue-500/40"
      selected={selected}
    >
      {asStr(params.url) || "(no url)"}
    </BaseNode>
  );
}
