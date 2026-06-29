import type { StreamEvent } from "@/types/api";

export function traceLabel(event: Extract<StreamEvent, { type: "trace" }>) {
  if (event.stage === "tool" && event.tool_id === "exam_generation") return "در حال تولید آزمون";
  if (event.stage === "tool") return "اجرای ابزار";
  if (event.stage === "request") return "آماده‌سازی";
  if (event.stage === "understand_query") return event.status === "done" ? "سؤال تحلیل شد" : "تحلیل سؤال";
  if (event.stage === "retrieve") {
    if (event.status === "done") return event.total ? "منابع پیدا شدند" : "منابع رتبه‌بندی شدند";
    return "جستجوی منابع و رتبه‌بندی";
  }
  if (event.stage === "generate") return event.status === "done" ? "پاسخ آماده شد" : "تولید پاسخ";
  if (event.stage === "sub_question") return event.total ? `بخش ${event.index}/${event.total}` : "بخش سؤال";
  return "پردازش";
}
