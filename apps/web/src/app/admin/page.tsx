import Link from "next/link";
import { AuthGate } from "@/components/AuthGate";
import { AdminClient } from "@/features/admin/components/AdminClient";
import { getServerAuth } from "@/lib/server-auth";
import styles from "@/app/page.module.css";

export default async function AdminPage() {
  const auth = await getServerAuth();

  if (auth.state === "guest") {
    return <AuthGate auth={{ state: "guest" }} />;
  }

  if (auth.state !== "ready" || !auth.isAdmin) {
    return (
      <main className={styles.centerState}>
        <div className={styles.gate}>
          <h1>دسترسی غیرمجاز</h1>
          <p>برای مشاهده پنل مدیریت باید با حساب مدیر وارد شوید.</p>
          <Link href="/">بازگشت به برنامه</Link>
        </div>
      </main>
    );
  }

  return <AdminClient />;
}
