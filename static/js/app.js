/* منصة إدارة المهام – سلوكيات الواجهة */
(function () {
  "use strict";

  const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || "";

  // ===== القائمة الجانبية للجوال =====
  const sidebar = document.querySelector(".sidebar");
  const backdrop = document.querySelector(".sidebar-backdrop");
  document.querySelectorAll("[data-toggle-sidebar]").forEach((b) =>
    b.addEventListener("click", () => {
      sidebar?.classList.toggle("open");
      backdrop?.classList.toggle("show");
    })
  );
  backdrop?.addEventListener("click", () => {
    sidebar?.classList.remove("open");
    backdrop.classList.remove("show");
  });

  // ===== Tooltips =====
  document.querySelectorAll('[data-bs-toggle="tooltip"],[title][data-tip]').forEach((el) => new bootstrap.Tooltip(el));

  // ===== Toasts (من رسائل Django) =====
  document.querySelectorAll(".toast").forEach((t) => new bootstrap.Toast(t, { delay: 5000 }).show());
  window.showToast = function (message, tone = "success") {
    const box = document.querySelector(".toast-container");
    if (!box) return;
    const el = document.createElement("div");
    el.className = `toast align-items-center text-bg-${tone} border-0`;
    el.innerHTML = `<div class="d-flex"><div class="toast-body"></div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
    el.querySelector(".toast-body").textContent = message;
    box.appendChild(el);
    new bootstrap.Toast(el, { delay: 4000 }).show();
  };

  // ===== حالات التحميل عند إرسال النماذج =====
  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (form.dataset.noLoading !== undefined || e.defaultPrevented) return;
    const btn = form.querySelector('button[type="submit"]:not([data-no-spinner])');
    if (btn && !btn.disabled) {
      btn.dataset.originalHtml = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm ms-1"></span> جارٍ التنفيذ...';
    }
  });
  window.addEventListener("pageshow", () => {
    document.querySelectorAll("button[data-original-html]").forEach((b) => {
      b.disabled = false;
      b.innerHTML = b.dataset.originalHtml;
    });
  });

  // ===== نوافذ التأكيد =====
  const confirmModalEl = document.getElementById("confirmModal");
  if (confirmModalEl) {
    const modal = new bootstrap.Modal(confirmModalEl);
    let pending = null;
    document.addEventListener("click", (e) => {
      const trigger = e.target.closest("[data-confirm]");
      if (!trigger) return;
      if (trigger.dataset.confirmed) return;
      e.preventDefault();
      pending = trigger;
      confirmModalEl.querySelector(".confirm-text").textContent = trigger.dataset.confirm;
      const okBtn = confirmModalEl.querySelector(".confirm-ok");
      okBtn.className = "btn confirm-ok " + (trigger.dataset.confirmTone || "btn-brand");
      modal.show();
    });
    confirmModalEl.querySelector(".confirm-ok").addEventListener("click", () => {
      if (!pending) return;
      modal.hide();
      pending.dataset.confirmed = "1";
      if (pending.tagName === "A") window.location = pending.href;
      else if (pending.form) {
        if (pending.form.reportValidity && !pending.form.reportValidity()) { delete pending.dataset.confirmed; return; }
        pending.form.requestSubmit ? pending.form.requestSubmit(pending) : pending.form.submit();
      } else pending.click();
      setTimeout(() => pending && delete pending.dataset.confirmed, 500);
    });
  }

  // ===== قوائم الاختيار المتقدمة (Tom Select) =====
  if (window.TomSelect) {
    document.querySelectorAll("select[data-enhance]").forEach((el) => {
      new TomSelect(el, {
        plugins: el.multiple ? ["remove_button"] : [],
        maxOptions: 500,
        allowEmptyOption: true,
        placeholder: el.dataset.placeholder || "اختر...",
        render: { no_results: () => '<div class="no-results p-2">لا توجد نتائج</div>' },
      });
    });
  }

  // ===== شريط الإنجاز التفاعلي =====
  document.querySelectorAll("[data-progress-range]").forEach((range) => {
    const out = document.getElementById(range.dataset.progressRange);
    const sync = () => out && (out.textContent = range.value + "%");
    range.addEventListener("input", sync);
    sync();
  });
  document.querySelectorAll("[data-set-progress]").forEach((b) =>
    b.addEventListener("click", () => {
      const r = document.querySelector(b.dataset.target);
      r.value = b.dataset.setProgress;
      r.dispatchEvent(new Event("input"));
    })
  );

  // ===== الإشارة @ في التعليقات =====
  document.querySelectorAll("textarea[data-mentions]").forEach((ta) => {
    let pop = null, items = [], idx = 0, startPos = -1, timer = null;
    const close = () => { pop?.remove(); pop = null; startPos = -1; };
    const insert = (name) => {
      const before = ta.value.slice(0, startPos);
      const after = ta.value.slice(ta.selectionStart);
      ta.value = `${before}@[${name}] ${after}`;
      const pos = before.length + name.length + 4;
      ta.setSelectionRange(pos, pos);
      ta.focus();
      close();
    };
    const render = () => {
      if (!pop) {
        pop = document.createElement("div");
        pop.className = "mention-pop";
        ta.parentElement.style.position = "relative";
        ta.parentElement.appendChild(pop);
      }
      pop.style.top = ta.offsetTop + ta.offsetHeight + 4 + "px";
      pop.style.right = "0px";
      pop.innerHTML = "";
      if (!items.length) { pop.innerHTML = '<div class="p-2 text-muted small">لا توجد نتائج</div>'; return; }
      items.forEach((it, i) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = i === idx ? "active" : "";
        b.innerHTML = `<i class="bi ${it.type === "unit" ? "bi-diagram-3" : "bi-person"} ms-1"></i> `;
        b.append(document.createTextNode(it.name));
        if (it.sub) { const s = document.createElement("small"); s.className = "text-muted me-1"; s.textContent = "– " + it.sub; b.append(s); }
        b.addEventListener("mousedown", (e) => { e.preventDefault(); insert(it.name); });
        pop.appendChild(b);
      });
    };
    ta.addEventListener("input", () => {
      const caret = ta.selectionStart;
      const text = ta.value.slice(0, caret);
      const m = text.match(/@([^\s@\[\]]{0,30})$/);
      if (!m) return close();
      startPos = caret - m[0].length;
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const res = await fetch(`${ta.dataset.mentions}?q=${encodeURIComponent(m[1])}`, { headers: { "X-Requested-With": "fetch" } });
        items = res.ok ? await res.json() : [];
        idx = 0;
        render();
      }, 150);
    });
    ta.addEventListener("keydown", (e) => {
      if (!pop || !items.length) return;
      if (e.key === "ArrowDown") { idx = (idx + 1) % items.length; render(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { idx = (idx - 1 + items.length) % items.length; render(); e.preventDefault(); }
      else if (e.key === "Enter") { insert(items[idx].name); e.preventDefault(); }
      else if (e.key === "Escape") close();
    });
    ta.addEventListener("blur", () => setTimeout(close, 150));
  });

  // ===== الرد على تعليق =====
  document.querySelectorAll("[data-reply-to]").forEach((b) =>
    b.addEventListener("click", () => {
      const form = document.getElementById("commentForm");
      form.querySelector('[name="parent"]').value = b.dataset.replyTo;
      const box = document.getElementById("replyingTo");
      box.classList.remove("d-none");
      box.querySelector("span").textContent = b.dataset.replyName;
      form.querySelector("textarea").focus();
      form.scrollIntoView({ behavior: "smooth", block: "center" });
    })
  );
  document.querySelector("#replyingTo .btn-close")?.addEventListener("click", () => {
    document.querySelector('#commentForm [name="parent"]').value = "";
    document.getElementById("replyingTo").classList.add("d-none");
  });

  // ===== تمرير بيانات المهمة إلى النوافذ المنبثقة في الجداول =====
  document.querySelectorAll("[data-task-modal]").forEach((b) =>
    b.addEventListener("click", () => {
      const modal = document.querySelector(b.dataset.taskModal);
      modal.querySelector("form").action = b.dataset.action;
      modal.querySelectorAll("[data-fill-title]").forEach((el) => (el.textContent = b.dataset.title));
    })
  );

  // ===== صفوف المهام المتعددة (تحويل القرار) =====
  const rowsBox = document.getElementById("convertRows");
  if (rowsBox) {
    const tpl = document.getElementById("convertRowTpl");
    const total = document.getElementById("id_rows");
    const addRow = () => {
      const i = rowsBox.children.length;
      const html = tpl.innerHTML.replaceAll("__i__", i).replaceAll("__n__", i + 1);
      const wrap = document.createElement("div");
      wrap.innerHTML = html.trim();
      const row = wrap.firstElementChild;
      rowsBox.appendChild(row);
      total.value = rowsBox.children.length;
      if (window.TomSelect) row.querySelectorAll("select[data-enhance-row]").forEach((el) => new TomSelect(el, { plugins: el.multiple ? ["remove_button"] : [], placeholder: el.dataset.placeholder || "اختر..." }));
      row.querySelector("[data-remove-row]")?.addEventListener("click", () => {
        if (rowsBox.children.length > 1) { row.remove(); renumber(); }
      });
    };
    const renumber = () => {
      [...rowsBox.children].forEach((r, i) => (r.querySelector(".row-no").textContent = i + 1));
      total.value = rowsBox.children.length;
    };
    document.getElementById("addConvertRow").addEventListener("click", addRow);
    if (!rowsBox.children.length) addRow();
  }

  // ===== تحديث عدّاد التنبيهات دوريًا =====
  const bell = document.querySelector("[data-unread-url]");
  if (bell) {
    setInterval(async () => {
      try {
        const r = await fetch(bell.dataset.unreadUrl, { headers: { "X-Requested-With": "fetch" } });
        if (!r.ok) return;
        const data = await r.json();
        let dot = bell.querySelector(".dot");
        if (data.unread > 0) {
          if (!dot) { dot = document.createElement("span"); dot.className = "dot"; bell.appendChild(dot); }
          dot.textContent = data.unread > 99 ? "99+" : data.unread;
        } else dot?.remove();
      } catch (_) {}
    }, 60000);
  }

  window.appCsrf = csrf;
})();

/* ===== الرسوم البيانية ===== */
window.renderChart = function (canvasId, cfg) {
  const el = document.getElementById(canvasId);
  if (!el || !window.Chart) return;
  Chart.defaults.font.family = "Tajawal, Cairo, sans-serif";
  Chart.defaults.color = "#575650";
  const type = cfg.type || "bar";
  const datasets = (cfg.datasets || []).map((d) => ({
    label: d.label,
    data: d.data,
    backgroundColor: d.colors || d.color || "#cf6028",
    borderColor: type === "line" ? d.color : "#fff",
    borderWidth: type === "doughnut" ? 2 : 0,
    borderRadius: type === "bar" ? 6 : 0,
    maxBarThickness: 34,
    tension: 0.35,
    fill: type === "line" ? false : undefined,
  }));
  const isRound = type === "doughnut" || type === "pie";
  new Chart(el, {
    type,
    data: { labels: cfg.labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: cfg.horizontal ? "y" : "x",
      plugins: {
        legend: { display: datasets.length > 1 || isRound, position: "bottom", rtl: true, labels: { usePointStyle: true, boxWidth: 8 } },
        tooltip: { rtl: true, textDirection: "rtl" },
      },
      scales: isRound ? {} : {
        x: { stacked: !!cfg.stacked, grid: { display: false }, ticks: { autoSkip: false, maxRotation: 50 } },
        y: { stacked: !!cfg.stacked, beginAtZero: true, grid: { color: "#f1ebe5" }, ticks: { precision: 0 } },
      },
      cutout: type === "doughnut" ? "68%" : undefined,
    },
  });
};
