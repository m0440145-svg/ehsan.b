import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.audit import services as audit
from apps.core.permissions import has_perm, perm_required
from apps.reports.kpis import compute_kpis
from apps.tasks import selectors
from apps.tasks.constants import ACTIVE_STATUSES, OPEN_STATUSES
from apps.tasks.models import Task
from apps.tasks.views import with_people

from .forms import EmployeeForm, EmployeeImportForm, UnitForm
from .models import Employee, EmployeeUnit, Unit
from .services import import_employees, save_employee, template_workbook


# ===== الوحدات =====

@perm_required("admin.units")
def units_list(request):
    units = Unit.objects.select_related("head", "parent").annotate(
        emp_count=Count("employees", distinct=True),
    )
    rows = []
    for u in units:
        k = compute_kpis(Task.objects.filter(unit=u))
        rows.append({"unit": u, "kpis": k})
    return render(request, "organization/units_list.html", {"rows": rows})


@perm_required("admin.units")
def unit_form(request, pk=None):
    instance = get_object_or_404(Unit, pk=pk) if pk else None
    form = UnitForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        unit = form.save()
        if unit.head and not EmployeeUnit.objects.filter(employee=unit.head, unit=unit).exists():
            EmployeeUnit.objects.create(employee=unit.head, unit=unit, is_primary=not unit.head.unit_links.exists())
        audit.log("unit.updated" if instance else "unit.created", obj=unit, description=unit.name)
        messages.success(request, "تم حفظ الوحدة")
        return redirect("organization:unit_detail", pk=unit.pk)
    return render(request, "organization/unit_form.html", {"form": form, "instance": instance})


@login_required
def unit_detail(request, pk):
    unit = get_object_or_404(Unit.objects.select_related("head"), pk=pk)
    is_head = selectors.employee_of(request.user) and unit.head_id == selectors.employee_of(request.user).pk
    if not (has_perm(request.user, "admin.units") or has_perm(request.user, "tasks.view_all") or is_head):
        raise PermissionDenied
    tasks = Task.objects.filter(Q(unit=unit) | Q(task_units__unit=unit)).distinct()
    tasks = selectors.visible_tasks(request.user).filter(pk__in=tasks.values("pk"))
    return render(request, "organization/unit_detail.html", {
        "unit": unit, "kpis": compute_kpis(tasks.filter(unit=unit)),
        "employees": unit.employees.select_related("user").order_by("full_name"),
        "tasks": with_people(tasks.filter(status__in=OPEN_STATUSES).order_by("due_date")[:15]),
    })


# ===== الموظفون =====

@perm_required("admin.employees")
def employees_list(request):
    qs = Employee.objects.select_related("user", "manager").prefetch_related("units").order_by("full_name")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(full_name__icontains=q) | Q(employee_no__icontains=q) | Q(job_title__icontains=q) | Q(user__email__icontains=q))
    if request.GET.get("unit"):
        qs = qs.filter(units__id=request.GET["unit"])
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    for e in page:
        k = compute_kpis(Task.objects.filter(assignees__employee=e))
        e.k = k
    return render(request, "organization/employees_list.html", {
        "page_obj": page, "units": Unit.objects.all(), "statuses": Employee.Status.choices,
    })


@perm_required("admin.employees")
@transaction.atomic
def employee_form(request, pk=None):
    instance = get_object_or_404(Employee, pk=pk) if pk else None
    form = EmployeeForm(request.POST or None, request.FILES or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        emp = save_employee(form, request.user)
        msg = "تم حفظ بيانات الموظف"
        if not instance and emp.user_id:
            msg += f" وإنشاء حساب دخول ({emp.user.email}) – سيُطلب منه تغيير كلمة المرور عند أول دخول"
        messages.success(request, msg)
        if request.POST.get("save_and_new"):
            return redirect("organization:employee_create")
        return redirect("organization:employee_detail", pk=emp.pk)
    return render(request, "organization/employee_form.html", {"form": form, "instance": instance})


@perm_required("admin.employees")
def employee_import(request):
    form = EmployeeImportForm(request.POST or None, request.FILES or None)
    created, errors = [], []
    if request.method == "POST" and form.is_valid():
        try:
            created, errors = import_employees(form.cleaned_data["file"], request.user,
                                               form.cleaned_data["create_missing_units"])
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
        else:
            if errors:
                messages.error(request, f"لم يُستورد أي موظف: يوجد {len(errors)} صف به أخطاء. صحّحها ثم أعد الرفع.")
            else:
                messages.success(request, f"تم استيراد {len(created)} موظف")
    return render(request, "organization/employee_import.html", {"form": form, "created": created, "errors": errors})


@perm_required("admin.employees")
def employee_import_template(request):
    resp = HttpResponse(template_workbook(),
                        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = 'attachment; filename="employees_template.xlsx"'
    return resp


@login_required
def employee_detail(request, pk):
    emp = get_object_or_404(Employee.objects.select_related("user", "manager"), pk=pk)
    me = selectors.employee_of(request.user)
    allowed = (
        has_perm(request.user, "admin.employees") or has_perm(request.user, "tasks.view_all")
        or (me and me.pk == emp.pk)
        or (me and emp.units.filter(head=me).exists())
    )
    if not allowed:
        raise PermissionDenied
    tasks = selectors.visible_tasks(request.user).filter(pk__in=Task.objects.filter(assignees__employee=emp).values("pk"))
    k = compute_kpis(tasks)
    in_progress = tasks.filter(status__in=ACTIVE_STATUSES).count() - k["overdue"] - k["stalled"]
    chart = {"type": "bar", "labels": ["إجمالي المهام", "المكتمل", "الجاري", "المتأخر", "المتعثر"],
             "datasets": [{"label": "عدد المهام", "data": [k["total"], k["done"], max(in_progress, 0), k["overdue"], k["stalled"]],
                           "colors": ["#cf6028", "#198754", "#1c6dd0", "#dc3545", "#8b1a1a"]}]}
    return render(request, "organization/employee_detail.html", {
        "emp": emp, "kpis": k, "chart": json.dumps(chart, ensure_ascii=False),
        "tasks": with_people(tasks.filter(status__in=OPEN_STATUSES).order_by("due_date")[:20]),
        "units": emp.unit_links.select_related("unit"),
    })
