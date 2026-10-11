"""
النسخ الاحتياطي:
- PostgreSQL: يستخدم pg_dump (بصيغة custom) إن كان متاحًا.
- أي قاعدة: تصدير JSON عبر dumpdata.
- نسخ مجلد الملفات المرفوعة (private_media) كملف مضغوط.
يُنصح بجدولته يوميًا (cron / Task Scheduler) مع الاحتفاظ بعدد محدد من النسخ.
"""
import os
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from apps.audit import services as audit


class Command(BaseCommand):
    help = "إنشاء نسخة احتياطية من قاعدة البيانات والمرفقات"

    def add_arguments(self, parser):
        parser.add_argument("--keep", type=int, default=14, help="عدد النسخ المحتفظ بها")

    def handle(self, *args, **opts):
        stamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
        target = Path(settings.BACKUP_DIR) / stamp
        target.mkdir(parents=True, exist_ok=True)
        db = settings.DATABASES["default"]
        if connection.vendor == "postgresql" and shutil.which("pg_dump"):
            env = {"PGPASSWORD": db.get("PASSWORD", "")}
            cmd = ["pg_dump", "-Fc", "-h", db.get("HOST") or "localhost", "-p", str(db.get("PORT") or 5432),
                   "-U", db.get("USER", ""), "-f", str(target / "database.dump"), db["NAME"]]
            subprocess.run(cmd, check=True, env={**os.environ, **env})
            self.stdout.write("تم إنشاء pg_dump")
        with open(target / "data.json", "w", encoding="utf-8") as fh:
            call_command("dumpdata", "--natural-foreign", "--exclude=contenttypes", "--exclude=sessions",
                         "--exclude=auth.permission", "--indent=1", stdout=fh)
        media = Path(settings.MEDIA_ROOT)
        if media.exists():
            shutil.make_archive(str(target / "media"), "zip", media)
        backups = sorted(p for p in Path(settings.BACKUP_DIR).iterdir() if p.is_dir())
        for old in backups[:-opts["keep"]]:
            shutil.rmtree(old, ignore_errors=True)
        audit.log("system.backup", description=f"نسخة احتياطية: {target}", system=True)
        self.stdout.write(self.style.SUCCESS(f"تم إنشاء النسخة الاحتياطية في {target}"))
