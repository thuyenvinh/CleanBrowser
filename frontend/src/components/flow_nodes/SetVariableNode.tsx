import type { NodeProps } from "reactflow";
import { BaseNode, asStr, summaryProps } from "./BaseNode";

export function SetVariableNode(props: NodeProps) {
  const { params, selected } = summaryProps(props);
  const name = asStr(params.name) || "?";
  const value = asStr(params.value);
  return (
    <BaseNode
      label="set_variable"
      colorClass="bg-indigo-500/15 border-indigo-500/40"
      selected={selected}
    >
      {name} = {value || "''"}
    </BaseNode>
  );
}
