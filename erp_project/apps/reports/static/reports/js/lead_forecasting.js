(function () {
    'use strict';

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

    function parseSortValue(cell, key) {
        var val = cell.getAttribute('data-value');
        if (val !== null && val !== '') {
            var num = parseFloat(val);
            return isNaN(num) ? val.toLowerCase() : num;
        }
        return (cell.textContent || '').trim().toLowerCase();
    }

    function initSortableTable(tableId, defaultSort) {
        var table = document.getElementById(tableId);
        if (!table) {
            return;
        }
        var tbody = table.querySelector('tbody');
        var headers = table.querySelectorAll('th[data-sort]');
        var sortState = { key: defaultSort.key, asc: defaultSort.asc };

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
            var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
            var colIdx = getColIndex(key);
            rows.sort(function (a, b) {
                var va = parseSortValue(a.children[colIdx], key);
                var vb = parseSortValue(b.children[colIdx], key);
                if (va < vb) {
                    return asc ? -1 : 1;
                }
                if (va > vb) {
                    return asc ? 1 : -1;
                }
                return 0;
            });
            rows.forEach(function (row) {
                tbody.appendChild(row);
            });
        }

        headers.forEach(function (th) {
            th.addEventListener('click', function () {
                var key = th.getAttribute('data-sort');
                if (sortState.key === key) {
                    sortState.asc = !sortState.asc;
                } else {
                    sortState.key = key;
                    sortState.asc = th.getAttribute('data-sort-default') !== 'asc';
                }
                headers.forEach(function (h) {
                    h.classList.remove('sorted');
                });
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
        var cfg = window.LF_CONFIG;
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
            body.append('stage', cfg.filters.stage || '');
            body.append('salesperson', cfg.filters.salesperson || '');
            body.append('source', cfg.filters.source || '');

            fetch(cfg.regenerateUrl, {
                method: 'POST',
                headers: { 'X-CSRFToken': getCsrfToken() },
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
        initSortableTable('lfSpTable', { key: 'predicted_conversions', asc: false });
        initSortableTable('lfLeadTable', { key: 'win_probability', asc: false });
        initRegenerateBrief();
    });
})();
