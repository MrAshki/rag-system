import { FormEvent, RefObject } from "react";
import { AppIcon } from "@/components/AppIcon";
import type { ChatModel } from "@/types/api";
import styles from "@/app/page.module.css";

type ChatComposerProps = {
  question: string;
  selectedModel: string;
  models: ChatModel[];
  selectedSourceCount: number;
  sourceMenuOpen: boolean;
  isSending: boolean;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  onQuestionChange: (value: string) => void;
  onSubmit: (event?: FormEvent) => void;
  onToggleSourceMenu: () => void;
  onOpenSourceModal: () => void;
  onModelChange: (value: string) => void;
};

export function ChatComposer({
  question,
  selectedModel,
  models,
  selectedSourceCount,
  sourceMenuOpen,
  isSending,
  textareaRef,
  onQuestionChange,
  onSubmit,
  onToggleSourceMenu,
  onOpenSourceModal,
  onModelChange,
}: ChatComposerProps) {
  return (
    <div className={styles.composer}>
      <form className={styles.composerCard} onSubmit={onSubmit}>
        <div className={styles.composerLeft}>
          <div className={styles.sourceWrap}>
            <button className={`${styles.iconButton} ${selectedSourceCount ? styles.hasSources : ""}`} type="button" onClick={onToggleSourceMenu} title="افزودن">
              <AppIcon name="plus" />
              {selectedSourceCount > 0 && <span>{selectedSourceCount.toLocaleString("fa-IR")}</span>}
            </button>
            {sourceMenuOpen && (
              <div className={styles.sourceMenu}>
                <button type="button" onClick={onOpenSourceModal}>
                  <AppIcon name="file" /> اضافه کردن منابع
                </button>
              </div>
            )}
          </div>
          <button className={styles.send} type="submit" disabled={isSending || !question.trim()} title="ارسال"><AppIcon name="send" /></button>
        </div>
        <textarea
          ref={textareaRef}
          value={question}
          rows={1}
          placeholder="سؤال خود را بنویسید..."
          onChange={(event) => onQuestionChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              onSubmit();
            }
          }}
        />
        <div className={styles.composerActions}>
          <label className={styles.modelPicker}>
            <AppIcon name="settings" />
            <select value={selectedModel} onChange={(event) => onModelChange(event.target.value)}>
              {models.map((model) => (
                <option value={`${model.provider}|${model.model}`} disabled={!model.enabled} key={`${model.provider}|${model.model}`}>
                  {model.label}{model.enabled ? "" : " (کلید تنظیم نشده)"}
                </option>
              ))}
            </select>
          </label>
          <button className={styles.iconButton} type="button" disabled title="تبدیل گفتار به متن - به‌زودی"><AppIcon name="mic" /></button>
          <button className={styles.iconButton} type="button" disabled title="گفتگو با مدل - به‌زودی"><AppIcon name="wave" /></button>
        </div>
      </form>
    </div>
  );
}
