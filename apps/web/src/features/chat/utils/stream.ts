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
  if (event.stage === "agent_plan") return "برنامه پاسخ انتخاب شد";
  if (event.stage === "agent_summary") return event.status === "done" ? "خلاصه جامع آماده شد" : "خلاصه‌سازی جامع";
  if (event.stage === "agent_summary_chapter") {
    const title = event.unit_title ? ` ${event.unit_title}` : "";
    if (event.status === "failed") return `خلاصه‌سازی${title} انجام نشد`;
    if (event.status === "done" && event.cached) return `خلاصه${title} از حافظه آماده شد`;
    if (event.status === "done") return `خلاصه${title} آماده شد`;
    return `در حال خلاصه‌سازی${title}`;
  }
  if (event.stage === "agent_summary_reduce") {
    return event.status === "done" ? "جمع‌بندی نهایی آماده شد" : "در حال جمع‌بندی نهایی";
  }
  if (event.stage === "agent_summary_window") {
    if (event.status === "failed") return `دسته شواهد ${event.index}/${event.total} رد شد`;
    return event.status === "done" ? `دسته شواهد ${event.index}/${event.total} خلاصه شد` : `خلاصه‌سازی شواهد ${event.index}/${event.total}`;
  }
  if (event.stage === "agent_retrieve") return "منابع رتبه‌بندی شدند";
  if (event.stage === "sub_question") return event.total ? `بخش ${event.index}/${event.total}` : "بخش سؤال";
  return "پردازش";
}
