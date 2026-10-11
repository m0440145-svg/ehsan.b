import json
from datetime import date

from django.http import Http404
from django.shortcuts import render

from apps.core.permissions import has_perm, perm_required
from apps.meetings.models import Meeting
from apps.organization.models import Employee, Unit
from apps.tasks import selectors
from apps.tasks.constants import Priority, Source, Status
from apps.tasks.models import Task

from .exports import export_csv, export_excel
from .registry import REPORTS, build_report

FILTER_KEYS = ["date_from", "date_to", "unit", "employee", "status", "priority", "source", "project", "meeting"]


def _filters(request):
    f = {}
    for k in FILTER_KEYS:
        v = request.GET.get(k, "").strip()
        if not v:
            continue
        if k in ("date_from", "date_to"):
            try:
                v = date.fromisoformat(v)
            except ValueError:
                continue
        f[k] = v
    return f


@perm_required("reports.view")
def index(request):
    return render(request, "reports/index.html", {"reports": [(k, v[0], v[1]) for k, v in REPORTS.items()]})


@perm_required("reports.view")
def report_view(request, key):
    if key not in REPORTS:
        raise Http404
    filters = _filters(request)
    qs = selectors.visible_tasks(request.user)
    report = build_report(key, qs, filters)
    fmt = request.GET.get("export")
    if fmt in ("csv", "xlsx") and has_perm(request.user, "reports.export"):
        return export_csv(report) if fmt == "csv" else export_excel(report)
    ctx = {
        "report": report, "filters": filters, "reports": [(k, v[0], v[1]) for k, v in REPORTS.items()],
        "units": Unit.objects.all(), "employees": Employee.objects.order_by("full_name"),
        "statuses": Status.choices, "priorities": Priority.choices, "sources": Source.choices,
        "meetings": Meeting.objects.all(),
        "projects": Task.objects.exclude(project="").values_list("project", flat=True).distinct(),
        "chart": json.dumps(report.get("chart"), ensure_ascii=False) if report.get("chart") else None,
        "can_export": has_perm(request.user, "reports.export"),
        "print_mode": request.GET.get("print") == "1",
    }
    template = "reports/print.html" if ctx["print_mode"] else "reports/report.html"
    return render(request, template, ctx)
