"""Detect whether an estimate edit form actually changed data."""


def estimate_form_has_changes(form, items_formset) -> bool:
    """True when header or line items were modified (not a no-op save)."""
    if form.has_changed():
        return True
    if items_formset.has_changed():
        return True
    return False
