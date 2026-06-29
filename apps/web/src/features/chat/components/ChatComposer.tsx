import { FormEvent, RefObject } from "react";
import { AppIcon } from "@/components/AppIcon";
import type { ChatModel, SelectedTool } from "@/types/api";
import styles from "@/app/page.module.css";

type ChatComposerProps = {
  question: string;
  selectedModel: string;
  models: ChatModel[];
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
  onClearTool: () => void;
  onModelChange: (value: string) => void;
};

export function ChatComposer({
  question,
  selectedModel,
  models,
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
  onClearTool,
  onModelChange,
}: ChatComposerProps) {
  return (
    <div className={styles.composer}>
      {selectedTool && (
        <div className={styles.composerMeta}>
          <span><AppIcon name="tools" /> ابزار فعال: {selectedTool.tool.title}{selectedTool.assetIds.length ? ` · ${selectedTool.assetIds.length.toLocaleString("fa-IR")} منبع` : ""}</span>
          <button className={styles.toolRunButton} disabled={isSending} onClick={() => onSubmit()} type="button">
            اجرای ابزار
          </button>
          <button onClick={onClearTool} type="button" title="حذف ابزار"><AppIcon name="x" /></button>
        </div>
      )}
      <form className={styles.composerCard} onSubmit={onSubmit}>
        <div className={styles.composerLeft}>
          <div className={styles.sourceWrap}>
            <button className={`${styles.iconButton} ${selectedSourceCount || selectedTool ? styles.hasSources : ""}`} type="button" onClick={onToggleSourceMenu} title="افزودن">
              <AppIcon name="plus" />
              {selectedSourceCount > 0 && <span>{selectedSourceCount.toLocaleString("fa-IR")}</span>}
            </button>
            {sourceMenuOpen && (
              <div className={styles.sourceMenu}>
                <button type="button" onClick={onOpenSourceModal}>
                  <AppIcon name="file" /> اضافه کردن منابع
                </button>
                <button type="button" onClick={onOpenToolPicker}>
                  <AppIcon name="tools" /> انتخاب ابزار
                </button>
              </div>
            )}
          </div>
          <button className={styles.send} type="submit" disabled={isSending || (!question.trim() && !selectedTool)} title="ارسال"><AppIcon name="send" /></button>
        </div>
        <textarea
          ref={textareaRef}
          value={question}
          rows={1}
          placeholder={selectedTool ? "برای اجرای ابزار، ارسال را بزنید یا جزئیات بیشتری بنویسید..." : "سؤال خود را بنویسید..."}
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
