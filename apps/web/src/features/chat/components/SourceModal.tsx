import { AppIcon } from "@/components/AppIcon";
import type { Asset } from "@/types/api";
import { assetIsSelectable, assetName, categoryLabel, sourceCategories, statusLabel } from "@/features/chat/utils/assets";
import styles from "@/app/page.module.css";

type SourceModalProps = {
  assets: Asset[];
  selectedAssetIds: Set<string>;
  selectedAssets: Asset[];
  sourceQuery: string;
  onClose: () => void;
  onUploadClick: () => void;
  onClearSelection: () => void;
  onQueryChange: (value: string) => void;
  onToggleAsset: (asset: Asset, checked: boolean) => void;
};

export function SourceModal({
  assets,
  selectedAssetIds,
  selectedAssets,
  sourceQuery,
  onClose,
  onUploadClick,
  onClearSelection,
  onQueryChange,
  onToggleAsset,
}: SourceModalProps) {
  const normalizedQuery = sourceQuery.trim().toLowerCase();

  return (
    <div className={styles.modalBackdrop} onClick={onClose}>
      <div className={styles.modal} onClick={(event) => event.stopPropagation()}>
        <div className={styles.modalHead}>
          <div>
            <h2>انتخاب منابع چت</h2>
            <p>فقط فایل‌های متنی پردازش‌شده به مدل پاس داده می‌شوند.</p>
          </div>
          <button onClick={onClose} type="button"><AppIcon name="x" /></button>
        </div>
        <div className={styles.modalToolbar}>
          <input value={sourceQuery} onChange={(event) => onQueryChange(event.target.value)} placeholder="جستجوی فایل‌ها..." />
          <div>
            <button onClick={onUploadClick} type="button">آپلود فایل</button>
            <button onClick={onClearSelection} type="button">پاک‌کردن انتخاب‌ها</button>
          </div>
        </div>
        <div className={styles.chips}>
          {selectedAssets.length
            ? selectedAssets.map((asset) => <span key={asset.id}>{assetName(asset)}</span>)
            : <em>بدون منبع؛ چت آزاد فعال است.</em>}
        </div>
        <div className={styles.assetGroups}>
          {sourceCategories.map((category) => {
            const rows = assets.filter((asset) => asset.category === category && assetName(asset).toLowerCase().includes(normalizedQuery));
            return (
              <div className={styles.assetGroup} key={category}>
                <div className={styles.assetGroupHead}><span>{categoryLabel(category)}</span><b>{rows.length.toLocaleString("fa-IR")}</b></div>
                {rows.length ? rows.map((asset) => {
                  const selectable = assetIsSelectable(asset);
                  return (
                    <label className={`${styles.assetRow} ${selectable ? "" : styles.disabledAsset}`} key={asset.id}>
                      <input type="checkbox" disabled={!selectable} checked={selectedAssetIds.has(asset.id)} onChange={(event) => onToggleAsset(asset, event.target.checked)} />
                      <span>{assetName(asset)}</span>
                      <small>{selectable ? "آماده" : category === "text" ? statusLabel(asset.status) : "به‌زودی"}</small>
                    </label>
                  );
                }) : <p className={styles.emptyAssets}>فایلی در این دسته وجود ندارد.</p>}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
