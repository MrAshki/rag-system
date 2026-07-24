"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AppIcon } from "@/components/AppIcon";
import { gradeGeneratedOutput } from "@/features/chat/api";
import type { ExamGrade, GeneratedOutput } from "@/types/api";
import styles from "@/app/page.module.css";

type OutputCanvasProps = {
  output: GeneratedOutput;
  onClose: () => void;
};

type ExamQuestion = {
  id: string;
  type: "multiple_choice" | "descriptive";
  points?: number;
  prompt: string;
  choices?: string[];
  answer_index?: number | null;
  answer_key?: string | null;
  sample_answer?: string;
  rubric?: string[];
  explanation?: string;
  citations?: string[];
};

type ExamContent = {
  kind: "exam";
  title: string;
  total_score?: number;
  duration_minutes: number;
  questions: ExamQuestion[];
};

export function OutputCanvas({ output, onClose }: OutputCanvasProps) {
  const exam = getExam(output);
  const [isFullscreen, setIsFullscreen] = useState(false);

  return (
    <section className={`${styles.canvasPanel} ${isFullscreen ? styles.canvasFullscreen : ""}`} aria-labelledby="canvas-title">
      <header className={styles.canvasHead}>
        <div>
          <span><AppIcon name="output" /></span>
          <div>
            <h2 id="canvas-title">{exam?.title || output.title}</h2>
            <p>{exam ? "محیط آزمون" : outputTypeLabel(output.type)}</p>
          </div>
        </div>
        <div className={styles.canvasActions}>
          <button
            onClick={() => setIsFullscreen((value) => !value)}
            type="button"
            title={isFullscreen ? "خروج از تمام‌صفحه" : "تمام‌صفحه"}
          >
            <AppIcon name={isFullscreen ? "minimize" : "maximize"} />
          </button>
          <button onClick={onClose} type="button" title="بستن"><AppIcon name="x" /></button>
        </div>
      </header>
      {exam ? <ExamCanvas exam={exam} outputId={output.id} /> : (
        <div className={styles.canvasBody}>
          <article>{output.content_markdown}</article>
        </div>
      )}
    </section>
  );
}

function ExamCanvas({ exam, outputId }: { exam: ExamContent; outputId: string }) {
  const [answers, setAnswers] = useState<Record<string, string | number>>({});
  const [started, setStarted] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [isGrading, setIsGrading] = useState(false);
  const [grade, setGrade] = useState<ExamGrade | null>(null);
  const [gradeError, setGradeError] = useState("");
  const [remainingSeconds, setRemainingSeconds] = useState(() => Math.max(1, exam.duration_minutes || 20) * 60);
  const answersRef = useRef(answers);

  useEffect(() => {
    answersRef.current = answers;
  }, [answers]);

  useEffect(() => {
    if (!started || submitted) return;
    const id = window.setInterval(() => {
      setRemainingSeconds((current) => {
        if (current <= 1) {
          window.clearInterval(id);
          void submitExam();
          return 0;
        }
        return current - 1;
      });
    }, 1000);
    return () => window.clearInterval(id);
    // submitExam reads latest answers from answersRef when invoked by the timer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [started, submitted]);

  const objectiveQuestions = exam.questions.filter((question) => question.type === "multiple_choice");
  const descriptiveQuestions = exam.questions.filter((question) => question.type === "descriptive");
  const answeredCount = exam.questions.filter((question) => answers[question.id] !== undefined && String(answers[question.id]).trim() !== "").length;
  const gradeByQuestion = useMemo(() => {
    return Object.fromEntries((grade?.questions || []).map((item) => [item.id, item]));
  }, [grade]);

  async function submitExam() {
    if (submitted || isGrading) return;
    setIsGrading(true);
    setGradeError("");
    try {
      const data = await gradeGeneratedOutput(outputId, answersRef.current);
      setGrade(data.grade);
      setSubmitted(true);
    } catch (error) {
      setGradeError(error instanceof Error ? error.message : "خطا در تصحیح آزمون");
    } finally {
      setIsGrading(false);
    }
  }

  if (!started) {
    return (
      <div className={styles.examStart}>
        <div>
          <AppIcon name="exam" />
          <h3>{exam.title}</h3>
          <p>آزمون آماده است. با شروع آزمون، زمان‌سنج فعال می‌شود و پاسخ‌ها تا پایان آزمون نمایش داده نمی‌شوند.</p>
          <dl>
            <div><dt>تعداد سؤال</dt><dd>{exam.questions.length.toLocaleString("fa-IR")}</dd></div>
            <div><dt>نمره کل</dt><dd>{formatScore(exam.total_score || exam.questions.reduce((sum, question) => sum + Number(question.points || 0), 0))}</dd></div>
            <div><dt>زمان</dt><dd>{exam.duration_minutes.toLocaleString("fa-IR")} دقیقه</dd></div>
            <div><dt>تستی</dt><dd>{objectiveQuestions.length.toLocaleString("fa-IR")}</dd></div>
            <div><dt>تشریحی</dt><dd>{descriptiveQuestions.length.toLocaleString("fa-IR")}</dd></div>
          </dl>
          <button className={styles.primaryButton} onClick={() => setStarted(true)} type="button">شروع آزمون</button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.examCanvas}>
      <aside className={styles.examAside}>
        <div className={styles.examTimer}>
          <span>زمان باقی‌مانده</span>
          <strong>{formatTime(remainingSeconds)}</strong>
        </div>
        <div className={styles.examProgress}>
          <span>پاسخ داده‌شده</span>
          <strong>{answeredCount.toLocaleString("fa-IR")} / {exam.questions.length.toLocaleString("fa-IR")}</strong>
        </div>
        {submitted && (
          <div className={styles.examResult}>
            <span>نمره کل</span>
            <strong>{formatScore(grade?.total_score || 0)} / {formatScore(grade?.total_max || 0)}</strong>
            <small>تستی: {formatScore(grade?.objective_score || 0)} / {formatScore(grade?.objective_max || 0)}</small>
            {descriptiveQuestions.length > 0 && <small>تشریحی: {formatScore(grade?.descriptive_score || 0)} / {formatScore(grade?.descriptive_max || 0)}</small>}
          </div>
        )}
        {gradeError && <div className={styles.examGradeError}>{gradeError}</div>}
        <button className={styles.primaryButton} disabled={submitted || isGrading} onClick={() => void submitExam()} type="button">
          {isGrading ? "در حال تصحیح..." : "تکمیل آزمون"}
        </button>
      </aside>

      <div className={styles.examQuestions}>
        {exam.questions.map((question, index) => (
          <section className={styles.examQuestion} key={question.id}>
            <div className={styles.examQuestionHead}>
              <h3>{(index + 1).toLocaleString("fa-IR")}. {question.prompt}</h3>
              <span>{question.type === "multiple_choice" ? "تستی" : "تشریحی"} · {formatScore(Number(question.points || 0))} نمره</span>
            </div>
            {question.citations?.length ? <p className={styles.examCitations}>{question.citations.map((citation) => `[${citation}]`).join(" ")}</p> : null}

            {question.type === "multiple_choice" ? (
              <div className={styles.examChoices}>
                {(question.choices || []).map((choice, choiceIndex) => {
                  const selected = Number(answers[question.id]) === choiceIndex;
                  const correct = submitted && question.answer_index === choiceIndex;
                  const wrong = submitted && selected && !correct;
                  return (
                    <label className={`${correct ? styles.correctChoice : ""} ${wrong ? styles.wrongChoice : ""}`} key={`${question.id}-${choiceIndex}`}>
                      <input
                        checked={selected}
                        disabled={submitted}
                        name={question.id}
                        type="radio"
                        onChange={() => setAnswers((current) => ({ ...current, [question.id]: choiceIndex }))}
                      />
                      <span>{choice}</span>
                    </label>
                  );
                })}
              </div>
            ) : (
              <textarea
                disabled={submitted}
                value={String(answers[question.id] || "")}
                placeholder="پاسخ تشریحی خود را بنویسید..."
                onChange={(event) => setAnswers((current) => ({ ...current, [question.id]: event.target.value }))}
              />
            )}

            {submitted && (
              <div className={styles.examFeedback}>
                {question.type === "multiple_choice" ? (
                  <>
                    <b>{gradeByQuestion[question.id]?.correct ? "درست" : "نادرست"}</b>
                    {typeof gradeByQuestion[question.id]?.answer_index === "number" && Number(gradeByQuestion[question.id]?.answer_index) >= 0 && (
                      <p>گزینه صحیح: {choiceLabel(Number(gradeByQuestion[question.id]?.answer_index))} - {question.choices?.[Number(gradeByQuestion[question.id]?.answer_index)]}</p>
                    )}
                    {(gradeByQuestion[question.id]?.answer_index === undefined || gradeByQuestion[question.id]?.answer_index === null || Number(gradeByQuestion[question.id]?.answer_index) < 0) && (
                      <p>کلید پاسخ این سؤال معتبر تولید نشده است و در نمره تستی درست حساب نمی‌شود.</p>
                    )}
                    {gradeByQuestion[question.id]?.feedback && <p>{gradeByQuestion[question.id]?.feedback}</p>}
                  </>
                ) : (
                  <>
                    <b>نمره: {formatScore(gradeByQuestion[question.id]?.score || 0)} / {formatScore(gradeByQuestion[question.id]?.max_score || 5)}</b>
                    {gradeByQuestion[question.id]?.feedback && <p>{gradeByQuestion[question.id]?.feedback}</p>}
                    {gradeByQuestion[question.id]?.sample_answer && <p>نمونه پاسخ: {gradeByQuestion[question.id]?.sample_answer}</p>}
                    {gradeByQuestion[question.id]?.rubric?.length ? (
                      <ul>{gradeByQuestion[question.id]?.rubric?.map((item) => <li key={item}>{item}</li>)}</ul>
                    ) : null}
                  </>
                )}
              </div>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}

function getExam(output: GeneratedOutput): ExamContent | null {
  const data = output.content_json as Partial<ExamContent> | undefined;
  if (output.type !== "exam_generation" || data?.kind !== "exam" || !Array.isArray(data.questions)) return null;
  return {
    kind: "exam",
    title: data.title || output.title,
    total_score: Number(data.total_score || 0),
    duration_minutes: Number(data.duration_minutes || 20),
    questions: data.questions as ExamQuestion[],
  };
}

function formatTime(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes.toLocaleString("fa-IR")}:${rest.toString().padStart(2, "0")}`;
}

function choiceLabel(index: number) {
  return ["الف", "ب", "ج", "د"][index] || "";
}

function formatScore(score: number) {
  return score.toLocaleString("fa-IR", { maximumFractionDigits: 1 });
}

function outputTypeLabel(type: string) {
  return {
    summary: "خلاصه‌سازی",
    exam_generation: "آزمون",
    flashcards: "فلش‌کارت",
    article_draft: "مقاله",
    legal_pleading: "لایحه",
    legal_review: "بررسی حقوقی",
    rewrite: "بازنویسی",
  }[type] || "خروجی ابزار";
}
