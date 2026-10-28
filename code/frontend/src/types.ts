export type Level =
  "remember" | "understand" | "apply" | "analyze" | "evaluate" | "create";
export interface User {
  id: string;
  username: string;
  role: "student" | "maintainer" | "admin";
}
export interface LoginResult {
  access_token: string;
  user: User;
  expires_at: number;
}
export interface KnowledgeNode {
  id: string;
  name: string;
  prerequisites: string[];
}
export interface KnowledgeGraph {
  version: string;
  nodes: KnowledgeNode[];
}
export interface CognitiveEvidence {
  level: Level;
  count: number;
  correct_rate: number | null;
  evidence_status: "sufficient" | "insufficient";
  last_at: number | null;
}
export interface KnowledgeState {
  knowledge_id: string;
  name: string;
  status: "insufficient" | "needs_review" | "provisional";
  evidence_count: number;
  correct_rate: number | null;
  unmet_prerequisites: string[];
  cognitive: CognitiveEvidence[];
}
export interface LearningState {
  graph_version: string;
  policy_version: string;
  window_days: number;
  states: KnowledgeState[];
  notice: string;
}
export interface Question {
  key: string;
  question_id: string;
  version: number;
  knowledge_id: string;
  prompt: string;
  options: string[];
  level: Level;
  status: string;
  dataset: string;
}
export interface Attempt {
  id: string;
  task_id: string;
  question_key: string;
  submission_id: string;
  selected: string;
  correct: boolean;
  created_at: number;
  answer: string;
  explanation: string;
  level: Level;
  question_version: number;
  content_status: string;
  replayed?: boolean;
  retirement_reason?: string | null;
}
export interface HistoryPage {
  items: Attempt[];
  total: number;
  correct_total: number;
  limit: number;
  offset: number;
}
export interface Material {
  id: string;
  title: string;
  text: string;
  knowledge_id: string;
  confirmed: boolean;
  source_location: string;
  chunks?: SourceChunk[];
}
export interface UnavailableMaterial {
  id: string;
  unavailable: true;
  reason: string;
}
export interface SourceChunk {
  id: string;
  text: string;
  knowledge_id: string;
  status: "pending" | "confirmed" | "rejected";
  location: string;
  implementation: string;
}
export interface Resource {
  id: string;
  type: string;
  title?: string;
  text?: string;
  location?: string;
  implementation?: string;
  unavailable?: boolean;
  reason?: string;
}
export interface Goal {
  knowledge_id: string;
  title: string;
  level: Level;
  description: string;
}
export interface TaskFeedback {
  answered: number;
  correct: number;
  message: string;
  state: KnowledgeState | null;
  next_action: string;
  knowledge_id: string;
  target_level: Level;
}
export interface Scope {
  id: string;
  title: string;
  knowledge_ids: string[];
  published: boolean;
  description: string;
}
export interface Diagnostic {
  id: string;
  scope_id: string;
  status: string;
  completed_segments: number;
  notice: string;
  segments: {
    task_id: string;
    knowledge_id: string;
    level: Level;
    question_count: number;
    answered: number;
    status: string;
  }[];
}
export interface LearningContext {
  selected_scope: Scope | null;
  diagnostic: Diagnostic | null;
  current_task: Task | null;
  last_feedback: TaskFeedback | null;
  stage: string;
}
export interface Job {
  can_run?: boolean;
  id: string;
  kind: string;
  status: string;
  implementation: string;
  notice: string;
  result: Record<string, any>;
}
export interface ContentReport {
  id: string;
  question_key: string;
  category: string;
  message: string;
  status: string;
  resolution: string;
}
export interface TimelineItem {
  id: string;
  scope_id: string;
  status: string;
  goal: Goal;
  activity: string;
  created_at: number;
  feedback: TaskFeedback | null;
}
export interface Task {
  id: string;
  lifecycle?: string;
  activity?: string;
  scope_id?: string;
  round_id?: string;
  goal?: Goal;
  plan?: { kind: string; title: string; required: boolean }[];
  evidence_facts?: string[];
  resources?: Resource[];
  feedback?: TaskFeedback | null;
  resume_level?: Level;
  mode: "diagnostic" | "practice";
  graph_version: string;
  created_at: number;
  knowledge_id: string;
  target_level: Level;
  question_keys: string[];
  reason: string;
  warnings: string[];
  policy_version: string;
  material_ids: string[];
  status: "ready" | "material_review" | "content_unavailable";
  questions: Question[];
  materials: (Material | UnavailableMaterial)[];
  attempts: Attempt[];
  evidence_snapshot: KnowledgeState[];
  notice: string;
}
export interface PendingSubmission {
  taskId: string;
  questionKey: string;
  selected: string;
  submissionId: string;
}
export const levelLabels: Record<Level, string> = {
  remember: "记忆",
  understand: "理解",
  apply: "应用",
  analyze: "分析",
  evaluate: "评价",
  create: "创造",
};
export const levelDescriptions: Record<Level, string> = {
  remember: "识别概念与事实",
  understand: "解释知识的含义",
  apply: "在情境中执行方法",
  analyze: "辨别结构、关系与原因",
  evaluate: "依据准则进行判断",
  create: "组合知识形成新方案",
};
export const stateLabels = {
  insufficient: "证据不足",
  needs_review: "待巩固",
  provisional: "初步掌握",
};
