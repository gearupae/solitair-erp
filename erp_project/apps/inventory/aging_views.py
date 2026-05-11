"""
Inventory Aging Report — views.

Three entry points:
  - inventory_aging_report         → full-page HTML (GET params = filters)
  - inventory_aging_report_xlsx    → Excel download
  - inventory_aging_report_pdf     → PDF download

These functions live in a dedicated module so that existing inventory
views.py is NOT touched at all.
"""
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import render

from apps.core.utils import PermissionChecker

from .aging_report import build_aging_report, export_aging_xlsx, export_aging_pdf


# ---------------------------------------------------------------------------
# Permission check
# ---------------------------------------------------------------------------

def _has_perm(user):
    return user.is_superuser or (
        PermissionChecker.has_permission(user, "inventory", "view")
        or PermissionChecker.has_permission(user, "finance", "view")
    )


# ---------------------------------------------------------------------------
# Shared filter parsing
# ---------------------------------------------------------------------------

def _parse_filters(request):
    """Extract and validate GET filter params. Returns a dict."""
    from apps.inventory.models import Category, Warehouse

    cat_id = request.GET.get("category") or None
    wh_id = request.GET.get("warehouse") or None
    bucket = request.GET.get("bucket") or None
    slow_only = request.GET.get("slow_moving") == "1"
    search = (request.GET.get("q") or "").strip() or None
    sort = request.GET.get("sort", "age_desc")  # age_desc|age_asc|name|value|qty

    date_str = request.GET.get("date_as_of", "")
    as_of = None
    if date_str:
        try:
            as_of = date.fromisoformat(date_str)
        except ValueError:
            pass

    # Convert to int safely
    try:
        cat_id = int(cat_id)
    except (TypeError, ValueError):
        cat_id = None
    try:
        wh_id = int(wh_id)
    except (TypeError, ValueError):
        wh_id = None

    return {
        "as_of_date": as_of,
        "category_id": cat_id,
        "warehouse_id": wh_id,
        "bucket_filter": bucket if bucket in ("0-30", "31-60", "61-90", "91-180", "180+") else None,
        "slow_moving_only": slow_only,
        "search": search,
        "sort": sort,
        # For template dropdowns
        "categories": Category.objects.filter(is_active=True).order_by("name"),
        "warehouses": Warehouse.objects.filter(status="active").order_by("name"),
        # Raw values for repopulating filters
        "filter_category": cat_id,
        "filter_warehouse": wh_id,
        "filter_bucket": bucket or "",
        "filter_slow_moving": slow_only,
        "filter_search": search or "",
        "filter_date_as_of": date_str,
        "filter_sort": sort,
    }


def _sort_rows(rows: list, sort: str) -> list:
    if sort == "age_asc":
        return sorted(rows, key=lambda r: r["age_days"])
    if sort == "name":
        return sorted(rows, key=lambda r: r["item_name"].lower())
    if sort == "value_desc":
        return sorted(rows, key=lambda r: r["total_value"], reverse=True)
    if sort == "value_asc":
        return sorted(rows, key=lambda r: r["total_value"])
    if sort == "qty_desc":
        return sorted(rows, key=lambda r: r["qty_on_hand"], reverse=True)
    # default: age_desc
    return sorted(rows, key=lambda r: r["age_days"], reverse=True)


# ---------------------------------------------------------------------------
# Main page view
# ---------------------------------------------------------------------------

PAGE_SIZE = 50


@login_required
def inventory_aging_report(request):
    if not _has_perm(request.user):
        return HttpResponseForbidden("Permission denied.")

    filters = _parse_filters(request)

    # Build report
    result = build_aging_report(
        as_of_date=filters["as_of_date"],
        category_id=filters["category_id"],
        warehouse_id=filters["warehouse_id"],
        bucket_filter=filters["bucket_filter"],
        slow_moving_only=filters["slow_moving_only"],
        search=filters["search"],
    )

    rows = _sort_rows(result["rows"], filters["sort"])

    # Paginate
    paginator = Paginator(rows, PAGE_SIZE)
    page_num = request.GET.get("page", 1)
    try:
        page_num = int(page_num)
    except (ValueError, TypeError):
        page_num = 1
    page_obj = paginator.get_page(page_num)

    context = {
        "title": "Inventory Aging Report",
        "page_obj": page_obj,
        "rows": page_obj.object_list,
        "summary": result["summary"],
        "as_of_date": result["as_of_date"],
        "total_rows": len(rows),
        **filters,
    }
    return render(request, "inventory/inventory_aging_report.html", context)


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------

@login_required
def inventory_aging_report_xlsx(request):
    if not _has_perm(request.user):
        return HttpResponseForbidden("Permission denied.")

    filters = _parse_filters(request)
    result = build_aging_report(
        as_of_date=filters["as_of_date"],
        category_id=filters["category_id"],
        warehouse_id=filters["warehouse_id"],
        bucket_filter=filters["bucket_filter"],
        slow_moving_only=filters["slow_moving_only"],
        search=filters["search"],
    )
    result["rows"] = _sort_rows(result["rows"], filters["sort"])

    try:
        xlsx_bytes = export_aging_xlsx(
            result,
            generated_by=request.user.get_full_name() or request.user.username,
        )
    except Exception as exc:
        messages.error(request, f"Export error: {exc}")
        return HttpResponseForbidden(str(exc))

    resp = HttpResponse(
        xlsx_bytes,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    as_of_str = (result["as_of_date"] or "").strftime("%Y-%m-%d") if result.get("as_of_date") else "today"
    resp["Content-Disposition"] = f'attachment; filename="inventory_aging_{as_of_str}.xlsx"'
    return resp


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------

@login_required
def inventory_aging_report_pdf(request):
    if not _has_perm(request.user):
        return HttpResponseForbidden("Permission denied.")

    filters = _parse_filters(request)
    result = build_aging_report(
        as_of_date=filters["as_of_date"],
        category_id=filters["category_id"],
        warehouse_id=filters["warehouse_id"],
        bucket_filter=filters["bucket_filter"],
        slow_moving_only=filters["slow_moving_only"],
        search=filters["search"],
    )
    result["rows"] = _sort_rows(result["rows"], filters["sort"])

    try:
        pdf_bytes = export_aging_pdf(
            result,
            generated_by=request.user.get_full_name() or request.user.username,
        )
    except Exception as exc:
        messages.error(request, f"PDF export error: {exc}")
        return HttpResponseForbidden(str(exc))

    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    as_of_str = result["as_of_date"].strftime("%Y-%m-%d") if result.get("as_of_date") else "today"
    resp["Content-Disposition"] = f'inline; filename="inventory_aging_{as_of_str}.pdf"'
    return resp
