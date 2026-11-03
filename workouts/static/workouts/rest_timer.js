// Rest timer for the workout page. Progressive enhancement: the buttons and the timer are `hidden` in the markup and
// only revealed here, so without JavaScript the page still works and the rest times are plain text.
(function () {
  var panel = document.querySelector('[data-rest-timer]');
  if (!panel) return;
  var display = panel.querySelector('[data-rest-display]');
  var announce = panel.querySelector('[data-rest-announce]');
  var stop = panel.querySelector('[data-rest-stop]');
  var buttons = document.querySelectorAll('[data-rest-start]');
  var interval = null;
  var endsAt = 0;

  function format(seconds) {
    var m = Math.floor(seconds / 60);
    var s = seconds % 60;
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  function finish(message) {
    window.clearInterval(interval);
    interval = null;
    stop.hidden = true;
    display.textContent = '0:00';
    // One polite announcement when the rest is over, not one per second.
    announce.textContent = message;
  }

  function tick() {
    var left = Math.max(0, Math.round((endsAt - Date.now()) / 1000));
    display.textContent = format(left);
    if (left === 0) finish('Rest is over. Start your next set.');
  }

  function start(seconds) {
    if (interval) window.clearInterval(interval);
    announce.textContent = '';
    endsAt = Date.now() + seconds * 1000;
    panel.hidden = false;
    stop.hidden = false;
    tick();
    interval = window.setInterval(tick, 250);
  }

  buttons.forEach(function (button) {
    button.hidden = false;
    button.addEventListener('click', function () {
      var seconds = parseInt(button.getAttribute('data-rest-start'), 10);
      if (seconds > 0 && seconds <= 600) start(seconds);
    });
  });
  stop.addEventListener('click', function () {
    finish('Rest timer stopped.');
  });
})();
