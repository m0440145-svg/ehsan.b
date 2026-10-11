from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .events import EVENTS
from .models import Notification
from .services import mark_read


@login_required
def center(request):
    qs = Notification.objects.filter(recipient=request.user).select_related("task", "actor")
    if request.GET.get("filter") == "unread":
        qs = qs.filter(is_read=False)
    if request.GET.get("event"):
        qs = qs.filter(event=request.GET["event"])
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "notifications/center.html", {"page_obj": page, "events": [(k, v[0]) for k, v in EVENTS.items()]})


@login_required
def open_notification(request, pk):
    n = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if not n.is_read:
        n.is_read = True
        n.read_at = timezone.now()
        n.save(update_fields=["is_read", "read_at"])
    target = n.url or "notifications:center"
    if n.url and not url_has_allowed_host_and_scheme(n.url, allowed_hosts={request.get_host()}):
        target = "notifications:center"
    return redirect(target)


@login_required
@require_POST
def mark_all_read(request):
    count = mark_read(request.user)
    messages.success(request, f"تم تعليم {count} تنبيه كمقروء")
    return redirect("notifications:center")


@login_required
def unread_count(request):
    return JsonResponse({"unread": Notification.objects.filter(recipient=request.user, is_read=False).count()})
