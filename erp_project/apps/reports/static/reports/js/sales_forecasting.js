(function () {
    'use strict';

    var RISK_ORDER = { red: 0, amber: 1, green: 2 };

    function getCsrfToken() {
        var input = document.querySelector('[name=csrfmiddlewaretoken]');
        if (input && input.value) return input.value;
        if (typeof getCookie === 'function') return getCookie('csrftoken');
        return '';
    }

    function initSortableTable(tableId, defaultSort) {
        var table = document.getElementById(tableId);
        if (!table) return;

        var tbody = table.querySelector('tbody');
        var headers = table.querySelectorAll('th[data-sort]');
        var sortState = { key: defaultSort.key, asc: defaultSort.asc };

        function getColIndex(key) {
            var allHeaders = table.querySelectorAll('thead th');
            for (var i = 0; i < allHeaders.length; i++) {
                if (allHeaders[i].getAttribute('data-sort') === key) return i;
            }
            return 0;
        }

        function parseValue(cell, key) {
            if (key === 'risk_flag') {
                return RISK_ORDER[(cell.getAttribute('data-value') || 'green').toLowerCase()] ?? 9;
            }
            var val = cell.getAttribute('data-value');
            if (val !== null && val !== '') {
                var num = parseFloat(String(val).replace('%', ''));
                return isNaN(num) ? val.toLowerCase() : num;
            }
            return (cell.textContent || '').trim().toLowerCase();
        }

        function sortRows(key, asc) {
            var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
            var colIdx = getColIndex(key);
            rows.sort(function (a, b) {
                var va = parseValue(a.children[colIdx], key);
                var vb = parseValue(b.children[colIdx], key);
                if (va < vb) return asc ? -1 : 1;
                if (va > vb) return asc ? 1 : -1;
                return 0;
            });
            rows.forEach(function (row) { tbody.appendChild(row); });
        }

        headers.forEach(function (th) {
            th.addEventListener('click', function () {
                var key = th.getAttribute('data-sort');
                if (sortState.key === key) {
                    sortState.asc = !sortState.asc;
                } else {
                    sortState.key = key;
                    sortState.asc = th.getAttribute('data-sort-default') !== 'desc';
                }
                headers.forEach(function (h) { h.classList.remove('sorted'); });
                th.classList.add('sorted');
                sortRows(key, sortState.asc);
            });
        });

        var defaultHeader = table.querySelector('th[data-sort="' + defaultSort.key + '"]');
        if (defaultHeader) {
            defaultHeader.classList.add('sorted');
            sortRows(defaultSort.key, defaultSort.asc);
        }
    }

    function initRegenerateBrief() {
        var btn = document.getElementById('btnRegenerateBrief');
        var briefEl = document.getElementById('executiveBrief');
        var cfg = window.SF_CONFIG;
        if (!btn || !briefEl || !cfg) return;

        btn.addEventListener('click', function () {
            btn.disabled = true;
            var original = btn.innerHTML;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Generating…';

            var body = new FormData();
            body.append('start_date', cfg.filters.start_date || '');
            body.append('end_date', cfg.filters.end_date || '');
            body.append('status', cfg.filters.status || '');
            body.append('salesperson', cfg.filters.salesperson || '');
            body.append('customer', cfg.filters.customer || '');
            body.append('job_type', cfg.filters.job_type || '');

            fetch(cfg.regenerateUrl, {
                method: 'POST',
                headers: { 'X-CSRFToken': getCsrfToken() },
                body: body,
                credentials: 'same-origin',
            })
                .then(function (resp) {
                    if (!resp.ok) throw new Error('failed');
                    return resp.json();
                })
                .then(function (data) {
                    briefEl.textContent = data.brief || 'No brief returned.';
                })
                .catch(function () {
                    briefEl.textContent = 'Failed to regenerate brief. Please try again.';
                })
                .finally(function () {
                    btn.disabled = false;
                    btn.innerHTML = original;
                });
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        initSortableTable('sfEstimateTable', { key: 'risk_flag', asc: true });
        initRegenerateBrief();
    });
})();
