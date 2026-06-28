"use client";

import { FormEvent, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { AppIcon } from "@/components/AppIcon";
import { completeRegistration, sendRegistrationOtp, verifyRegistrationOtp } from "@/features/auth/api";
import styles from "./register.module.css";

const JALALI_MONTHS = [
  "فروردین",
  "اردیبهشت",
  "خرداد",
  "تیر",
  "مرداد",
  "شهریور",
  "مهر",
  "آبان",
  "آذر",
  "دی",
  "بهمن",
  "اسفند",
];

const WEEK_DAYS = ["ش", "ی", "د", "س", "چ", "پ", "ج"];

function toEnglishDigits(value: string) {
  return value
    .replace(/[۰-۹]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit)))
    .replace(/[٠-٩]/g, (digit) => String("٠١٢٣٤٥٦٧٨٩".indexOf(digit)));
}

function toPersianDigits(value: string | number) {
  return String(value).replace(/\d/g, (digit) => "۰۱۲۳۴۵۶۷۸۹"[Number(digit)]);
}

function formatJalaliDate(jy: number, jm: number, jd: number) {
  return `${toPersianDigits(jy)}/${toPersianDigits(String(jm).padStart(2, "0"))}/${toPersianDigits(String(jd).padStart(2, "0"))}`;
}

function isJalaliLeapYear(year: number) {
  const breaks = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178];
  let jump = 0;
  let previous = breaks[0];
  for (let i = 1; i < breaks.length; i++) {
    jump = breaks[i] - previous;
    if (year < breaks[i]) break;
    previous = breaks[i];
  }
  let n = year - previous;
  if (jump - n < 6) n = n - jump + Math.floor((jump + 4) / 33) * 33;
  return (((n + 1) % 33) - 1) % 4 === 0;
}

function jalaliMonthLength(year: number, month: number) {
  if (month <= 6) return 31;
  if (month <= 11) return 30;
  return isJalaliLeapYear(year) ? 30 : 29;
}

function jalaliToGregorian(jy: number, jm: number, jd: number) {
  jy += 1595;
  let days =
    -355668 +
    365 * jy +
    Math.floor(jy / 33) * 8 +
    Math.floor(((jy % 33) + 3) / 4) +
    jd +
    (jm < 7 ? (jm - 1) * 31 : (jm - 7) * 30 + 186);

  let gy = 400 * Math.floor(days / 146097);
  days %= 146097;

  if (days > 36524) {
    gy += 100 * Math.floor(--days / 36524);
    days %= 36524;
    if (days >= 365) days++;
  }

  gy += 4 * Math.floor(days / 1461);
  days %= 1461;

  if (days > 365) {
    gy += Math.floor((days - 1) / 365);
    days = (days - 1) % 365;
  }

  let gd = days + 1;
  const monthDays = [0, 31, 28 + Number((gy % 4 === 0 && gy % 100 !== 0) || gy % 400 === 0), 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  let gm = 1;
  while (gm <= 12 && gd > monthDays[gm]) {
    gd -= monthDays[gm];
    gm++;
  }

  return { gy, gm, gd };
}

function parseJalaliDate(value: string) {
  const normalized = toEnglishDigits(value.trim()).replace(/-/g, "/");
  const match = normalized.match(/^(\d{4})\/(\d{1,2})\/(\d{1,2})$/);
  if (!match) return null;

  const jy = Number(match[1]);
  const jm = Number(match[2]);
  const jd = Number(match[3]);
  const maxDay = jalaliMonthLength(jy, jm);
  if (jy < 1200 || jy > 1500 || jm < 1 || jm > 12 || jd < 1 || jd > maxDay) return null;

  const { gy, gm, gd } = jalaliToGregorian(jy, jm, jd);
  return `${gy}-${String(gm).padStart(2, "0")}-${String(gd).padStart(2, "0")}`;
}

function jalaliWeekday(jy: number, jm: number, jd: number) {
  const { gy, gm, gd } = jalaliToGregorian(jy, jm, jd);
  return (new Date(gy, gm - 1, gd).getDay() + 1) % 7;
}

function readJalaliParts(value: string) {
  const normalized = toEnglishDigits(value.trim()).replace(/-/g, "/");
  const match = normalized.match(/^(\d{4})\/(\d{1,2})\/(\d{1,2})$/);
  if (!match) return null;
  return {
    year: Number(match[1]),
    month: Number(match[2]),
    day: Number(match[3]),
  };
}

export default function RegisterPage() {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [verified, setVerified] = useState(false);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [datePickerOpen, setDatePickerOpen] = useState(false);
  const [pickerYear, setPickerYear] = useState(1375);
  const [pickerMonth, setPickerMonth] = useState(1);
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [message, setMessage] = useState("");
  const [isError, setIsError] = useState(false);
  const [loading, setLoading] = useState(false);

  function showMessage(text: string, error = false) {
    setMessage(text);
    setIsError(error);
  }

  async function sendOtp() {
    setLoading(true);
    showMessage("");
    try {
      await sendRegistrationOtp(phone.trim());
      setOtpSent(true);
      showMessage("کد تأیید ارسال شد.");
    } catch (error) {
      showMessage(error instanceof Error ? error.message : "خطا در ارسال کد.", true);
    } finally {
      setLoading(false);
    }
  }

  async function verifyOtp() {
    setLoading(true);
    showMessage("");
    try {
      await verifyRegistrationOtp(phone.trim(), code.trim());
      setVerified(true);
      showMessage("");
    } catch (error) {
      showMessage(error instanceof Error ? error.message : "کد نامعتبر است.", true);
    } finally {
      setLoading(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!verified) {
      showMessage("ابتدا شماره موبایل را تأیید کنید.", true);
      return;
    }
    if (!firstName.trim() || !lastName.trim()) {
      showMessage("نام و نام خانوادگی را وارد کنید.", true);
      return;
    }
    if (!email.trim()) {
      showMessage("ایمیل را وارد کنید.", true);
      return;
    }
    const gregorianBirthDate = parseJalaliDate(birthDate);
    if (!gregorianBirthDate) {
      showMessage("تاریخ تولد را وارد کنید.", true);
      return;
    }
    if (password.length < 6) {
      showMessage("رمز عبور باید حداقل ۶ کاراکتر باشد.", true);
      return;
    }
    if (password !== password2) {
      showMessage("رمز عبور و تکرار آن یکسان نیستند.", true);
      return;
    }

    setLoading(true);
    showMessage("");
    try {
      const data = await completeRegistration({
        phone: phone.trim(),
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        email: email.trim(),
        birth_date: gregorianBirthDate,
        password,
      });
      window.location.href = data.is_admin ? "/admin" : "/";
    } catch (error) {
      showMessage(error instanceof Error ? error.message : "خطا در ساخت حساب.", true);
    } finally {
      setLoading(false);
    }
  }

  function openDatePicker() {
    const parsed = readJalaliParts(birthDate);
    if (parsed) {
      setPickerYear(parsed.year);
      setPickerMonth(parsed.month);
    }
    setDatePickerOpen((open) => !open);
  }

  function shiftMonth(delta: number) {
    const next = pickerMonth + delta;
    if (next < 1) {
      setPickerYear((year) => year - 1);
      setPickerMonth(12);
      return;
    }
    if (next > 12) {
      setPickerYear((year) => year + 1);
      setPickerMonth(1);
      return;
    }
    setPickerMonth(next);
  }

  function selectJalaliDay(day: number) {
    setBirthDate(formatJalaliDate(pickerYear, pickerMonth, day));
    setDatePickerOpen(false);
  }

  const selectedDate = readJalaliParts(birthDate);
  const firstWeekday = jalaliWeekday(pickerYear, pickerMonth, 1);
  const daysInMonth = jalaliMonthLength(pickerYear, pickerMonth);
  const calendarCells = [
    ...Array.from({ length: firstWeekday }, () => null),
    ...Array.from({ length: daysInMonth }, (_, index) => index + 1),
  ];

  return (
    <main className={styles.page}>
      <section className={styles.card}>
        <div className={styles.brand}>
          <span className={styles.brandIcon}><AppIcon name="file" /></span>
          <h1>ساخت حساب کاربری</h1>
        </div>

        <form onSubmit={submit}>
          <p className={styles.hint}>ابتدا شماره موبایل را تأیید کنید، سپس اطلاعات حساب را تکمیل کنید.</p>

          <div className={styles.field}>
            <label htmlFor="phone">شماره موبایل</label>
            <input id="phone" autoComplete="tel" dir="ltr" readOnly={verified} value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="09xxxxxxxxx" />
          </div>

          <div className={styles.field}>
            <label htmlFor="code">کد تأیید پیامک</label>
            <div className={styles.otpRow}>
              <input id="code" autoComplete="one-time-code" dir="ltr" disabled={!otpSent || verified} inputMode="numeric" maxLength={6} value={code} onChange={(event) => setCode(event.target.value)} placeholder="کد ۶ رقمی" />
              <button className={styles.secondary} disabled={loading || verified || !phone.trim()} onClick={otpSent ? verifyOtp : sendOtp} type="button">
                {verified ? "تأیید شد" : otpSent ? "تأیید کد" : "ارسال پیامک"}
              </button>
            </div>
          </div>

          {verified && <span className={styles.verified}>شماره تأیید شد</span>}
          <div className={styles.divider} />

          <fieldset disabled={!verified || loading}>
            <div className={styles.row}>
              <div className={styles.field}>
                <label htmlFor="firstName">نام</label>
                <input id="firstName" autoComplete="given-name" value={firstName} onChange={(event) => setFirstName(event.target.value)} />
              </div>
              <div className={styles.field}>
                <label htmlFor="lastName">نام خانوادگی</label>
                <input id="lastName" autoComplete="family-name" value={lastName} onChange={(event) => setLastName(event.target.value)} />
              </div>
            </div>

            <div className={styles.field}>
              <label htmlFor="birthDate">تاریخ تولد</label>
              <div className={styles.dateField}>
                <input
                  id="birthDate"
                  dir="ltr"
                  inputMode="numeric"
                  value={birthDate}
                  onChange={(event) => setBirthDate(event.target.value)}
                  onFocus={() => setDatePickerOpen(true)}
                  placeholder="مثلاً ۱۳۷۵/۰۵/۲۱"
                />
                <button aria-label="انتخاب تاریخ از تقویم" className={styles.calendarButton} onClick={openDatePicker} type="button">
                  <CalendarDays size={20} />
                </button>
                {datePickerOpen && (
                  <div className={styles.datePicker} role="dialog" aria-label="تقویم شمسی">
                    <div className={styles.datePickerHeader}>
                      <button aria-label="ماه قبل" type="button" onClick={() => shiftMonth(-1)}>
                        <ChevronRight size={18} />
                      </button>
                      <strong>{JALALI_MONTHS[pickerMonth - 1]} {toPersianDigits(pickerYear)}</strong>
                      <button aria-label="ماه بعد" type="button" onClick={() => shiftMonth(1)}>
                        <ChevronLeft size={18} />
                      </button>
                    </div>
                    <div className={styles.weekGrid}>
                      {WEEK_DAYS.map((day) => <span key={day}>{day}</span>)}
                    </div>
                    <div className={styles.dayGrid}>
                      {calendarCells.map((day, index) => {
                        const selected = Boolean(day && selectedDate?.year === pickerYear && selectedDate.month === pickerMonth && selectedDate.day === day);
                        return day ? (
                          <button className={selected ? styles.selectedDay : ""} key={`${pickerYear}-${pickerMonth}-${day}`} type="button" onClick={() => selectJalaliDay(day)}>
                            {toPersianDigits(day)}
                          </button>
                        ) : (
                          <span key={`empty-${index}`} />
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
              <span className={styles.helpText}>تاریخ را شمسی وارد کنید؛ در سیستم به میلادی ذخیره می‌شود.</span>
            </div>

            <div className={styles.field}>
              <label htmlFor="email">ایمیل</label>
              <input id="email" autoComplete="email" dir="ltr" type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
            </div>

            <div className={styles.row}>
              <div className={styles.field}>
                <label htmlFor="password">رمز عبور</label>
                <input id="password" autoComplete="new-password" dir="ltr" type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
              </div>
              <div className={styles.field}>
                <label htmlFor="password2">تکرار رمز عبور</label>
                <input id="password2" autoComplete="new-password" dir="ltr" type="password" value={password2} onChange={(event) => setPassword2(event.target.value)} />
              </div>
            </div>

            <button className={styles.primary} disabled={loading} type="submit">ساخت حساب</button>
          </fieldset>
        </form>

        <div className={`${styles.message} ${isError ? styles.error : ""}`}>{message}</div>
        <div className={styles.footer}>قبلاً ثبت‌نام کرده‌اید؟ <a href="/login">وارد شوید</a></div>
      </section>
    </main>
  );
}
