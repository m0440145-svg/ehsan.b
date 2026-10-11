from .menu import build_menu


def platform(request):
    ctx = {
        "PLATFORM_NAME": "منصة إدارة المهام ومتابعة القرارات",
        "ORG_NAME": "جمعية الإحسان للخدمات الاجتماعية ببريدة",
    }
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        from apps.notifications.models import Notification

        unread = Notification.objects.filter(recipient=user, is_read=False)
        ctx.update({
            "menu": build_menu(request),
            "unread_count": unread.count(),
            "latest_notifications": Notification.objects.filter(recipient=user).select_related("task")[:6],
            "current_employee": getattr(user, "employee", None),
        })
    return ctx
