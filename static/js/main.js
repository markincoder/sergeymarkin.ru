/**
 * Интерактивная логика сайта sergeymarkin.ru:
 * 1. Фильтрация кейсов по категориям
 * 2. Интерактивный ROI-калькулятор
 * 3. Проактивный тизер для FAQ-виджета
 */
document.documentElement.classList.add('js-ready');

document.addEventListener('DOMContentLoaded', function() {
  
  // =========================================================
  // 1. Фильтрация кейсов (главная и каталог)
  // =========================================================
  var filterContainer = document.getElementById('case-filters');
  var caseItems = document.querySelectorAll('.case-item');

  if (filterContainer && caseItems.length > 0) {
    var filterBtns = filterContainer.querySelectorAll('.filter-btn');
    
    filterBtns.forEach(function(btn) {
      btn.addEventListener('click', function() {
        filterBtns.forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');

        var filter = btn.getAttribute('data-filter');

        caseItems.forEach(function(item) {
          var cat = item.getAttribute('data-category');
          if (filter === 'all' || cat === filter) {
            item.style.display = '';
            item.classList.add('animate-fade-in');
          } else {
            item.style.display = 'none';
            item.classList.remove('animate-fade-in');
          }
        });
      });
    });
  }

  // =========================================================
  // 2. Интерактивный AI ROI-калькулятор
  // =========================================================
  var deptChips = document.querySelectorAll('#calc-dept-chips .calc-chip-btn');
  var teamChips = document.querySelectorAll('#calc-team-chips .calc-chip-btn');
  var hoursOut = document.getElementById('calc-hours-out');
  var moneyOut = document.getElementById('calc-money-out');
  var paybackOut = document.getElementById('calc-payback-out');

  var currentDept = 'sales';
  var currentTeam = 'small';

  var roiData = {
    sales: {
      small:  { hours: 'до 45–65 ч',   money: '~70 000 – 110 000 ₽',  payback: 'Срок окупаемости: от 2–3 недель' },
      medium: { hours: 'до 110–160 ч', money: '~170 000 – 260 000 ₽', payback: 'Срок окупаемости: от 10–14 дней' },
      large:  { hours: 'до 250–380 ч', money: '~380 000 – 600 000 ₽', payback: 'Срок окупаемости: от 1 недели' }
    },
    hr: {
      small:  { hours: 'до 50–70 ч',   money: '~75 000 – 115 000 ₽',  payback: 'Срок окупаемости: от 2–3 недель' },
      medium: { hours: 'до 120–180 ч', money: '~180 000 – 280 000 ₽', payback: 'Срок окупаемости: от 12 дней' },
      large:  { hours: 'до 280–420 ч', money: '~420 000 – 650 000 ₽', payback: 'Срок окупаемости: от 1 недели' }
    },
    support: {
      small:  { hours: 'до 60–90 ч',   money: '~85 000 – 130 000 ₽',  payback: 'Срок окупаемости: от 2 недель' },
      medium: { hours: 'до 140–210 ч', money: '~210 000 – 320 000 ₽', payback: 'Срок окупаемости: от 10 дней' },
      large:  { hours: 'до 320–500 ч', money: '~480 000 – 750 000 ₽', payback: 'Срок окупаемости: от 1 недели' }
    },
    ops: {
      small:  { hours: 'до 40–60 ч',   money: '~60 000 – 95 000 ₽',   payback: 'Срок окупаемости: от 3 недель' },
      medium: { hours: 'до 100–150 ч', money: '~150 000 – 230 000 ₽', payback: 'Срок окупаемости: от 2 недель' },
      large:  { hours: 'до 220–340 ч', money: '~330 000 – 520 000 ₽', payback: 'Срок окупаемости: от 10 дней' }
    }
  };

  function updateCalc() {
    if (!hoursOut || !moneyOut || !paybackOut) return;
    var info = roiData[currentDept] && roiData[currentDept][currentTeam];
    if (info) {
      hoursOut.textContent = info.hours;
      moneyOut.textContent = info.money;
      paybackOut.textContent = info.payback;
    }
  }

  if (deptChips.length > 0) {
    deptChips.forEach(function(btn) {
      btn.addEventListener('click', function() {
        deptChips.forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');
        currentDept = btn.getAttribute('data-dept');
        updateCalc();
      });
    });
  }

  if (teamChips.length > 0) {
    teamChips.forEach(function(btn) {
      btn.addEventListener('click', function() {
        teamChips.forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');
        currentTeam = btn.getAttribute('data-team');
        updateCalc();
      });
    });
  }

});
