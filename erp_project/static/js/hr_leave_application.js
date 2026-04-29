/**
 * Leave apply UX: employee context fetch, eligible leave types, balance strip,
 * UAE Fri–Sat working days, overlap + overflow validation (mirrors backend rules via API flags).
 */
(function () {
  'use strict';

  function pythonWeekday(d) {
    return (d.getDay() + 6) % 7;
  }

  function parseISODate(s) {
    if (!s) return null;
    var p = String(s).split('-');
    if (p.length !== 3) return null;
    var y = parseInt(p[0], 10),
      m = parseInt(p[1], 10),
      day = parseInt(p[2], 10);
    return new Date(y, m - 1, day);
  }

  function countUaeWorkingDays(startStr, endStr) {
    var start = parseISODate(startStr);
    var end = parseISODate(endStr);
    if (!start || !end || end < start) return 0;
    var n = 0;
    var cur = new Date(start.getTime());
    while (cur <= end) {
      var pw = pythonWeekday(cur);
      if (pw !== 4 && pw !== 5) n += 1;
      cur.setDate(cur.getDate() + 1);
    }
    return n;
  }

  function inclusiveEndForWorkingDays(startStr, targetWd) {
    var start = parseISODate(startStr);
    if (!start || targetWd <= 0) return '';
    var end = new Date(start.getTime());
    while (countUaeWorkingDays(startStr, fmt(end)) < targetWd) {
      end.setDate(end.getDate() + 1);
    }
    return fmt(end);
  }

  function fmt(d) {
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + day;
  }

  function rangesOverlap(aStart, aEnd, bStart, bEnd) {
    return aStart <= bEnd && bStart <= aEnd;
  }

  function parseActiveRanges(rows) {
    return (rows || []).map(function (r) {
      return {
        start: parseISODate(r.start_date),
        end: parseISODate(r.end_date),
      };
    });
  }

  function unpaidBalanceRow(rows, ltId) {
    var found = null;
    (rows || []).forEach(function (r) {
      if (String(r.leave_type_id) === String(ltId)) found = r;
    });
    return found;
  }

  function eligibleLeaveRows(data) {
    if (data.eligible_leave_types && data.eligible_leave_types.length) return data.eligible_leave_types;
    return (data.leave_balances || []).filter(function (r) {
      return r.eligible;
    });
  }

  function getCsrf() {
    var m = document.querySelector('[name=csrfmiddlewaretoken]');
    return m ? m.value : '';
  }

  function init(cfg) {
    var root = cfg.rootEl || document.getElementById('leave-app-root');
    if (!root) return;

    var contextUrl = cfg.contextUrl || root.dataset.contextUrl;
    var isPublic = !!cfg.isPublic;
    var isAdmin = cfg.isAdmin === true || root.dataset.isAdmin === 'true';

    var selEmployee = document.querySelector(cfg.employeeSelect || '#id_employee');
    var inpCode = document.querySelector(cfg.employeeCodeInput || '#id_employee_code');
    var selLeave = document.querySelector(cfg.leaveTypeSelect || '#id_leave_type');
    var inpStart = document.querySelector(cfg.startDateInput || '#id_start_date');
    var inpEnd = document.querySelector(cfg.endDateInput || '#id_end_date');
    var inpOverflow = document.querySelector(cfg.overflowInput || '#id_overflow_action');

    var spin = document.getElementById('leave-context-spinner');
    var balanceBox = document.getElementById('leave-balance-display');
    var durationEl = document.getElementById('leave-working-days');
    var overlapAlert = document.getElementById('leave-overlap-alert');
    var overflowBox = document.getElementById('leave-overflow-options');
    var exhaustedBox = document.getElementById('leave-exhausted-banner');

    var ctxData = null;

    function showSpinner(on) {
      if (!spin) return;
      spin.classList.toggle('d-none', !on);
    }

    function clearAlerts() {
      if (overlapAlert) {
        overlapAlert.classList.add('d-none');
        overlapAlert.textContent = '';
      }
      if (overflowBox) {
        overflowBox.classList.add('d-none');
        overflowBox.innerHTML = '';
      }
      if (exhaustedBox) {
        exhaustedBox.classList.add('d-none');
        exhaustedBox.innerHTML = '';
      }
      if (inpOverflow) inpOverflow.value = '';
    }

    function populateLeaveTypes(rows) {
      if (!selLeave) return;
      var v = selLeave.value;
      selLeave.innerHTML = '';
      var empty = document.createElement('option');
      empty.value = '';
      empty.textContent = '— Select leave type —';
      selLeave.appendChild(empty);
      (rows || []).forEach(function (r) {
        var o = document.createElement('option');
        o.value = r.leave_type_id;
        o.textContent = r.leave_type_name;
        o.dataset.payType = r.pay_type || '';
        selLeave.appendChild(o);
      });
      if ([].some.call(selLeave.options, function (o) { return o.value === v; })) selLeave.value = v;
    }

    function balanceColor(rem, payType) {
      var pt = (payType || '').toLowerCase();
      if (rem <= 0 && (pt === 'unpaid' || pt === '')) return 'text-info';
      if (rem > 10) return 'text-success';
      if (rem >= 1) return 'text-warning';
      return 'text-danger';
    }

    function renderBalanceStrip() {
      if (!balanceBox || !selLeave || !ctxData) return;
      var ltId = selLeave.value;
      var rows = ctxData.leave_balances || [];
      var row = unpaidBalanceRow(rows, ltId);
      balanceBox.innerHTML = '';
      if (!row) return;

      var rem = parseFloat(row.remaining_days);
      var entitled = row.entitled_days;
      var used = row.used_days;
      var pend = row.pending_days;

      var line1 = document.createElement('div');
      line1.className = 'fw-semibold ' + balanceColor(rem, row.pay_type);
      line1.textContent =
        'You have ' +
        row.remaining_days +
        ' days remaining for ' +
        row.leave_type_name +
        ' this year.';

      var line2 = document.createElement('div');
      line2.className = 'small text-muted mt-1';
      line2.textContent =
        'Entitled: ' +
        entitled +
        ' | Used: ' +
        used +
        ' | Pending: ' +
        pend +
        ' | Remaining: ' +
        row.remaining_days;

      balanceBox.appendChild(line1);
      balanceBox.appendChild(line2);

      var ptLow = (row.pay_type || '').toLowerCase();
      var entNum = parseFloat(entitled);
      if (ptLow !== 'unpaid' && entNum > 0 && entNum < 90000) {
        var usedNum = parseFloat(used) + parseFloat(pend);
        var pct = Math.min(100, Math.round((usedNum / entNum) * 100));
        var progWrap = document.createElement('div');
        progWrap.className = 'progress mt-2';
        progWrap.style.height = '8px';
        var prog = document.createElement('div');
        prog.className = 'progress-bar';
        prog.style.width = pct + '%';
        prog.setAttribute('aria-valuenow', pct);
        prog.setAttribute('aria-valuemax', '100');
        progWrap.appendChild(prog);
        balanceBox.appendChild(progWrap);
      }

      var tb = row.tier_breakdown || {};
      if (tb.full_remaining != null && (row.pay_type || '').toLowerCase() === 'tiered') {
        var tierEl = document.createElement('div');
        tierEl.className = 'small mt-2 border rounded p-2 bg-light';
        var fr = tb.full_remaining,
          hr = tb.half_remaining,
          ur = tb.unpaid_remaining,
          pr = tb.pct75_remaining;
        var lines = [];
        if (fr != null) lines.push('Full pay remaining: ' + Number(fr).toFixed(1) + ' days');
        if (hr != null) lines.push('Half pay remaining: ' + Number(hr).toFixed(1) + ' days');
        if (pr != null) lines.push('75% pay remaining: ' + Number(pr).toFixed(1) + ' days');
        if (ur != null) lines.push('Unpaid segment remaining: ' + Number(ur).toFixed(1) + ' days');
        tierEl.innerHTML = lines.join('<br>');
        balanceBox.appendChild(tierEl);
      }

      if (parseFloat(row.remaining_days) <= 0 && (row.pay_type || '').toLowerCase() === 'unpaid') {
        var unpaidHint = document.createElement('div');
        unpaidHint.className = 'small text-info mt-2';
        unpaidHint.textContent = 'This is unpaid leave. No balance deducted.';
        balanceBox.appendChild(unpaidHint);
      }

    }

    function validateDatesAndBalance() {
      clearAlerts();
      if (!inpStart || !inpEnd || !selLeave || !ctxData) return;
      var sd = inpStart.value;
      var ed = inpEnd.value;
      if (!sd || !ed) {
        if (durationEl) durationEl.textContent = '—';
        return;
      }

      var wd = countUaeWorkingDays(sd, ed);
      if (durationEl) durationEl.textContent = wd + ' working day' + (wd !== 1 ? 's' : '');

      var rangesSrc = ctxData.existing_leave_dates || ctxData.active_leave_dates || [];
      var s = parseISODate(sd);
      var e = parseISODate(ed);
      for (var i = 0; i < rangesSrc.length; i++) {
        var rr = rangesSrc[i];
        var bs = parseISODate(rr.start_date);
        var be = parseISODate(rr.end_date);
        if (bs && be && rangesOverlap(s, e, bs, be)) {
          if (overlapAlert) {
            overlapAlert.classList.remove('d-none');
            overlapAlert.innerHTML =
              'You have an existing leave request' +
              (rr.leave_type_name ? ' (' + rr.leave_type_name + ')' : '') +
              ' from ' +
              rr.start_date +
              ' to ' +
              rr.end_date +
              ' that overlaps.';
          }
          return;
        }
      }

      var ltId = selLeave.value;
      var row = unpaidBalanceRow(ctxData.leave_balances || [], ltId);
      if (!row) return;

      var rem = parseFloat(row.remaining_days);
      var pt = (row.pay_type || '').toLowerCase();
      var isUnpaid = pt === 'unpaid';

      if (!isUnpaid && rem <= 0) {
        if (exhaustedBox) {
          exhaustedBox.classList.remove('d-none');
          exhaustedBox.innerHTML =
            '<div class="alert alert-warning mb-0">' +
            '<p class="mb-2">Your ' +
            row.leave_type_name +
            ' balance is exhausted for this year. You may apply for Unpaid Leave instead.</p>' +
            '<button type="button" class="btn btn-sm btn-outline-primary" id="btn-switch-unpaid">Apply for Unpaid Leave</button>' +
            '</div>';
          var btn = document.getElementById('btn-switch-unpaid');
          if (btn) {
            btn.addEventListener('click', function () {
              var uid = ctxData.default_unpaid_leave_type_id;
              if (uid && selLeave) {
                selLeave.value = String(uid);
                selLeave.dispatchEvent(new Event('change'));
              }
            });
          }
        }
        return;
      }

      if (!isUnpaid && wd > rem) {
        var over = wd - rem;
        if (overflowBox) {
          overflowBox.classList.remove('d-none');
          overflowBox.innerHTML =
            '<div class="alert alert-warning">' +
            '<p>You have only ' +
            rem +
            ' days remaining. Your request exceeds your balance by ' +
            over +
            ' days.</p>' +
            '<div class="form-check">' +
            '<input class="form-check-input" type="radio" name="leave_overflow_ui" id="ov_reduce" value="reduce">' +
            '<label class="form-check-label" for="ov_reduce">Reduce my leave to ' +
            rem +
            ' working days (adjust end date automatically)</label>' +
            '</div>' +
            '<div class="form-check">' +
            '<input class="form-check-input" type="radio" name="leave_overflow_ui" id="ov_split" value="split">' +
            '<label class="form-check-label" for="ov_split">Split: take ' +
            rem +
            ' paid days + remaining as Unpaid Leave</label>' +
            '</div>' +
            '</div>';

          function syncOverflowHidden() {
            var r = overflowBox.querySelector('input[name="leave_overflow_ui"]:checked');
            if (inpOverflow) inpOverflow.value = r ? r.value : '';
            if (r && r.value === 'reduce' && inpEnd) {
              inpEnd.value = inclusiveEndForWorkingDays(sd, rem);
              inpEnd.dispatchEvent(new Event('change'));
            }
          }

          overflowBox.querySelectorAll('input[name="leave_overflow_ui"]').forEach(function (el) {
            el.addEventListener('change', syncOverflowHidden);
          });
        }
      }
    }

    function fetchContext(paramName, paramVal) {
      if (!contextUrl || !paramVal) return Promise.resolve(null);
      showSpinner(true);
      var url = contextUrl + '?' + encodeURIComponent(paramName) + '=' + encodeURIComponent(paramVal);
      return fetch(url, {
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' },
      })
        .then(function (r) {
          if (!r.ok) throw new Error('Failed to load employee');
          return r.json();
        })
        .then(function (data) {
          ctxData = data;
          populateLeaveTypes(eligibleLeaveRows(data));
          renderBalanceStrip();
          validateDatesAndBalance();
          return data;
        })
        .catch(function () {
          ctxData = null;
          if (balanceBox) balanceBox.innerHTML = '<span class="text-danger small">Could not load leave context.</span>';
        })
        .finally(function () {
          showSpinner(false);
        });
    }

    if (selLeave)
      selLeave.addEventListener('change', function () {
        renderBalanceStrip();
        validateDatesAndBalance();
      });
    if (inpStart)
      inpStart.addEventListener('change', validateDatesAndBalance);
    if (inpEnd)
      inpEnd.addEventListener('change', validateDatesAndBalance);

    if (isPublic && inpCode) {
      inpCode.addEventListener('blur', function () {
        var c = (inpCode.value || '').trim();
        if (c.length < 3) return;
        fetchContext('code', c);
      });
    }

    if (!isPublic && selEmployee) {
      selEmployee.addEventListener('change', function () {
        var id = selEmployee.value;
        if (!id) return;
        fetchContext('employee_id', id);
      });
      if (selEmployee.value) {
        fetchContext('employee_id', selEmployee.value);
      }
    }

    function attachSubmitGuard(formEl) {
      if (!formEl) return;
      formEl.addEventListener('submit', function (ev) {
        validateDatesAndBalance();
        if (overlapAlert && !overlapAlert.classList.contains('d-none')) {
          ev.preventDefault();
          return false;
        }
        if (!selLeave || !selLeave.value || !ctxData) return;
        var ltId = selLeave.value;
        var row = unpaidBalanceRow(ctxData.leave_balances || [], ltId);
        if (!row) return;
        var sd = inpStart ? inpStart.value : '';
        var ed = inpEnd ? inpEnd.value : '';
        var wd = countUaeWorkingDays(sd, ed);
        var rem = parseFloat(row.remaining_days);
        var pt = (row.pay_type || '').toLowerCase();
        var isUnpaid = pt === 'unpaid';
        var ov = inpOverflow ? (inpOverflow.value || '').trim() : '';
        if (!isUnpaid && wd > rem && !ov) {
          ev.preventDefault();
          window.alert(
            'You only have ' +
              rem +
              ' days remaining for ' +
              row.leave_type_name +
              '. Please choose Reduce or Split options above, or shorten your dates.'
          );
          return false;
        }
      });
    }

    attachSubmitGuard(document.getElementById('public-leave-form'));
    attachSubmitGuard(document.getElementById('hr-leave-request-form'));
  }

  window.initHrLeaveApplication = init;
})();
