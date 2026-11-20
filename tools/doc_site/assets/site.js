// Row filter and the menu drawer. Without scripts the pages are complete: the links show as a plain navigation.
(function () {
  var q = document.getElementById('q');
  if (q) {
    q.addEventListener('input', function (e) {
      var v = e.target.value.toLowerCase();
      document.querySelectorAll('tbody tr').forEach(function (r) {
        r.hidden = v && r.textContent.toLowerCase().indexOf(v) < 0;
      });
    });
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
