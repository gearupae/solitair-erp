(function () {
    function getCookie(name) {
        var match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
        return match ? decodeURIComponent(match[2]) : '';
    }

    function initProformaModal() {
        var modal = document.getElementById('proformaInvoiceModal');
        if (!modal || modal.dataset.proformaBound === '1') {
            return;
        }
        var form = modal.querySelector('#proformaInvoiceForm');
        var submitBtn = modal.querySelector('#proformaSubmitBtn');
        if (!form || !submitBtn) {
            return;
        }
        modal.dataset.proformaBound = '1';

        var createUrlTemplate = modal.getAttribute('data-create-url-template') || '';
        var estSubtotal = 0;
        var estVat = 0;
        var estVatRate = 0;
        var estTotal = 0;
        var remainingTotal = 0;
        var remainingSubtotal = 0;
        var maxPercent = 100;

        function q(id) {
            return modal.querySelector('#' + id);
        }

        function hideAlert(el) {
            if (el) {
                el.classList.add('d-none');
            }
        }

        function showAlert(el, message) {
            if (!el) {
                window.alert(message);
                return;
            }
            el.textContent = message;
            el.classList.remove('d-none');
        }

        function fmt(n) {
            return 'AED ' + (isFinite(n) ? Number(n) : 0).toFixed(2);
        }

        function activeChargeType() {
            var checked = form.querySelector('input[name="charge_type"]:checked');
            return checked ? checked.value : 'percent';
        }

        function activeValue() {
            if (activeChargeType() === 'percent') {
                return parseFloat(q('proformaValuePercent').value) || 0;
            }
            return parseFloat(q('proformaValueAmount').value) || 0;
        }

        function lineVatAmount(lineSub) {
            if (estSubtotal > 0 && estVat > 0) {
                return lineSub * estVat / estSubtotal;
            }
            if (estVatRate > 0) {
                return lineSub * estVatRate / 100;
            }
            return 0;
        }

        function syncChargeTypeUi() {
            var isPercent = activeChargeType() === 'percent';
            q('proformaValuePercentWrap').classList.toggle('d-none', !isPercent);
            q('proformaValueAmountWrap').classList.toggle('d-none', isPercent);
            q('proformaValuePercent').disabled = !isPercent;
            q('proformaValueAmount').disabled = isPercent;
            updatePreview();
        }

        function updatePreview() {
            var type = activeChargeType();
            var value = activeValue();
            var lineSub = type === 'percent' ? estSubtotal * value / 100 : value;
            var lineVat = lineVatAmount(lineSub);
            q('proformaPreviewSubtotal').textContent = fmt(lineSub);
            q('proformaPreviewVat').textContent = fmt(lineVat);
            q('proformaPreviewTotal').textContent = fmt(lineSub + lineVat);
        }

        function buildPostUrl(pk) {
            if (!createUrlTemplate || !pk) {
                return '';
            }
            return createUrlTemplate.replace('/0/', '/' + pk + '/');
        }

        modal.addEventListener('show.bs.modal', function (event) {
            var trigger = event.relatedTarget;
            if (!trigger) {
                return;
            }
            var pk = trigger.getAttribute('data-estimate-pk');
            estSubtotal = parseFloat(trigger.getAttribute('data-subtotal')) || 0;
            estVat = parseFloat(trigger.getAttribute('data-vat')) || 0;
            estVatRate = parseFloat(trigger.getAttribute('data-vat-rate')) || 0;
            estTotal = parseFloat(trigger.getAttribute('data-estimate-total')) || 0;
            if (estTotal <= 0 && estSubtotal > 0) {
                estTotal = estSubtotal + estVat;
            }
            remainingTotal = parseFloat(trigger.getAttribute('data-remaining-total')) || 0;
            remainingSubtotal = parseFloat(trigger.getAttribute('data-remaining-subtotal')) || 0;
            maxPercent = parseFloat(trigger.getAttribute('data-max-percent')) || 0;
            if (remainingTotal <= 0 && estTotal > 0) {
                var billed = parseFloat(trigger.getAttribute('data-billed-total')) || 0;
                remainingTotal = Math.max(estTotal - billed, 0);
            }
            if (remainingSubtotal <= 0 && estSubtotal > 0) {
                remainingSubtotal = estSubtotal;
            }
            if (maxPercent <= 0 && estSubtotal > 0 && remainingSubtotal > 0) {
                maxPercent = Math.min(100, (remainingSubtotal / estSubtotal) * 100);
            }

            q('proformaEstimateLabel').textContent = trigger.getAttribute('data-estimate-number') || ('#' + pk);
            q('proformaEstSubtotal').textContent = fmt(estSubtotal);
            if (q('proformaEstTotal')) {
                q('proformaEstTotal').textContent = fmt(estTotal);
            }
            if (q('proformaRemainingTotal')) {
                q('proformaRemainingTotal').textContent = fmt(remainingTotal);
            }
            q('proformaEstVatRate').textContent = estVatRate.toFixed(2) + '%';
            var pctInput = q('proformaValuePercent');
            if (pctInput && maxPercent > 0) {
                pctInput.max = String(Math.max(0.01, maxPercent).toFixed(2));
            }
            var amtInput = q('proformaValueAmount');
            if (amtInput && remainingSubtotal > 0) {
                amtInput.max = String(remainingSubtotal.toFixed(2));
            }

            hideAlert(q('proformaFormError'));
            hideAlert(q('proformaFormSuccess'));

            form.reset();
            q('proformaTypePercent').checked = true;

            modal.dataset.proformaCreateUrl = buildPostUrl(pk);
            form.action = modal.dataset.proformaCreateUrl;

            syncChargeTypeUi();
        });

        form.querySelectorAll('input[name="charge_type"]').forEach(function (el) {
            el.addEventListener('change', syncChargeTypeUi);
        });
        form.querySelectorAll('.proforma-value-input').forEach(function (el) {
            el.addEventListener('input', updatePreview);
        });

        submitBtn.addEventListener('click', function () {
            var errEl = q('proformaFormError');
            var okEl = q('proformaFormSuccess');
            hideAlert(errEl);
            hideAlert(okEl);

            var nameEl = q('proformaName');
            var name = nameEl ? nameEl.value.trim() : '';
            var type = activeChargeType();
            var value = activeValue();

            if (!name) {
                showAlert(errEl, 'Name is required.');
                return;
            }
            if (value <= 0) {
                showAlert(errEl, 'Enter a valid charge value greater than zero.');
                return;
            }
            if (remainingTotal <= 0) {
                showAlert(errEl, 'This quotation is already fully covered by proforma invoice(s).');
                return;
            }
            if (type === 'percent' && value > 100) {
                showAlert(errEl, 'Percentage cannot exceed 100%.');
                return;
            }
            if (type === 'percent' && value > maxPercent + 0.001) {
                showAlert(errEl, 'Percentage cannot exceed ' + maxPercent.toFixed(2) + '% (' + fmt(remainingSubtotal) + ' of quotation subtotal remains).');
                return;
            }
            if (type === 'amount' && value > remainingSubtotal + 0.001) {
                showAlert(errEl, 'Amount cannot exceed ' + fmt(remainingSubtotal) + ' (quotation subtotal remaining).');
                return;
            }
            var previewSub = type === 'percent' ? estSubtotal * value / 100 : value;
            var previewTot = previewSub + lineVatAmount(previewSub);
            if (previewTot > remainingTotal + 0.01) {
                showAlert(errEl, 'Proforma total ' + fmt(previewTot) + ' exceeds available ' + fmt(remainingTotal) + ' (incl. VAT).');
                return;
            }

            var postUrl = modal.dataset.proformaCreateUrl || form.action;
            if (!postUrl || postUrl === '#' || postUrl.indexOf('/proforma/create/') === -1) {
                showAlert(errEl, 'Could not determine save URL. Close the dialog and try again.');
                return;
            }

            var fd = new FormData(form);
            fd.set('charge_value', String(value));
            fd.set('name', name);
            fd.set('charge_type', type);

            var csrfInput = form.querySelector('[name=csrfmiddlewaretoken]');
            var csrf = (csrfInput && csrfInput.value) || getCookie('csrftoken');
            var headers = { 'X-Requested-With': 'XMLHttpRequest' };
            if (csrf) {
                headers['X-CSRFToken'] = csrf;
            }

            submitBtn.disabled = true;

            fetch(postUrl, {
                method: 'POST',
                body: fd,
                headers: headers,
                credentials: 'same-origin',
            })
                .then(function (r) {
                    var ct = (r.headers.get('content-type') || '').toLowerCase();
                    if (ct.indexOf('application/json') === -1) {
                        throw new Error('Unexpected server response (HTTP ' + r.status + ').');
                    }
                    return r.json().then(function (data) {
                        return { ok: r.ok, data: data };
                    });
                })
                .then(function (res) {
                    submitBtn.disabled = false;
                    if (res.ok && res.data && res.data.ok && res.data.pdf_url) {
                        window.location.href = res.data.pdf_url;
                        return;
                    }
                    showAlert(errEl, (res.data && res.data.error) || 'Could not create proforma invoice.');
                })
                .catch(function (err) {
                    submitBtn.disabled = false;
                    showAlert(errEl, (err && err.message) || 'Could not create proforma invoice.');
                });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initProformaModal);
    } else {
        initProformaModal();
    }
})();
