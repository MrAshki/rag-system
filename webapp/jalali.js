/* =========================================================================
   Jalali (Shamsi) <-> Gregorian date conversion + form helpers.
   Conversion core is jalaali-js (MIT, github.com/jalaali/jalaali-js), inlined
   so there is no CDN dependency. Birth dates are entered in Jalali via three
   <select>s and converted to a Gregorian ISO 'YYYY-MM-DD' string for storage
   (the DB column is a Gregorian DATE); reads convert back for display.
   ========================================================================= */
const Jalali = (function () {
  function div(a, b) { return ~~(a / b); }
  function mod(a, b) { return a - ~~(a / b) * b; }

  function jalCal(jy) {
    var breaks = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210,
      1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178];
    var bl = breaks.length, gy = jy + 621, leapJ = -14, jp = breaks[0];
    var jm, jump, leap, leapG, march, n, i;
    if (jy < jp || jy >= breaks[bl - 1]) throw new Error('Invalid Jalaali year ' + jy);
    for (i = 1; i < bl; i += 1) {
      jm = breaks[i];
      jump = jm - jp;
      if (jy < jm) break;
      leapJ = leapJ + div(jump, 33) * 8 + div(mod(jump, 33), 4);
      jp = jm;
    }
    n = jy - jp;
    leapJ = leapJ + div(n, 33) * 8 + div(mod(n, 33) + 3, 4);
    if (mod(jump, 33) === 4 && jump - n === 4) leapJ += 1;
    leapG = div(gy, 4) - div((div(gy, 100) + 1) * 3, 4) - 150;
    march = 20 + leapJ - leapG;
    if (jump - n < 6) n = n - jump + div(jump + 4, 33) * 33;
    leap = mod(mod(n + 1, 33) - 1, 4);
    if (leap === -1) leap = 4;
    return { leap: leap, gy: gy, march: march };
  }

  function g2d(gy, gm, gd) {
    var d = div((gy + div(gm - 8, 6) + 100100) * 1461, 4)
      + div(153 * mod(gm + 9, 12) + 2, 5) + gd - 34840408;
    d = d - div(div(gy + 100100 + div(gm - 8, 6), 100) * 3, 4) + 752;
    return d;
  }
  function d2g(jdn) {
    var j = 4 * jdn + 139361631;
    j = j + div(div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908;
    var i = div(mod(j, 1461), 4) * 5 + 308;
    var gd = div(mod(i, 153), 5) + 1;
    var gm = mod(div(i, 153), 12) + 1;
    var gy = div(j, 1461) - 100100 + div(8 - gm, 6);
    return { gy: gy, gm: gm, gd: gd };
  }
  function j2d(jy, jm, jd) {
    var r = jalCal(jy);
    return g2d(r.gy, 3, r.march) + (jm - 1) * 31 - div(jm, 7) * (jm - 7) + jd - 1;
  }
  function d2j(jdn) {
    var gy = d2g(jdn).gy, jy = gy - 621, r = jalCal(jy), jdn1f = g2d(gy, 3, r.march), jd, jm, k;
    k = jdn - jdn1f;
    if (k >= 0) {
      if (k <= 185) { jm = 1 + div(k, 31); jd = mod(k, 31) + 1; return { jy: jy, jm: jm, jd: jd }; }
      else k -= 186;
    } else { jy -= 1; k += 179; if (r.leap === 1) k += 1; }
    jm = 7 + div(k, 30);
    jd = mod(k, 30) + 1;
    return { jy: jy, jm: jm, jd: jd };
  }
  function isLeapJalaaliYear(jy) { return jalCal(jy).leap === 0; }
  function jalaaliMonthLength(jy, jm) {
    if (jm <= 6) return 31;
    if (jm <= 11) return 30;
    return isLeapJalaaliYear(jy) ? 30 : 29;
  }
  function toJalaali(gy, gm, gd) { return d2j(g2d(gy, gm, gd)); }
  function toGregorian(jy, jm, jd) { return d2g(j2d(jy, jm, jd)); }

  return { toJalaali, toGregorian, isLeapJalaaliYear, jalaaliMonthLength };
})();

const PERSIAN_MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
  'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند'];

/* Populate year/month/day <select>s for a Jalali birth-date picker. Years run
   from the current Jalali year (can't be born in the future) back 100 years. */
function fillJalaliSelects(yearSel, monthSel, daySel) {
  const now = new Date();
  const jnow = Jalali.toJalaali(now.getFullYear(), now.getMonth() + 1, now.getDate());
  const maxYear = jnow.jy;
  const minYear = maxYear - 100;
  let years = '<option value="">سال</option>';
  for (let y = maxYear; y >= minYear; y--) years += `<option value="${y}">${y}</option>`;
  yearSel.innerHTML = years;
  monthSel.innerHTML = '<option value="">ماه</option>'
    + PERSIAN_MONTHS.map((m, i) => `<option value="${i + 1}">${m}</option>`).join('');
  let days = '<option value="">روز</option>';
  for (let d = 1; d <= 31; d++) days += `<option value="${d}">${d}</option>`;
  daySel.innerHTML = days;
}

/* Read the three selects.
   Returns: ''        -> nothing selected (treated as "no birth date", which is OK)
            null      -> partially filled (caller should ask user to complete it)
            undefined -> a complete but invalid combination (e.g. 31 Esfand in a
                         non-leap year)
            'YYYY-MM-DD' -> the Gregorian ISO date otherwise. */
function jalaliSelectsToISO(yearSel, monthSel, daySel) {
  const jy = +yearSel.value, jm = +monthSel.value, jd = +daySel.value;
  if (!yearSel.value && !monthSel.value && !daySel.value) return '';
  if (!jy || !jm || !jd) return null;
  if (jd > Jalali.jalaaliMonthLength(jy, jm)) return undefined;
  const g = Jalali.toGregorian(jy, jm, jd);
  return `${g.gy}-${String(g.gm).padStart(2, '0')}-${String(g.gd).padStart(2, '0')}`;
}

/* Set the three selects from a stored Gregorian ISO date string. */
function isoToJalaliSelects(iso, yearSel, monthSel, daySel) {
  if (!iso) return;
  const [gy, gm, gd] = iso.slice(0, 10).split('-').map(Number);
  if (!gy || !gm || !gd) return;
  const j = Jalali.toJalaali(gy, gm, gd);
  yearSel.value = String(j.jy);
  monthSel.value = String(j.jm);
  daySel.value = String(j.jd);
}

/* Format a Gregorian ISO date/datetime string as a Jalali 'YYYY/MM/DD' string
   for display (e.g. payment dates, birth date readout). */
function formatJalali(iso) {
  if (!iso) return '—';
  const [gy, gm, gd] = iso.slice(0, 10).split('-').map(Number);
  if (!gy || !gm || !gd) return '—';
  const j = Jalali.toJalaali(gy, gm, gd);
  return `${j.jy}/${String(j.jm).padStart(2, '0')}/${String(j.jd).padStart(2, '0')}`;
}
