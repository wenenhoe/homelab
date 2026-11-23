// Row filter, the menu drawer and the contents list, which is open in the markup and closed here on a narrow screen. Without scripts the pages are complete: the links show as a plain navigation.
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
})();
