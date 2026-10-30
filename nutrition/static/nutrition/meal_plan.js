// Meal plan page: switch days, load a meal's details, and run the details tabs, without reloading.
// The page works without this script (every control is a normal link and both details sections
// show); this only enhances it.
(function () {
  'use strict';

  // Tabs (WAI-ARIA tabs pattern): one tab stop, arrow keys / Home / End move between tabs.
  function initTabs(container) {
    container.querySelectorAll('[data-tabs]').forEach(function (tabs) {
      var list = tabs.querySelector('[data-tablist]');
      var tabButtons = Array.prototype.slice.call(list.querySelectorAll('[role="tab"]'));
      var panels = Array.prototype.slice.call(tabs.querySelectorAll('[data-tabpanel]'));

      function select(index, moveFocus) {
        tabButtons.forEach(function (tab, i) {
          var selected = i === index;
          tab.setAttribute('aria-selected', String(selected));
          tab.tabIndex = selected ? 0 : -1;
          panels[i].hidden = !selected;
        });
        if (moveFocus) tabButtons[index].focus();
      }

      list.hidden = false;
      panels.forEach(function (panel, i) {
        panel.setAttribute('role', 'tabpanel');
        panel.setAttribute('aria-labelledby', tabButtons[i].id);
        panel.tabIndex = 0;
        var heading = panel.querySelector('.tabs__heading');
        if (heading) heading.hidden = true; // the tab names the panel now
      });
      select(0, false);

      tabButtons.forEach(function (tab, i) {
        tab.addEventListener('click', function () { select(i, false); });
        tab.addEventListener('keydown', function (event) {
          var next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabButtons.length - 1 }[event.key];
          if (next === undefined) return;
          event.preventDefault();
          select((next + tabButtons.length) % tabButtons.length, true);
        });
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var root = document.querySelector('[data-meal-plan]');
    if (!root) return;

    var detailsUrl = root.dataset.detailsUrl;
    var details = root.querySelector('[data-meal-details]');
    var currentLabel = root.querySelector('[data-day-current]');
    var dayLinks = Array.prototype.slice.call(root.querySelectorAll('[data-day-link]'));
    var days = dayLinks.map(function (link) { return link.dataset.dayLink; });

    initTabs(details);

    function panelFor(day) {
      return root.querySelector('[data-day-panel="' + day + '"]');
    }

    function rememberSelection(day, meal) {
      var url = new URL(window.location.href);
      url.searchParams.set('day', day);
      if (meal) url.searchParams.set('meal', meal); else url.searchParams.delete('meal');
      url.hash = '';
      window.history.replaceState(null, '', url);
      // Saving returns to whatever is selected now.
      document.querySelectorAll('[data-keep-selection]').forEach(function (form) {
        form.elements.day.value = day;
        form.elements.meal.value = meal || '';
      });
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
          details.scrollTop = 0;
          initTabs(details);
          root.querySelectorAll('[data-meal-link]').forEach(function (other) { other.removeAttribute('aria-current'); });
          link.setAttribute('aria-current', 'true');
          rememberSelection(link.dataset.day, link.dataset.meal);
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
        rememberSelection(day, null);
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
