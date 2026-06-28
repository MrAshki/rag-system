import { AppIcon } from "@/components/AppIcon";
import type { Conversation } from "@/types/api";
import styles from "@/app/page.module.css";
import { useState } from "react";

type ConversationRailProps = {
  conversations: Conversation[];
  activeConversationId: string | null;
  onCreateConversation: () => void;
  onSelectConversation: (id: string) => void;
  onRenameConversation: (conversation: Conversation) => void;
  onDeleteConversation: (conversation: Conversation) => void;
};

export function ConversationRail({
  conversations,
  activeConversationId,
  onCreateConversation,
  onSelectConversation,
  onRenameConversation,
  onDeleteConversation,
}: ConversationRailProps) {
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);

  return (
    <aside className={styles.conversations}>
      <div className={styles.conversationHead}>
        <h2>گفتگوها</h2>
        <button onClick={onCreateConversation} type="button"><AppIcon name="plus" /></button>
      </div>
      <div className={styles.conversationList}>
        {conversations.map((conversation) => (
          <div
            className={`${styles.conversationItem} ${conversation.id === activeConversationId ? styles.activeConversation : ""}`}
            key={conversation.id}
          >
            <button className={styles.conversationSelect} onClick={() => onSelectConversation(conversation.id)} type="button">
              <span>{conversation.title}</span>
              <AppIcon name="chat" />
            </button>
            <div className={styles.conversationActions}>
              <button
                className={styles.menuButton}
                onClick={() => setOpenMenuId((current) => current === conversation.id ? null : conversation.id)}
                type="button"
                title="گزینه‌های گفتگو"
              >
                <AppIcon name="more" />
              </button>
              {openMenuId === conversation.id && (
                <div className={styles.conversationMenu}>
                  <button onClick={() => { setOpenMenuId(null); onRenameConversation(conversation); }} type="button">
                    <AppIcon name="edit" /> تغییر نام
                  </button>
                  <button onClick={() => { setOpenMenuId(null); onDeleteConversation(conversation); }} type="button">
                    <AppIcon name="trash" /> حذف گفتگو
                  </button>
                  <button disabled type="button">
                    <AppIcon name="share" /> اشتراک‌گذاری
                  </button>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}
