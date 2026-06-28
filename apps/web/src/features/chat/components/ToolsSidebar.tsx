"use client";

import Link from "next/link";
import { useState } from "react";
import { AppIcon } from "@/components/AppIcon";
import styles from "@/app/page.module.css";

type ToolItem = {
  label: string;
  icon: Parameters<typeof AppIcon>[0]["name"];
  href?: string;
  active?: boolean;
  soon?: boolean;
};

type ToolGroup = {
  id: string;
  title: string;
  icon?: Parameters<typeof AppIcon>[0]["name"];
  items: ToolItem[];
};

const toolGroups: ToolGroup[] = [
  {
    id: "chat",
    title: "چت",
    icon: "chat",
    items: [
      { label: "چت هوشمند", icon: "chat", href: "/", active: true },
    ],
  },
  {
    id: "library",
    title: "کتابخانه",
    icon: "library",
    items: [
      { label: "فایل‌های من", icon: "file", href: "/gallery" },
      { label: "خروجی‌های من", icon: "output", soon: true },
      { label: "قالب‌ها", icon: "template", soon: true },
    ],
  },
  {
    id: "analysis",
    title: "تولید و تحلیل",
    items: [
      { label: "خلاصه‌سازی", icon: "summary", soon: true },
      { label: "استخراج نکات کلیدی", icon: "key", soon: true },
      { label: "مقایسه اسناد", icon: "compare", soon: true },
      { label: "جستجو در اسناد", icon: "search", soon: true },
      { label: "تولید مقاله", icon: "article", soon: true },
    ],
  },
  {
    id: "education",
    title: "آموزش و آزمون",
    items: [
      { label: "طراحی آزمون", icon: "exam", soon: true },
      { label: "فلش‌کارت", icon: "flashcard", soon: true },
      { label: "توضیح ساده‌سازی‌شده", icon: "simple", soon: true },
    ],
  },
  {
    id: "legal",
    title: "حقوقی",
    items: [
      { label: "لایحه‌نویسی", icon: "legal", soon: true },
      { label: "بررسی لایحه", icon: "check", soon: true },
      { label: "قراردادها", icon: "contract", soon: true },
    ],
  },
  {
    id: "media",
    title: "رسانه",
    items: [
      { label: "ابزارهای صوتی", icon: "audio", soon: true },
      { label: "ابزارهای ویدیویی", icon: "video", soon: true },
      { label: "گفتار به متن", icon: "stt", soon: true },
      { label: "متن به گفتار", icon: "tts", soon: true },
    ],
  },
  {
    id: "settings",
    title: "تنظیمات",
    items: [
      { label: "مدل‌ها", icon: "settings", soon: true },
      { label: "Providerها", icon: "provider", soon: true },
      { label: "حساب و اشتراک", icon: "user", href: "/profile" },
    ],
  },
];

export function ToolsSidebar() {
  const [openGroups, setOpenGroups] = useState<Set<string>>(() => new Set(toolGroups.map((group) => group.id)));

  function toggleGroup(id: string) {
    setOpenGroups((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <aside className={styles.tools}>
      <div className={styles.sectionTitle}>ابزارها</div>
      <div className={styles.toolGroups}>
        {toolGroups.map((group) => {
          const open = openGroups.has(group.id);
          return (
            <section className={styles.toolGroup} key={group.id}>
              <button className={styles.toolGroupHeader} onClick={() => toggleGroup(group.id)} type="button" aria-expanded={open}>
                <span className={styles.toolGroupTitle}>
                  {group.icon && <AppIcon name={group.icon} />}
                  {group.title}
                </span>
                <span className={`${styles.toolChevron} ${open ? styles.toolChevronOpen : ""}`}>
                  <AppIcon name="chevron" />
                </span>
              </button>
              {open && (
                <div className={styles.toolGroupItems}>
                  {group.items.map((item) => (
                    <ToolRow item={item} key={`${group.id}-${item.label}`} />
                  ))}
                </div>
              )}
            </section>
          );
        })}
      </div>
    </aside>
  );
}

function ToolRow({ item }: { item: ToolItem }) {
  const className = `${styles.toolRow} ${item.active ? styles.activeTool : ""} ${item.soon && !item.href ? styles.disabledTool : ""}`;
  const content = (
    <>
      <span className={styles.toolIcon}><AppIcon name={item.icon} /></span>
      <span className={styles.toolLabel}>{item.label}</span>
      {item.soon && <span className={styles.soon}>به‌زودی</span>}
    </>
  );

  if (item.href) {
    return <Link className={className} href={item.href}>{content}</Link>;
  }

  return <div className={className} aria-disabled="true">{content}</div>;
}
