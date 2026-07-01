(function () {
    'use strict';

    var card = document.getElementById('estimateContractCard');
    if (!card) return;

    var canEdit = card.dataset.canEdit === 'true';
    var saveUrl = card.dataset.saveUrl || '';
    var statusEl = document.getElementById('contractSaveStatus');
    var editorEl = document.getElementById('contractEditor');
    var initialEl = document.getElementById('contractInitialHtml');

    function csrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    }

    function setStatus(text, cls) {
        if (!statusEl) return;
        statusEl.textContent = text || '';
        statusEl.className = 'estimate-contract-save-status' + (cls ? ' ' + cls : '');
    }

    if (!canEdit || !editorEl || typeof Quill === 'undefined') {
        return;
    }

    var initialHtml = initialEl ? initialEl.value : '';
    var quill = new Quill(editorEl, {
        theme: 'snow',
        modules: {
            toolbar: [
                [{ header: [1, 2, 3, false] }],
                ['bold', 'italic', 'underline', 'strike'],
                [{ list: 'ordered' }, { list: 'bullet' }],
                [{ indent: '-1' }, { indent: '+1' }],
                [{ align: [] }],
                ['clean'],
            ],
            clipboard: { matchVisual: false },
        },
        placeholder: 'Enter or paste contract text…',
    });

    if (initialHtml) {
        quill.clipboard.dangerouslyPasteHTML(initialHtml);
    }

    var saveTimer = null;
    var lastSaved = initialHtml;
    var saving = false;
    var pending = false;

    function currentHtml() {
        var html = quill.root.innerHTML.trim();
        if (html === '<p><br></p>' || html === '<p></p>') return '';
        return html;
    }

    function doSave() {
        var html = currentHtml();
        if (html === lastSaved) {
            setStatus('', '');
            return;
        }
        if (saving) {
            pending = true;
            return;
        }
        saving = true;
        pending = false;
        setStatus('Saving…', 'is-saving');

        var fd = new FormData();
        fd.append('csrfmiddlewaretoken', csrfToken());
        fd.append('contract_body', html);

        fetch(saveUrl, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken() },
            body: fd,
        })
            .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
            .then(function (res) {
                saving = false;
                if (!res.ok || !res.data.ok) {
                    setStatus('Save failed', 'is-error');
                    if (window.toastr) toastr.error(res.data.error || 'Could not save contract.');
                    return;
                }
                lastSaved = html;
                setStatus('Saved', 'is-saved');
                window.setTimeout(function () {
                    if (!saving && currentHtml() === lastSaved) setStatus('', '');
                }, 2000);
                if (pending) doSave();
            })
            .catch(function () {
                saving = false;
                setStatus('Save failed', 'is-error');
                if (window.toastr) toastr.error('Network error while saving contract.');
            });
    }

    function scheduleSave() {
        setStatus('Editing…', '');
        window.clearTimeout(saveTimer);
        saveTimer = window.setTimeout(doSave, 800);
    }

    quill.on('text-change', scheduleSave);
})();
