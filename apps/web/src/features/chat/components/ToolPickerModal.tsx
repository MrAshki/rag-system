"use client";

import { useMemo, useState } from "react";
import { AppIcon } from "@/components/AppIcon";
import type { Asset, ChatTool, SelectedTool, ToolParamSchema } from "@/types/api";
import { assetIsSelectable, assetName } from "@/features/chat/utils/assets";
import styles from "@/app/page.module.css";

type ToolPickerModalProps = {
  tools: ChatTool[];
  assets: Asset[];
  selectedTool: SelectedTool | null;
  selectedAssetIds: Set<string>;
  onClose: () => void;
  onConfirm: (selection: SelectedTool) => void;
  onClear: () => void;
};

const categoryLabels: Record<string, string> = {
  documents: "اسناد",
  education: "آموزش",
  writing: "نوشتن",
  legal: "حقوقی",
};

function initialParams(tool: ChatTool) {
  const values: SelectedTool["params"] = {};
  for (const field of tool.params_schema) {
    if (field.default !== undefined) values[field.id] = field.default;
    else if (field.type === "boolean") values[field.id] = false;
    else values[field.id] = "";
  }
  return values;
}

function isFilled(value: unknown) {
  return value !== undefined && value !== null && String(value).trim() !== "";
}

export function ToolPickerModal({
  tools,
  assets,
  selectedTool,
  selectedAssetIds,
  onClose,
  onConfirm,
  onClear,
}: ToolPickerModalProps) {
  const [activeToolId, setActiveToolId] = useState(selectedTool?.tool.id || tools[0]?.id || "");
  const activeTool = useMemo(() => tools.find((tool) => tool.id === activeToolId) || null, [activeToolId, tools]);
  const selectableAssets = useMemo(() => assets.filter(assetIsSelectable), [assets]);
  const [assetQuery, setAssetQuery] = useState("");
  const [toolAssetIds, setToolAssetIds] = useState<Set<string>>(
    () => new Set(selectedTool?.assetIds?.length ? selectedTool.assetIds : [...selectedAssetIds]),
  );
  const [paramsByTool, setParamsByTool] = useState<Record<string, SelectedTool["params"]>>(() => {
    const initial: Record<string, SelectedTool["params"]> = {};
    for (const tool of tools) initial[tool.id] = initialParams(tool);
    if (selectedTool) initial[selectedTool.tool.id] = selectedTool.params;
    return initial;
  });

  const groupedTools = useMemo(() => {
    const groups: Record<string, ChatTool[]> = {};
    for (const tool of tools) {
      groups[tool.category] = groups[tool.category] || [];
      groups[tool.category].push(tool);
    }
    return groups;
  }, [tools]);

  const params = activeTool ? paramsByTool[activeTool.id] || initialParams(activeTool) : {};
  const missingRequired = activeTool?.params_schema.some((field) => field.required && !isFilled(params[field.id])) ?? true;
  const missingAssets = Boolean(activeTool?.requires_assets && toolAssetIds.size === 0);
  const examCountError = activeTool?.id === "exam_generation" ? getExamCountError(params) : "";
  const canConfirm = Boolean(activeTool && !missingRequired && !missingAssets && !examCountError);
  const filteredAssets = selectableAssets.filter((asset) => assetName(asset).toLowerCase().includes(assetQuery.trim().toLowerCase()));

  function updateParam(field: ToolParamSchema, value: string | number | boolean) {
    if (!activeTool) return;
    setParamsByTool((current) => ({
      ...current,
      [activeTool.id]: {
        ...(current[activeTool.id] || initialParams(activeTool)),
        [field.id]: value,
      },
    }));
  }

  function toggleToolAsset(assetId: string, checked: boolean) {
    setToolAssetIds((current) => {
      const next = new Set(current);
      if (checked) next.add(assetId);
      else next.delete(assetId);
      return next;
    });
  }

  return (
    <div className={styles.modalBackdrop} role="dialog" aria-modal="true" aria-labelledby="tool-picker-title">
      <div className={styles.toolModal}>
        <div className={styles.modalHead}>
          <div>
            <h2 id="tool-picker-title">انتخاب ابزار چت</h2>
            <p>ابزار و پارامترها جدا از متن پیام به بک‌اند ارسال می‌شوند.</p>
          </div>
          <button onClick={onClose} type="button" title="بستن"><AppIcon name="x" /></button>
        </div>

        <div className={styles.toolPickerBody}>
          <aside className={styles.toolPickerList}>
            {Object.entries(groupedTools).map(([category, rows]) => (
              <section key={category}>
                <h3>{categoryLabels[category] || category}</h3>
                {rows.map((tool) => (
                  <button
                    className={`${styles.toolChoice} ${tool.id === activeToolId ? styles.activeToolChoice : ""}`}
                    key={tool.id}
                    onClick={() => setActiveToolId(tool.id)}
                    type="button"
                  >
                    <span><AppIcon name={iconForTool(tool)} /></span>
                    <strong>{tool.title}</strong>
                    {tool.requires_assets && <small>نیازمند منبع</small>}
                  </button>
                ))}
              </section>
            ))}
          </aside>

          <section className={styles.toolPickerForm}>
            {activeTool ? (
              <>
                <div className={styles.toolDetailHead}>
                  <span><AppIcon name={iconForTool(activeTool)} /></span>
                  <div>
                    <h3>{activeTool.title}</h3>
                    <p>{activeTool.description}</p>
                  </div>
                </div>

                {missingAssets && (
                  <div className={styles.toolWarning}>این ابزار به حداقل یک منبع انتخاب‌شده نیاز دارد.</div>
                )}
                {examCountError && (
                  <div className={styles.toolWarning}>{examCountError}</div>
                )}

                <div className={styles.toolSourcesBox}>
                  <div className={styles.toolSourcesHead}>
                    <div>
                      <h4>منابع ابزار</h4>
                      <p>{activeTool.requires_assets ? "برای اجرای این ابزار منبع انتخاب کنید." : "اگر می‌خواهید ابزار روی فایل‌ها کار کند، منابع را همین‌جا انتخاب کنید."}</p>
                    </div>
                    <span>{toolAssetIds.size.toLocaleString("fa-IR")} منبع</span>
                  </div>
                  <input
                    value={assetQuery}
                    onChange={(event) => setAssetQuery(event.target.value)}
                    placeholder="جستجوی منابع آماده..."
                  />
                  <div className={styles.toolAssetList}>
                    {filteredAssets.length ? filteredAssets.map((asset) => (
                      <label key={asset.id}>
                        <input
                          type="checkbox"
                          checked={toolAssetIds.has(asset.id)}
                          onChange={(event) => toggleToolAsset(asset.id, event.target.checked)}
                        />
                        <span>{assetName(asset)}</span>
                      </label>
                    )) : <p>منبع متنی آماده‌ای پیدا نشد.</p>}
                  </div>
                </div>

                <div className={styles.paramGrid}>
                  {activeTool.params_schema.map((field) => (
                    <label className={field.type === "textarea" ? styles.paramWide : ""} key={field.id}>
                      <span>{field.label}{field.required ? " *" : ""}</span>
                      <ParamInput field={field} value={params[field.id]} onChange={(value) => updateParam(field, value)} />
                    </label>
                  ))}
                </div>
              </>
            ) : (
              <div className={styles.emptyAssets}>ابزاری برای نمایش وجود ندارد.</div>
            )}
          </section>
        </div>

        <div className={styles.toolPickerActions}>
          <button className={styles.secondaryButton} onClick={onClear} type="button" disabled={!selectedTool}>
            حذف ابزار
          </button>
          <div>
            <button className={styles.secondaryButton} onClick={onClose} type="button">انصراف</button>
            <button
              className={styles.primaryButton}
              disabled={!canConfirm || !activeTool}
              onClick={() => activeTool && onConfirm({ tool: activeTool, params, assetIds: [...toolAssetIds] })}
              type="button"
            >
              تایید ابزار
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ParamInput({
  field,
  value,
  onChange,
}: {
  field: ToolParamSchema;
  value: string | number | boolean | undefined;
  onChange: (value: string | number | boolean) => void;
}) {
  if (field.type === "select") {
    return (
      <select value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}>
        {(field.options || []).map((option) => (
          <option value={option.value} key={option.value}>{option.label}</option>
        ))}
      </select>
    );
  }

  if (field.type === "number") {
    return (
      <input
        type="number"
        min={field.min}
        max={field.max}
        value={String(value ?? "")}
        onChange={(event) => onChange(event.target.value ? Number(event.target.value) : "")}
      />
    );
  }

  if (field.type === "textarea") {
    return <textarea value={String(value ?? "")} placeholder={field.placeholder} onChange={(event) => onChange(event.target.value)} />;
  }

  if (field.type === "boolean") {
    return (
      <input
        checked={Boolean(value)}
        type="checkbox"
        onChange={(event) => onChange(event.target.checked)}
      />
    );
  }

  return <input value={String(value ?? "")} placeholder={field.placeholder} onChange={(event) => onChange(event.target.value)} />;
}

function getExamCountError(params: SelectedTool["params"]) {
  const total = Number(params.question_count || 0);
  const multipleChoice = Number(params.multiple_choice_count || 0);
  const descriptive = Number(params.descriptive_count || 0);
  if (!total && !multipleChoice && !descriptive) return "";
  if (multipleChoice + descriptive !== total) {
    return "جمع سؤال‌های تستی و تشریحی باید با تعداد کل سؤال برابر باشد.";
  }
  if (total <= 0) return "تعداد سؤال باید بیشتر از صفر باشد.";
  return "";
}

function iconForTool(tool: ChatTool): Parameters<typeof AppIcon>[0]["name"] {
  if (tool.id === "exam_generation") return "exam";
  if (tool.id === "flashcards") return "flashcard";
  if (tool.id === "legal_pleading" || tool.id === "legal_review") return "legal";
  if (tool.id === "compare_documents") return "compare";
  if (tool.id === "key_points") return "key";
  if (tool.id === "article_draft") return "article";
  if (tool.id === "rewrite") return "edit";
  return "summary";
}
