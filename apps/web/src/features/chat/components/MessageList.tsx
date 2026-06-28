import { ReactNode } from "react";
import { AppIcon } from "@/components/AppIcon";
import type { ChatMessage } from "@/types/api";
import styles from "@/app/page.module.css";

function answerNodes(content: string, sources: string[] = []) {
  const nodes: ReactNode[] = [];
  const regex = /\[(S\d+)\]/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(content))) {
    if (match.index > lastIndex) nodes.push(content.slice(lastIndex, match.index));
    const sourceIndex = Number(match[1].replace("S", "")) - 1;
    const source = sources[sourceIndex];
    if (source) {
      nodes.push(
        <span className={styles.cite} key={`${match[1]}-${match.index}`} title={source}>
          {sourceIndex + 1}
        </span>,
      );
    }
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < content.length) nodes.push(content.slice(lastIndex));
  return nodes;
}

export function MessageList({ messages }: { messages: ChatMessage[] }) {
  return (
    <div className={styles.messages}>
      {!messages.length && (
        <div className={styles.empty}>
          <AppIcon name="chat" />
          <h2>سؤال خود را بپرسید</h2>
          <p>برای پاسخ مستند، از دکمه + منابع آماده را انتخاب کنید.</p>
        </div>
      )}
      {messages.map((message) => (
        <div className={`${styles.message} ${message.role === "user" ? styles.userMessage : styles.assistantMessage}`} key={message.id}>
          {message.role === "assistant" && message.status === "streaming" && !message.content && (
            <span className={styles.trace}>{message.stream_status || "در حال آماده‌سازی..."}</span>
          )}
          <div>{message.role === "assistant" ? answerNodes(message.content, message.sources) : message.content}</div>
        </div>
      ))}
    </div>
  );
}
