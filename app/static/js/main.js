// ==================================================
// main.js -- perilaku halaman, bukan tampilan.
//
// Ditulis ulang 2026-09-29 bersama CSS baru (app/static/css/app/). Tampilan
// sepenuhnya urusan CSS dan template; skrip ini TIDAK menulis ulang markup
// dan tidak memindahkan tombol. Dropdown, kalender, dan grafik ada di
// controls.js (Tom Select, Flatpickr, ApexCharts dari app/static/vendor).
// Isinya hanya perilaku:
//   1. sidebar (laci di layar kecil, satu grup terbuka);
//   2. dialog konfirmasi + notifikasi modal tengah (window.appConfirm / window.appNotify / window.appToast);
//   3. aksi deklaratif data-app-* (confirm, print, back, call, navigate);
//   4. cegah kirim ganda + tanda sedang memproses;
//   5. tabel: bungkus agar bisa digeser, kolom angka rata kanan (judul ikut);
//   6. lihat/sembunyikan kata sandi;
//   7. pengendali form: uang muka, biaya transport, transaksi terpadu, pratinjau
//      akun COA, pratinjau pesanan portal.
// ==================================================

// --- 1. Sidebar ------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", function () {
    const sidebar = document.getElementById("appSidebar");
    const toggle = document.getElementById("sidebarToggle");
    const backdrop = document.getElementById("sidebarBackdrop");
    const offcanvas = window.matchMedia("(max-width: 1023.98px)");
    if (!sidebar || !toggle) return;

    function setOpen(isOpen) {
        sidebar.classList.toggle("is-open", isOpen);
        document.body.classList.toggle("sidebar-open", isOpen);
        if (backdrop) backdrop.classList.toggle("is-visible", isOpen);
        toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
        toggle.setAttribute("aria-label", isOpen ? "Tutup menu navigasi" : "Buka menu navigasi");
        if (isOpen && offcanvas.matches) {
            setTimeout(function () { sidebar.focus({ preventScroll: true }); }, 10);
        }
    }

    toggle.addEventListener("click", function (event) {
        event.preventDefault();
        setOpen(!sidebar.classList.contains("is-open"));
    });
    document.querySelectorAll("[data-sidebar-close]").forEach(function (button) {
        button.addEventListener("click", function (event) {
            event.preventDefault();
            setOpen(false);
            toggle.focus();
        });
    });
    if (backdrop) backdrop.addEventListener("click", function () { setOpen(false); });
    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && sidebar.classList.contains("is-open")) {
            setOpen(false);
            toggle.focus();
        }
    });
    sidebar.querySelectorAll("a.sidebar-link").forEach(function (link) {
        link.addEventListener("click", function () { if (offcanvas.matches) setOpen(false); });
    });
    offcanvas.addEventListener("change", function () { if (!offcanvas.matches) setOpen(false); });

    // Satu grup menu terbuka pada satu waktu.
    const groups = sidebar.querySelectorAll("details.sidebar-group");
    groups.forEach(function (group) {
        group.addEventListener("toggle", function () {
            if (group.open) {
                groups.forEach(function (other) { if (other !== group) other.open = false; });
            }
        });
    });

    // Menu aktif terlihat walau grupnya jauh di bawah.
    const active = sidebar.querySelector(".sidebar-link.active");
    if (active && active.scrollIntoView) {
        const box = active.getBoundingClientRect();
        if (box.bottom > window.innerHeight) active.scrollIntoView({ block: "center" });
    }
});

// --- 2. Dialog konfirmasi dan toast --------------------------------------------------
(function () {
    function escapeHtml(text) {
        return String(text || "").replace(/[&<>"']/g, function (char) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
        });
    }

    window.appConfirm = function (message, options) {
        options = options || {};
        return new Promise(function (resolve) {
            if (typeof HTMLDialogElement !== "function") {
                resolve(window.confirm(message));
                return;
            }
            const dialog = document.createElement("dialog");
            dialog.className = "app-confirm-dialog";
            dialog.setAttribute("aria-labelledby", "appConfirmTitle");
            dialog.innerHTML =
                '<form method="dialog">' +
                '<div class="app-confirm-body">' +
                '<span class="app-confirm-icon" aria-hidden="true"><i class="bi bi-question-lg"></i></span>' +
                '<div><div class="app-confirm-title" id="appConfirmTitle">' + escapeHtml(options.title || "Konfirmasi") + "</div>" +
                '<p class="app-confirm-message">' + escapeHtml(message) + "</p></div>" +
                "</div>" +
                '<div class="app-confirm-actions">' +
                '<button type="submit" value="cancel" class="btn app-btn-secondary">' + escapeHtml(options.cancelLabel || "Batal") + "</button>" +
                '<button type="submit" value="ok" class="btn app-btn-primary">' + escapeHtml(options.okLabel || "Ya, lanjutkan") + "</button>" +
                "</div></form>";
            document.body.appendChild(dialog);
            dialog.addEventListener("close", function () {
                const confirmed = dialog.returnValue === "ok";
                dialog.remove();
                if (options.returnFocus && options.returnFocus.focus) options.returnFocus.focus();
                resolve(confirmed);
            });
            dialog.showModal();
            const okButton = dialog.querySelector('button[value="ok"]');
            if (okButton) okButton.focus();
        });
    };

    window.appNotify = function (message, tone, options) {
        options = options || {};
        let normTone = (tone || "info").toLowerCase();
        if (normTone === "error") normTone = "danger";
        if (normTone !== "success" && normTone !== "danger" && normTone !== "warning" && normTone !== "info") {
            normTone = "info";
        }

        const titles = {
            success: "Berhasil",
            danger: "Gagal",
            warning: "Perhatian",
            info: "Informasi"
        };
        const titleText = options.title || titles[normTone] || "Informasi";

        const iconSvgs = {
            success: '<svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>',
            danger: '<svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>',
            warning: '<svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
            info: '<svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>'
        };

        if (!document.querySelector('link[href*="flash_dialog.css"]')) {
            const link = document.createElement("link");
            link.rel = "stylesheet";
            link.href = "/static/css/flash_dialog.css";
            document.head.appendChild(link);
        }

        let dialog = document.getElementById("appFlashDialog");
        if (!dialog) {
            dialog = document.createElement("dialog");
            dialog.id = "appFlashDialog";
            dialog.className = "app-flash-dialog";
            dialog.setAttribute("role", "alertdialog");
            dialog.setAttribute("aria-modal", "true");
            dialog.setAttribute("aria-labelledby", "appFlashDialogTitle");
            dialog.innerHTML = `
                <div class="app-flash-dialog-header">
                    <div class="app-flash-dialog-icon is-${normTone}">
                        ${iconSvgs[normTone]}
                    </div>
                    <h2 id="appFlashDialogTitle" class="app-flash-dialog-title">${titleText}</h2>
                </div>
                <div class="app-flash-dialog-body" role="status" aria-live="polite">
                    <div class="alert alert-${normTone} app-flash-item" role="alert"></div>
                </div>
                <form method="dialog" class="app-flash-dialog-form">
                    <button type="submit" id="appFlashDialogBtn" class="app-flash-dialog-btn" autofocus>Mengerti</button>
                </form>
            `;
            dialog.querySelector(".alert").textContent = message || "";
            document.body.appendChild(dialog);

            dialog.addEventListener("cancel", function (e) {
                e.preventDefault();
            });
            dialog.addEventListener("close", function () {
                document.body.classList.remove("flash-dialog-open");
            });
        } else {
            const iconEl = dialog.querySelector(".app-flash-dialog-icon");
            if (iconEl) {
                iconEl.className = "app-flash-dialog-icon is-" + normTone;
                iconEl.innerHTML = iconSvgs[normTone];
            }
            const titleEl = document.getElementById("appFlashDialogTitle");
            if (titleEl) {
                titleEl.textContent = titleText;
            }
            const bodyEl = dialog.querySelector(".app-flash-dialog-body");
            if (bodyEl) {
                bodyEl.innerHTML = "";
                const item = document.createElement("div");
                item.className = "alert alert-" + normTone + " app-flash-item";
                item.setAttribute("role", "alert");
                item.textContent = message || "";
                bodyEl.appendChild(item);
            }
            if (!dialog.querySelector(".app-flash-dialog-form")) {
                const form = document.createElement("form");
                form.method = "dialog";
                form.className = "app-flash-dialog-form";
                form.innerHTML = '<button type="submit" id="appFlashDialogBtn" class="app-flash-dialog-btn" autofocus>Mengerti</button>';
                dialog.appendChild(form);
            }
        }

        try {
            if (!dialog.open && typeof dialog.showModal === "function") {
                dialog.showModal();
            }
            document.body.classList.add("flash-dialog-open");
        } catch (err) {
            console.error("Gagal membuka dialog:", err);
        }

        const btn = dialog.querySelector("#appFlashDialogBtn") || dialog.querySelector('button[type="submit"]');
        if (btn) {
            setTimeout(function () {
                btn.focus();
            }, 10);
        }
    };

    window.appToast = window.appNotify;
})();

// --- 3. Aksi deklaratif data-app-* -------------------------------------------------------
document.addEventListener("DOMContentLoaded", function () {
    const bypass = new WeakMap();

    function cleanText(value) {
        return String(value || "").replace(/\s+/g, " ").trim();
    }
    function isDisabled(element) {
        return !!(element && (element.disabled || element.getAttribute("aria-disabled") === "true" || element.classList.contains("disabled")));
    }
    function setBypass(element) {
        if (element && element.nodeType === 1) bypass.set(element, Date.now() + 2500);
    }
    function hasBypass(element) {
        if (!element || element.nodeType !== 1) return false;
        if ((bypass.get(element) || 0) > Date.now()) return true;
        bypass.delete(element);
        return false;
    }
    function confirmAction(message, returnFocus) {
        return window.appConfirm(cleanText(message) || "Lanjutkan aksi ini?", { returnFocus: returnFocus });
    }
    function submitAfterConfirm(form, submitter) {
        setBypass(form);
        if (submitter) setBypass(submitter);
        setTimeout(function () {
            if (typeof form.requestSubmit === "function") {
                if (submitter && submitter.form === form) form.requestSubmit(submitter);
                else form.requestSubmit();
            } else {
                form.submit();
            }
        }, 10);
    }
    function parseArg(raw, element) {
        const value = cleanText(raw);
        if (!value) return undefined;
        if (value === "this") return element;
        if (value === "true") return true;
        if (value === "false") return false;
        if (/^-?\d+(?:\.\d+)?$/.test(value)) return Number(value);
        return document.getElementById(value) || value;
    }
    function callNamed(element, names) {
        String(names || "").split(",").map(cleanText).filter(Boolean).forEach(function (name, index) {
            const fn = window[name];
            if (typeof fn !== "function") {
                window.appToast("Aksi halaman tidak ditemukan: " + name, "danger");
                return;
            }
            let args = [];
            if (element.getAttribute("data-app-call-arg") === "this" && index === 0) args = [element];
            else if (element.getAttribute("data-app-call-args")) args = [parseArg(element.getAttribute("data-app-call-args"), element)];
            try {
                fn.apply(element, args);
            } catch (error) {
                console.error("Aksi halaman gagal", name, error);
                window.appToast("Aksi gagal dijalankan.", "danger");
            }
        });
    }

    document.addEventListener("click", function (event) {
        const target = event.target.closest && event.target.closest("[data-app-action], [data-app-call], [data-app-confirm], [data-app-temp-label]");
        if (!target || isDisabled(target)) return;

        if (target.hasAttribute("data-app-temp-label")) {
            target.dataset.originalText = target.dataset.originalText || cleanText(target.textContent);
            target.textContent = target.getAttribute("data-app-temp-label") || "Memproses...";
            setTimeout(function () { target.textContent = target.dataset.originalText; }, 1800);
        }

        const action = target.getAttribute("data-app-action");
        if (action === "print" || action === "back" || action === "close") {
            event.preventDefault();
            event.stopImmediatePropagation();
            if (action === "print") window.print();
            else if (action === "back") window.history.back();
            else window.close();
            return;
        }
        if (target.hasAttribute("data-app-call")) {
            event.preventDefault();
            event.stopImmediatePropagation();
            callNamed(target, target.getAttribute("data-app-call"));
            return;
        }

        const message = target.getAttribute("data-app-confirm");
        const form = target.form || target.closest("form");
        const isSubmitter = !!(form && target.matches('button[type="submit"], input[type="submit"], button:not([type])'));
        if (message && isSubmitter && !hasBypass(target) && !hasBypass(form)) {
            event.preventDefault();
            event.stopImmediatePropagation();
            confirmAction(message, target).then(function (confirmed) {
                if (confirmed) submitAfterConfirm(form, target);
            });
        }
    }, true);

    document.addEventListener("submit", function (event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        const submitter = event.submitter || document.activeElement;
        const message = (submitter && submitter.getAttribute && submitter.getAttribute("data-app-confirm")) || form.getAttribute("data-app-confirm");
        if (!message || hasBypass(form) || hasBypass(submitter)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        confirmAction(message, submitter || form).then(function (confirmed) {
            if (confirmed) submitAfterConfirm(form, submitter && submitter.form === form ? submitter : null);
        });
    }, true);

    document.addEventListener("change", function (event) {
        const element = event.target;
        if (!element || element.nodeType !== 1) return;
        if (element.hasAttribute("data-app-select-navigate")) {
            const value = cleanText(element.value);
            if (!value) return;
            const url = new URL(element.getAttribute("data-app-select-navigate") || window.location.pathname, window.location.href);
            url.searchParams.set(element.getAttribute("data-app-select-param") || "value", value);
            window.location.href = url.toString();
            return;
        }
        if (element.hasAttribute("data-app-change-call")) callNamed(element, element.getAttribute("data-app-change-call"));
    });

    document.addEventListener("input", function (event) {
        const element = event.target;
        if (element && element.nodeType === 1 && element.hasAttribute("data-app-input-call")) {
            callNamed(element, element.getAttribute("data-app-input-call"));
        }
    });
});

// --- 4. Cegah kirim ganda --------------------------------------------------------------
document.addEventListener("DOMContentLoaded", function () {
    const submitted = new WeakSet();

    function skip(form) {
        if (form.closest("[data-no-action-loading], [data-action-loading='off']")) return true;
        const method = String(form.getAttribute("method") || "get").toLowerCase();
        return method === "dialog" || method === "get" || String(form.getAttribute("target") || "").toLowerCase() === "_blank";
    }

    function loadingLabel(submitter) {
        if (!submitter) return "Memproses...";
        const explicit = submitter.getAttribute("data-loading-text") || submitter.getAttribute("data-submit-loading");
        if (explicit) return explicit;
        const text = String(submitter.textContent || submitter.value || "").toLowerCase();
        if (/simpan|ubah|update/.test(text)) return "Menyimpan...";
        if (/bayar|lunas|cicilan/.test(text)) return "Mencatat pembayaran...";
        if (/masuk|login/.test(text)) return "Masuk...";
        return "Memproses...";
    }

    document.addEventListener("submit", function (event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || skip(form)) return;
        if (submitted.has(form)) {
            event.preventDefault();
            event.stopImmediatePropagation();
            window.appToast("Sedang diproses. Tunggu sampai selesai agar data tidak dobel.", "warning");
            return;
        }
        const submitter = event.submitter;
        // Tunggu validator/konfirmasi lain: kalau kiriman dibatalkan, jangan tandai.
        setTimeout(function () {
            if (event.defaultPrevented) return;
            submitted.add(form);
            form.setAttribute("aria-busy", "true");
            if (submitter && submitter.tagName === "BUTTON") {
                submitter.dataset.originalHtml = submitter.innerHTML;
                submitter.classList.add("is-action-loading");
                submitter.setAttribute("aria-disabled", "true");
                submitter.innerHTML = '<span class="app-button-spinner" aria-hidden="true"></span><span>' + loadingLabel(submitter) + "</span>";
            }
        }, 0);
    });

    // Kembali lewat tombol Back browser: kembalikan tombol seperti semula.
    window.addEventListener("pageshow", function () {
        document.querySelectorAll("form[aria-busy='true']").forEach(function (form) { form.removeAttribute("aria-busy"); });
        document.querySelectorAll(".is-action-loading").forEach(function (button) {
            if (button.dataset.originalHtml) button.innerHTML = button.dataset.originalHtml;
            button.classList.remove("is-action-loading");
            button.removeAttribute("aria-disabled");
        });
    });
});

// --- 5. Tabel ----------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", function () {
    const moneyOrNumber = /^(-\s*)?(rp\.?\s*)?-?[\d.,]+(\s*(%|porsi|kg|pcs|liter|l|x))?$/i;
    // Nomor dokumen (JRN-20260929-037, INV-..., DLV-...-LUNCH-001) dan tanggal:
    // jangan dipatah di tanda hubung.
    const codeOrDate = /^([A-Z]{2,6}-[A-Z0-9-]+|\d{2}-\d{2}-\d{4}( \d{2}:\d{2})?)$/;

    document.querySelectorAll("main table.table, main table.app-table, main table.app-data-table, main table.print-table, main table.ui-data-table").forEach(function (table) {
        if (table.classList.contains("table") && !table.closest(".table-responsive, .app-table-wrap, .app-table-wrapper, .print-table-wrapper, .ui-table-scroll")) {
            const wrapper = document.createElement("div");
            wrapper.className = "app-table-wrap";
            table.parentNode.insertBefore(wrapper, table);
            wrapper.appendChild(table);
        }

        // Kolom yang isinya angka/rupiah: rata kanan, termasuk judulnya.
        const bodyRows = Array.prototype.slice.call(table.tBodies[0] ? table.tBodies[0].rows : []);
        const headRow = table.tHead && table.tHead.rows[0];
        if (!headRow || !bodyRows.length) return;
        Array.prototype.forEach.call(headRow.cells, function (headCell, index) {
            if (headCell.colSpan > 1) return;
            let numeric = 0;
            let coded = 0;
            let filled = 0;
            bodyRows.forEach(function (row) {
                const cell = row.cells[index];
                if (!cell || cell.colSpan > 1) return;
                const text = cell.textContent.replace(/\s+/g, " ").trim();
                if (!text || text === "-") return;
                filled += 1;
                if (moneyOrNumber.test(text) && !cell.querySelector("a.btn, button, form")) numeric += 1;
                if (codeOrDate.test(text)) coded += 1;
            });
            if (filled && coded / filled >= 0.8) {
                headCell.classList.add("nowrap");
                bodyRows.forEach(function (row) {
                    const cell = row.cells[index];
                    if (cell && cell.colSpan === 1) cell.classList.add("nowrap");
                });
            }
            if (filled && numeric / filled >= 0.8) {
                headCell.classList.add("num");
                bodyRows.forEach(function (row) {
                    const cell = row.cells[index];
                    if (cell && cell.colSpan === 1) cell.classList.add("num");
                });
                const footRows = table.tFoot ? table.tFoot.rows : [];
                Array.prototype.forEach.call(footRows, function (row) {
                    if (row.cells[index] && row.cells.length === headRow.cells.length) row.cells[index].classList.add("num");
                });
            }
        });
    });
});

// --- 6. Lihat/sembunyikan kata sandi ---------------------------------------------------------
document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll('input[type="password"]:not([data-no-reveal])').forEach(function (input) {
        if (input.closest(".input-group")) return;
        const group = document.createElement("div");
        group.className = "input-group";
        input.parentNode.insertBefore(group, input);
        group.appendChild(input);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "btn app-btn-secondary";
        button.setAttribute("aria-label", "Tampilkan kata sandi");
        button.innerHTML = '<i class="bi bi-eye" aria-hidden="true"></i>';
        button.addEventListener("click", function () {
            const show = input.type === "password";
            input.type = show ? "text" : "password";
            button.setAttribute("aria-label", show ? "Sembunyikan kata sandi" : "Tampilkan kata sandi");
            button.innerHTML = '<i class="bi ' + (show ? "bi-eye-slash" : "bi-eye") + '" aria-hidden="true"></i>';
        });
        group.appendChild(button);
    });
});

// --- 7. Pengendali form ------------------------------------------------------------------------
function appToggleRequiredSection(wrapper, visible) {
    if (!wrapper) return;
    wrapper.style.display = visible ? "" : "none";
    wrapper.querySelectorAll("select, input").forEach(function (input) {
        input.required = visible;
        if (!visible) input.value = "";
    });
}

// Uang muka / DP: kolom pihak sesuai jenis, rekening hanya untuk transfer.
document.addEventListener("DOMContentLoaded", function () {
    const advanceType = document.getElementById("advanceType");
    const paymentMethod = document.getElementById("advancePaymentMethod");

    function updateParty() {
        const selected = advanceType.options[advanceType.selectedIndex];
        const party = selected ? selected.getAttribute("data-party") : "";
        document.querySelectorAll("[data-party-field]").forEach(function (field) {
            appToggleRequiredSection(field, field.getAttribute("data-party-field") === party);
        });
    }

    if (advanceType) {
        advanceType.addEventListener("change", updateParty);
        updateParty();
    }
    if (paymentMethod) {
        const update = function () { appToggleRequiredSection(document.getElementById("advanceBankWrap"), paymentMethod.value === "TRANSFER"); };
        paymentMethod.addEventListener("change", update);
        update();
    }
});

// Biaya transport: rekening hanya untuk transfer, penanda BBM.
document.addEventListener("DOMContentLoaded", function () {
    const expenseType = document.getElementById("transportExpenseType");
    const paymentMethod = document.getElementById("transportExpensePaymentMethod");

    if (paymentMethod) {
        const update = function () { appToggleRequiredSection(document.getElementById("transportExpenseBankWrap"), paymentMethod.value === "TRANSFER"); };
        paymentMethod.addEventListener("change", update);
        update();
    }
    if (expenseType) {
        const update = function () {
            const isFuel = expenseType.value === "VEHICLE_FUEL";
            document.querySelectorAll("input[name='vehicle_label'], select[name='driver_id'], select[name='delivery_id']").forEach(function (input) {
                input.setAttribute("data-trace-priority", isFuel ? "required-one-of" : "optional");
            });
        };
        expenseType.addEventListener("change", update);
        update();
    }
});

// Pratinjau akun COA dari pilihan yang punya data-account.
document.addEventListener("DOMContentLoaded", function () {
    function updatePreview(select) {
        const group = select.closest(".col-md-4, .col-md-6, .col-12, .form-section, .app-card") || select.parentElement;
        const preview = group ? group.querySelector("[data-coa-preview]") : null;
        if (!preview) return;
        const selected = select.options[select.selectedIndex];
        const account = selected ? selected.getAttribute("data-account") : "";
        if (account) {
            preview.textContent = "Akun COA otomatis: " + account + " — " + selected.textContent.trim();
            preview.setAttribute("data-state", "ready");
        } else {
            preview.textContent = "Pilih kategori/jenis biaya untuk melihat akun COA otomatis.";
            preview.removeAttribute("data-state");
        }
    }
    const selects = new Set();
    document.querySelectorAll("select option[data-account]").forEach(function (option) {
        const select = option.closest("select");
        if (select) selects.add(select);
    });
    selects.forEach(function (select) {
        select.addEventListener("change", function () { updatePreview(select); });
        updatePreview(select);
    });
});

// Input transaksi keuangan terpadu: tampilkan bagian yang sesuai jenisnya.
document.addEventListener("DOMContentLoaded", function () {
    const form = document.querySelector("[data-unified-finance-form='true']");
    if (!form) return;
    const kindSelect = form.querySelector("#unifiedTransactionKind");
    const paymentMethod = form.querySelector("#unifiedPaymentMethod");
    const advanceType = form.querySelector("#unifiedAdvanceType");

    function currentKind() {
        return kindSelect ? kindSelect.value : "ADVANCE";
    }
    function updateParty() {
        if (!advanceType) return;
        const selected = advanceType.options[advanceType.selectedIndex];
        const party = selected ? selected.getAttribute("data-party") : "";
        const isAdvance = currentKind() === "ADVANCE";
        form.querySelectorAll(".unified-advance-party[data-party-field]").forEach(function (field) {
            const show = isAdvance && field.getAttribute("data-party-field") === party;
            field.hidden = !show;
            field.querySelectorAll("select, input").forEach(function (input) {
                input.required = show;
                if (!show) input.value = "";
            });
        });
    }
    function updateSections() {
        const kind = currentKind();
        form.querySelectorAll("[data-unified-section]").forEach(function (section) {
            const active = section.getAttribute("data-unified-section") === kind;
            section.hidden = !active;
            section.querySelectorAll("select, input, textarea").forEach(function (input) {
                const requiredWhen = input.getAttribute("data-required-when");
                if (requiredWhen) input.required = active && requiredWhen === kind;
                if (!active && input.type !== "hidden") {
                    if (input.tagName === "SELECT") input.selectedIndex = 0;
                    else input.value = "";
                }
            });
        });
        updateParty();
    }
    function updateBank() {
        appToggleRequiredSection(form.querySelector("#unifiedBankWrap"), paymentMethod && paymentMethod.value === "TRANSFER");
    }

    if (kindSelect) kindSelect.addEventListener("change", updateSections);
    if (paymentMethod) paymentMethod.addEventListener("change", updateBank);
    if (advanceType) advanceType.addEventListener("change", updateParty);
    updateSections();
    if (paymentMethod) updateBank();
});

// Pratinjau pesanan portal dan cegah kirim ganda draft.
document.addEventListener("DOMContentLoaded", function () {
    function cleanText(value) {
        return String(value || "").replace(/\s+/g, " ").trim();
    }
    function updatePreview(form) {
        const field = function (name) { return form.querySelector("[data-portal-" + name + "]"); };
        const title = form.querySelector("[data-portal-preview-title]");
        const detail = form.querySelector("[data-portal-preview-detail]");
        if (!title || !detail) return;
        const location = field("location-select");
        const selected = location && location.selectedOptions ? location.selectedOptions[0] : null;
        const meal = field("meal-type");
        const orderDate = cleanText(field("order-date") && field("order-date").value);
        const portion = cleanText(field("portion-input") && field("portion-input").value);
        const locationName = selected && selected.value ? cleanText(selected.textContent) : "";
        if (!orderDate || !locationName || !portion) {
            title.textContent = "Pilih tanggal, lokasi, dan jumlah porsi";
            detail.textContent = "Draft ini belum membuat produksi, pengiriman, tagihan, pembayaran, stok, atau jurnal.";
            return;
        }
        const mealLabel = meal && meal.selectedIndex >= 0 && meal.options ? cleanText(meal.options[meal.selectedIndex].textContent) : cleanText(meal && meal.value);
        title.textContent = portion + " porsi " + mealLabel + " untuk " + locationName;
        detail.textContent = [
            "Tanggal " + orderDate,
            field("time-input") && field("time-input").value ? "Jam kirim " + field("time-input").value : "",
            selected && selected.getAttribute("data-client-name") ? "Client/PT " + selected.getAttribute("data-client-name") : "",
            selected && selected.getAttribute("data-mandor-name") ? "Mandor " + selected.getAttribute("data-mandor-name") : "",
            field("contact-input") && field("contact-input").value ? "Penerima " + field("contact-input").value : "",
            field("phone-input") && field("phone-input").value ? "HP " + field("phone-input").value : "",
            selected && selected.getAttribute("data-location-description") ? "Catatan lokasi: " + selected.getAttribute("data-location-description") : ""
        ].filter(Boolean).join(" | ");
    }

    document.querySelectorAll("[data-portal-order-form]").forEach(function (form) {
        form.querySelectorAll("input, select, textarea").forEach(function (input) {
            input.addEventListener("change", function () { updatePreview(form); });
            input.addEventListener("input", function () { updatePreview(form); });
        });
        updatePreview(form);
    });
});

// Pencarian Global Internal (Ctrl+K)
document.addEventListener("DOMContentLoaded", function () {
    const modal = document.getElementById("globalSearchModal");
    const trigger = document.getElementById("globalSearchTrigger");
    const input = document.getElementById("globalSearchInput");
    const resultsContainer = document.getElementById("globalSearchResults");
    const closeBtn = document.getElementById("globalSearchClose");
    if (!modal || !input || !resultsContainer) return;

    let debounceTimer = null;
    let activeIndex = -1;

    function openSearch() {
        if (!modal.open) {
            modal.showModal();
        }
        input.value = "";
        input.focus();
        resetResults();
    }

    function closeSearch() {
        if (modal.open) {
            modal.close();
        }
    }

    function resetResults() {
        resultsContainer.innerHTML = "";
        const hint = document.createElement("div");
        hint.className = "global-search-hint";
        const icon = document.createElement("i");
        icon.className = "bi bi-keyboard";
        const text = document.createElement("p");
        text.textContent = "Ketik minimal 2 huruf untuk mencari pelanggan, mandor, invoice, pesanan, atau karyawan.";
        const shortcuts = document.createElement("div");
        shortcuts.className = "global-search-shortcuts";
        const span1 = document.createElement("span");
        span1.innerHTML = "<kbd>↑</kbd> <kbd>↓</kbd> Pilih";
        const span2 = document.createElement("span");
        span2.innerHTML = "<kbd>Enter</kbd> Buka";
        const span3 = document.createElement("span");
        span3.innerHTML = "<kbd>Esc</kbd> Tutup";
        shortcuts.appendChild(span1);
        shortcuts.appendChild(span2);
        shortcuts.appendChild(span3);
        hint.appendChild(icon);
        hint.appendChild(text);
        hint.appendChild(shortcuts);
        resultsContainer.appendChild(hint);
        activeIndex = -1;
    }

    if (trigger) {
        trigger.addEventListener("click", openSearch);
    }
    if (closeBtn) {
        closeBtn.addEventListener("click", closeSearch);
    }

    document.addEventListener("keydown", function (e) {
        if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
            e.preventDefault();
            if (modal.open) {
                closeSearch();
            } else {
                openSearch();
            }
        }
    });

    input.addEventListener("input", function () {
        const q = input.value.trim();
        clearTimeout(debounceTimer);
        if (q.length < 2) {
            resetResults();
            return;
        }

        debounceTimer = setTimeout(function () {
            fetch("/search?q=" + encodeURIComponent(q))
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    renderResults(data);
                })
                .catch(function () {
                    resultsContainer.innerHTML = "";
                    const err = document.createElement("div");
                    err.className = "global-search-empty";
                    err.textContent = "Gagal memuat hasil pencarian.";
                    resultsContainer.appendChild(err);
                });
        }, 180);
    });

    function renderResults(data) {
        resultsContainer.innerHTML = "";
        activeIndex = -1;
        if (!data || !data.results || data.results.length === 0) {
            const empty = document.createElement("div");
            empty.className = "global-search-empty";
            const icon = document.createElement("i");
            icon.className = "bi bi-search";
            const p = document.createElement("p");
            p.textContent = "Tidak ditemukan hasil untuk \"" + (data ? data.q : "") + "\"";
            empty.appendChild(icon);
            empty.appendChild(p);
            resultsContainer.appendChild(empty);
            return;
        }

        data.results.forEach(function (category) {
            const catHeader = document.createElement("div");
            catHeader.className = "global-search-category";
            const catIcon = document.createElement("i");
            catIcon.className = "bi " + (category.icon || "bi-folder");
            const catName = document.createElement("span");
            catName.textContent = category.category;
            catHeader.appendChild(catIcon);
            catHeader.appendChild(catName);
            resultsContainer.appendChild(catHeader);

            category.items.forEach(function (item) {
                const link = document.createElement("a");
                link.href = item.url;
                link.className = "global-search-item";

                const infoWrap = document.createElement("div");
                infoWrap.className = "item-info";
                const title = document.createElement("div");
                title.className = "item-title";
                title.textContent = item.title;
                const sub = document.createElement("div");
                sub.className = "item-subtitle";
                sub.textContent = item.subtitle;
                infoWrap.appendChild(title);
                infoWrap.appendChild(sub);

                link.appendChild(infoWrap);

                if (item.badge) {
                    const badge = document.createElement("span");
                    badge.className = "item-badge";
                    badge.textContent = item.badge;
                    link.appendChild(badge);
                }

                resultsContainer.appendChild(link);
            });
        });
    }

    input.addEventListener("keydown", function (e) {
        const items = resultsContainer.querySelectorAll(".global-search-item");
        if (items.length === 0) return;

        if (e.key === "ArrowDown") {
            e.preventDefault();
            activeIndex++;
            if (activeIndex >= items.length) activeIndex = 0;
            updateItemFocus(items);
        } else if (e.key === "ArrowUp") {
            e.preventDefault();
            activeIndex--;
            if (activeIndex < 0) activeIndex = items.length - 1;
            updateItemFocus(items);
        } else if (e.key === "Enter") {
            if (activeIndex >= 0 && items[activeIndex]) {
                e.preventDefault();
                items[activeIndex].click();
            }
        }
    });

    function updateItemFocus(items) {
        items.forEach(function (el, idx) {
            if (idx === activeIndex) {
                el.classList.add("is-selected");
                el.scrollIntoView({ block: "nearest" });
            } else {
                el.classList.remove("is-selected");
            }
        });
    }
});


// --- Desktop internal: garis progres saat pindah halaman & angka KPI yang menghitung naik ---
(function () {
    const bar = document.getElementById("navProgress");
    if (bar) {
        const start = function () { bar.classList.remove("is-active"); void bar.offsetWidth; bar.classList.add("is-active"); };
        document.addEventListener("click", function (event) {
            const link = event.target.closest("a[href]");
            if (!link || event.defaultPrevented || event.button !== 0) return;
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            if (link.target && link.target !== "_self") return;
            if (link.hasAttribute("download") || link.dataset.bsToggle) return;
            const url = new URL(link.href, window.location.href);
            if (url.origin !== window.location.origin) return;
            if (url.pathname === window.location.pathname && url.search === window.location.search && url.hash) return;
            start();
        });
        document.addEventListener("submit", function (event) {
            if (!event.defaultPrevented && !event.target.target) start();
        });
        window.addEventListener("pageshow", function () { bar.classList.remove("is-active"); });
    }

    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const plain = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 });
    document.querySelectorAll("[data-count-to]").forEach(function (element) {
        const target = Number(element.dataset.countTo) || 0;
        const prefix = element.dataset.countFormat === "rupiah" ? "Rp " : "";
        const started = performance.now();
        const step = function (now) {
            const t = reduce || !target ? 1 : Math.min((now - started) / 700, 1);
            element.textContent = prefix + plain.format(Math.round(target * (1 - Math.pow(1 - t, 3))));
            if (t < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
    });
})();
