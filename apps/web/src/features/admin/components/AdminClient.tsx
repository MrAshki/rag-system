"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { AppIcon } from "@/components/AppIcon";
import {
  AdminPayment,
  AdminSubscription,
  AdminUser,
  getAdminPayments,
  getAdminStats,
  getAdminSubscriptions,
  getAdminUsers,
  getPlans,
  grantSubscription,
  Plan,
  revokeSubscription,
} from "@/features/admin/api";
import { logout } from "@/features/auth/api";
import styles from "@/app/admin/admin.module.css";

function formatDate(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10);
  return date.toLocaleDateString("fa-IR");
}

function statusLabel(status: string) {
  if (status === "active") return "فعال";
  if (status === "cancelled") return "لغو شده";
  if (status === "paid") return "پرداخت شده";
  if (status === "pending") return "در انتظار";
  if (status === "failed") return "ناموفق";
  return status;
}

function statusClass(status: string) {
  if (["active", "paid"].includes(status)) return styles.ok;
  if (["failed", "cancelled"].includes(status)) return styles.bad;
  return "";
}

export function AdminClient() {
  const [stats, setStats] = useState({ total_users: 0, active_subscriptions: 0 });
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [subscriptions, setSubscriptions] = useState<AdminSubscription[]>([]);
  const [payments, setPayments] = useState<AdminPayment[]>([]);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [grantPhone, setGrantPhone] = useState("");
  const [grantPlan, setGrantPlan] = useState("");
  const [message, setMessage] = useState("");
  const [isError, setIsError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  function showMessage(text: string, error = false) {
    setMessage(text);
    setIsError(error);
  }

  const load = useCallback(async function load() {
    setLoading(true);
    try {
      const [statsData, usersData, subsData, paymentsData, plansData] = await Promise.all([
        getAdminStats(),
        getAdminUsers(),
        getAdminSubscriptions(),
        getAdminPayments(),
        getPlans(),
      ]);
      setStats(statsData);
      setUsers(usersData.users || []);
      setSubscriptions(subsData.subscriptions || []);
      setPayments(paymentsData.payments || []);
      setPlans(plansData.plans || []);
      if (!grantPlan && plansData.plans?.[0]) setGrantPlan(String(plansData.plans[0].id));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : "خطا در دریافت اطلاعات مدیریت.", true);
    } finally {
      setLoading(false);
    }
  }, [grantPlan]);

  async function submitGrant(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    showMessage("در حال اعطا...");
    try {
      await grantSubscription(grantPhone.trim(), grantPlan);
      setGrantPhone("");
      showMessage("اشتراک اعطا شد.");
      await load();
    } catch (error) {
      showMessage(error instanceof Error ? error.message : "خطا در اعطای اشتراک.", true);
    } finally {
      setSaving(false);
    }
  }

  async function revoke(id: number) {
    if (!window.confirm("این اشتراک لغو شود؟")) return;
    setSaving(true);
    try {
      await revokeSubscription(id);
      await load();
    } catch (error) {
      showMessage(error instanceof Error ? error.message : "خطا در لغو اشتراک.", true);
    } finally {
      setSaving(false);
    }
  }

  async function logoutUser() {
    await logout();
    window.location.href = "/login";
  }

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <div className={styles.brand}><AppIcon name="settings" /> پنل مدیریت</div>
        <div className={styles.actions}>
          <Link href="/">بازگشت به برنامه</Link>
          <button onClick={() => void logoutUser()} type="button">خروج</button>
        </div>
      </header>

      <div className={styles.content}>
        <section className={styles.stats}>
          <div className={styles.stat}><b>{stats.total_users.toLocaleString("fa-IR")}</b><span>کل کاربران</span></div>
          <div className={styles.stat}><b>{stats.active_subscriptions.toLocaleString("fa-IR")}</b><span>اشتراک فعال</span></div>
        </section>

        <form className={styles.card} onSubmit={submitGrant}>
          <h2>اعطای دستی اشتراک</h2>
          <div className={styles.grant}>
            <div className={styles.field}>
              <label htmlFor="grantPhone">شماره موبایل</label>
              <input id="grantPhone" dir="ltr" inputMode="numeric" value={grantPhone} onChange={(event) => setGrantPhone(event.target.value)} placeholder="09xxxxxxxxx" />
            </div>
            <div className={styles.field}>
              <label htmlFor="grantPlan">پلن</label>
              <select id="grantPlan" value={grantPlan} onChange={(event) => setGrantPlan(event.target.value)}>
                {plans.map((plan) => (
                  <option key={plan.id} value={plan.id}>{plan.name} - {plan.price_toman.toLocaleString("fa-IR")} تومان</option>
                ))}
              </select>
            </div>
            <button className={styles.primary} disabled={saving || !grantPhone.trim() || !grantPlan} type="submit">اعطا کن</button>
          </div>
          <div className={`${styles.message} ${isError ? styles.error : ""}`}>{message}</div>
        </form>

        <AdminTable title="کاربران" empty={loading ? "در حال دریافت..." : "کاربری وجود ندارد."} rowCount={users.length}>
          <table className={styles.table}>
            <thead><tr><th>شماره</th><th>ثبت‌نام</th><th>اشتراک</th><th>انقضا</th><th>نقش</th></tr></thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td dir="ltr">{user.phone}</td>
                  <td>{formatDate(user.created_at)}</td>
                  <td><span className={`${styles.badge} ${user.has_subscription ? styles.ok : ""}`}>{user.has_subscription ? "فعال" : "ندارد"}</span></td>
                  <td>{formatDate(user.subscription_expires_at)}</td>
                  <td><span className={styles.badge}>{user.is_admin ? "مدیر" : "کاربر"}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </AdminTable>

        <AdminTable title="اشتراک‌ها" empty={loading ? "در حال دریافت..." : "اشتراکی وجود ندارد."} rowCount={subscriptions.length}>
          <table className={styles.table}>
            <thead><tr><th>شماره</th><th>پلن</th><th>شروع</th><th>انقضا</th><th>وضعیت</th><th /></tr></thead>
            <tbody>
              {subscriptions.map((sub) => (
                <tr key={sub.id}>
                  <td dir="ltr">{sub.phone}</td>
                  <td>{sub.plan_name}</td>
                  <td>{formatDate(sub.starts_at)}</td>
                  <td>{formatDate(sub.expires_at)}</td>
                  <td><span className={`${styles.badge} ${statusClass(sub.status)}`}>{statusLabel(sub.status)}</span></td>
                  <td>{sub.status === "active" && <button className={styles.danger} disabled={saving} onClick={() => void revoke(sub.id)} type="button">لغو</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </AdminTable>

        <AdminTable title="پرداخت‌ها" empty={loading ? "در حال دریافت..." : "پرداختی وجود ندارد."} rowCount={payments.length}>
          <table className={styles.table}>
            <thead><tr><th>شماره</th><th>پلن</th><th>مبلغ</th><th>وضعیت</th><th>تاریخ</th></tr></thead>
            <tbody>
              {payments.map((payment) => (
                <tr key={payment.id}>
                  <td dir="ltr">{payment.phone}</td>
                  <td>{payment.plan_name}</td>
                  <td>{payment.amount_toman.toLocaleString("fa-IR")}</td>
                  <td><span className={`${styles.badge} ${statusClass(payment.status)}`}>{statusLabel(payment.status)}</span></td>
                  <td>{formatDate(payment.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </AdminTable>
      </div>
    </main>
  );
}

function AdminTable({ title, empty, rowCount, children }: { title: string; empty: string; rowCount: number; children: ReactNode }) {
  return (
    <section className={styles.card}>
      <h2>{title}</h2>
      <div className={styles.tableWrap}>{children}</div>
      {!rowCount && <div className={styles.empty}>{empty}</div>}
    </section>
  );
}
