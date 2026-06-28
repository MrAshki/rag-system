import type { Asset } from "@/types/api";

export const sourceCategories = ["text", "image", "audio", "video"] as const;

export function assetName(asset: Asset) {
  return asset.original_filename || asset.filename || "فایل";
}

export function categoryLabel(category: string) {
  return { text: "متنی", image: "تصویر", audio: "صوت", video: "ویدیو" }[category] || category;
}

export function statusLabel(status: string) {
  return {
    uploaded: "در صف",
    scanning: "در حال پردازش",
    scanned: "آماده",
    stored: "ذخیره‌شده",
    failed: "ناموفق",
  }[status] || status;
}

export function assetIsSelectable(asset: Asset) {
  return asset.category === "text" && asset.status === "scanned";
}
