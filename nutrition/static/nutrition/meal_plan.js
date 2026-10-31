// Meal plan day picker: switch days in place (story D-5).
// Without JavaScript the day links reload the page with ?day=; this shows the chosen day's section instead, without a
// reload or a scroll, keeps focus on the control that was used, and updates the address so the day can be shared.
(function () {
  'use strict';

  var root = document.querySelector('[data-meal-plan]');
  if (!root) return;

  var links = Array.prototype.slice.call(root.querySelectorAll('[data-day-link]'));
  var panels = Array.prototype.slice.call(root.querySelectorAll('[data-day-panel]'));
  var current = root.querySelector('[data-day-current]');
  var steps = root.querySelectorAll('[data-day-step]');
  var dayInputs = root.querySelectorAll('[data-day-input]');
  var keys = links.map(function (link) { return link.getAttribute('data-day-link'); });

  function show(key) {
    var index = keys.indexOf(key);
    if (index < 0) return;
    panels.forEach(function (panel) { panel.hidden = panel.getAttribute('data-day-panel') !== key; });
    links.forEach(function (link) {
      if (link.getAttribute('data-day-link') === key) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    });
    current.textContent = links[index].getAttribute('data-day-name');
    Array.prototype.forEach.call(steps, function (step) {
      var offset = Number(step.getAttribute('data-day-step'));
      step.setAttribute('href', '?day=' + keys[(index + offset + keys.length) % keys.length]);
    });
    Array.prototype.forEach.call(dayInputs, function (input) { input.value = key; });
    if (window.history && window.history.replaceState) window.history.replaceState(null, '', '?day=' + key);
  }

  links.forEach(function (link) {
    link.addEventListener('click', function (event) {
      event.preventDefault();
      show(link.getAttribute('data-day-link'));
    });
  });
  Array.prototype.forEach.call(steps, function (step) {
    step.addEventListener('click', function (event) {
      event.preventDefault();
      show(new URLSearchParams(step.getAttribute('href').slice(1)).get('day'));
    });
  });
})();
