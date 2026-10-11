from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render
from django.urls import path
from django.utils import timezone

from apps.core.settings_service import get_rules

from . import selectors
from .views import with_people


@login_required
def center(request):
    rules = get_rules()
    base = selectors.visible_tasks(request.user)
    tab = request.GET.get("tab", "overdue")
    valid = [t[0] for t in selectors.FOLLOWUP_TABS]
    if tab not in valid:
        tab = "overdue"
    tabs = []
    for key, label, icon, tone in selectors.FOLLOWUP_TABS:
        if key == "due_soon":
            label = f"تستحق خلال {rules['due_soon_days']} أيام"
        tabs.append({"key": key, "label": label, "icon": icon, "tone": tone,
                     "count": selectors.followup_filter(base, key, rules).count()})
    qs = selectors.followup_filter(base, tab, rules)
    if request.GET.get("unit"):
        qs = qs.filter(unit_id=request.GET["unit"])
    order = "due_date" if tab not in ("stale",) else "last_activity_at"
    qs = with_people(qs.order_by(order, "-id"))
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    current = next(t for t in tabs if t["key"] == tab)
    return render(request, "tasks/followup.html", {
        "tabs": tabs, "tab": tab, "current": current, "page_obj": page, "rules": rules, "today": timezone.localdate(),
    })


app_name = "followup"
urlpatterns = [path("", center, name="center")]
