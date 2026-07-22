"use client";

import Link from "next/link";
import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppIcon } from "@/components/AppIcon";
import { listAssets, uploadAsset } from "@/features/chat/api";
import { assetName, categoryLabel, statusLabel } from "@/features/chat/utils/assets";
import type { Asset } from "@/types/api";
import styles from "@/app/gallery/gallery.module.css";

function statusClass(asset: Asset) {
  if (asset.status === "scanned") return styles.ready;
  if (asset.status === "failed") return styles.error;
  return "";
}

function assetIsPending(asset: Asset) {
  return asset.status === "uploaded" || asset.status === "scanning";
}

export function GalleryClient() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const hasPendingAssets = assets.some(assetIsPending);

  const filteredAssets = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return assets.filter((asset) => {
      if (category !== "all" && asset.category !== category) return false;
      if (normalized && !assetName(asset).toLowerCase().includes(normalized)) return false;
      return true;
    });
  }, [assets, category, query]);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const data = await listAssets();
      setAssets(data.assets || []);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "خطا در دریافت فایل‌ها.");
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    setUploading(true);
    setStatus("در حال آپلود...");
    try {
      const data = await uploadAsset(file);
      if (data.rejected?.length) {
        setStatus(data.rejected[0].error);
      } else {
        setStatus("فایل دریافت شد و در صف پردازش قرار گرفت.");
      }
      await load();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "خطا در آپلود فایل.");
    } finally {
      setUploading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!hasPendingAssets) return;
    const intervalId = window.setInterval(() => {
      void load(true);
    }, 2500);
    return () => window.clearInterval(intervalId);
  }, [hasPendingAssets, load]);

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <Link className={styles.brand} href="/">
          <AppIcon name="file" /> دستیار اسناد
        </Link>
        <div className={styles.actions}>
          <Link href="/">بازگشت به داشبورد</Link>
        </div>
      </header>

      <div className={styles.content}>
        <div className={styles.head}>
          <div>
            <h1>فایل‌های من</h1>
            <p>فایل‌های خام اینجا مدیریت می‌شوند؛ فقط نسخه پردازش‌شده فایل‌های متنی به مدل پاس داده می‌شود.</p>
          </div>
          <button className={styles.upload} disabled={uploading} onClick={() => inputRef.current?.click()} type="button">
            {uploading ? "در حال آپلود..." : "آپلود فایل"}
          </button>
          <input ref={inputRef} accept=".txt,.pdf,.docx" hidden onChange={(event) => void upload(event)} type="file" />
        </div>

        <section className={styles.card}>
          <div className={styles.toolbar}>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="جستجوی فایل..." />
            <select value={category} onChange={(event) => setCategory(event.target.value)}>
              <option value="all">همه دسته‌ها</option>
              <option value="text">متنی</option>
              <option value="image">تصویر</option>
              <option value="audio">صوت</option>
              <option value="video">ویدیو</option>
            </select>
            <span className={styles.status}>{status}</span>
          </div>

          {loading ? (
            <div className={styles.empty}>در حال دریافت فایل‌ها...</div>
          ) : !filteredAssets.length ? (
            <div className={styles.empty}>فایلی پیدا نشد.</div>
          ) : (
            <div className={styles.grid}>
              {filteredAssets.map((asset) => (
                <article className={styles.asset} key={asset.id}>
                  <h3>{assetName(asset)}</h3>
                  <div className={styles.meta}>
                    <span className={styles.badge}>{categoryLabel(asset.category)}</span>
                    <span className={`${styles.badge} ${statusClass(asset)}`}>{statusLabel(asset.status)}</span>
                    {typeof asset.chunk_count === "number" && <span className={styles.badge}>{asset.chunk_count.toLocaleString("fa-IR")} بخش</span>}
                  </div>
                  {asset.status === "failed" && asset.scan_error && (
                    <p className={styles.assetError}>{asset.scan_error}</p>
                  )}
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
