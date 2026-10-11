from django.core.management.base import BaseCommand

from apps.tasks.engine import run_engine


class Command(BaseCommand):
    help = "تشغيل محرك القواعد والتصعيد على جميع المهام المفتوحة (للجدولة كل 15 دقيقة مثلًا)"

    def handle(self, *args, **opts):
        stats = run_engine()
        self.stdout.write(self.style.SUCCESS(f"تم: {stats}"))
