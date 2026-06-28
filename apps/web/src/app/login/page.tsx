"use client";

import { FormEvent, useState } from "react";
import { AppIcon } from "@/components/AppIcon";
import { loginWithEmail, requestOtp, verifyOtp } from "@/features/auth/api";
import styles from "./login.module.css";

type LoginMode = "email" | "phone";

export default function LoginPage() {
  const [mode, setMode] = useState<LoginMode>("email");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [isError, setIsError] = useState(false);
  const [loading, setLoading] = useState(false);

  function showMessage(text: string, error = false) {
    setMessage(text);
    setIsError(error);
  }

  function redirectAfterLogin(isAdmin?: boolean) {
    window.location.href = isAdmin ? "/admin" : "/";
  }

  async function submitEmail(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    showMessage("");
    try {
      const data = await loginWithEmail(email.trim(), password);
      redirectAfterLogin(data.is_admin);
    } catch (error) {
      showMessage(error instanceof Error ? error.message : "ورود ناموفق بود.", true);
    } finally {
      setLoading(false);
    }
  }

  async function submitPhone(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    showMessage("");
    try {
      if (!otpSent) {
        await requestOtp(phone.trim());
        setOtpSent(true);
        showMessage("کد ورود ارسال شد.");
      } else {
        const data = await verifyOtp(phone.trim(), code.trim());
        redirectAfterLogin(data.is_admin);
      }
    } catch (error) {
      showMessage(error instanceof Error ? error.message : "ورود ناموفق بود.", true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className={styles.page}>
      <section className={styles.card}>
        <div className={styles.brand}>
          <span className={styles.brandIcon}><AppIcon name="file" /></span>
          <h1>دستیار اسناد</h1>
        </div>

        <div className={styles.tabs}>
          <button className={mode === "email" ? styles.active : ""} onClick={() => setMode("email")} type="button">ایمیل</button>
          <button className={mode === "phone" ? styles.active : ""} onClick={() => setMode("phone")} type="button">موبایل</button>
        </div>

        {mode === "email" ? (
          <form onSubmit={submitEmail}>
            <p className={styles.hint}>با ایمیل و رمز عبوری که هنگام ثبت‌نام انتخاب کرده‌اید وارد شوید.</p>
            <div className={styles.field}>
              <label htmlFor="email">ایمیل</label>
              <input id="email" autoComplete="email" dir="ltr" value={email} onChange={(event) => setEmail(event.target.value)} required type="email" />
            </div>
            <div className={styles.field}>
              <label htmlFor="password">رمز عبور</label>
              <input id="password" autoComplete="current-password" dir="ltr" value={password} onChange={(event) => setPassword(event.target.value)} required type="password" />
            </div>
            <button className={styles.primary} disabled={loading} type="submit">ورود</button>
          </form>
        ) : (
          <form onSubmit={submitPhone}>
            <p className={styles.hint}>شماره موبایل خود را وارد کنید؛ سپس کد تأیید را همین‌جا ثبت کنید.</p>
            <div className={styles.field}>
              <label htmlFor="phone">موبایل</label>
              <input id="phone" autoComplete="tel" dir="ltr" value={phone} onChange={(event) => setPhone(event.target.value)} required type="tel" />
            </div>
            {otpSent && (
              <div className={styles.field}>
                <label htmlFor="code">کد تأیید</label>
                <input id="code" autoComplete="one-time-code" dir="ltr" inputMode="numeric" maxLength={6} value={code} onChange={(event) => setCode(event.target.value)} required />
              </div>
            )}
            <button className={styles.primary} disabled={loading} type="submit">{otpSent ? "ورود" : "دریافت کد"}</button>
          </form>
        )}

        <div className={`${styles.message} ${isError ? styles.error : ""}`}>{message}</div>
        <div className={styles.footer}>حساب کاربری ندارید؟ <a href="/register">ثبت‌نام کنید</a></div>
      </section>
    </main>
  );
}
