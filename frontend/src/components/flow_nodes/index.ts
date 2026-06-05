import { GoToUrlNode } from "./GoToUrlNode";
import { ClickNode } from "./ClickNode";
import { TypeNode } from "./TypeNode";
import { WaitNode } from "./WaitNode";
import { WaitSecondsNode } from "./WaitSecondsNode";
import { ExtractNode } from "./ExtractNode";
import { ConditionNode } from "./ConditionNode";
import { LoopNode } from "./LoopNode";
import { SetVariableNode } from "./SetVariableNode";
import { LogNode } from "./LogNode";

/**
 * React Flow ``nodeTypes`` map. Keys MUST match the DSL ``type`` field
 * (see ``backend/automation/nodes.py``).
 */
export const nodeTypes = {
  goto_url: GoToUrlNode,
  click: ClickNode,
  type: TypeNode,
  wait: WaitNode,
  wait_seconds: WaitSecondsNode,
  extract: ExtractNode,
  condition: ConditionNode,
  loop: LoopNode,
  set_variable: SetVariableNode,
  log: LogNode,
};

export {
  GoToUrlNode,
  ClickNode,
  TypeNode,
  WaitNode,
  WaitSecondsNode,
  ExtractNode,
  ConditionNode,
  LoopNode,
  SetVariableNode,
  LogNode,
};
