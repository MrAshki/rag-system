"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { AppIcon } from "@/components/AppIcon";
import { getProfile, getProfilePayments, Payment, updateProfile } from "@/features/account/api";
import { logout } from "@/features/auth/api";
import styles from "@/app/profile/profile.module.css";

function paymentStatus(status: string) {
  if (status === "paid") return { label: "موفق", className: styles.paid };
  if (status === "failed") return { label: "ناموفق", className: styles.failed };
  if (status === "pending") return { label: "در انتظار", className: "" };
  return { label: status, className: "" };
}

function formatDate(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("fa-IR");
}

export function ProfileClient() {
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [password, setPassword] = useState("");
  const [payments, setPayments] = useState<Payment[]>([]);
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
      const [profile, paymentData] = await Promise.all([getProfile(), getProfilePayments()]);
      setFirstName(profile.first_name || "");
      setLastName(profile.last_name || "");
      setPhone(profile.phone || "");
      setEmail(profile.email || "");
      setBirthDate(profile.birth_date || "");
      setPayments(paymentData.payments || []);
    } catch (error) {
      showMessage(error instanceof Error ? error.message : "خطا در دریافت اطلاعات.", true);
    } finally {
      setLoading(false);
    }
  }, []);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (password && password.length < 6) {
      showMessage("رمز عبور حداقل ۶ کاراکتر باشد.", true);
      return;
    }
    setSaving(true);
    showMessage("");
    try {
      await updateProfile({
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        email: email.trim(),
        birth_date: birthDate || null,
        password: password || undefined,
      });
      setPassword("");
      showMessage("ذخیره شد.");
    } catch (error) {
      showMessage(error instanceof Error ? error.message : "خطا در ذخیره.", true);
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
        <Link className={styles.brand} href="/">
          <AppIcon name="file" /> دستیار اسناد
        </Link>
        <div className={styles.actions}>
          <Link href="/">بازگشت به داشبورد</Link>
          <button onClick={() => void logoutUser()} type="button">خروج</button>
        </div>
      </header>

      <div className={styles.content}>
        <div className={styles.head}>
          <h1>حساب کاربری</h1>
          <p>اطلاعات حساب و سوابق پرداخت خود را مدیریت کنید.</p>
        </div>

        <form className={styles.card} onSubmit={save}>
          <h2>اطلاعات من</h2>
          <p className={styles.sub}>شماره موبایل قابل ویرایش نیست؛ بقیه فیلدها را می‌توانید تغییر دهید.</p>

          <div className={styles.row}>
            <div className={styles.field}>
              <label htmlFor="firstName">نام</label>
              <input id="firstName" disabled={loading} value={firstName} onChange={(event) => setFirstName(event.target.value)} />
            </div>
            <div className={styles.field}>
              <label htmlFor="lastName">نام خانوادگی</label>
              <input id="lastName" disabled={loading} value={lastName} onChange={(event) => setLastName(event.target.value)} />
            </div>
          </div>

          <div className={styles.field}>
            <label htmlFor="phone">شماره موبایل</label>
            <input id="phone" dir="ltr" disabled value={phone} />
          </div>

          <div className={styles.field}>
            <label htmlFor="birthDate">تاریخ تولد</label>
            <input id="birthDate" dir="ltr" disabled={loading} type="date" value={birthDate} onChange={(event) => setBirthDate(event.target.value)} />
          </div>

          <div className={styles.field}>
            <label htmlFor="email">ایمیل</label>
            <input id="email" dir="ltr" disabled={loading} type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
          </div>

          <div className={styles.field}>
            <label htmlFor="password">تغییر رمز عبور اختیاری</label>
            <input id="password" autoComplete="new-password" dir="ltr" disabled={loading} type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
          </div>

          <div className={styles.saveRow}>
            <button className={styles.primary} disabled={loading || saving} type="submit">{saving ? "در حال ذخیره..." : "ذخیره تغییرات"}</button>
            <span className={`${styles.message} ${isError ? styles.error : ""}`}>{message}</span>
          </div>
        </form>

        <section className={styles.card}>
          <h2>سوابق پرداخت</h2>
          <p className={styles.sub}>تراکنش‌های خرید اشتراک شما.</p>
          {!payments.length ? (
            <div className={styles.empty}>{loading ? "در حال دریافت..." : "هنوز پرداختی ثبت نشده است."}</div>
          ) : (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr><th>پلن</th><th>مبلغ</th><th>وضعیت</th><th>تاریخ</th></tr>
                </thead>
                <tbody>
                  {payments.map((payment) => {
                    const status = paymentStatus(payment.status);
                    return (
                      <tr key={payment.id}>
                        <td>{payment.plan_name || "-"}</td>
                        <td>{Number(payment.amount_toman || 0).toLocaleString("fa-IR")}</td>
                        <td><span className={`${styles.badge} ${status.className}`}>{status.label}</span></td>
                        <td>{formatDate(payment.created_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
