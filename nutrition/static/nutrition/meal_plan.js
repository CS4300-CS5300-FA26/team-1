// Meal plan page: switch days and load a meal's details without reloading the page.
// The page works without this script (every control is a normal link); this only enhances it.
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var root = document.querySelector('[data-meal-plan]');
    if (!root) return;

    var detailsUrl = root.dataset.detailsUrl;
    var details = root.querySelector('[data-meal-details]');
    var currentLabel = root.querySelector('[data-day-current]');
    var dayLinks = Array.prototype.slice.call(root.querySelectorAll('[data-day-link]'));
    var days = dayLinks.map(function (link) { return link.dataset.dayLink; });

    function panelFor(day) {
      return root.querySelector('[data-day-panel="' + day + '"]');
    }

    function rememberInUrl(day, meal) {
      var url = new URL(window.location.href);
      url.searchParams.set('day', day);
      if (meal) url.searchParams.set('meal', meal); else url.searchParams.delete('meal');
      url.hash = '';
      window.history.replaceState(null, '', url);
    }

    function showDay(day) {
      root.querySelectorAll('[data-day-panel]').forEach(function (panel) {
        panel.hidden = panel.dataset.dayPanel !== day;
      });
      dayLinks.forEach(function (link) {
        if (link.dataset.dayLink === day) link.setAttribute('aria-current', 'true');
        else link.removeAttribute('aria-current');
      });
      var index = days.indexOf(day);
      root.querySelector('[data-day-step="-1"]').href = '?day=' + days[(index + days.length - 1) % days.length];
      root.querySelector('[data-day-step="1"]').href = '?day=' + days[(index + 1) % days.length];
      // The label is an aria-live region, so screen readers hear the new day.
      currentLabel.textContent = panelFor(day).querySelector('h2').textContent;
    }

    function selectMeal(link, moveFocus) {
      var query = '?day=' + encodeURIComponent(link.dataset.day) + '&meal=' + encodeURIComponent(link.dataset.meal);
      details.setAttribute('aria-busy', 'true');
      return fetch(detailsUrl + query, { credentials: 'same-origin' })
        .then(function (response) {
          if (!response.ok) throw new Error('HTTP ' + response.status);
          return response.text();
        })
        .then(function (html) {
          details.innerHTML = html; // our own server-rendered, auto-escaped template
          root.querySelectorAll('[data-meal-link]').forEach(function (other) { other.removeAttribute('aria-current'); });
          link.setAttribute('aria-current', 'true');
          rememberInUrl(link.dataset.day, link.dataset.meal);
          if (moveFocus) {
            var heading = details.querySelector('#meal-details-title');
            if (heading) heading.focus();
          }
        })
        .catch(function () {
          window.location.href = link.href; // fall back to a normal page load
        })
        .finally(function () {
          details.removeAttribute('aria-busy');
        });
    }

    root.addEventListener('click', function (event) {
      var dayControl = event.target.closest('[data-day-link], [data-day-step]');
      if (dayControl) {
        event.preventDefault();
        var day = new URL(dayControl.href).searchParams.get('day');
        showDay(day);
        rememberInUrl(day, null);
        var firstMeal = panelFor(day).querySelector('[data-meal-link]');
        if (firstMeal) selectMeal(firstMeal, false);
        return;
      }
      var mealLink = event.target.closest('[data-meal-link]');
      if (mealLink) {
        event.preventDefault();
        selectMeal(mealLink, true);
      }
    });
  });
})();
