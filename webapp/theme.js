/* Light/dark theme toggle. The actual data-theme attribute is set as early as
   possible by a tiny inline <head> script on each page (to avoid a flash of the
   wrong theme); this file only powers the toggle button and keeps its icon in
   sync. Preference is stored in localStorage and falls back to the OS setting. */
(function () {
  function current() {
    return document.documentElement.getAttribute('data-theme') || 'light';
  }

  function updateIcons() {
    const dark = current() === 'dark';
    document.querySelectorAll('[data-theme-toggle]').forEach(function (btn) {
      const sun = btn.querySelector('.icon-sun');
      const moon = btn.querySelector('.icon-moon');
      // Show the icon of the theme you'd switch TO: moon while light, sun while dark.
      if (sun) sun.style.display = dark ? 'block' : 'none';
      if (moon) moon.style.display = dark ? 'none' : 'block';
      btn.setAttribute('aria-label', dark ? 'حالت روشن' : 'حالت تاریک');
    });
  }

  window.toggleTheme = function () {
    const next = current() === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('theme', next); } catch (e) {}
    updateIcons();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', updateIcons);
  } else {
    updateIcons();
  }
})();
