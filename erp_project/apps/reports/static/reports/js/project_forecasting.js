(function () {
    'use strict';

    var RISK_ORDER = { red: 0, amber: 1, green: 2 };

    function getCsrfToken() {
        var input = document.querySelector('[name=csrfmiddlewaretoken]');
        if (input && input.value) {
            return input.value;
        }
        if (typeof getCookie === 'function') {
            return getCookie('csrftoken');
        }
        return '';
    }

    function initRowExpand() {
        document.querySelectorAll('.pf-row-expandable').forEach(function (row) {
            row.addEventListener('click', function () {
                var id = row.getAttribute('data-row-id');
                var detail = document.querySelector('[data-detail-for="' + id + '"]');
                if (detail) {
                    detail.classList.toggle('d-none');
                }
            });
        });
    }

    function parseSortValue(cell, key) {
        if (key === 'risk_level') {
            return RISK_ORDER[(cell.getAttribute('data-value') || 'green').toLowerCase()] ?? 9;
        }
        var val = cell.getAttribute('data-value');
        if (val !== null && val !== '') {
            var num = parseFloat(val);
            return isNaN(num) ? val.toLowerCase() : num;
        }
        return (cell.textContent || '').trim().toLowerCase();
    }

    function initSortableTable() {
        var table = document.getElementById('pfRiskTable');
        if (!table) {
            return;
        }
        var tbody = table.querySelector('tbody');
        var headers = table.querySelectorAll('th[data-sort]');
        var sortState = { key: 'risk_level', asc: true };

        function getColIndex(key) {
            var allHeaders = table.querySelectorAll('thead th');
            for (var i = 0; i < allHeaders.length; i++) {
                if (allHeaders[i].getAttribute('data-sort') === key) {
                    return i;
                }
            }
            return 0;
        }

        function sortRows(key, asc) {
            var pairs = [];
            tbody.querySelectorAll('.pf-row-expandable').forEach(function (row) {
                var id = row.getAttribute('data-row-id');
                var detail = tbody.querySelector('[data-detail-for="' + id + '"]');
                pairs.push({ row: row, detail: detail });
            });

            var colIdx = getColIndex(key);

            pairs.sort(function (a, b) {
                var cellA = a.row.children[colIdx];
                var cellB = b.row.children[colIdx];
                var va = parseSortValue(cellA, key);
                var vb = parseSortValue(cellB, key);
                if (va < vb) {
                    return asc ? -1 : 1;
                }
                if (va > vb) {
                    return asc ? 1 : -1;
                }
                return 0;
            });

            pairs.forEach(function (p) {
                tbody.appendChild(p.row);
                if (p.detail) {
                    tbody.appendChild(p.detail);
                }
            });
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
                headers.forEach(function (h) {
                    h.classList.remove('sorted');
                });
                th.classList.add('sorted');
                sortRows(key, sortState.asc);
            });
        });

        var defaultHeader = table.querySelector('th[data-sort="risk_level"]');
        if (defaultHeader) {
            defaultHeader.classList.add('sorted');
            sortRows('risk_level', true);
        }
    }

    function initRegenerateBrief() {
        var btn = document.getElementById('btnRegenerateBrief');
        var briefEl = document.getElementById('executiveBrief');
        var cfg = window.PF_CONFIG;
        if (!btn || !briefEl || !cfg) {
            return;
        }

        btn.addEventListener('click', function () {
            btn.disabled = true;
            var original = btn.innerHTML;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Generating…';

            var body = new FormData();
            body.append('start_date', cfg.filters.start_date || '');
            body.append('end_date', cfg.filters.end_date || '');
            body.append('status', cfg.filters.status || '');
            body.append('manager', cfg.filters.manager || '');
            body.append('customer', cfg.filters.customer || '');

            fetch(cfg.regenerateUrl, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken(),
                },
                body: body,
                credentials: 'same-origin',
            })
                .then(function (resp) {
                    if (!resp.ok) {
                        throw new Error('Request failed');
                    }
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
        initRowExpand();
        initSortableTable();
        initRegenerateBrief();
    });
})();
