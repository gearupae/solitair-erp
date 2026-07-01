(function () {
    'use strict';

    var card = document.getElementById('estimateContractCard');
    if (!card) return;

    var canEdit = card.dataset.canEdit === 'true';
    var saveUrl = card.dataset.saveUrl || '';
    var statusEl = document.getElementById('contractSaveStatus');
    var editor = document.getElementById('contractHtmlEditor');
    var initialEl = document.getElementById('contractInitialHtml');
    var toolbar = document.getElementById('contractEditorToolbar');

    function csrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    }

    function setStatus(text, cls) {
        if (!statusEl) return;
        statusEl.textContent = text || '';
        statusEl.className = 'estimate-contract-save-status' + (cls ? ' ' + cls : '');
    }

    if (!canEdit || !editor) {
        return;
    }

    function cleanPastedHtml(html) {
        if (!html) return '';
        html = html.replace(/<!--[\s\S]*?-->/g, '');
        try {
            var doc = new DOMParser().parseFromString(html, 'text/html');
            doc.querySelectorAll('script, meta, link').forEach(function (node) {
                node.remove();
            });
            var styles = Array.prototype.map.call(doc.querySelectorAll('style'), function (node) {
                return node.outerHTML;
            }).join('');
            doc.querySelectorAll('style').forEach(function (node) {
                node.remove();
            });
            var bodyHtml = doc.body ? doc.body.innerHTML : html;
            return (styles + bodyHtml).trim();
        } catch (e) {
            return html.trim();
        }
    }

    function insertHtmlAtCursor(html) {
        editor.focus();
        if (document.queryCommandSupported('insertHTML')) {
            document.execCommand('insertHTML', false, html);
            return;
        }
        var sel = window.getSelection();
        if (!sel || !sel.rangeCount) {
            editor.insertAdjacentHTML('beforeend', html);
            return;
        }
        var range = sel.getRangeAt(0);
        range.deleteContents();
        range.insertNode(range.createContextualFragment(html));
        range.collapse(false);
        sel.removeAllRanges();
        sel.addRange(range);
    }

    function currentHtml() {
        var html = editor.innerHTML.trim();
        if (html === '<p><br></p>' || html === '<p></p>' || html === '<br>') return '';
        return html;
    }

    var saveTimer = null;
    var lastSaved = '';
    var saving = false;
    var pending = false;

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

    var initialHtml = initialEl ? initialEl.value : '';
    if (initialHtml) {
        editor.innerHTML = initialHtml;
    }
    lastSaved = currentHtml();

    editor.addEventListener('paste', function (e) {
        var clipboard = e.clipboardData || window.clipboardData;
        if (!clipboard) return;
        var html = clipboard.getData('text/html');
        if (html) {
            e.preventDefault();
            insertHtmlAtCursor(cleanPastedHtml(html));
            scheduleSave();
            return;
        }
        scheduleSave();
    });

    editor.addEventListener('input', scheduleSave);

    if (toolbar) {
        toolbar.addEventListener('click', function (e) {
            var btn = e.target.closest('[data-cmd]');
            if (!btn) return;
            e.preventDefault();
            var cmd = btn.getAttribute('data-cmd');
            var val = btn.getAttribute('data-value') || null;
            editor.focus();
            document.execCommand(cmd, false, val);
            scheduleSave();
        });
    }
})();
