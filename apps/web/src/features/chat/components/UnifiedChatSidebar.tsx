"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { AppIcon } from "@/components/AppIcon";
import type { Conversation } from "@/types/api";
import styles from "@/app/page.module.css";

type UnifiedChatSidebarProps = {
  userLabel: string;
  conversations: Conversation[];
  activeConversationId: string | null;
  isLoggingOut: boolean;
  onCreateConversation: () => void;
  onSelectConversation: (id: string) => void;
  onRenameConversation: (conversation: Conversation) => void;
  onDeleteConversation: (conversation: Conversation) => void;
  onLogout: () => void;
};

export function UnifiedChatSidebar({
  userLabel,
  conversations,
  activeConversationId,
  isLoggingOut,
  onCreateConversation,
  onSelectConversation,
  onRenameConversation,
  onDeleteConversation,
  onLogout,
}: UnifiedChatSidebarProps) {
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLowerCase();
  const filteredConversations = useMemo(() => {
    if (!normalizedQuery) return conversations;
    return conversations.filter((conversation) => conversation.title.toLowerCase().includes(normalizedQuery));
  }, [conversations, normalizedQuery]);

  return (
    <aside className={styles.unifiedSidebar} aria-label="ناوبری و گفتگوها">
      <div className={styles.sidebarBrand}>
        <span className={styles.brandMark} aria-hidden="true" />
        <div>
          <strong>دستیار اسناد</strong>
          <small>چت، ابزارها و منابع در یک جریان</small>
        </div>
      </div>

      <button className={styles.newChatButton} onClick={onCreateConversation} type="button">
        <AppIcon name="plus" />
        گفتگوی جدید
      </button>

      <label className={styles.sidebarSearch}>
        <AppIcon name="search" />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="جستجوی گفتگوها" />
      </label>

      <nav className={styles.sidebarNav} aria-label="بخش‌های اصلی">
        <Link className={`${styles.sidebarNavItem} ${styles.activeSidebarNavItem}`} href="/">
          <AppIcon name="chat" />
          <span>
            <strong>گفتگو</strong>
            <small>چت آزاد، مستند و ابزارها</small>
          </span>
        </Link>
        <Link className={styles.sidebarNavItem} href="/gallery">
          <AppIcon name="library" />
          <span>
            <strong>کتابخانه</strong>
            <small>منابع و فایل‌ها</small>
          </span>
        </Link>
        <Link className={styles.sidebarNavItem} href="/profile">
          <AppIcon name="settings" />
          <span>
            <strong>تنظیمات</strong>
            <small>حساب، اشتراک و مدل‌ها</small>
          </span>
        </Link>
      </nav>

      <div className={styles.sidebarSectionHead}>
        <span>گفتگوهای اخیر</span>
        <b>{filteredConversations.length.toLocaleString("fa-IR")}</b>
      </div>

      <div className={styles.sidebarConversationList}>
        {filteredConversations.length ? filteredConversations.map((conversation) => (
          <div
            className={`${styles.sidebarConversation} ${conversation.id === activeConversationId ? styles.activeSidebarConversation : ""}`}
            key={conversation.id}
          >
            <button className={styles.sidebarConversationSelect} onClick={() => onSelectConversation(conversation.id)} type="button">
              <AppIcon name="chat" />
              <span>{conversation.title}</span>
            </button>
            <button
              className={styles.sidebarMenuButton}
              onClick={() => setOpenMenuId((current) => current === conversation.id ? null : conversation.id)}
              type="button"
              title="گزینه‌های گفتگو"
            >
              <AppIcon name="more" />
            </button>
            {openMenuId === conversation.id && (
              <div className={styles.sidebarConversationMenu}>
                <button onClick={() => { setOpenMenuId(null); onRenameConversation(conversation); }} type="button">
                  <AppIcon name="edit" /> تغییر نام
                </button>
                <button onClick={() => { setOpenMenuId(null); onDeleteConversation(conversation); }} type="button">
                  <AppIcon name="trash" /> حذف گفتگو
                </button>
              </div>
            )}
          </div>
        )) : (
          <p className={styles.sidebarEmpty}>گفتگویی پیدا نشد.</p>
        )}
      </div>

      <div className={styles.sidebarFooter}>
        <Link className={styles.sidebarUser} href="/profile">
          <span><AppIcon name="user" /></span>
          <strong>{userLabel}</strong>
        </Link>
        <button className={styles.sidebarLogout} disabled={isLoggingOut} onClick={onLogout} type="button">
          <AppIcon name="logout" />
          {isLoggingOut ? "در حال خروج" : "خروج"}
        </button>
      </div>
    </aside>
  );
}
