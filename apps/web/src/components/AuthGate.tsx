import { AppIcon } from "@/components/AppIcon";
import type { AuthState } from "@/types/api";
import styles from "@/app/page.module.css";

export function AuthGate({ auth }: { auth: Extract<AuthState, { state: "guest" | "unsubscribed" }> }) {
  return (
    <main className={styles.centerState}>
      <div className={styles.gate}>
        <AppIcon name="chat" />
        <h1>{auth.state === "guest" ? "ورود لازم است" : "اشتراک فعال نیست"}</h1>
        <p>
          {auth.state === "guest" && auth.checking
            ? "در حال بررسی نشست کاربری..."
            : "برای استفاده از دستیار، از مسیر فعلی احراز هویت وارد شوید."}
        </p>
        <a href="/login">رفتن به ورود</a>
      </div>
    </main>
  );
}
