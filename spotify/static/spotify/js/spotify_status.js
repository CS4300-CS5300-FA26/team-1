// Spotify connection check on the profile page (story D-7). Calls /spotify/status/, which uses the server-side
// token helper and GET /v1/me, then shows the result on the pill: pulsing grey while checking, green when it works,
// red with troubleshooting help when it doesn't. Tokens never reach this script; the endpoint only returns a state.
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var pill = document.querySelector('[data-spotify-status]');
    if (!pill) return;
    var text = document.querySelector('[data-status-text]');
    var help = document.querySelector('[data-status-help]');
    var name = pill.querySelector('.connection-pill__name');

    function show(state, message) {
      pill.dataset.state = state;
      if (text) text.textContent = message;
      if (help) help.hidden = state !== 'error';
    }

    show('checking', 'Checking the connection to Spotify…');

    fetch(pill.dataset.statusUrl, { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
      .then(function (response) {
        return response.json().catch(function () { return {}; });
      })
      .then(function (data) {
        if (data.state === 'ok') {
          if (name && data.display_name) name.textContent = data.display_name;
          show('ok', 'Connection OK: FitPro can reach your Spotify account.');
        } else {
          show('error', 'Connection problem: ' + (data.message || 'the connection check failed.'));
        }
      })
      .catch(function () {
        show('error', 'Connection problem: the connection check could not run. Check your internet connection.');
      });
  });
})();
