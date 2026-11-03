// Light/dark theme toggle for the header button (see core/static/core/css/theme.css).
// With no saved choice the page follows the operating system. Clicking the button saves an
// explicit "light" or "dark" in localStorage; base.html applies it before first paint.
(function () {
  'use strict';

  var STORAGE_KEY = 'fitpro-theme';
  var root = document.documentElement;
  var prefersDark = window.matchMedia('(prefers-color-scheme: dark)');

  function currentTheme() {
    return root.dataset.theme || (prefersDark.matches ? 'dark' : 'light');
  }

  function render(button) {
    var dark = currentTheme() === 'dark';
    // A toggle button keeps one label ("Dark mode"); aria-pressed says whether it is on.
    button.setAttribute('aria-pressed', String(dark));
    button.querySelector('[data-theme-icon]').textContent = dark ? '\u263E' : '\u2600';
  }

  document.addEventListener('DOMContentLoaded', function () {
    var button = document.querySelector('[data-theme-toggle]');
    if (!button) return;

    button.hidden = false;
    render(button);

    button.addEventListener('click', function () {
      var next = currentTheme() === 'dark' ? 'light' : 'dark';
      root.dataset.theme = next;
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch (e) {
        // Storage can be blocked (private mode); the choice then lasts for this page only.
      }
      render(button);
    });

    // Follow OS changes while the user hasn't picked a theme.
    prefersDark.addEventListener('change', function () {
      if (!root.dataset.theme) render(button);
    });
  });
})();
