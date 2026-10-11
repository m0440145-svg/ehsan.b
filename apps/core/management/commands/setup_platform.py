from django.core.management.base import BaseCommand

from apps.core.bootstrap import ensure_reference_data


class Command(BaseCommand):
    help = "تهيئة الصلاحيات والأدوار وقواعد التصعيد الافتراضية وأنواع المهام"

    def add_arguments(self, parser):
        parser.add_argument("--reset-permissions", action="store_true", help="إعادة صلاحيات الأدوار للوضع الافتراضي")

    def handle(self, *args, **opts):
        ensure_reference_data(reset_role_permissions=opts["reset_permissions"])
        self.stdout.write(self.style.SUCCESS("تمت تهيئة البيانات المرجعية"))
