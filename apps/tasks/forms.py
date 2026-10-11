from django import forms
from django.utils import timezone

from apps.core.forms import BootstrapMixin, DateInput, MultiFileField
from apps.organization.models import Employee, Unit

from .constants import Priority, Source, Status, SubtaskStatus
from .models import EscalationRule, Task, TaskObstacle, TaskType


def active_employees():
    return Employee.objects.filter(status__in=[Employee.Status.ACTIVE, Employee.Status.LEAVE]).order_by("full_name")


def active_units():
    return Unit.objects.filter(is_active=True)


class EmployeeChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.full_name} – {obj.job_title}" if obj.job_title else obj.full_name


class EmployeeMultipleField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.full_name} – {obj.job_title}" if obj.job_title else obj.full_name


class TaskForm(BootstrapMixin, forms.ModelForm):
    owner = EmployeeChoiceField(
        label="الموظف المسؤول الرئيسي", queryset=Employee.objects.none(), required=False,
        help_text="عند تركه فارغًا تُسند المهمة للوحدة كاملة ويكون رئيسها هو المسؤول الرئيسي",
    )
    participants = EmployeeMultipleField(label="الموظفون المشاركون", queryset=Employee.objects.none(), required=False)
    participant_units = forms.ModelMultipleChoiceField(label="الوحدات المشاركة", queryset=Unit.objects.none(), required=False)
    attachments = MultiFileField(label="مرفقات", help_text="PDF, Word, Excel, صور – بحد أقصى 20 ميجابايت للملف")

    class Meta:
        model = Task
        fields = [
            "title", "description", "source", "source_reference", "task_type", "project", "unit",
            "start_date", "due_date", "priority", "confidentiality", "progress", "expected_result",
            "success_indicator", "notes", "requires_approval", "auto_progress",
        ]
        widgets = {
            "start_date": DateInput(), "due_date": DateInput(),
            "description": forms.Textarea(attrs={"rows": 4}),
            "expected_result": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 2}),
            "progress": forms.NumberInput(attrs={"min": 0, "max": 100, "step": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        emps = active_employees()
        self.fields["owner"].queryset = emps
        self.fields["participants"].queryset = emps
        self.fields["unit"].queryset = active_units()
        self.fields["participant_units"].queryset = active_units()
        self.fields["task_type"].queryset = TaskType.objects.filter(is_active=True)
        self.fields["description"].required = True
        for name in ("owner", "participants", "participant_units", "unit", "task_type"):
            self.fields[name].widget.attrs["data-enhance"] = "1"
        self.fields["participants"].widget.attrs["data-placeholder"] = "اختر موظفًا أو أكثر"
        self.fields["participant_units"].widget.attrs["data-placeholder"] = "اختر وحدة أو أكثر"
        if self.instance.pk:
            self.fields.pop("progress")
            self.fields.pop("attachments")
            self.fields["owner"].initial = self.instance.owner_id
            self.fields["participants"].initial = [e.pk for e in self.instance.participants]
            self.fields["participant_units"].initial = [u.pk for u in self.instance.participant_units]
        else:
            from apps.core.settings_service import get_rules

            self.fields["requires_approval"].initial = get_rules().get("require_approval", True)
            self.fields["start_date"].initial = timezone.localdate()

    def clean(self):
        data = super().clean()
        if data.get("participants") and not data.get("owner"):
            self.add_error("owner", "يجب تحديد مسؤول رئيسي واحد عند إسناد المهمة لأكثر من موظف")
        start, due = data.get("start_date"), data.get("due_date")
        if start and due and due < start:
            self.add_error("due_date", "تاريخ الاستحقاق يجب أن يكون بعد تاريخ البدء")
        if not self.instance.pk and due and due < timezone.localdate():
            self.add_error("due_date", "لا يمكن أن يكون تاريخ الاستحقاق في الماضي")
        unit = data.get("unit")
        if unit and not data.get("owner") and not unit.head_id:
            self.add_error("owner", "الوحدة المختارة ليس لها رئيس؛ حدد المسؤول الرئيسي")
        return data

    def service_data(self):
        skip = {"owner", "participants", "participant_units", "attachments"}
        return {k: v for k, v in self.cleaned_data.items() if k not in skip}


class ProgressForm(BootstrapMixin, forms.Form):
    progress = forms.IntegerField(label="نسبة الإنجاز", min_value=0, max_value=100,
                                  widget=forms.NumberInput(attrs={"type": "range", "class": "form-range", "step": 5}))
    comment = forms.CharField(label="تعليق التحديث", widget=forms.Textarea(attrs={"rows": 2}))
    done_work = forms.CharField(label="الأعمال المنجزة", widget=forms.Textarea(attrs={"rows": 2}))
    remaining_work = forms.CharField(label="الأعمال المتبقية", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    update_date = forms.DateField(label="تاريخ التحديث", widget=DateInput(), initial=timezone.localdate)
    attachments = MultiFileField(label="إرفاق ملفات")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["progress"].widget.attrs["class"] = "form-range"


class CommentForm(BootstrapMixin, forms.Form):
    body = forms.CharField(label="التعليق", required=False, widget=forms.Textarea(attrs={
        "rows": 3, "placeholder": "اكتب تعليقك... استخدم @ للإشارة إلى موظف أو وحدة"}))
    parent = forms.IntegerField(required=False, widget=forms.HiddenInput)
    attachments = MultiFileField(label="ملفات (صورة، PDF، Word، Excel)")


class ObstacleForm(BootstrapMixin, forms.ModelForm):
    attachments = MultiFileField(label="مرفقات داعمة")

    class Meta:
        model = TaskObstacle
        fields = ["obstacle_type", "description", "cause_party", "needs_admin_decision", "required_action",
                  "intervener", "expected_resolution_date", "impact"]
        widgets = {"expected_resolution_date": DateInput(), "description": forms.Textarea(attrs={"rows": 3}),
                   "required_action": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["intervener"].queryset = active_employees()
        self.fields["intervener"].label = "الشخص المطلوب منه التدخل"


class ObstacleResponseForm(BootstrapMixin, forms.Form):
    response = forms.CharField(label="الرد / التوجيه", widget=forms.Textarea(attrs={"rows": 3}))
    resolve = forms.BooleanField(label="تمت معالجة العائق", required=False)


class NotesForm(BootstrapMixin, forms.Form):
    notes = forms.CharField(label="الملاحظات", required=False, widget=forms.Textarea(attrs={"rows": 3}))


class EscalateForm(BootstrapMixin, forms.Form):
    LEVELS = [("", "المستوى التالي تلقائيًا"), ("1", "رئيس الوحدة"), ("2", "مساعد المدير التنفيذي"), ("3", "المدير التنفيذي")]
    level = forms.ChoiceField(label="التصعيد إلى", choices=LEVELS, required=False)
    reason = forms.CharField(label="سبب التصعيد", widget=forms.Textarea(attrs={"rows": 3}))


class TransitionForm(BootstrapMixin, forms.Form):
    to = forms.ChoiceField(label="الحالة الجديدة", choices=[])
    note = forms.CharField(label="ملاحظة", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, targets=(), **kwargs):
        super().__init__(*args, **kwargs)
        labels = dict(Status.choices)
        self.fields["to"].choices = [(s, labels[s]) for s in targets]


class SubtaskForm(BootstrapMixin, forms.Form):
    title = forms.CharField(label="عنوان المهمة الفرعية", max_length=250)
    assignee = EmployeeChoiceField(label="المسؤول", queryset=Employee.objects.none(), required=False)
    due_date = forms.DateField(label="الموعد النهائي", required=False, widget=DateInput())
    comment = forms.CharField(label="تعليق", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignee"].queryset = active_employees()


class SubtaskUpdateForm(BootstrapMixin, forms.Form):
    status = forms.ChoiceField(label="الحالة", choices=SubtaskStatus.choices)
    progress = forms.IntegerField(label="النسبة", min_value=0, max_value=100)
    comment = forms.CharField(label="تعليق", required=False)
    attachments = MultiFileField(label="مرفقات")


class TaskFilterForm(BootstrapMixin, forms.Form):
    FLAGS = [("", "كل المؤشرات"), ("late", "متأخرة"), ("followup", "بحاجة متابعة"), ("at_risk", "مرشحة للتعثر"),
             ("stale", "بدون تحديث"), ("escalated", "مصعدة")]
    q = forms.CharField(label="بحث", required=False, widget=forms.TextInput(attrs={"placeholder": "رقم المهمة، العنوان، الوصف، القرار، الاجتماع..."}))
    unit = forms.ModelChoiceField(label="الوحدة", queryset=Unit.objects.all(), required=False, empty_label="كل الوحدات")
    employee = EmployeeChoiceField(label="الموظف", queryset=Employee.objects.all(), required=False, empty_label="كل الموظفين")
    status = forms.ChoiceField(label="الحالة", choices=[("", "كل الحالات"), ("open", "المفتوحة")] + list(Status.choices), required=False)
    priority = forms.ChoiceField(label="الأولوية", choices=[("", "كل الأولويات")] + list(Priority.choices), required=False)
    source = forms.ChoiceField(label="المصدر", choices=[("", "كل المصادر")] + list(Source.choices), required=False)
    date_from = forms.DateField(label="الاستحقاق من", required=False, widget=DateInput())
    date_to = forms.DateField(label="إلى", required=False, widget=DateInput())
    progress_min = forms.IntegerField(label="الإنجاز من %", required=False, min_value=0, max_value=100)
    progress_max = forms.IntegerField(label="إلى %", required=False, min_value=0, max_value=100)
    flag = forms.ChoiceField(label="المؤشر", choices=FLAGS, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = Employee.objects.order_by("full_name")


class TaskTypeForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = TaskType
        fields = ["name", "description", "is_active"]


class EscalationRuleForm(BootstrapMixin, forms.ModelForm):
    from .constants import EscalationTarget

    targets = forms.MultipleChoiceField(label="المستهدفون", choices=EscalationTarget.choices, widget=forms.CheckboxSelectMultiple)
    priorities = forms.MultipleChoiceField(label="الأولويات المشمولة (فارغ = الكل)", choices=Priority.choices,
                                           widget=forms.CheckboxSelectMultiple, required=False)

    class Meta:
        model = EscalationRule
        fields = ["name", "trigger", "days", "action", "level", "targets", "priorities", "is_active", "sort_order"]
