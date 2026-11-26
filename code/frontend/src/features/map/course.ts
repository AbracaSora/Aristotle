export type CourseCall = <T>(path: string, method?: string, body?: unknown) => Promise<T>;

export interface CoursePoint { id: string; name: string; description: string; prerequisite_ids: string[] }
export interface Chapter { id: string; name: string; knowledge_points: CoursePoint[] }
export interface Subject { id: string; name: string; chapters: Chapter[] }

export interface CourseProgress {
  knowledge_id: string;
  status: "available" | "completed" | "mastered" | "locked";
  unlocked: boolean;
  total_count: number;
  completed_count: number;
  latest_correct_count: number;
  required_correct_count: number;
  unmet_prerequisite_ids: string[];
  ai_test_eligible: boolean;
}

export const courseStates = {
  locked: { label: "先修待达标", color: "#777d80" },
  available: { label: "可学习", color: "#fff9eb" },
  learning: { label: "练习中", color: "#3976b9" },
  completed: { label: "预设题已完成", color: "#268052" },
  mastered: { label: "已掌握", color: "#8255aa" },
};

export function courseState(progress?: CourseProgress) {
  if (!progress?.unlocked) return courseStates.locked;
  if (progress.status === "available" && progress.completed_count) return courseStates.learning;
  return courseStates[progress.status];
}

export function courseLabel(progress?: CourseProgress) {
  return progress ? courseState(progress).label : "进度待加载";
}

export interface CourseQuestion {
  key: string; stem: string; options: {id: string; text: string}[];
}
export interface CourseFeedback {
  question_key: string; correct: boolean; answer: {option_id: string}; explanation: string;
}
