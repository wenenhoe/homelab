// Row filter, the menu drawer, the contents list, which is open in the markup and closed here on a narrow screen, and a copy button on each code block. Without scripts the pages are complete: the links show as a plain navigation and code is selected by hand.
(function () {
  var q = document.getElementById('q');
  if (q) {
    q.addEventListener('input', function (e) {
      var v = e.target.value.toLowerCase();
      document.querySelectorAll('tbody tr').forEach(function (r) {
        r.hidden = v && r.textContent.toLowerCase().indexOf(v) < 0;
      });
      document.querySelectorAll('.tabs').forEach(function (t) {
        t.classList.toggle('filtering', !!v);
        t.querySelectorAll('.panel').forEach(function (p) {
          p.hidden = !!v && !p.querySelector('tbody tr:not([hidden])');
        });
      });
    });
  }
  var list = document.querySelector('.toc details');
  if (list && window.matchMedia) {
    var wide = window.matchMedia('(min-width: 1100px)');
    var sync = function () { list.open = wide.matches; };
    sync();
    wide.addEventListener('change', sync);
  }
  var d = document.getElementById('drawer');
  var b = document.querySelector('.menu-btn');
  if (d && b && d.showModal) {
    b.addEventListener('click', function () { d.showModal(); });
    d.addEventListener('click', function (e) {
      if (e.target === d || e.target.closest('.close') || e.target.closest('a')) { d.close(); }
    });
  }
  // The clipboard is only there in a secure context (HTTPS or localhost); without it no button is added.
  if (navigator.clipboard) {
    var draw = function (shapes) {
      return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + shapes + '</svg>';
    };
    var squares = draw('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15a1 1 0 0 1-1-1V6a2 2 0 0 1 2-2h8a1 1 0 0 1 1 1"/>');
    var tick = draw('<path d="M5 12.5l4.5 4.5L19 7"/>');
    var cross = draw('<path d="M7 7l10 10M17 7L7 17"/>');
    document.querySelectorAll('.doc pre').forEach(function (pre) {
      var box = document.createElement('div');
      var button = document.createElement('button');
      var icon = document.createElement('span');
      var label = document.createElement('span');
      var reset;
      var show = function (drawing, word) {
        icon.innerHTML = drawing;
        label.textContent = word;
      };
      var say = function (drawing, word) {
        show(drawing, word);
        clearTimeout(reset);
        reset = setTimeout(function () { show(squares, 'Copy'); }, 2000);
      };
      box.className = 'code';
      button.type = 'button';
      button.className = 'copy';
      // The icon is what is seen; the word beside it, clipped out of sight, is what a screen reader says.
      label.className = 'said';
      label.setAttribute('aria-live', 'polite');
      show(squares, 'Copy');
      button.append(icon, label);
      button.addEventListener('click', function () {
        // A final newline would make a terminal run the last line as it is pasted.
        navigator.clipboard.writeText(pre.textContent.replace(/\n+$/, '')).then(
          function () { say(tick, 'Copied'); },
          function () { say(cross, 'Copy failed'); });
      });
      pre.replaceWith(box);
      box.append(button, pre);
    });
  }
})();
