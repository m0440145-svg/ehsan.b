"""
بيانات تجريبية واقعية بالعربية: وحدات، 27 مستخدمًا/موظفًا بأدوار مختلفة، اجتماعات وقرارات،
أكثر من 35 مهمة بحالات متنوعة (مكتملة، متأخرة، متعثرة، بانتظار اعتماد...)، تعليقات وتنبيهات.

كلمة المرور التجريبية لجميع الحسابات: DEMO_PASSWORD أدناه (للتطوير المحلي فقط).
"""
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.bootstrap import ensure_reference_data
from apps.meetings import services as meeting_services
from apps.meetings.models import Meeting
from apps.organization.models import Employee, EmployeeUnit, Unit
from apps.tasks import services
from apps.tasks.engine import run_engine
from apps.tasks.models import Task, TaskType

DEMO_PASSWORD = "Ehsan@Demo2026"
DOMAIN = "demo.ehsan.test"

UNITS = [
    ("board", "مجلس الإدارة", "الجهة العليا المسؤولة عن رسم السياسات واعتماد الخطط الاستراتيجية."),
    ("ed", "المدير التنفيذي", "قيادة العمل التنفيذي ومتابعة تحقيق أهداف الجمعية."),
    ("sec", "السكرتارية", "إدارة المراسلات والاجتماعات وتنظيم أعمال الإدارة التنفيذية."),
    ("eda", "مساعد المدير التنفيذي", "دعم المدير التنفيذي في المتابعة والتنسيق بين الوحدات."),
    ("comm", "وحدة الاتصال المؤسسي", "الإعلام والتسويق وإدارة الهوية والعلاقات العامة."),
    ("tech", "وحدة التقنية والتحول الرقمي", "الأنظمة والبنية التقنية والتحول الرقمي."),
    ("care", "وحدة الخدمات الرعوية", "دراسة الحالات وصرف المساعدات ورعاية الأسر المستفيدة."),
    ("comty", "وحدة خدمة المجتمع", "المبادرات المجتمعية والشراكات المحلية."),
    ("dev", "وحدة الخدمات التنموية", "برامج التمكين والتدريب والأسر المنتجة."),
    ("vol", "وحدة التطوع", "استقطاب المتطوعين وإدارة الفرص التطوعية."),
    ("hr", "وحدة الموارد البشرية", "التوظيف وتقييم الأداء وشؤون الموظفين."),
    ("fin", "وحدة الشؤون المالية والإدارية", "المحاسبة والميزانيات والمشتريات."),
    ("audit", "وحدة المراجعة الداخلية", "مراجعة الإجراءات والامتثال والرقابة الداخلية."),
    ("inv", "وحدة الاستثمار", "تنمية الموارد والأوقاف والاستثمارات."),
    ("exc", "وحدة التميز المؤسسي", "الجودة والتميز المؤسسي وقياس الأداء."),
    ("sup", "وحدة الخدمات المساندة", "الصيانة والمستودعات والخدمات العامة."),
]

# المفتاح: (الاسم، المسمى، الوحدة، الدور، رئيس وحدة؟، المدير المباشر)
PEOPLE = {
    "chair": ("د. صالح بن عبدالله الفوزان", "رئيس مجلس الإدارة", "board", "viewer", True, None),
    "ed": ("عبدالله بن محمد السالم", "المدير التنفيذي", "ed", "executive_director", True, None),
    "eda": ("خالد بن إبراهيم العمر", "مساعد المدير التنفيذي", "eda", "ed_assistant", True, "ed"),
    "noura": ("نورة بنت سعد الحربي", "مديرة مكتب المدير التنفيذي", "sec", "unit_head", True, "ed"),
    "reem": ("ريم بنت عبدالعزيز القحطاني", "رئيسة وحدة الاتصال المؤسسي", "comm", "unit_head", True, "eda"),
    "fahad": ("فهد بن ناصر الدوسري", "رئيس وحدة التقنية والتحول الرقمي", "tech", "unit_head", True, "eda"),
    "sara": ("سارة بنت محمد العتيبي", "رئيسة وحدة الخدمات الرعوية", "care", "unit_head", True, "eda"),
    "majed": ("ماجد بن علي الشمري", "رئيس وحدة خدمة المجتمع", "comty", "unit_head", True, "eda"),
    "haifa": ("هيفاء بنت خالد المطيري", "رئيسة وحدة الخدمات التنموية", "dev", "unit_head", True, "eda"),
    "yousef": ("يوسف بن أحمد الزهراني", "رئيس وحدة التطوع", "vol", "unit_head", True, "eda"),
    "muneera": ("منيرة بنت فهد السبيعي", "رئيسة وحدة الموارد البشرية", "hr", "unit_head", True, "eda"),
    "sultan": ("سلطان بن عبدالرحمن الغامدي", "رئيس وحدة الشؤون المالية والإدارية", "fin", "unit_head", True, "eda"),
    "abdulrahman": ("عبدالرحمن بن صالح التميمي", "رئيس وحدة المراجعة الداخلية", "audit", "unit_head", True, "ed"),
    "turki": ("تركي بن سعود العنزي", "رئيس وحدة الاستثمار", "inv", "unit_head", True, "eda"),
    "latifa": ("لطيفة بنت حمد الرشيد", "رئيسة وحدة التميز المؤسسي", "exc", "unit_head", True, "eda"),
    "bandar": ("بندر بن مشعل الحارثي", "رئيس وحدة الخدمات المساندة", "sup", "unit_head", True, "eda"),
    "ahmad": ("أحمد بن سالم الجهني", "مطور أنظمة", "tech", "employee", False, "fahad"),
    "mohammed": ("محمد بن عبدالله القرني", "أخصائي دعم فني", "tech", "employee", False, "fahad"),
    "amal": ("أمل بنت ناصر الشهري", "أخصائية اجتماعية", "care", "employee", False, "sara"),
    "jawaher": ("جواهر بنت سعد البقمي", "باحثة اجتماعية", "care", "employee", False, "sara"),
    "abdulaziz": ("عبدالعزيز بن فهد الخالدي", "محاسب أول", "fin", "employee", False, "sultan"),
    "maha": ("مها بنت عبدالله الدخيل", "أخصائية محتوى وتسويق", "comm", "employee", False, "reem"),
    "nayef": ("نايف بن حمد العصيمي", "منسق برامج تنموية", "dev", "employee", False, "haifa"),
    "shahd": ("شهد بنت محمد الفهيد", "منسقة تطوع", "vol", "employee", False, "yousef"),
    "omar": ("عمر بن خالد الصقير", "أخصائي موارد بشرية", "hr", "employee", False, "muneera"),
    "rahaf": ("رهف بنت علي الحمدان", "أخصائية جودة", "exc", "employee", False, "latifa"),
}

# (العنوان، الوحدة، المسؤول، المشاركون، الأولوية، المصدر، بدء، استحقاق، السيناريو، النسبة، إضافات)
TASKS = [
    ("تحديث الموقع الإلكتروني للجمعية", "tech", "ahmad", ["mohammed", "maha"], "important", "operational_plan", -30, 10, "progress", 60, {"project": "التحول الرقمي"}),
    ("أتمتة نموذج طلب المساعدة إلكترونيًا", "tech", "ahmad", [], "urgent", "ed_assignment", -25, -5, "progress", 45, {"project": "التحول الرقمي"}),
    ("ترقية أجهزة الحاسب في الاستقبال", "tech", "mohammed", [], "normal", "unit_request", -40, -20, "closed", 15, {}),
    ("صرف المساعدات الشهرية للأسر المستفيدة", "care", "amal", ["jawaher"], "critical", "operational_plan", -15, 2, "progress", 70, {}),
    ("دراسة حالات الأسر الجديدة – دفعة شوال", "care", "jawaher", [], "important", "internal_procedure", -20, -3, "stalled", 35,
     {"obstacle": ("missing_info", "لم تكتمل مستندات 14 أسرة (صكوك الإعالة وتعريف الراتب)", "الأسر المتقدمة", False, "sara")}),
    ("زيارات ميدانية للأسر الأشد احتياجًا", "care", "amal", [], "urgent", "operational_plan", -30, -12, "progress", 30, {}),
    ("إعداد الخطة الإعلامية لشهر رمضان", "comm", "maha", ["reem"], "important", "operational_plan", -10, 20, "progress", 25, {"project": "حملة رمضان"}),
    ("تصميم التقرير السنوي المرئي", "comm", "maha", [], "normal", "project", -35, -8, "closed", 30, {}),
    ("إطلاق حملة التبرع الإلكتروني", "comm", "reem", ["maha", "ahmad"], "critical", "ed_assignment", -5, 1, "pending", 100, {"project": "حملة رمضان"}),
    ("إعداد القوائم المالية الربعية", "fin", "abdulaziz", [], "urgent", "operational_plan", -20, 5, "progress", 80, {}),
    ("تسوية حسابات الموردين", "fin", "abdulaziz", [], "normal", "internal_procedure", -30, -10, "closed", 18, {}),
    ("اعتماد ميزانية البرامج للربع القادم", "fin", "sultan", [], "critical", "ed_assignment", -12, -2, "stalled", 60,
     {"obstacle": ("financial", "تجاوز تقديرات البرامج الميزانية المعتمدة بنسبة 12% ويحتاج قرارًا بإعادة التوزيع", "وحدة الشؤون المالية", True, "eda")}),
    ("تحديث سجلات المتطوعين في النظام", "vol", "shahd", [], "low", "internal_procedure", -25, 15, "stale", 20, {}),
    ("تنظيم يوم التطوع السنوي", "vol", "shahd", ["yousef"], "important", "project", -8, 25, "new", 0, {}),
    ("تحديث الهيكل الوظيفي والأوصاف الوظيفية", "hr", "omar", ["muneera"], "important", "ed_assignment", -20, 8, "waiting_reply", 50, {}),
    ("إجراءات التوظيف لوظيفة أخصائي اجتماعي", "hr", "omar", [], "urgent", "unit_request", -18, -1, "progress", 60, {}),
    ("تقييم الأداء نصف السنوي للموظفين", "hr", "muneera", ["omar"], "normal", "operational_plan", -45, -15, "closed", 25, {}),
    ("مراجعة إجراءات صرف المساعدات", "audit", "abdulrahman", [], "important", "internal_procedure", -14, 6, "progress", 40, {}),
    ("تقرير المراجعة الداخلية للربع الثالث", "audit", "abdulrahman", [], "normal", "operational_plan", -30, -6, "closed", 20, {}),
    ("دراسة جدوى مشروع وقف تجاري", "inv", "turki", ["sultan"], "important", "project", -20, 30, "waiting_external", 35, {"project": "تنمية الأوقاف"}),
    ("تجديد عقود الإيجار الاستثمارية", "inv", "turki", [], "urgent", "incoming_letter", -10, 3, "returned", 100, {}),
    ("تطبيق نموذج التميز المؤسسي", "exc", "rahaf", ["latifa"], "important", "project", -40, 40, "progress", 35, {"project": "التميز المؤسسي"}),
    ("قياس رضا المستفيدين", "exc", "rahaf", ["amal"], "normal", "operational_plan", -20, -4, "progress", 70, {}),
    ("صيانة مقر الجمعية الدورية", "sup", "bandar", [], "normal", "unit_request", -15, 12, "on_hold", 20, {}),
    ("تجهيز مستودع المساعدات العينية", "sup", "bandar", [], "urgent", "ed_assignment", -10, 0, "progress", 75, {}),
    ("برنامج تمكين الأسر المنتجة", "dev", "nayef", ["haifa"], "critical", "project", -20, 3, "progress", 55, {"project": "الأسر المنتجة"}),
    ("شراكة مع الغرفة التجارية للتدريب المهني", "dev", "haifa", ["nayef"], "important", "outgoing_letter", -30, -2, "stalled", 40,
     {"obstacle": ("external", "لم يصل رد الغرفة التجارية على مسودة الاتفاقية منذ أسبوعين", "الغرفة التجارية ببريدة", False, "eda")}),
    ("مبادرة السلال الغذائية", "comty", "majed", [], "important", "standalone", -25, -9, "closed", 20, {}),
    ("الرد على خطاب وزارة الموارد البشرية والتنمية الاجتماعية", "sec", "noura", [], "urgent", "incoming_letter", -3, 2, "progress", 30, {}),
    ("إعداد محاضر اجتماعات الإدارة التنفيذية", "sec", "noura", [], "normal", "internal_procedure", -20, 1, "stale", 40, {}),
    ("حصر احتياجات وحدة خدمة المجتمع", "comty", "majed", [], "low", "unit_request", -2, 14, "new", 0, {}),
    ("تطوير بوابة التبرعات", "tech", "fahad", ["ahmad"], "important", "project", -10, 20, "subtasks", 0, {"project": "التحول الرقمي"}),
]


def at(days):
    return timezone.make_aware(datetime.combine(timezone.localdate() + timedelta(days=days), time(10, 0)))


class Command(BaseCommand):
    help = "إدخال بيانات تجريبية واقعية بالعربية"

    def handle(self, *args, **opts):
        if Task.objects.exists():
            raise CommandError("توجد بيانات مسبقًا. لإعادة التهيئة احذف قاعدة البيانات ثم شغّل migrate ثم seed_demo.")
        with transaction.atomic():
            ensure_reference_data()
            self.today = timezone.localdate()
            self._org()
            self._tasks()
            self._decisions()
            self._comments()
        stats = run_engine()
        self.stdout.write(self.style.SUCCESS(
            f"تم إنشاء {Unit.objects.count()} وحدة، {Employee.objects.count()} موظف، {Task.objects.count()} مهمة. "
            f"محرك القواعد: {stats}"))
        self.stdout.write(f"الدخول: admin@{DOMAIN} / {DEMO_PASSWORD} (مسؤول النظام) – وبقية الحسابات بنفس كلمة المرور")

    # ===== الهيكل التنظيمي =====
    def _org(self):
        roles = {r.code: r for r in Role.objects.all()}
        self.units = {}
        for i, (key, name, desc) in enumerate(UNITS):
            self.units[key] = Unit.objects.create(name=name, code=key.upper(), description=desc, sort_order=i,
                                                  established_on=self.today - timedelta(days=900 - i * 20))
        User.objects.create_superuser(f"admin@{DOMAIN}", DEMO_PASSWORD, full_name="مسؤول النظام",
                                      phone="0500000000", role=roles["admin"])
        self.emp = {}
        self.users = {}
        for i, (key, (name, title, unit_key, role, is_head, _)) in enumerate(PEOPLE.items(), 1):
            user = User.objects.create_user(f"{key}@{DOMAIN}", DEMO_PASSWORD, full_name=name,
                                            phone=f"05000000{i:02d}", role=roles[role])
            emp = Employee.objects.create(user=user, employee_no=f"EH-{1000 + i}", full_name=name, job_title=title,
                                          join_date=self.today - timedelta(days=200 + i * 37))
            EmployeeUnit.objects.create(employee=emp, unit=self.units[unit_key], is_primary=True)
            if is_head:
                Unit.objects.filter(pk=self.units[unit_key].pk).update(head=emp)
            self.emp[key] = emp
            self.users[key] = user
        # المدير التنفيذي ومساعده مرتبطان بالسكرتارية أيضًا (موظف في أكثر من وحدة)
        EmployeeUnit.objects.create(employee=self.emp["eda"], unit=self.units["sec"], is_primary=False)
        for key, (_, _, _, _, _, manager) in PEOPLE.items():
            if manager:
                Employee.objects.filter(pk=self.emp[key].pk).update(manager=self.emp[manager])
        for k in self.units:
            self.units[k].refresh_from_db()
        for k in self.emp:
            self.emp[k].refresh_from_db()

    def approver(self, task):
        head = task.unit.head
        if head and head.pk != task.owner_id:
            return head.user
        return self.users["eda"]

    def _update(self, task, key, progress, comment, done):
        services.update_progress(task, user=self.users[key], progress=progress, comment=comment, done_work=done,
                                 remaining_work="استكمال بقية الأعمال" if progress < 100 else "")
        task.refresh_from_db()

    # ===== المهام =====
    def _tasks(self):
        types = list(TaskType.objects.all())
        ed = self.users["ed"]
        self.tasks = {}
        for i, (title, unit, owner, parts, prio, source, start, due, scenario, prog, extra) in enumerate(TASKS):
            creator = ed if prio in ("critical", "urgent") or source == "ed_assignment" else self.emp[owner].user
            if not creator.permission_codes or "tasks.create" not in creator.permission_codes:
                creator = self.units[unit].head.user if self.units[unit].head else ed
                if "tasks.create" not in creator.permission_codes:
                    creator = ed
            task = services.create_task(user=creator, data={
                "title": title,
                "description": f"{title} وفق الخطة المعتمدة، مع رفع التحديثات الدورية وتوثيق المخرجات في المنصة.",
                "source": source, "task_type": types[i % len(types)], "project": extra.get("project", ""),
                "unit": self.units[unit], "owner": self.emp[owner],
                "start_date": self.today + timedelta(days=start), "due_date": self.today + timedelta(days=due),
                "priority": prio, "expected_result": f"إنجاز «{title}» بجودة عالية وفي الموعد المحدد",
                "success_indicator": "اكتمال المخرجات واعتمادها من رئيس الوحدة",
                "auto_progress": scenario == "subtasks",
            }, participants=[self.emp[p] for p in parts])
            Task.objects.filter(pk=task.pk).update(created_at=at(start))
            self._play(task, owner, scenario, prog, start, due, extra)
            self.tasks[title] = task

    def _play(self, task, owner, scenario, prog, start, due, extra):
        if scenario == "new":
            return
        if scenario == "subtasks":
            ahmad, fahad = self.emp["ahmad"], self.users["fahad"]
            s1 = services.add_subtask(task, user=fahad, title="تحليل المتطلبات مع وحدة الاتصال", assignee=ahmad,
                                      due_date=self.today + timedelta(days=2))
            s2 = services.add_subtask(task, user=fahad, title="ربط بوابة الدفع الإلكتروني", assignee=ahmad,
                                      due_date=self.today + timedelta(days=12))
            services.add_subtask(task, user=fahad, title="اختبار البوابة وإطلاقها", assignee=self.emp["mohammed"],
                                 due_date=self.today + timedelta(days=18))
            services.update_subtask(s1, user=self.users["ahmad"], progress=100)
            services.update_subtask(s2, user=self.users["ahmad"], progress=40)
            return
        if scenario in ("closed", "pending", "returned"):
            self._update(task, owner, 50, "تم إنجاز نصف الأعمال", "إعداد المسودة الأولى ومراجعتها مع الفريق")
            self._update(task, owner, 100, "اكتمل التنفيذ", "تسليم المخرجات النهائية مع المرفقات")
            if scenario == "closed":
                services.approve(task, user=self.approver(task), notes="تم الاطلاع والاعتماد، شكرًا للجهود")
                done_at = at(start + prog)  # prog هنا = عدد أيام الإنجاز
                Task.objects.filter(pk=task.pk).update(completed_at=done_at, approved_at=done_at + timedelta(hours=5),
                                                       closed_at=done_at + timedelta(hours=5), last_activity_at=done_at)
            elif scenario == "returned":
                services.return_task(task, user=self.approver(task),
                                     notes="يرجى إرفاق نسخ العقود الموقعة وتحديث جدول الإيجارات قبل الاعتماد")
            return
        self._update(task, owner, prog, "تحديث دوري لسير العمل", "تنفيذ الأعمال المخطط لها لهذه المرحلة")
        if scenario == "stalled":
            ob_type, desc, cause, admin_decision, intervener = extra["obstacle"]
            ob = services.register_obstacle(task, user=self.users[owner], data={
                "obstacle_type": ob_type, "description": desc, "cause_party": cause,
                "needs_admin_decision": admin_decision, "required_action": "التوجيه واتخاذ الإجراء اللازم لاستكمال التنفيذ",
                "intervener": self.emp[intervener], "expected_resolution_date": self.today + timedelta(days=5),
                "impact": "high" if admin_decision else "medium",
            })
            if not admin_decision:
                responder = self.approver(task)
                services.respond_obstacle(ob, user=responder, response="تمت مخاطبة الجهة المعنية، نتابع معكم خلال يومين")
        elif scenario == "waiting_reply":
            services.transition(task, user=self.users[owner], to="waiting_reply", note="بانتظار رد الإدارة على المسودة")
        elif scenario == "waiting_external":
            services.transition(task, user=self.users[owner], to="waiting_external", note="بانتظار عروض المكاتب الاستشارية")
        elif scenario == "on_hold":
            services.transition(task, user=self.users["ed"], to="on_hold", note="إيقاف مؤقت لحين اعتماد ميزانية الصيانة")
        elif scenario == "stale":
            Task.objects.filter(pk=task.pk).update(last_activity_at=timezone.now() - timedelta(days=9))

    # ===== الاجتماعات والقرارات =====
    def _decisions(self):
        ed, eda = self.users["ed"], self.users["eda"]
        m1 = Meeting.objects.create(number="BM-2026-03", title="الاجتماع الدوري الثالث لمجلس الإدارة",
                                    committee="مجلس الإدارة", date=self.today - timedelta(days=40), location="قاعة المجلس", created_by=ed)
        m2 = Meeting.objects.create(number="EX-2026-09", title="اجتماع الإدارة التنفيذية الشهري",
                                    committee="اجتماع الإدارة التنفيذية", date=self.today - timedelta(days=12), created_by=ed)
        m3 = Meeting.objects.create(number="IC-2026-02", title="اجتماع لجنة الاستثمار",
                                    committee="لجنة الاستثمار", date=self.today - timedelta(days=5), created_by=ed)

        def decision(number, meeting, text, owner, days_ago, due):
            d = meeting_services.create_decision(user=ed, data={
                "number": number, "meeting": meeting, "text": text, "decision_date": self.today - timedelta(days=days_ago),
                "due_date": self.today + timedelta(days=due), "followup_owner": self.emp[owner]})
            return d

        d1 = decision("Q-2026-031", m1, "إطلاق برنامج تدريبي لتأهيل الأسر المستفيدة على الإدارة المالية الأسرية بالشراكة مع الجهات المختصة.", "eda", 40, 15)
        d2 = decision("Q-2026-032", m1, "اعتماد خطة التحول الرقمي للجمعية لعام 2026 والبدء في تنفيذ مرحلتها الأولى.", "fahad", 40, 30)
        d3 = decision("Q-2026-033", m1, "مراجعة لائحة الموارد البشرية وتحديثها بما يتوافق مع نظام العمل.", "muneera", 40, -3)
        d4 = decision("Q-2026-091", m2, "رفع عدد المتطوعين المسجلين بنسبة 20% خلال الربع القادم.", "yousef", 12, 60)
        decision("Q-2026-092", m2, "إعداد تقرير الأثر الاجتماعي السنوي ورفعه لمجلس الإدارة.", "latifa", 12, 25)
        decision("Q-2026-021", m3, "دراسة فرص استثمار الأوقاف في القطاع التجاري ورفع توصية للمجلس.", "turki", 5, 45)

        def item(title, unit, owner, parts, due, prio="normal"):
            return {"title": title, "unit": self.units[unit], "owner": self.emp[owner],
                    "participants": [self.emp[p] for p in parts], "due_date": self.today + timedelta(days=due), "priority": prio}

        t1 = meeting_services.convert_to_tasks(d1, user=eda, items=[
            item("إعداد المحتوى التدريبي للبرنامج", "dev", "nayef", ["haifa"], 10, "important"),
            item("إعداد ميزانية البرنامج التدريبي", "fin", "abdulaziz", [], 5, "important"),
            item("إعداد الإعلان والتسويق للبرنامج", "comm", "maha", [], 8),
            item("حجز القاعة وتجهيزها", "sup", "bandar", [], 12),
            item("تجهيز تقرير البرنامج التدريبي", "exc", "rahaf", [], 20),
        ])
        # تنفيذ جزء من مهام القرار الأول
        for t in t1[:2]:
            owner_key = next(k for k, e in self.emp.items() if e.pk == t.owner_id)
            self._update(t, owner_key, 100, "اكتمل", "تسليم المخرج النهائي")
            services.approve(t, user=self.approver(t), notes="معتمد")
        owner_key = next(k for k, e in self.emp.items() if e.pk == t1[2].owner_id)
        self._update(t1[2], owner_key, 60, "تصميم الإعلانات جاهز للمراجعة", "تصميم 3 نماذج إعلانية")

        t2 = meeting_services.convert_to_tasks(d2, user=eda, items=[
            item("إعداد وثيقة متطلبات المرحلة الأولى للتحول الرقمي", "tech", "fahad", ["ahmad"], 7, "urgent"),
            item("طرح منافسة توريد نظام إدارة علاقات المستفيدين", "tech", "mohammed", ["abdulaziz"], 25),
        ])
        self._update(t2[0], "fahad", 40, "جمع المتطلبات من الوحدات", "عقد ورش عمل مع 5 وحدات")
        t3 = meeting_services.convert_to_tasks(d3, user=eda, items=[
            item("تحديث لائحة الموارد البشرية", "hr", "muneera", ["omar"], 0, "urgent"),
        ])
        Task.objects.filter(pk=t3[0].pk).update(start_date=self.today - timedelta(days=35), due_date=self.today - timedelta(days=3))
        t3[0].refresh_from_db()
        self._update(t3[0], "muneera", 30, "مراجعة أولية للائحة", "مراجعة الفصول الأربعة الأولى")
        ob = services.register_obstacle(t3[0], user=self.users["muneera"], data={
            "obstacle_type": "admin_approval", "description": "بانتظار رأي المستشار القانوني في مواد الإجازات والعمل عن بعد",
            "cause_party": "المستشار القانوني", "needs_admin_decision": True, "required_action": "التوجيه بسرعة إنهاء المراجعة القانونية",
            "intervener": self.emp["ed"], "expected_resolution_date": self.today + timedelta(days=3), "impact": "high"})
        meeting_services.convert_to_tasks(d4, user=eda, items=[
            item("حملة استقطاب المتطوعين في الجامعات", "vol", "shahd", ["maha"], 30, "important"),
        ])

    # ===== التعليقات =====
    def _comments(self):
        def c(title, author, body, reply=None):
            task = Task.objects.get(title=title)
            parent = services.add_comment(task, user=self.users[author], body=body)
            if reply:
                services.add_comment(task, user=self.users[reply[0]], body=reply[1], parent=parent)

        c("تحديث الموقع الإلكتروني للجمعية", "fahad", "@[مها بنت عبدالله الدخيل] نحتاج المحتوى النصي للصفحات الجديدة قبل نهاية الأسبوع.",
          ("maha", "تم، سأرفع المحتوى يوم الأربعاء إن شاء الله."))
        c("صرف المساعدات الشهرية للأسر المستفيدة", "sara", "يرجى التأكد من تحديث بيانات الحسابات البنكية للأسر قبل الصرف. @[وحدة الشؤون المالية والإدارية]",
          ("amal", "تم تحديث 120 حسابًا، والمتبقي 8 حسابات قيد المراجعة."))
        c("اعتماد ميزانية البرامج للربع القادم", "eda", "سيتم عرض الموضوع على المدير التنفيذي في اجتماع الأحد.")
        c("إطلاق حملة التبرع الإلكتروني", "ed", "عمل مميز، نرجو مشاركة مؤشرات الحملة الأولية في التقرير.")
        c("أتمتة نموذج طلب المساعدة إلكترونيًا", "eda", "المهمة متأخرة، ما المتبقي وما الدعم المطلوب؟ @[أحمد بن سالم الجهني]",
          ("ahmad", "المتبقي ربط النموذج بقاعدة بيانات المستفيدين، نحتاج صلاحية الوصول من الشؤون المالية."))
