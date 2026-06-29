"use client";

import Link from "next/link";
import { AppIcon } from "@/components/AppIcon";
import styles from "@/app/page.module.css";

type NavItem = {
  label: string;
  description: string;
  icon: Parameters<typeof AppIcon>[0]["name"];
  href?: string;
  active?: boolean;
  soon?: boolean;
};

const navItems: NavItem[] = [
  {
    label: "گفتگو",
    description: "چت آزاد، چت با اسناد و ابزارهای متنی",
    icon: "chat",
    href: "/",
    active: true,
  },
  {
    label: "کتابخانه",
    description: "فایل‌ها و منابع قابل انتخاب",
    icon: "library",
    href: "/gallery",
  },
  {
    label: "استودیو",
    description: "تولید تصویر، ویدیو، صوت و محتوای رسانه‌ای",
    icon: "studio",
    soon: true,
  },
  {
    label: "خروجی‌ها",
    description: "Canvas، آزمون‌ها، مقاله‌ها و فایل‌های تولیدشده",
    icon: "output",
    soon: true,
  },
  {
    label: "قالب‌ها",
    description: "قالب‌ها و presetهای شخصی",
    icon: "template",
    soon: true,
  },
  {
    label: "تنظیمات",
    description: "حساب، اشتراک و مدل‌های فعال",
    icon: "settings",
    href: "/profile",
  },
];

export function ToolsSidebar() {
  return (
    <aside className={styles.tools}>
      <div className={styles.navIntro}>
        <span><AppIcon name="file" /></span>
        <div>
          <b>دستیار اسناد</b>
          <small>محور اصلی کار از گفتگو شروع می‌شود.</small>
        </div>
      </div>
      <nav className={styles.mainNav} aria-label="ناوبری اصلی">
        {navItems.map((item) => (
          <NavRow item={item} key={item.label} />
        ))}
      </nav>
    </aside>
  );
}

function NavRow({ item }: { item: NavItem }) {
  const className = `${styles.navRow} ${item.active ? styles.activeNavRow : ""} ${item.soon && !item.href ? styles.disabledNavRow : ""}`;
  const content = (
    <>
      <span className={styles.navIcon}><AppIcon name={item.icon} /></span>
      <span className={styles.navText}>
        <strong>{item.label}</strong>
        <small>{item.description}</small>
      </span>
      {item.soon && <span className={styles.soon}>به‌زودی</span>}
    </>
  );

  if (item.href) {
    return <Link className={className} href={item.href}>{content}</Link>;
  }

  return <div className={className} aria-disabled="true">{content}</div>;
}
