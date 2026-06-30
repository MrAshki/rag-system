import { FormEvent, RefObject, useEffect, useMemo, useRef, useState } from "react";
import { AppIcon } from "@/components/AppIcon";
import type { ChatModel, ChatTool, SelectedTool } from "@/types/api";
import styles from "@/app/page.module.css";

type ChatComposerProps = {
  question: string;
  selectedModel: string;
  models: ChatModel[];
  tools: ChatTool[];
  selectedSourceCount: number;
  selectedTool: SelectedTool | null;
  sourceMenuOpen: boolean;
  isSending: boolean;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  onQuestionChange: (value: string) => void;
  onSubmit: (event?: FormEvent) => void;
  onToggleSourceMenu: () => void;
  onOpenSourceModal: () => void;
  onOpenToolPicker: () => void;
  onQuickToolSelect: (toolId: string) => void;
  onClearTool: () => void;
  onClearSources: () => void;
  onModelChange: (value: string) => void;
};

const quickTools = [
  { id: "summary", label: "خلاصه‌سازی", icon: "summary" },
  { id: "flashcards", label: "فلش‌کارت", icon: "flashcard" },
  { id: "rewrite", label: "بازنویسی", icon: "edit" },
  { id: "exam_generation", label: "طراحی آزمون", icon: "exam" },
] satisfies { id: string; label: string; icon: Parameters<typeof AppIcon>[0]["name"] }[];

export function ChatComposer({
  question,
  selectedModel,
  models,
  tools,
  selectedSourceCount,
  selectedTool,
  sourceMenuOpen,
  isSending,
  textareaRef,
  onQuestionChange,
  onSubmit,
  onToggleSourceMenu,
  onOpenSourceModal,
  onOpenToolPicker,
  onQuickToolSelect,
  onClearTool,
  onClearSources,
  onModelChange,
}: ChatComposerProps) {
  const canSend = Boolean(question.trim() || selectedTool) && !isSending;
  const availableQuickTools = quickTools.filter((quickTool) => tools.some((tool) => tool.id === quickTool.id));

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "0px";
    textarea.style.height = `${Math.min(Math.max(textarea.scrollHeight, 30), 150)}px`;
  }, [question, textareaRef]);

  return (
    <div className={styles.composer}>
      <form className={styles.composerBox} onSubmit={onSubmit}>
        <textarea
          ref={textareaRef}
          value={question}
          rows={1}
          placeholder={selectedTool ? "جزئیات اجرا را بنویسید..." : "سؤال خود را بنویسید..."}
          onChange={(event) => onQuestionChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              onSubmit();
            }
          }}
        />

        <div className={styles.composerFooter}>
          <div className={styles.composerControls}>
            <div className={styles.sourceWrap}>
              <button
                className={`${styles.iconButton} ${selectedSourceCount || selectedTool ? styles.hasSources : ""}`}
                type="button"
                onClick={onToggleSourceMenu}
                title="افزودن منبع یا ابزار"
              >
                <AppIcon name="plus" />
              </button>
              {sourceMenuOpen && (
                <div className={styles.sourceMenu}>
                  <button type="button" onClick={onOpenSourceModal}>
                    <AppIcon name="file" /> انتخاب منابع
                  </button>
                  <button type="button" onClick={onOpenToolPicker}>
                    <AppIcon name="tools" /> انتخاب ابزار
                  </button>
                  {availableQuickTools.length > 0 && <span className={styles.sourceMenuDivider} />}
                  {availableQuickTools.map((tool) => (
                    <button type="button" onClick={() => onQuickToolSelect(tool.id)} key={tool.id}>
                      <AppIcon name={tool.icon} /> {tool.label}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {selectedTool && (
              <button className={styles.contextChip} onClick={onClearTool} type="button" title="حذف ابزار">
                <AppIcon name="tools" />
                <span>ابزار: {selectedTool.tool.title}</span>
                <AppIcon name="x" />
              </button>
            )}

            {selectedSourceCount > 0 && (
              <button className={styles.contextChip} onClick={onClearSources} type="button" title="پاک کردن منابع">
                <AppIcon name="file" />
                <span>منابع: {selectedSourceCount.toLocaleString("fa-IR")}</span>
                <AppIcon name="x" />
              </button>
            )}
          </div>

          <div className={styles.composerActions}>
            <ModelPicker models={models} selectedModel={selectedModel} onModelChange={onModelChange} />
            <button className={styles.iconButton} type="button" disabled title="تبدیل گفتار به متن - به‌زودی"><AppIcon name="mic" /></button>
            <button className={styles.send} type="submit" disabled={!canSend} title="ارسال">
              <AppIcon name="send" />
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

function ModelPicker({
  models,
  selectedModel,
  onModelChange,
}: {
  models: ChatModel[];
  selectedModel: string;
  onModelChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement | null>(null);
  const chatModels = useMemo(
    () => models.filter((model) => model.provider !== "litellm" || model.model === "chat_free"),
    [models],
  );
  const selected = useMemo(
    () => chatModels.find((model) => modelValue(model) === selectedModel) || null,
    [chatModels, selectedModel],
  );

  useEffect(() => {
    if (!open) return;
    function closeOnOutside(event: MouseEvent) {
      if (!pickerRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <div className={styles.modelPicker} ref={pickerRef}>
      <button type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open} title="انتخاب مدل">
        <span>{selected ? modelAlias(selected) : "مدل"}</span>
        <AppIcon name="chevron" />
      </button>
      {open && (
        <div className={styles.modelPopover} role="listbox">
          {chatModels.map((model) => {
            const value = modelValue(model);
            const active = value === selectedModel;
            return (
              <button
                className={`${styles.modelOption} ${active ? styles.activeModelOption : ""}`}
                disabled={!model.enabled}
                key={value}
                onClick={() => {
                  if (!model.enabled) return;
                  onModelChange(value);
                  setOpen(false);
                }}
                role="option"
                aria-selected={active}
                type="button"
              >
                <span>
                  <strong>{modelAlias(model)}</strong>
                  <small>{model.provider}</small>
                </span>
                {active && <AppIcon name="check" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function modelValue(model: ChatModel) {
  return `${model.provider}|${model.model}`;
}

function modelAlias(model: ChatModel) {
  const label = model.model || model.label;
  return label.replace(/^.+?\s+-\s+/, "");
}
