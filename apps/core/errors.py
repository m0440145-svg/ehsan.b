from django.shortcuts import render


def _page(request, status, icon, title, text):
    template = "errors.html"
    return render(request, template, {"code": status, "icon": icon, "title": title, "text": text}, status=status)


def forbidden(request, exception=None):
    msg = str(exception) if exception and str(exception) else "ليس لديك صلاحية للوصول إلى هذه الصفحة أو البيانات."
    return _page(request, 403, "bi-shield-lock", "غير مصرح", msg)


def not_found(request, exception=None):
    return _page(request, 404, "bi-signpost", "الصفحة غير موجودة", "الرابط غير صحيح أو أن البيانات غير متاحة لك.")


def server_error(request):
    return render(request, "errors_plain.html", status=500)
