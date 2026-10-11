import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.audit import services as audit
from apps.core import ratelimit
from apps.core.forms import BootstrapMixin
from apps.core.middleware import client_ip
from apps.core.permissions import PERMISSIONS, perm_required

from . import otp
from .backends import find_user
from .forms import LoginForm, OTPForm, ProfilePasswordForm, UserForm
from .models import LoginAttempt, Permission, Role, User

security_log = logging.getLogger("security")


class _LoginForm(BootstrapMixin, LoginForm):
    pass


class _OTPForm(BootstrapMixin, OTPForm):
    pass


class _UserForm(BootstrapMixin, UserForm):
    pass


class _PasswordForm(BootstrapMixin, ProfilePasswordForm):
    pass


def _record_attempt(request, identifier, user, success, reason=""):
    LoginAttempt.objects.create(
        identifier=identifier[:190], user=user, ip_address=client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:300], success=success, reason=reason,
    )


def _finish_login(request, user):
    login(request, user, backend="apps.accounts.backends.EmailOrPhoneBackend")
    User.objects.filter(pk=user.pk).update(failed_login_count=0, locked_until=None)
    audit.log("auth.login", user=user, obj=user)
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(nxt)
    return redirect("dashboard:home")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")
    if not User.objects.exists():
        return redirect("setup")  # أول تشغيل: معالج الإعداد
    form = _LoginForm(request.POST or None)
    status = 200
    if request.method == "POST":
        ip = client_ip(request) or "unknown"
        identifier = request.POST.get("identifier", "").strip()
        if ratelimit.hit(f"login-ip:{ip}", settings.LOGIN_IP_RATE_LIMIT, settings.LOGIN_IP_RATE_WINDOW):
            _record_attempt(request, identifier, None, False, "rate_limited")
            security_log.warning("تجاوز حد محاولات الدخول من %s", ip)
            form.add_error(None, "عدد كبير من المحاولات. يرجى الانتظار عدة دقائق ثم المحاولة مجددًا.")
            status = 429
        elif form.is_valid():
            identifier = form.cleaned_data["identifier"]
            candidate = find_user(identifier)
            if candidate and candidate.is_locked:
                _record_attempt(request, identifier, candidate, False, "locked")
                minutes = int((candidate.locked_until - timezone.now()).total_seconds() // 60) + 1
                form.add_error(None, f"الحساب مقفل مؤقتًا بسبب محاولات فاشلة متكررة. حاول بعد {minutes} دقيقة.")
            else:
                user = authenticate(request, username=identifier, password=form.cleaned_data["password"])
                if user is not None:
                    _record_attempt(request, identifier, user, True)
                    if otp.is_required(user):
                        otp.start(request, user)
                        return redirect("accounts:otp")
                    return _finish_login(request, user)
                reason = "bad_credentials"
                if candidate:
                    candidate.failed_login_count += 1
                    fields = ["failed_login_count"]
                    if not candidate.is_active:
                        reason = "inactive"
                    if candidate.failed_login_count >= settings.LOGIN_MAX_ATTEMPTS:
                        candidate.locked_until = timezone.now() + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
                        candidate.failed_login_count = 0
                        fields.append("locked_until")
                        audit.log("auth.locked", user=candidate, obj=candidate, description="قفل تلقائي بعد محاولات فاشلة")
                        security_log.warning("قفل الحساب %s بعد محاولات فاشلة", candidate.email)
                    candidate.save(update_fields=fields)
                _record_attempt(request, identifier, candidate, False, reason)
                audit.log("auth.login_failed", user=None, description=f"محاولة دخول فاشلة: {identifier}")
                form.add_error(None, "بيانات الدخول غير صحيحة")
    return render(request, "accounts/login.html", {"form": form, "otp_enabled": settings.OTP_ENABLED}, status=status)


def otp_view(request):
    if otp.SESSION_KEY not in request.session:
        return redirect("accounts:login")
    form = _OTPForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user_id = otp.verify(request, form.cleaned_data["code"])
        if user_id:
            return _finish_login(request, User.objects.get(pk=user_id))
        form.add_error("code", "رمز التحقق غير صحيح أو منتهي الصلاحية")
    return render(request, "accounts/otp.html", {"form": form})


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        audit.log("auth.logout", user=request.user, obj=request.user)
    logout(request)
    messages.info(request, "تم تسجيل الخروج بنجاح")
    return redirect("accounts:login")


@login_required
def profile_view(request):
    form = _PasswordForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        request.user.set_password(form.cleaned_data["new_password"])
        request.user.must_change_password = False
        request.user.save()
        update_session_auth_hash(request, request.user)
        audit.log("auth.password_changed", user=request.user, obj=request.user)
        messages.success(request, "تم تغيير كلمة المرور بنجاح")
        return redirect("accounts:profile")
    attempts = LoginAttempt.objects.filter(user=request.user)[:10]
    return render(request, "accounts/profile.html", {"form": form, "attempts": attempts})


# ===== إدارة المستخدمين =====

@perm_required("admin.users")
def users_list(request):
    qs = User.objects.select_related("role", "employee").order_by("full_name")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(full_name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))
    if request.GET.get("role"):
        qs = qs.filter(role__code=request.GET["role"])
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    attempts = LoginAttempt.objects.select_related("user")[:15]
    return render(request, "accounts/users_list.html", {"page_obj": page, "roles": Role.objects.all(), "attempts": attempts})


@perm_required("admin.users")
@transaction.atomic
def user_form(request, pk=None):
    instance = get_object_or_404(User, pk=pk) if pk else None
    initial = {}
    if not instance:
        initial = {"must_change_password": True, "role": Role.objects.filter(code=request.GET.get("role", "employee")).first()}
    form = _UserForm(request.POST or None, instance=instance, initial=initial)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        if form.cleaned_data.get("password"):
            user.set_password(form.cleaned_data["password"])
        user.save()
        emp = form.cleaned_data.get("employee")
        from apps.organization.models import Employee

        Employee.objects.filter(user=user).exclude(pk=getattr(emp, "pk", None)).update(user=None)
        if emp:
            emp.user = user
            emp.save(update_fields=["user"])
        audit.log("user.updated" if instance else "user.created", obj=user,
                  description=f"{user.full_name} – {user.role.name if user.role else ''}")
        messages.success(request, "تم حفظ المستخدم بنجاح")
        return redirect("accounts:users")
    return render(request, "accounts/user_form.html", {"form": form, "instance": instance})


@perm_required("admin.users")
@require_POST
def user_unlock(request, pk):
    user = get_object_or_404(User, pk=pk)
    user.locked_until = None
    user.failed_login_count = 0
    user.save(update_fields=["locked_until", "failed_login_count"])
    audit.log("user.updated", obj=user, description="فك قفل الحساب")
    messages.success(request, f"تم فك قفل حساب {user.full_name}")
    return redirect("accounts:users")


@perm_required("admin.roles")
def roles_view(request):
    roles = list(Role.objects.prefetch_related("permissions").order_by("id"))
    perms = list(Permission.objects.all())
    if request.method == "POST":
        with transaction.atomic():
            for role in roles:
                if role.code == "admin":
                    continue  # صلاحيات مسؤول النظام ثابتة لمنع الإقفال الذاتي
                selected = set(request.POST.getlist(f"role_{role.pk}"))
                before = set(role.permissions.values_list("code", flat=True))
                role.permissions.set([p for p in perms if p.code in selected])
                if before != selected:
                    audit.log("role.updated", obj=role, description=role.name,
                              old={"الصلاحيات": sorted(before)}, new={"الصلاحيات": sorted(selected)})
        messages.success(request, "تم تحديث مصفوفة الصلاحيات")
        return redirect("accounts:roles")
    groups = {}
    for p in perms:
        groups.setdefault(p.group, []).append(p)
    matrix = {r.pk: set(r.permissions.values_list("code", flat=True)) for r in roles}
    return render(request, "accounts/roles.html", {"roles": roles, "groups": groups, "matrix": matrix})
