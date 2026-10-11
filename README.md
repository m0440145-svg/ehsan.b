# منصة إدارة المهام ومتابعة القرارات
### جمعية الإحسان للخدمات الاجتماعية ببريدة

نظام ويب مؤسسي لإدارة المهام والتكليفات، متابعة التنفيذ، اكتشاف المتأخر والمتعثر، ربط قرارات الاجتماعات بالمهام، ولوحات قيادة وتقارير.

```
اجتماع → قرار → مهمة → وحدة → موظف مسؤول → مشاركون → متابعة → تحديث → تعثر → معالجة → تصعيد → إنجاز → اعتماد → إغلاق → تقرير → مؤشر أداء
```

---

## 1. البنية (Architecture)

| الطبقة | التقنية |
|---|---|
| Backend | Django 5.1 + Django REST Framework |
| قاعدة البيانات | PostgreSQL (عبر `DATABASE_URL`) – SQLite للتطوير المحلي فقط |
| الواجهة | Django Templates + Bootstrap 5.3 RTL + Chart.js + Tom Select، خط Cairo/Tajawal |
| API | REST v1 على `/api/v1/` (جلسة + Token) |

**تقسيم وحدات النظام (Modular):**

```
apps/
├── core/           الإعدادات، RBAC، الوسيطات، القائمة، حماية الملفات، الأوامر (seed / backup / setup)
├── accounts/       المستخدمون، الأدوار، الصلاحيات، تسجيل الدخول، OTP، محاولات الدخول
├── organization/   الوحدات التنظيمية والموظفون (الموظف يرتبط بأكثر من وحدة)
├── tasks/          النماذج، سير العمل (workflow)، طبقة الخدمات (services)، محددات الوصول (selectors)،
│                   محرك القواعد والتصعيد (engine)، مركز المتابعة، API
├── meetings/       الاجتماعات، القرارات، تحويل القرار إلى مهام، نسبة تنفيذ القرار
├── notifications/  مركز التنبيهات + قنوات (داخل النظام / بريد / WhatsApp)
├── audit/          سجل تدقيق غير قابل للتعديل أو الحذف
├── reports/        مؤشرات الأداء (KPIs) و12 تقريرًا + التصدير
└── dashboard/      لوحات: الموظف، الوحدة، التنفيذية، مسؤول النظام
```

**مبادئ التصميم:**
- **طبقة خدمات (Service Layer):** كل منطق الأعمال في `apps/tasks/services.py` و`apps/meetings/services.py`؛ الواجهات وAPI تستدعي نفس الدوال، فلا تختلف القواعد بين الويب والتكامل.
- **محددات الوصول (Selectors):** `apps/tasks/selectors.py` هو المصدر الوحيد لـ "ما الذي يراه المستخدم" ولصلاحيات مستوى المهمة.
- **آلة حالات صارمة:** `apps/tasks/constants.py` (جدول `TRANSITIONS`) + `workflow.py`؛ أي انتقال خارج الجدول يُرفض ويُسجَّل كل انتقال.

## 2. التشغيل

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # ثم عدّل القيم (DATABASE_URL لـ PostgreSQL)
python manage.py migrate
python manage.py seed_demo      # بيانات تجريبية (أو setup_platform لبيئة نظيفة)
python manage.py runserver
```

**PostgreSQL:**
```sql
CREATE DATABASE ehsan_tasks; CREATE USER ehsan WITH PASSWORD '...'; GRANT ALL PRIVILEGES ON DATABASE ehsan_tasks TO ehsan;
```
ثم في `.env`: `DATABASE_URL=postgres://ehsan:...@localhost:5432/ehsan_tasks`

**بيئة نظيفة بلا بيانات تجريبية:**
```bash
python manage.py migrate
python manage.py setup_platform          # الصلاحيات والأدوار وقواعد التصعيد وأنواع المهام
python manage.py createsuperuser
```

### الحسابات التجريبية (بعد `seed_demo`)
كلمة المرور لجميع الحسابات: **`Ehsan@Demo2026`** (للتطوير المحلي فقط – غيّرها أو لا تستخدم seed في الإنتاج).

| الدور | البريد |
|---|---|
| مسؤول النظام | `admin@demo.ehsan.test` |
| المدير التنفيذي | `ed@demo.ehsan.test` |
| مساعد المدير التنفيذي | `eda@demo.ehsan.test` |
| رئيس وحدة (التقنية) | `fahad@demo.ehsan.test` (وكذلك sara, reem, sultan, muneera, ...) |
| موظف | `ahmad@demo.ehsan.test` (وكذلك amal, maha, omar, ...) |
| للعرض فقط | `chair@demo.ehsan.test` |

يمكن الدخول برقم الجوال أيضًا (مثال: `0500000017`).

## 3. الأدوار والصلاحيات (RBAC)

الأدوار: مسؤول النظام، المدير التنفيذي، مساعد المدير التنفيذي، رئيس الوحدة، موظف، مستخدم للعرض فقط.
صلاحيات كل دور قابلة للتعديل من **الإدارة ← الصلاحيات** (مصفوفة). نطاق البيانات:

| الدور | يرى | لوحة الدخول |
|---|---|---|
| موظف | مهامه فقط (مسؤول/مشارك/مهام فرعية) | لوحة الموظف |
| رئيس وحدة | مهام وحدته + ما شارك فيه | لوحة الوحدة |
| المدير التنفيذي / المساعد | جميع الوحدات (بما فيها السرية) | اللوحة التنفيذية |
| مسؤول النظام | الإدارة والإعدادات وكل شيء | لوحة مسؤول النظام |
| للعرض فقط | جميع المهام غير السرية، بلا أي تعديل | اللوحة التنفيذية |

## 4. سير عمل المهمة

```
جديدة → تم الإسناد → قيد التنفيذ ⇄ بانتظار رد / بانتظار جهة خارجية
                       │ تسجيل عائق → متعثرة → (معالجة) → قيد التنفيذ
                       │ تجاوز الاستحقاق (آلي) → متأخرة
                       └ 100% → بانتظار الاعتماد → اعتماد → مغلقة
                                               └ رفض/إعادة → معادة للتنفيذ
موقوفة / ملغاة: للمدير المخول فقط
```
الجدول الكامل في **الإعدادات ← حالات المهام**.

## 5. محرك القواعد والتصعيد

- قواعد المتابعة قابلة للتعديل (**الإعدادات ← قواعد المتابعة**): بحاجة متابعة (30%/0%)، مرشحة للتعثر (70%/<30%)، بدون تحديث (5 أيام)، التحويل الآلي إلى متأخرة، العائق يحوّل إلى متعثرة.
- قواعد التصعيد (**الإعدادات ← قواعد التصعيد**): الافتراضي −3 أيام تنبيه للموظف، يوم الاستحقاق للموظف ورئيس الوحدة، +1 رئيس الوحدة، +3 مساعد المدير، +7 المدير التنفيذي؛ والحرجة أسرع (+1 المساعد، +2 المدير). كل قاعدة تُطبق مرة واحدة لكل مهمة/موعد.
- يعمل المحرك تلقائيًا داخل التطبيق كل N دقيقة، ويُفضل جدولته في الإنتاج:
  ```bash
  python manage.py run_task_engine
  ```

## 6. الأمان المطبق

| البند | التطبيق |
|---|---|
| Authentication | بريد أو جوال + كلمة مرور، `EmailOrPhoneBackend` |
| تشفير كلمات المرور | PBKDF2-SHA256 (افتراضي Django) + سياسات قوة كلمة المرور |
| Rate limiting | حد لمحاولات الدخول لكل IP + throttling في API |
| قفل الحساب | بعد 5 محاولات فاشلة لمدة 15 دقيقة (قابل للضبط) |
| تسجيل محاولات الدخول | جدول `login_attempts` + `logs/security.log` |
| CSRF | مفعّل لكل النماذج وطلبات الجلسة في API |
| الجلسات | انتهاء بعد 8 ساعات خمول، HttpOnly، SameSite، تدوير المعرف عند الدخول |
| HTTPS | عند `DJANGO_DEBUG=False`: إعادة توجيه HTTPS، HSTS، ملفات تعريف آمنة |
| رفع الملفات | قائمة بيضاء، حد 20MB، فحص توقيع المحتوى، أسماء عشوائية، تخزين خارج المسار العام، تنزيل عبر عرض محمي بالصلاحيات |
| Audit Logs | `audit_logs` غير قابل للتعديل/الحذف (النموذج + مشغّل PostgreSQL) |
| OTP | جاهز للتفعيل (`OTP_ENABLED`) مع مزوّد قابل للاستبدال (حاليًا يكتب الرمز في السجل) |
| النسخ الاحتياطي | `python manage.py backup_data` (pg_dump + JSON + المرفقات، مع الاحتفاظ بآخر 14 نسخة) |

## 7. REST API

```
POST /api/v1/auth/token/                  {identifier, password} → token
GET  /api/v1/tasks/?scope=mine|unit&status=&priority=&unit=&followup=overdue&search=
POST /api/v1/tasks/                       إنشاء مهمة (owner, participants, participant_units ...)
POST /api/v1/tasks/{id}/progress/         {progress, comment, done_work, remaining_work}
GET|POST /api/v1/tasks/{id}/comments/ | obstacles/ | subtasks/ | attachments/
POST /api/v1/tasks/{id}/obstacles/{oid}/respond/
POST /api/v1/tasks/{id}/approve/ | reject/ | return/ | transition/ | escalate/
GET  /api/v1/tasks/{id}/activity/
GET|POST /api/v1/meetings/  /api/v1/decisions/   POST /api/v1/decisions/{id}/convert/
GET  /api/v1/dashboard/kpis/   /api/v1/reports/{key}/   /api/v1/notifications/
```
الترويسة: `Authorization: Token <token>`.

## 8. الربط المستقبلي

| النظام | نقطة الربط الجاهزة |
|---|---|
| منصة الاجتماعات | `Meeting.external_ref` + `POST /api/v1/meetings/`, `/decisions/`, `/decisions/{id}/convert/` |
| الصادر والوارد | مصدر المهمة «مراسلة واردة/صادرة» + `Task.source_reference` + API إنشاء المهام |
| البريد الإلكتروني | `EmailChannel` في `notifications/services.py` (فعّل `EMAIL_NOTIFICATIONS_ENABLED` و SMTP) |
| WhatsApp API | `WhatsAppChannel` (POST عام لـ `WHATSAPP_API_URL`) – يحتاج مواءمة صيغة الطلب مع مزوّد الخدمة |
| Google Calendar / Teams / Drive / التوقيع الإلكتروني / الموارد البشرية / مؤشرات الأداء | عبر REST API + Token، وإضافة قناة تنبيه جديدة بنفس نمط القنوات الحالية |

## 9. الاختبارات

```bash
python manage.py test tests
```
29 اختبارًا تشمل:
- `test_scenario.py`: السيناريو الإلزامي كاملًا عبر واجهات الويب (16 خطوة من الإنشاء حتى الإغلاق وظهوره في اللوحات والتقارير وسجل النشاط).
- `test_decisions.py`: اجتماع ← قرار ← تحويل لعدة مهام ← تنفيذ ← اعتماد ← تحديث نسبة تنفيذ القرار حتى 100%.
- `test_permissions.py`: نطاق البيانات لكل دور، منع الوصول للصفحات، السرية، الاعتماد الذاتي.
- `test_engine_security.py`: سير العمل، المهام الفرعية، محرك القواعد والتصعيد (دون تكرار)، الدخول بالجوال، القفل، CSRF، الملفات، عدم قابلية تعديل السجل، API بالـ Token.

## 10. ملاحظات وحدود حالية

- **PDF:** يُنتج عبر نسخة طباعة مهيأة تفتح نافذة الطباعة تلقائيًا («حفظ كـ PDF»)، وليس عبر مولّد PDF على الخادم.
- **PostgreSQL:** الكود والترحيلات مهيأة له (بما فيها مشغّل حماية السجل)، لكن الاختبارات في بيئة التطوير الحالية جرت على SQLite لعدم توفر PostgreSQL على الجهاز. يجب تشغيل `migrate` و`test` على PostgreSQL قبل الإطلاق.
- **التخزين المؤقت:** Rate limiting يستخدم ذاكرة العملية؛ في الإنتاج متعدد العمليات استخدم Redis (`CACHE_BACKEND`).
- **ملفات الواجهة:** Bootstrap وChart.js والخطوط تُحمَّل من CDN؛ لبيئة بلا إنترنت انسخها إلى `static/`.
- **قنوات البريد وWhatsApp وOTP:** البنية جاهزة لكنها معطلة حتى ضبط مزودي الخدمة.
- **الإنتاج:** استخدم `gunicorn`/`waitress` خلف Nginx مع HTTPS، و`DJANGO_DEBUG=False`، و`collectstatic`، وجدولة `run_task_engine` و`backup_data`.

توثيق الجداول والعلاقات والفهارس: [docs/database_schema.md](docs/database_schema.md)
