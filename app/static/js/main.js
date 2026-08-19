// ==================================================
// UI Theme Controller + Enterprise Shell Controller
// - 2 theme mode: Dark Mono and Light Mono
// - Desktop fixed sidebar
// - Tablet/mobile offcanvas sidebar
// - Parent-child accordion single-open
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    const allowedThemes = ["dark-mono", "light-mono"];
    const themeLabels = {
        "dark-mono": "Dark Mono",
        "light-mono": "Light Mono"
    };
    const legacyThemeMap = {
        "dark-enterprise": "dark-mono",
        "light-clean": "light-mono",
        "clear-focus": "light-mono",
        "azure-calm": "light-mono",
        "bright": "light-mono",
        "clear": "light-mono",
        "good": "light-mono"
    };
    const root = document.documentElement;
    const body = document.body;
    const labelNodes = document.querySelectorAll(".theme-current-label");
    const themeOptions = document.querySelectorAll("[data-theme-option]");

    function getStoredTheme() {
        try {
            const value = window.localStorage.getItem("idha_boga_theme");
            return allowedThemes.includes(value) ? value : (legacyThemeMap[value] || "light-mono");
        } catch (error) {
            return "light-mono";
        }
    }

    function storeTheme(theme) {
        try {
            window.localStorage.setItem("idha_boga_theme", theme);
        } catch (error) {
            return;
        }
    }

    function applyTheme(theme, shouldStore) {
        const safeTheme = allowedThemes.includes(theme) ? theme : (legacyThemeMap[theme] || "light-mono");
        root.setAttribute("data-theme", safeTheme);
        if (body) {
            body.setAttribute("data-theme", safeTheme);
        }

        labelNodes.forEach(function (node) {
            node.textContent = themeLabels[safeTheme] || "Light Mono";
        });

        themeOptions.forEach(function (option) {
            const isActive = option.getAttribute("data-theme-option") === safeTheme;
            option.classList.toggle("is-active", isActive);
            option.setAttribute("aria-pressed", isActive ? "true" : "false");
        });

        if (shouldStore) {
            storeTheme(safeTheme);
        }
    }

    themeOptions.forEach(function (option) {
        option.addEventListener("click", function () {
            applyTheme(option.getAttribute("data-theme-option"), true);
        });
    });

    applyTheme(getStoredTheme(), false);
});

document.addEventListener("DOMContentLoaded", function () {
    const sidebar = document.getElementById("appSidebar");
    const toggle = document.getElementById("sidebarToggle");
    const backdrop = document.getElementById("sidebarBackdrop");
    const closeButtons = document.querySelectorAll("[data-sidebar-close]");
    const offcanvasQuery = window.matchMedia("(max-width: 1023.98px)");

    if (!sidebar || !toggle) {
        return;
    }

    function setToggleState(isOpen) {
        toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
        toggle.setAttribute("aria-label", isOpen ? "Tutup menu navigasi" : "Buka menu navigasi");
    }

    function openSidebar() {
        sidebar.classList.add("is-open", "show");
        document.body.classList.add("sidebar-open");
        if (backdrop) {
            backdrop.classList.add("is-visible");
        }
        setToggleState(true);

        if (offcanvasQuery.matches) {
            setTimeout(function () {
                sidebar.focus({ preventScroll: true });
            }, 10);
        }
    }

    function closeSidebar() {
        sidebar.classList.remove("is-open", "show");
        document.body.classList.remove("sidebar-open");
        if (backdrop) {
            backdrop.classList.remove("is-visible");
        }
        setToggleState(false);
    }

    function toggleSidebar() {
        if (sidebar.classList.contains("is-open") || sidebar.classList.contains("show")) {
            closeSidebar();
        } else {
            openSidebar();
        }
    }

    function syncAccordionState() {
        sidebar.querySelectorAll("details.sidebar-group").forEach(function (group) {
            const summary = group.querySelector("summary.sidebar-group-toggle");
            if (summary) {
                summary.setAttribute("aria-expanded", group.open ? "true" : "false");
            }
        });
    }

    function closeOtherGroups(activeGroup) {
        sidebar.querySelectorAll("details.sidebar-group").forEach(function (group) {
            if (group !== activeGroup) {
                group.open = false;
            }
        });
        syncAccordionState();
    }

    sidebar.querySelectorAll("details.sidebar-group").forEach(function (group) {
        group.addEventListener("toggle", function () {
            if (group.open) {
                closeOtherGroups(group);
            }
            syncAccordionState();
        });
    });

    toggle.addEventListener("click", function (event) {
        event.preventDefault();
        toggleSidebar();
    });

    closeButtons.forEach(function (button) {
        button.addEventListener("click", function (event) {
            event.preventDefault();
            closeSidebar();
            toggle.focus();
        });
    });

    if (backdrop) {
        backdrop.addEventListener("click", closeSidebar);
    }

    sidebar.querySelectorAll("a.sidebar-link").forEach(function (link) {
        link.addEventListener("click", function () {
            if (offcanvasQuery.matches) {
                closeSidebar();
            }
        });
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && (sidebar.classList.contains("is-open") || sidebar.classList.contains("show"))) {
            closeSidebar();
            toggle.focus();
        }
    });

    function handleViewportChange() {
        if (!offcanvasQuery.matches) {
            closeSidebar();
        }
    }

    if (typeof offcanvasQuery.addEventListener === "function") {
        offcanvasQuery.addEventListener("change", handleViewportChange);
    } else if (typeof offcanvasQuery.addListener === "function") {
        offcanvasQuery.addListener(handleViewportChange);
    }

    syncAccordionState();
    handleViewportChange();
});

// ==================================================
// UI Page Header + Action System Controller
// - Adds metadata to every page header action group
// - Enforces one visible primary action in page header by demoting duplicates
// - Keeps mobile action groups touch friendly through global classes
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    function isVisible(node) {
        if (!node) return false;
        return !!(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
    }

    function normalizeButtonVariant(button, tier) {
        if (!button) return;
        button.setAttribute("data-action-tier", tier);
        if (tier === "primary") {
            button.classList.remove("btn-success", "btn-info", "btn-warning", "btn-outline-success", "btn-outline-info", "btn-outline-warning", "btn-outline-primary", "btn-outline-secondary", "app-btn-outline", "app-btn-secondary");
            button.classList.add("app-btn-primary");
        } else if (tier === "danger") {
            button.classList.add("app-btn-danger");
        } else if (tier === "ghost") {
            button.classList.add("app-btn-ghost");
        } else {
            button.classList.remove("btn-success", "btn-info", "btn-warning", "btn-outline-success", "btn-outline-info", "btn-outline-warning", "btn-primary", "app-btn-primary");
            button.classList.add("app-btn-secondary");
        }
    }

    function directActionButtons(actionGroup) {
        return Array.from(actionGroup.querySelectorAll(":scope > a.btn, :scope > button.btn, :scope > form > button.btn, :scope > form > .btn, :scope > .btn"))
            .filter(isVisible);
    }

    document.querySelectorAll(".page-header, .app-page-header, .content-header").forEach(function (header) {
        header.setAttribute("data-page-header", "true");

        const title = header.querySelector("h1, .page-title");
        if (title && !title.classList.contains("page-title")) {
            title.classList.add("page-title");
        }

        const description = header.querySelector("p, .page-description");
        if (description && !description.classList.contains("page-description")) {
            description.classList.add("page-description");
        }

        const actions = header.querySelector(".page-actions, [data-page-actions]");
        if (!actions) return;

        actions.setAttribute("data-page-actions", "true");
        actions.setAttribute("aria-label", actions.getAttribute("aria-label") || "Aksi halaman");

        const buttons = directActionButtons(actions);
        const primaryButtons = buttons.filter(function (button) {
            return button.classList.contains("app-btn-primary") || button.classList.contains("btn-primary") || button.getAttribute("data-action-tier") === "primary";
        });

        if (primaryButtons.length === 0) {
            actions.setAttribute("data-primary-count", "0");
        } else if (primaryButtons.length === 1) {
            actions.setAttribute("data-primary-count", "1");
            normalizeButtonVariant(primaryButtons[0], "primary");
        } else {
            actions.setAttribute("data-primary-count", "over");
            primaryButtons.forEach(function (button, index) {
                normalizeButtonVariant(button, index === 0 ? "primary" : "secondary");
            });
        }

        buttons.forEach(function (button) {
            if (button.getAttribute("data-action-tier")) return;
            const text = (button.textContent || "").trim().toLowerCase();
            const dangerWord = ["hapus", "batalkan", "reset", "nonaktif", "tolak"];
            if (dangerWord.some(function (word) { return text.includes(word); })) {
                normalizeButtonVariant(button, "danger");
            } else if (button.classList.contains("app-btn-primary") || button.classList.contains("btn-primary")) {
                normalizeButtonVariant(button, "primary");
            } else {
                normalizeButtonVariant(button, "secondary");
            }
        });
    });

    document.querySelectorAll(".table-actions, [data-row-actions]").forEach(function (rowActions) {
        rowActions.setAttribute("data-row-actions", "true");
        const buttons = Array.from(rowActions.querySelectorAll("a.btn, button.btn")).filter(isVisible);
        buttons.forEach(function (button) {
            if (button.getAttribute("data-action-tier")) return;
            const text = (button.textContent || "").trim().toLowerCase();
            const dangerWord = ["hapus", "batalkan", "reset", "nonaktif", "tolak"];
            if (dangerWord.some(function (word) { return text.includes(word); })) {
                normalizeButtonVariant(button, "danger");
            } else if (text.includes("detail") || text.includes("lihat")) {
                normalizeButtonVariant(button, "secondary");
            } else {
                normalizeButtonVariant(button, "ghost");
            }
        });
    });
});

// ==================================================
// UI Button Cleanup Semua Modul
// - fallback normalizer untuk tombol legacy/dynamic
// - tidak mengubah logic bisnis, hanya kelas visual
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    const dangerWords = ["hapus", "batalkan", "reset", "nonaktif", "tolak", "batal"];
    const neutralLegacy = [
        "btn-success", "btn-info", "btn-warning",
        "btn-outline-success", "btn-outline-info", "btn-outline-warning",
        "btn-outline-primary", "btn-outline-secondary", "btn-secondary"
    ];

    function textOf(button) {
        return (button.textContent || "").trim().toLowerCase();
    }

    function hasDangerMeaning(button) {
        const text = textOf(button);
        return dangerWords.some(function (word) { return text.includes(word); }) ||
            button.classList.contains("btn-danger") ||
            button.classList.contains("btn-outline-danger") ||
            button.classList.contains("app-btn-danger");
    }

    document.querySelectorAll("a.btn, button.btn, input.btn").forEach(function (button) {
        if (button.classList.contains("btn-close")) return;

        if (hasDangerMeaning(button)) {
            button.classList.remove("btn-danger", "btn-outline-danger");
            button.classList.add("app-btn-danger");
            button.setAttribute("data-action-tier", button.getAttribute("data-action-tier") || "danger");
            return;
        }

        neutralLegacy.forEach(function (className) {
            if (button.classList.contains(className)) {
                button.classList.remove(className);
                button.classList.add("app-btn-secondary");
                button.setAttribute("data-action-tier", button.getAttribute("data-action-tier") || "secondary");
            }
        });

        const inRowAction = button.closest(".table-actions, [data-row-actions]");
        if (inRowAction && button.classList.contains("app-btn-primary")) {
            button.classList.remove("app-btn-primary", "btn-primary");
            button.classList.add("app-btn-secondary");
            button.setAttribute("data-action-tier", "secondary");
        }
    });
});

// ==================================================
// UI Table + Mobile Card List System
// - memberi data-label otomatis dari header table
// - membungkus table tanpa wrapper agar overflow desktop terkontrol
// - mobile default card list; table kompleks bisa fallback scroll
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    function cleanText(value) {
        return (value || "")
            .replace(/\s+/g, " ")
            .replace(/[\n\t]/g, " ")
            .trim();
    }

    function isPrintContext(table) {
        return !!table.closest(".print-page, .print-sheet, [data-print-page], .print-container");
    }

    function isComplexTable(table) {
        if (table.querySelector("thead tr:nth-child(2), tbody td[rowspan], tbody th[rowspan], tbody td[colspan]:not([colspan='1']), tbody th[colspan]:not([colspan='1'])")) {
            return true;
        }
        const headerCount = table.querySelectorAll("thead tr:first-child th, thead tr:first-child td").length;
        return headerCount > 9;
    }

    function findWrapper(table) {
        return table.closest(".app-table-wrap, .table-responsive, .table-wrapper, .data-table-wrapper");
    }

    function wrapTable(table) {
        const existing = findWrapper(table);
        if (existing) {
            existing.classList.add("app-table-wrap");
            return existing;
        }
        const wrapper = document.createElement("div");
        wrapper.className = "app-table-wrap";
        table.parentNode.insertBefore(wrapper, table);
        wrapper.appendChild(table);
        return wrapper;
    }

    function headerLabels(table) {
        const headers = Array.from(table.querySelectorAll("thead tr:first-child th, thead tr:first-child td"));
        return headers.map(function (header, index) {
            const text = cleanText(header.textContent);
            if (text) return text;
            return index === headers.length - 1 ? "Aksi" : "";
        });
    }

    function markActionCell(cell) {
        if (!cell) return;
        const text = cleanText(cell.textContent).toLowerCase();
        const hasAction = cell.querySelector("a.btn, button.btn, .dropdown, form button, .table-actions, [data-row-actions]");
        const label = (cell.getAttribute("data-label") || "").toLowerCase();
        if (hasAction || label.includes("aksi") || text === "detail" || text.includes("edit") || text.includes("hapus")) {
            cell.classList.add("app-table-action-cell");
            cell.setAttribute("data-table-action-cell", "true");
            const actions = cell.querySelector(".table-actions, [data-row-actions]");
            if (actions) {
                actions.setAttribute("data-row-actions", "true");
            }
        }
    }

    document.querySelectorAll("table").forEach(function (table) {
        if (table.closest(".calendar, .datepicker, .flatpickr-calendar")) return;
        if (table.matches(".ui-data-table, [data-ui-table]")) return;

        table.classList.add("app-data-table");
        const wrapper = wrapTable(table);
        const mobileMode = (table.getAttribute("data-mobile-table") || wrapper.getAttribute("data-mobile-table") || (isPrintContext(table) || isComplexTable(table) ? "scroll" : "card"));
        table.setAttribute("data-mobile-table", mobileMode);
        wrapper.setAttribute("data-mobile-table", mobileMode);
        wrapper.setAttribute("data-enhanced-table", "UI");

        if (!wrapper.querySelector(":scope > .app-table-scroll-hint") && mobileMode === "scroll") {
            const hint = document.createElement("div");
            hint.className = "app-table-scroll-hint";
            hint.innerHTML = '<i class="bi bi-arrow-left-right" aria-hidden="true"></i><span>Geser tabel untuk melihat kolom lainnya</span>';
            wrapper.insertBefore(hint, table);
        }

        const labels = headerLabels(table);
        const rows = Array.from(table.querySelectorAll("tbody tr"));
        if (rows.length === 0) {
            wrapper.classList.add("is-empty");
        }

        rows.forEach(function (row) {
            const cells = Array.from(row.children).filter(function (cell) {
                return cell.matches("td, th");
            });

            if (cells.length === 1 && cells[0].hasAttribute("colspan")) {
                row.classList.add("app-table-empty-row");
                cells[0].setAttribute("data-label", "");
                return;
            }

            cells.forEach(function (cell, index) {
                if (!cell.hasAttribute("data-label")) {
                    cell.setAttribute("data-label", labels[index] || "");
                }
                const text = cleanText(cell.textContent);
                if (/^Rp\s|^Rp\.|^[\d\.]+,\d{2}$/.test(text) || cell.classList.contains("text-end")) {
                    cell.classList.add("money-cell");
                }
                if (index === cells.length - 1) {
                    markActionCell(cell);
                } else {
                    markActionCell(cell);
                }
            });
        });
    });
});



// ==================================================
// UI Form System Semua Modul
// - klasifikasi form: page, filter, inline/row action, auth
// - section treatment untuk form panjang tanpa mengubah action/method/name field
// - satu primary submit per form; submit tambahan turun menjadi secondary
// - normalisasi field, label, error dekat field, action footer, mobile touch target
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    function cleanText(value) {
        return (value || "").replace(/\s+/g, " ").trim();
    }

    function cssEscape(value) {
        if (window.CSS && typeof window.CSS.escape === "function") {
            return window.CSS.escape(value);
        }
        return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
    }

    function visibleFields(form) {
        return Array.from(form.querySelectorAll("input, select, textarea"))
            .filter(function (field) {
                const type = (field.getAttribute("type") || "").toLowerCase();
                return !["hidden", "submit", "button", "reset"].includes(type);
            });
    }

    function submitButtons(form) {
        return Array.from(form.querySelectorAll("button[type='submit'], input[type='submit'], button:not([type])"))
            .filter(function (button) {
                return !button.closest(".dropdown-menu");
            });
    }

    function actionElements(form) {
        return Array.from(form.querySelectorAll("button, input[type='submit'], input[type='button'], input[type='reset'], a.btn"))
            .filter(function (button) {
                return !button.closest(".dropdown-menu") && !button.closest(".input-group");
            });
    }

    function isInsideRowAction(form) {
        return !!form.closest("td, th, tr, .table-actions, [data-row-actions], .dropdown-menu");
    }

    function isFilterForm(form) {
        const method = (form.getAttribute("method") || "get").toLowerCase();
        const text = cleanText(form.textContent).toLowerCase();
        const endpoint = (form.getAttribute("action") || "").toLowerCase();
        return form.closest(".filter-bar, .filter-card, .toolbar, .table-toolbar, .search-box, [data-filter]") ||
            method === "get" ||
            text.includes("filter") ||
            text.includes("tampilkan") ||
            text.includes("cari") ||
            endpoint.includes("filter");
    }

    function setFormKind(form) {
        if (form.closest(".auth-card, .auth-page") || form.querySelector("input[type='password']") && cleanText(form.textContent).toLowerCase().includes("login")) {
            form.setAttribute("data-form-kind", "auth");
            form.classList.add("app-auth-form");
            return "auth";
        }

        const fields = visibleFields(form);
        const hasOnlySubmitAction = fields.length === 0;

        if (isInsideRowAction(form) || hasOnlySubmitAction) {
            form.setAttribute("data-form-kind", "row-action");
            form.classList.add("app-inline-form");
            return "row-action";
        }

        if (isFilterForm(form)) {
            form.setAttribute("data-form-kind", "filter");
            form.classList.add("app-filter-form");
            return "filter";
        }

        form.setAttribute("data-form-kind", "page");
        form.classList.add("app-form-page");
        if (fields.length > 6) {
            form.classList.add("app-form-long");
            form.setAttribute("data-form-length", "long");
        } else {
            form.setAttribute("data-form-length", "short");
        }
        return "page";
    }

    function normalizeFields(form) {
        visibleFields(form).forEach(function (field) {
            const tag = field.tagName.toLowerCase();
            const type = (field.getAttribute("type") || "").toLowerCase();

            if (type === "checkbox" || type === "radio") {
                field.classList.add("form-check-input");
            } else if (tag === "select") {
                field.classList.add("form-select");
            } else {
                field.classList.add("form-control");
            }

            if (type === "file") {
                field.classList.add("app-file-input");
            }

            field.setAttribute("data-ui-field", "true");

            const label = field.id ? form.querySelector("label[for='" + cssEscape(field.id) + "']") : null;
            if (label) {
                label.classList.add("form-label");
                if (field.required) {
                    label.classList.add("form-required");
                    label.setAttribute("data-required", "true");
                }
            }

            if (field.classList.contains("is-invalid") && !field.hasAttribute("aria-invalid")) {
                field.setAttribute("aria-invalid", "true");
            }

            const fieldWrap = field.closest(".mb-3, .form-group, .form-floating, .col, [class*='col-']");
            if (fieldWrap && !fieldWrap.classList.contains("input-group")) {
                fieldWrap.classList.add("app-field");
            }
        });

        form.querySelectorAll(".form-check").forEach(function (check) {
            check.classList.add("app-field");
        });

        form.querySelectorAll(".invalid-feedback, .field-error, .error-message").forEach(function (error) {
            error.setAttribute("data-field-error", "true");
        });
    }

    function elementHasVisibleField(element) {
        return !!element.querySelector("input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='reset']), select, textarea");
    }

    function elementHasSubmit(element) {
        return !!element.querySelector("button[type='submit'], input[type='submit'], button:not([type])");
    }

    function normalizeSections(form, kind) {
        if (!(kind === "page" || kind === "auth")) return;
        const fields = visibleFields(form);
        if (fields.length <= 6) return;

        let sectionCount = 0;
        form.querySelectorAll("fieldset, .form-section, .app-form-section, .section-card").forEach(function (section) {
            if (elementHasVisibleField(section)) {
                section.classList.add("app-form-section");
                sectionCount += 1;
            }
        });

        Array.from(form.children).forEach(function (child) {
            if (child.matches("script, template, input[type='hidden']")) return;
            if (child.classList.contains("app-form-actions") || child.classList.contains("form-actions") || child.classList.contains("card-footer") || child.classList.contains("modal-footer")) return;
            if (child.matches(".card, .app-card, .content-card, fieldset, .form-section, .section-card")) {
                if (elementHasVisibleField(child)) {
                    child.classList.add("app-form-section");
                    sectionCount += 1;
                }
            } else if (child.classList.contains("row") && elementHasVisibleField(child) && !elementHasSubmit(child)) {
                child.classList.add("app-form-section");
                sectionCount += 1;
            }
        });

        if (sectionCount > 0) {
            form.classList.add("app-form-has-section");
        } else {
            form.classList.add("app-form-sectionless");
        }
    }

    function classifyActionTier(button, submitIndex) {
        const text = cleanText(button.textContent || button.value).toLowerCase();
        const type = (button.getAttribute("type") || "").toLowerCase();
        const isSubmit = button.matches("button[type='submit'], input[type='submit']") || (button.tagName.toLowerCase() === "button" && !type);
        const isDanger = text.includes("hapus") || text.includes("delete") || text.includes("batalkan") || text.includes("batal kirim") || text.includes("reset");
        const isCancel = text === "batal" || text.includes("kembali") || text.includes("tutup");

        if (isDanger) return "danger";
        if (isCancel) return "ghost";
        if (isSubmit && submitIndex === 0) return "primary";
        if (isSubmit && submitIndex > 0) return "secondary-submit";
        if (text.includes("simpan") || text.includes("tampilkan") || text.includes("login") || text.includes("masuk") || text.includes("buat") || text.includes("generate")) return submitIndex === 0 ? "primary" : "secondary-submit";
        return "secondary";
    }

    function ensureActionFooter(form, buttons) {
        const directButtons = buttons.filter(function (button) {
            return button.parentElement === form;
        });
        if (!directButtons.length) return null;

        const footer = document.createElement("div");
        footer.className = "app-form-actions";
        form.insertBefore(footer, directButtons[0]);
        directButtons.forEach(function (button) {
            footer.appendChild(button);
        });
        return footer;
    }

    function normalizeActions(form, kind) {
        const allActions = actionElements(form).filter(function (button) {
            return !button.classList.contains("btn-close");
        });

        if (kind === "row-action" || kind === "inline") {
            allActions.forEach(function (button) {
                if (!button.classList.contains("btn")) button.classList.add("btn");
                button.classList.add("app-btn-secondary");
            });
            return;
        }

        ensureActionFooter(form, allActions);
        let submitIndex = 0;
        let primaryCount = 0;

        allActions.forEach(function (button) {
            if (!button.classList.contains("btn")) {
                button.classList.add("btn");
            }

            const isSubmit = submitButtons(form).includes(button);
            const tier = classifyActionTier(button, isSubmit ? submitIndex : 999);
            if (isSubmit) submitIndex += 1;

            button.setAttribute("data-action-tier", tier);
            button.classList.remove("app-btn-primary", "app-btn-secondary", "app-btn-danger", "app-btn-ghost");

            if (tier === "primary") {
                primaryCount += 1;
                button.classList.add("app-btn-primary");
            } else if (tier === "danger") {
                button.classList.add("app-btn-danger");
            } else if (tier === "ghost") {
                button.classList.add("app-btn-ghost");
            } else {
                button.classList.add("app-btn-secondary");
                if (tier === "secondary-submit") {
                    button.classList.add("app-form-primary-duplicate");
                    button.setAttribute("data-primary-submit-downgraded", "true");
                }
            }
        });

        form.setAttribute("data-submit-count", String(submitIndex));
        form.setAttribute("data-primary-submit-count", String(primaryCount));

        allActions.forEach(function (button) {
            const parent = button.parentElement;
            if (!parent || parent === form) return;
            if (parent.matches(".d-flex, .text-end, .mt-3, .mt-4, .card-footer, .modal-footer, .page-actions, .form-actions, .app-form-actions")) {
                parent.classList.add("app-form-actions");
            }
        });

        const dangerButtons = allActions.filter(function (button) {
            return button.getAttribute("data-action-tier") === "danger";
        });
        if (dangerButtons.length && allActions.length > dangerButtons.length) {
            dangerButtons[0].classList.add("app-danger-separated");
        }
    }

    document.querySelectorAll("form").forEach(function (form) {
        if (form.matches("[data-ui-foundation-form]")) return;
        form.classList.add("app-form");
        form.setAttribute("data-ui-form", "true");
        form.setAttribute("data-enhanced-form", "UI");
        const kind = setFormKind(form);
        normalizeFields(form);
        normalizeSections(form, kind);
        normalizeActions(form, kind);
    });
});


// ==================================================
// UI Dashboard Semua Role
// - metadata dashboard section
// - satu primary action header tetap dikontrol oleh UI
// - shortcut/support list diberi role aksesibilitas ringan
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-ui-dashboard]").forEach(function (header) {
        header.setAttribute("data-enhanced-dashboard", "UI");
    });

    document.querySelectorAll(".dashboard-section").forEach(function (section) {
        section.setAttribute("data-enhanced-dashboard-section", "UI");
    });

    document.querySelectorAll(".dashboard-support-list").forEach(function (list) {
        if (!list.hasAttribute("role")) {
            list.setAttribute("role", "list");
        }
        list.querySelectorAll(".dashboard-support-item").forEach(function (item) {
            item.setAttribute("role", "listitem");
        });
    });
});


// ==================================================
// UI Finance Global polish Controller
// - Keeps finance header actions compact: max direct actions + dropdown.
// - Adds finance metadata, money alignment hints, and mobile overflow hints.
// - Does not change routes, forms, methods, or database data.
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    const body = document.body;
    const isFinancePage = body && ((body.getAttribute("data-endpoint") || "").indexOf("finance.") === 0 || window.location.pathname.indexOf("/finance") === 0);
    if (!isFinancePage) return;

    body.classList.add("is-finance-polish");
    body.setAttribute("data-finance-polish", "UI");

    function cleanText(node) {
        return (node.textContent || "").replace(/\s+/g, " ").trim();
    }

    function directActionNodes(group) {
        return Array.from(group.children).filter(function (child) {
            if (child.classList && (child.classList.contains("app-action-dropdown") || child.classList.contains("finance-more-dropdown"))) return false;
            if (child.matches && child.matches("a.btn, button.btn")) return true;
            if (child.matches && child.matches("form")) return false;
            return false;
        });
    }

    function actionImportance(node) {
        const text = cleanText(node).toLowerCase();
        if (node.querySelector && node.querySelector(".app-btn-primary, .btn-primary")) return 10;
        if (node.matches && node.matches(".app-btn-primary, .btn-primary")) return 10;
        if (text.includes("buat") || text.includes("terima pembayaran") || text.includes("beli aset") || text.includes("statement")) return 8;
        if (text.includes("cetak") || text.includes("download") || text.includes("export")) return 4;
        if (text.includes("kembali") || text.includes("daftar")) return 2;
        return 5;
    }

    function buttonLike(node) {
        if (node.matches && node.matches("a.btn, button.btn")) return node;
        if (node.querySelector) return node.querySelector("button.btn, .btn");
        return null;
    }

    function buildDropdownItem(node) {
        const button = buttonLike(node);
        const item = document.createElement("li");
        const clone = node.cloneNode(true);
        if (clone.matches && clone.matches("a.btn")) {
            clone.className = "dropdown-item";
        } else if (clone.matches && clone.matches("button.btn")) {
            clone.className = "dropdown-item";
            clone.setAttribute("type", clone.getAttribute("type") || "button");
        } else if (clone.matches && clone.matches("form")) {
            clone.classList.add("m-0");
            const inner = clone.querySelector("button.btn, .btn");
            if (inner) {
                inner.className = "dropdown-item";
            }
        } else if (button) {
            clone.classList.add("dropdown-item");
        }
        item.appendChild(clone);
        return item;
    }

    document.querySelectorAll(".finance-header-actions").forEach(function (group) {
        group.setAttribute("data-finance-actions", "UI");
        const direct = directActionNodes(group);
        if (direct.length <= 2) return;

        const sorted = direct.map(function (node, index) {
            return { node: node, index: index, score: actionImportance(node) };
        }).sort(function (a, b) {
            if (b.score !== a.score) return b.score - a.score;
            return a.index - b.index;
        });

        const keepSet = new Set(sorted.slice(0, 2).map(function (item) { return item.node; }));
        const moveNodes = direct.filter(function (node) { return !keepSet.has(node); });
        if (!moveNodes.length) return;

        const dropdown = document.createElement("div");
        dropdown.className = "dropdown app-action-dropdown finance-more-dropdown";
        dropdown.innerHTML = '<button class="btn app-btn-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false"><i class="bi bi-three-dots"></i> Aksi lainnya</button><ul class="dropdown-menu dropdown-menu-end"></ul>';
        const menu = dropdown.querySelector(".dropdown-menu");

        moveNodes.forEach(function (node) {
            menu.appendChild(buildDropdownItem(node));
            node.remove();
        });

        group.appendChild(dropdown);
        group.setAttribute("data-finance-collapsed", "true");
        group.setAttribute("data-direct-action-count", String(keepSet.size));
        group.setAttribute("data-dropdown-action-count", String(moveNodes.length));
    });

    document.querySelectorAll(".finance-page-shell .app-table td, .finance-page-shell .app-table th").forEach(function (cell) {
        const text = cleanText(cell);
        if (/Rp\s?[0-9.]+|^[0-9.]+(,[0-9]{2})?$/.test(text)) {
            cell.classList.add("finance-money");
            cell.setAttribute("data-finance-money", "true");
        }
    });

    document.querySelectorAll(".finance-page-shell .table-responsive").forEach(function (wrapper) {
        wrapper.setAttribute("data-finance-table", "UI");
        if (!wrapper.nextElementSibling || !wrapper.nextElementSibling.classList || !wrapper.nextElementSibling.classList.contains("finance-mobile-hint")) {
            const hint = document.createElement("div");
            hint.className = "finance-mobile-hint";
            hint.textContent = "Geser tabel ke samping untuk melihat detail finance lengkap.";
            wrapper.insertAdjacentElement("afterend", hint);
        }
    });
});


// ==================================================
// UI Accounting Global polish Controller
// - Keeps accounting header actions compact: max direct actions + dropdown.
// - Adds accounting metadata, debit/credit money alignment, active flow step, and mobile overflow hints.
// - Does not change routes, forms, methods, or database data.
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    const body = document.body;
    const endpoint = body ? (body.getAttribute("data-endpoint") || "") : "";
    const isAccountingPage = body && (endpoint.indexOf("accounting.") === 0 || window.location.pathname.indexOf("/accounting") === 0);
    if (!isAccountingPage) return;

    body.classList.add("is-accounting-polish");
    body.setAttribute("data-accounting-polish", "UI");

    function cleanText(node) {
        return (node.textContent || "").replace(/\s+/g, " ").trim();
    }

    function directActionNodes(group) {
        return Array.from(group.children).filter(function (child) {
            if (child.classList && (child.classList.contains("app-action-dropdown") || child.classList.contains("accounting-more-dropdown"))) return false;
            if (child.matches && child.matches("a.btn, button.btn")) return true;
            if (child.matches && child.matches("form")) return false;
            return false;
        });
    }

    function actionImportance(node) {
        const text = cleanText(node).toLowerCase();
        if (node.querySelector && node.querySelector(".app-btn-primary, .btn-primary")) return 10;
        if (node.matches && node.matches(".app-btn-primary, .btn-primary")) return 10;
        if (text.includes("cetak") || text.includes("pdf") || text.includes("tampilkan")) return 8;
        if (text.includes("download") || text.includes("csv") || text.includes("export")) return 5;
        if (text.includes("kembali") || text.includes("daftar")) return 3;
        if (text.includes("sinkron")) return 2;
        return 5;
    }

    function buttonLike(node) {
        if (node.matches && node.matches("a.btn, button.btn")) return node;
        if (node.querySelector) return node.querySelector("button.btn, .btn");
        return null;
    }

    function buildDropdownItem(node) {
        const button = buttonLike(node);
        const item = document.createElement("li");
        const clone = node.cloneNode(true);
        if (clone.matches && clone.matches("a.btn")) {
            clone.className = "dropdown-item";
        } else if (clone.matches && clone.matches("button.btn")) {
            clone.className = "dropdown-item";
            clone.setAttribute("type", clone.getAttribute("type") || "button");
        } else if (clone.matches && clone.matches("form")) {
            clone.classList.add("m-0");
            const inner = clone.querySelector("button.btn, .btn");
            if (inner) inner.className = "dropdown-item";
        } else if (button) {
            clone.classList.add("dropdown-item");
        }
        item.appendChild(clone);
        return item;
    }

    document.querySelectorAll(".accounting-header-actions, .accounting-page-shell .page-actions, .accounting-print-shell .page-actions").forEach(function (group) {
        group.classList.add("accounting-header-actions");
        group.setAttribute("data-accounting-actions", "UI");
        const direct = directActionNodes(group);
        if (direct.length <= 2) return;

        const sorted = direct.map(function (node, index) {
            return { node: node, index: index, score: actionImportance(node) };
        }).sort(function (a, b) {
            if (b.score !== a.score) return b.score - a.score;
            return a.index - b.index;
        });

        const keepSet = new Set(sorted.slice(0, 2).map(function (item) { return item.node; }));
        const moveNodes = direct.filter(function (node) { return !keepSet.has(node); });
        if (!moveNodes.length) return;

        const dropdown = document.createElement("div");
        dropdown.className = "dropdown app-action-dropdown accounting-more-dropdown";
        dropdown.innerHTML = '<button class="btn app-btn-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false"><i class="bi bi-three-dots"></i> Aksi lainnya</button><ul class="dropdown-menu dropdown-menu-end"></ul>';
        const menu = dropdown.querySelector(".dropdown-menu");

        moveNodes.forEach(function (node) {
            menu.appendChild(buildDropdownItem(node));
            node.remove();
        });

        group.appendChild(dropdown);
        group.setAttribute("data-accounting-collapsed", "true");
        group.setAttribute("data-direct-action-count", String(keepSet.size));
        group.setAttribute("data-dropdown-action-count", String(moveNodes.length));
    });

    const path = window.location.pathname;
    const stepMap = [
        ["/accounting/journals", "journals"],
        ["/accounting/coa-mapping", "coa"],
        ["/accounting/opening-balance", "opening"],
        ["/accounting/reports", "reports"],
        ["/accounting/order-to-cash-trace", "trace"],
        ["/accounting/daily-closing", "reports"],
        ["/accounting/data-health", "trace"]
    ];
    const activeStep = (stepMap.find(function (row) { return path.indexOf(row[0]) === 0; }) || [null, null])[1];
    if (activeStep) {
        document.querySelectorAll('[data-accounting-step="' + activeStep + '"]').forEach(function (step) {
            step.classList.add("is-active");
            step.setAttribute("aria-current", "page");
        });
    }

    document.querySelectorAll(".accounting-page-shell .app-table td, .accounting-page-shell .app-table th, .accounting-page-shell .table-sm td, .accounting-page-shell .table-sm th").forEach(function (cell) {
        const text = cleanText(cell);
        if (/Rp\s?[0-9.]+|^[0-9.]+(,[0-9]{2})?$/.test(text) || /debit|kredit|credit|saldo|amount|total/i.test(text)) {
            cell.classList.add("accounting-money");
            cell.setAttribute("data-accounting-money", "true");
        }
    });

    document.querySelectorAll(".accounting-page-shell .table-responsive, .accounting-print-shell .table-responsive").forEach(function (wrapper) {
        wrapper.setAttribute("data-accounting-table", "UI");
        if (!wrapper.nextElementSibling || !wrapper.nextElementSibling.classList || !wrapper.nextElementSibling.classList.contains("accounting-mobile-hint")) {
            const hint = document.createElement("div");
            hint.className = "accounting-mobile-hint";
            hint.textContent = "Geser tabel ke samping untuk melihat detail akuntansi lengkap.";
            wrapper.insertAdjacentElement("afterend", hint);
        }
    });

    document.querySelectorAll(".accounting-page-shell table, .accounting-print-shell table").forEach(function (table) {
        if (!table.hasAttribute("data-accounting-table-normalized")) {
            table.setAttribute("data-accounting-table-normalized", "UI");
        }
    });
});

// ==================================================
// UI Logistics + Costing + HPP Global polish Controller
// - Keeps logistics/HPP header actions compact: max direct actions + dropdown.
// - Adds stock/procurement/HPP numeric alignment, active flow step, and mobile overflow hints.
// - Does not change routes, forms, methods, or database data.
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    const body = document.body;
    const endpoint = body ? (body.getAttribute("data-endpoint") || "") : "";
    const path = window.location.pathname || "";
    const isLogisticsHppPage = body && (
        endpoint.indexOf("logistics.") === 0 ||
        endpoint.indexOf("costing.") === 0 ||
        endpoint.indexOf("master.item") === 0 ||
        endpoint.indexOf("master.supplier") === 0 ||
        endpoint.indexOf("master.unit_conversions") === 0 ||
        endpoint.indexOf("operational.order_hpp") === 0 ||
        path.indexOf("/logistics") === 0 ||
        path.indexOf("/costing") === 0
    );
    if (!isLogisticsHppPage) return;

    body.classList.add("is-logistics-hpp-polish");
    body.setAttribute("data-logistics-hpp-polish", "UI");

    function cleanText(node) {
        return (node.textContent || "").replace(/\s+/g, " ").trim();
    }

    function directActionNodes(group) {
        return Array.from(group.children).filter(function (child) {
            if (child.classList && (child.classList.contains("app-action-dropdown") || child.classList.contains("logistics-hpp-more-dropdown"))) return false;
            if (child.matches && child.matches("a.btn, button.btn")) return true;
            if (child.matches && child.matches("form")) return false;
            return false;
        });
    }

    function actionImportance(node) {
        const text = cleanText(node).toLowerCase();
        if (node.querySelector && node.querySelector(".app-btn-primary, .btn-primary")) return 10;
        if (node.matches && node.matches(".app-btn-primary, .btn-primary")) return 10;
        if (text.includes("tambah") || text.includes("buat") || text.includes("input") || text.includes("hitung")) return 9;
        if (text.includes("kartu") || text.includes("detail") || text.includes("forecast") || text.includes("hpp")) return 8;
        if (text.includes("print") || text.includes("cetak") || text.includes("export")) return 6;
        if (text.includes("kembali") || text.includes("reset")) return 3;
        return 5;
    }

    function buttonLike(node) {
        if (node.matches && node.matches("a.btn, button.btn")) return node;
        if (node.querySelector) return node.querySelector("button.btn, .btn");
        return null;
    }

    function buildDropdownItem(node) {
        const button = buttonLike(node);
        const item = document.createElement("li");
        const clone = node.cloneNode(true);
        if (clone.matches && clone.matches("a.btn")) {
            clone.className = "dropdown-item";
        } else if (clone.matches && clone.matches("button.btn")) {
            clone.className = "dropdown-item";
            clone.setAttribute("type", clone.getAttribute("type") || "button");
        } else if (clone.matches && clone.matches("form")) {
            clone.classList.add("m-0");
            const inner = clone.querySelector("button.btn, .btn");
            if (inner) inner.className = "dropdown-item";
        } else if (button) {
            clone.classList.add("dropdown-item");
        }
        item.appendChild(clone);
        return item;
    }

    document.querySelectorAll(".logistics-hpp-page-shell .page-actions, .logistics-hpp-header-actions").forEach(function (group) {
        group.classList.add("logistics-hpp-header-actions");
        group.setAttribute("data-logistics-hpp-actions", "UI");
        const direct = directActionNodes(group);
        if (direct.length <= 2) return;

        const sorted = direct.map(function (node, index) {
            return { node: node, index: index, score: actionImportance(node) };
        }).sort(function (a, b) {
            if (b.score !== a.score) return b.score - a.score;
            return a.index - b.index;
        });

        const keepSet = new Set(sorted.slice(0, 2).map(function (item) { return item.node; }));
        const moveNodes = direct.filter(function (node) { return !keepSet.has(node); });
        if (!moveNodes.length) return;

        const dropdown = document.createElement("div");
        dropdown.className = "dropdown app-action-dropdown logistics-hpp-more-dropdown";
        dropdown.innerHTML = '<button class="btn app-btn-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false"><i class="bi bi-three-dots"></i> Aksi lainnya</button><ul class="dropdown-menu dropdown-menu-end"></ul>';
        const menu = dropdown.querySelector(".dropdown-menu");

        moveNodes.forEach(function (node) {
            menu.appendChild(buildDropdownItem(node));
            node.remove();
        });

        group.appendChild(dropdown);
        group.setAttribute("data-logistics-hpp-collapsed", "true");
        group.setAttribute("data-direct-action-count", String(keepSet.size));
        group.setAttribute("data-dropdown-action-count", String(moveNodes.length));
    });

    document.querySelectorAll(".logistics-hpp-page-shell .app-table td, .logistics-hpp-page-shell .app-table th, .logistics-hpp-page-shell .table-sm td, .logistics-hpp-page-shell .table-sm th").forEach(function (cell) {
        const text = cleanText(cell);
        if (/Rp\s?[0-9.]+|^[0-9.]+(,[0-9]{2})?$/.test(text) || /harga|biaya|hpp|margin|total|amount/i.test(text)) {
            cell.classList.add("logistics-hpp-money");
            cell.setAttribute("data-logistics-hpp-money", "true");
        }
        if (/^[0-9.]+([,][0-9]+)?\s?(kg|gr|gram|liter|ltr|pcs|porsi|tabung|pak|box)?$/i.test(text) || /qty|stok|minimum|satuan|porsi|yield|waste/i.test(text)) {
            cell.classList.add("logistics-hpp-qty");
            cell.setAttribute("data-logistics-hpp-qty", "true");
        }
    });

    document.querySelectorAll(".logistics-hpp-page-shell .table-responsive").forEach(function (wrapper) {
        wrapper.setAttribute("data-logistics-hpp-table", "UI");
        if (!wrapper.nextElementSibling || !wrapper.nextElementSibling.classList || !wrapper.nextElementSibling.classList.contains("logistics-hpp-mobile-hint")) {
            const hint = document.createElement("div");
            hint.className = "logistics-hpp-mobile-hint";
            hint.textContent = "Geser tabel ke samping untuk melihat detail stok, procurement, recipe, atau HPP lengkap.";
            wrapper.insertAdjacentElement("afterend", hint);
        }
    });

    document.querySelectorAll(".logistics-hpp-page-shell table").forEach(function (table) {
        if (!table.hasAttribute("data-logistics-hpp-table-normalized")) {
            table.setAttribute("data-logistics-hpp-table-normalized", "UI");
        }
    });
});

// ==================================================
// UI Operasional + Produksi + Delivery Global polish Controller
// - Keeps operational/production/delivery header actions compact.
// - Adds active order-production-delivery flow, quantity/money alignment, and mobile table hints.
// - Does not change routes, forms, methods, or database data.
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    const body = document.body;
    const endpoint = body ? (body.getAttribute("data-endpoint") || "") : "";
    const path = window.location.pathname || "";
    const isOpProdDeliveryPage = body && (
        endpoint.indexOf("operational.") === 0 ||
        endpoint.indexOf("production.") === 0 ||
        endpoint.indexOf("delivery.") === 0 ||
        path.indexOf("/operational") === 0 ||
        path.indexOf("/production") === 0 ||
        path.indexOf("/delivery") === 0
    );
    if (!isOpProdDeliveryPage) return;

    body.classList.add("is-op-prod-delivery-polish");
    body.setAttribute("data-op-prod-delivery-polish", "UI");

    function cleanText(node) {
        return (node.textContent || "").replace(/\s+/g, " ").trim();
    }

    function directActionNodes(group) {
        return Array.from(group.children).filter(function (child) {
            if (child.classList && (child.classList.contains("app-action-dropdown") || child.classList.contains("op-prod-delivery-more-dropdown"))) return false;
            if (child.matches && child.matches("a.btn, button.btn")) return true;
            if (child.matches && child.matches("form")) return false;
            return false;
        });
    }

    function actionImportance(node) {
        const text = cleanText(node).toLowerCase();
        if (node.querySelector && node.querySelector(".app-btn-primary, .btn-primary")) return 10;
        if (node.matches && node.matches(".app-btn-primary, .btn-primary")) return 10;
        if (text.includes("lock") || text.includes("sinkron") || text.includes("realisasi") || text.includes("terima") || text.includes("catat")) return 9;
        if (text.includes("tambah") || text.includes("buat") || text.includes("detail")) return 8;
        if (text.includes("riwayat") || text.includes("pengiriman") || text.includes("produksi")) return 6;
        if (text.includes("kembali") || text.includes("reset")) return 3;
        return 5;
    }

    function buttonLike(node) {
        if (node.matches && node.matches("a.btn, button.btn")) return node;
        if (node.querySelector) return node.querySelector("button.btn, .btn");
        return null;
    }

    function buildDropdownItem(node) {
        const button = buttonLike(node);
        const item = document.createElement("li");
        const clone = node.cloneNode(true);
        if (clone.matches && clone.matches("a.btn")) {
            clone.className = "dropdown-item";
        } else if (clone.matches && clone.matches("button.btn")) {
            clone.className = "dropdown-item";
            clone.setAttribute("type", clone.getAttribute("type") || "button");
        } else if (clone.matches && clone.matches("form")) {
            clone.classList.add("m-0");
            const inner = clone.querySelector("button.btn, .btn");
            if (inner) inner.className = "dropdown-item";
        } else if (button) {
            clone.classList.add("dropdown-item");
        }
        item.appendChild(clone);
        return item;
    }

    document.querySelectorAll(".op-prod-delivery-page-shell .page-actions, .op-prod-delivery-header-actions").forEach(function (group) {
        group.classList.add("op-prod-delivery-header-actions");
        group.setAttribute("data-op-prod-delivery-actions", "UI");
        const direct = directActionNodes(group);
        if (direct.length <= 2) return;

        const sorted = direct.map(function (node, index) {
            return { node: node, index: index, score: actionImportance(node) };
        }).sort(function (a, b) {
            if (b.score !== a.score) return b.score - a.score;
            return a.index - b.index;
        });

        const keepSet = new Set(sorted.slice(0, 2).map(function (item) { return item.node; }));
        const moveNodes = direct.filter(function (node) { return !keepSet.has(node); });
        if (!moveNodes.length) return;

        const dropdown = document.createElement("div");
        dropdown.className = "dropdown app-action-dropdown op-prod-delivery-more-dropdown";
        dropdown.innerHTML = '<button class="btn app-btn-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false"><i class="bi bi-three-dots"></i> Aksi lainnya</button><ul class="dropdown-menu dropdown-menu-end"></ul>';
        const menu = dropdown.querySelector(".dropdown-menu");

        moveNodes.forEach(function (node) {
            menu.appendChild(buildDropdownItem(node));
            node.remove();
        });

        group.appendChild(dropdown);
        group.setAttribute("data-op-prod-delivery-collapsed", "true");
        group.setAttribute("data-direct-action-count", String(keepSet.size));
        group.setAttribute("data-dropdown-action-count", String(moveNodes.length));
    });

    const stepMap = [
        ["/operational/daily-log", "daily-log"],
        ["/operational/monthly-recap", "monthly-recap"],
        ["/operational/orders", "order"],
        ["/production", "production"],
        ["/delivery/today", "today"],
        ["/delivery/receiving", "today"],
        ["/delivery", "delivery"]
    ];
    const activeStep = (stepMap.find(function (row) { return path.indexOf(row[0]) === 0; }) || [null, null])[1];
    if (activeStep) {
        document.querySelectorAll('[data-op-prod-delivery-step="' + activeStep + '"]').forEach(function (step) {
            step.classList.add("is-active");
            step.setAttribute("aria-current", "page");
        });
    }

    document.querySelectorAll(".op-prod-delivery-page-shell .app-table td, .op-prod-delivery-page-shell .app-table th, .op-prod-delivery-page-shell .table-sm td, .op-prod-delivery-page-shell .table-sm th").forEach(function (cell) {
        const text = cleanText(cell);
        if (/Rp\s?[0-9.]+|^[0-9.]+(,[0-9]{2})?$/.test(text) || /harga|price|tagihan|invoice|total|amount/i.test(text)) {
            cell.classList.add("op-prod-delivery-money");
            cell.setAttribute("data-op-prod-delivery-money", "true");
        }
        if (/^[0-9.]+([,][0-9]+)?\s?(porsi|box|pak|kg|pcs)?$/i.test(text) || /qty|porsi|lunch|dinner|planned|delivered|shortage|lokasi|mandor/i.test(text)) {
            cell.classList.add("op-prod-delivery-qty");
            cell.setAttribute("data-op-prod-delivery-qty", "true");
        }
    });

    document.querySelectorAll(".op-prod-delivery-page-shell .table-responsive").forEach(function (wrapper) {
        wrapper.setAttribute("data-op-prod-delivery-table", "UI");
        if (!wrapper.nextElementSibling || !wrapper.nextElementSibling.classList || !wrapper.nextElementSibling.classList.contains("op-prod-delivery-mobile-hint")) {
            const hint = document.createElement("div");
            hint.className = "op-prod-delivery-mobile-hint";
            hint.textContent = "Geser tabel ke samping untuk melihat detail order, produksi, dan delivery lengkap.";
            wrapper.insertAdjacentElement("afterend", hint);
        }
    });

    document.querySelectorAll(".op-prod-delivery-page-shell table").forEach(function (table) {
        if (!table.hasAttribute("data-op-prod-delivery-table-normalized")) {
            table.setAttribute("data-op-prod-delivery-table-normalized", "UI");
        }
    });
});


// ==================================================
// UI HR + Master + Settings Global polish Controller
// - Keeps HR/master/settings actions compact.
// - Adds active HR/master/settings flow, number/money alignment, and mobile table hints.
// - Does not change routes, forms, methods, or database data.
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    const body = document.body;
    const endpoint = body ? (body.getAttribute("data-endpoint") || "") : "";
    const path = window.location.pathname || "";
    const isHrMasterSettingsPage = body && (
        endpoint.indexOf("hr.") === 0 ||
        endpoint.indexOf("master.") === 0 ||
        endpoint.indexOf("settings.") === 0 ||
        path.indexOf("/hr") === 0 ||
        path.indexOf("/master") === 0 ||
        path.indexOf("/settings") === 0
    );
    if (!isHrMasterSettingsPage) return;

    body.classList.add("is-hr-master-settings-polish");
    body.setAttribute("data-hr-master-settings-polish", "UI");

    function cleanText(node) {
        return (node.textContent || "").replace(/\s+/g, " ").trim();
    }

    function directActionNodes(group) {
        return Array.from(group.children).filter(function (child) {
            if (child.classList && (child.classList.contains("app-action-dropdown") || child.classList.contains("hr-master-settings-more-dropdown"))) return false;
            if (child.matches && child.matches("a.btn, button.btn")) return true;
            if (child.matches && child.matches("form")) return false;
            return false;
        });
    }

    function actionImportance(node) {
        const text = cleanText(node).toLowerCase();
        if (node.querySelector && node.querySelector(".app-btn-primary, .btn-primary")) return 10;
        if (node.matches && node.matches(".app-btn-primary, .btn-primary")) return 10;
        if (text.includes("simpan") || text.includes("buat") || text.includes("tambah") || text.includes("validasi")) return 9;
        if (text.includes("backup") || text.includes("restore") || text.includes("generate") || text.includes("finalisasi")) return 8;
        if (text.includes("filter") || text.includes("cari")) return 7;
        if (text.includes("riwayat") || text.includes("audit") || text.includes("detail")) return 6;
        if (text.includes("kembali") || text.includes("reset") || text.includes("batal")) return 3;
        return 5;
    }

    function buttonLike(node) {
        if (node.matches && node.matches("a.btn, button.btn")) return node;
        if (node.querySelector) return node.querySelector("button.btn, .btn");
        return null;
    }

    function buildDropdownItem(node) {
        const button = buttonLike(node);
        const item = document.createElement("li");
        const clone = node.cloneNode(true);
        if (clone.matches && clone.matches("a.btn")) {
            clone.className = "dropdown-item";
        } else if (clone.matches && clone.matches("button.btn")) {
            clone.className = "dropdown-item";
            clone.setAttribute("type", clone.getAttribute("type") || "button");
        } else if (clone.matches && clone.matches("form")) {
            clone.classList.add("m-0");
            const inner = clone.querySelector("button.btn, .btn");
            if (inner) inner.className = "dropdown-item";
        } else if (button) {
            clone.classList.add("dropdown-item");
        }
        item.appendChild(clone);
        return item;
    }

    document.querySelectorAll(".hr-master-settings-page-shell .page-actions, .hr-master-settings-page-shell .page-header > .d-flex, .hr-master-settings-header-actions").forEach(function (group) {
        group.classList.add("hr-master-settings-header-actions");
        group.setAttribute("data-hr-master-settings-actions", "UI");
        const direct = directActionNodes(group);
        if (direct.length <= 2) return;

        const sorted = direct.map(function (node, index) {
            return { node: node, index: index, score: actionImportance(node) };
        }).sort(function (a, b) {
            if (b.score !== a.score) return b.score - a.score;
            return a.index - b.index;
        });

        const keepSet = new Set(sorted.slice(0, 2).map(function (item) { return item.node; }));
        const moveNodes = direct.filter(function (node) { return !keepSet.has(node); });
        if (!moveNodes.length) return;

        const dropdown = document.createElement("div");
        dropdown.className = "dropdown app-action-dropdown hr-master-settings-more-dropdown";
        dropdown.innerHTML = '<button class="btn app-btn-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false"><i class="bi bi-three-dots"></i> Aksi lainnya</button><ul class="dropdown-menu dropdown-menu-end"></ul>';
        const menu = dropdown.querySelector(".dropdown-menu");

        moveNodes.forEach(function (node) {
            menu.appendChild(buildDropdownItem(node));
            node.remove();
        });

        group.appendChild(dropdown);
        group.setAttribute("data-hr-master-settings-collapsed", "true");
        group.setAttribute("data-direct-action-count", String(keepSet.size));
        group.setAttribute("data-dropdown-action-count", String(moveNodes.length));
    });

    const activeStep = endpoint.indexOf("hr.") === 0 ? "hr" :
        endpoint.indexOf("master.") === 0 ? "master" :
        (endpoint.indexOf("settings.audit") === 0 || endpoint.indexOf("settings.digital") === 0) ? "audit" :
        endpoint.indexOf("settings.backup") === 0 ? "backup" :
        (endpoint.indexOf("settings.notification") === 0 || endpoint.indexOf("settings.live_reminders") === 0) ? "reminder" :
        endpoint.indexOf("settings.user") === 0 ? "users" : null;
    if (activeStep) {
        document.querySelectorAll('[data-hr-master-settings-step="' + activeStep + '"]').forEach(function (step) {
            step.classList.add("is-active");
            step.setAttribute("aria-current", "page");
        });
    }

    document.querySelectorAll(".hr-master-settings-page-shell .app-table td, .hr-master-settings-page-shell .app-table th, .hr-master-settings-page-shell .table-sm td, .hr-master-settings-page-shell .table-sm th").forEach(function (cell) {
        const text = cleanText(cell);
        if (/Rp\s?[0-9.]+|^[0-9.]+(,[0-9]{2})?$/.test(text) || /gaji|salary|upah|payroll|total|amount|nominal|saldo|harga|nilai|aset|depresiasi/i.test(text)) {
            cell.classList.add("hr-master-settings-money");
            cell.setAttribute("data-hr-master-settings-money", "true");
        }
        if (/^[0-9.]+([,][0-9]+)?\s?(hari|jam|orang|file|baris|item|bulan)?$/i.test(text) || /qty|jumlah|count|stok|umur|hari|bulan|file|role|status/i.test(text)) {
            cell.classList.add("hr-master-settings-qty");
            cell.setAttribute("data-hr-master-settings-qty", "true");
        }
    });

    document.querySelectorAll(".hr-master-settings-page-shell .table-responsive").forEach(function (wrapper) {
        wrapper.setAttribute("data-hr-master-settings-table", "UI");
        if (!wrapper.nextElementSibling || !wrapper.nextElementSibling.classList || !wrapper.nextElementSibling.classList.contains("hr-master-settings-mobile-hint")) {
            const hint = document.createElement("div");
            hint.className = "hr-master-settings-mobile-hint";
            hint.textContent = "Geser tabel ke samping untuk melihat detail HR, master data, setting, audit, atau lampiran lengkap.";
            wrapper.insertAdjacentElement("afterend", hint);
        }
    });

    document.querySelectorAll(".hr-master-settings-page-shell table").forEach(function (table) {
        if (!table.hasAttribute("data-hr-master-settings-table-normalized")) {
            table.setAttribute("data-hr-master-settings-table-normalized", "UI");
        }
    });
});


// ==================================================
// UI Android/Mobile Browser Global polish Controller
// - Strengthens mobile offcanvas behavior, touch targets, controlled tables,
//   full-width filters/actions, and overflow risk detection.
// - Does not change routes, form methods, database data, or theme choices.
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    const body = document.body;
    if (!body) return;

    const mobileQuery = window.matchMedia("(max-width: 767.98px)");
    const tabletQuery = window.matchMedia("(max-width: 1023.98px)");
    const sidebar = document.getElementById("appSidebar");
    const backdrop = document.getElementById("sidebarBackdrop");
    const toggle = document.getElementById("sidebarToggle");

    body.setAttribute("data-mobile-polish", "UI");

    function setMobileFlags() {
        body.toggleAttribute("data-is-mobile-browser", mobileQuery.matches);
        body.toggleAttribute("data-is-tablet-browser", !mobileQuery.matches && tabletQuery.matches);
        if (!tabletQuery.matches && sidebar) {
            sidebar.classList.remove("is-open", "show");
            body.classList.remove("sidebar-open");
            if (backdrop) backdrop.classList.remove("is-visible");
            if (toggle) toggle.setAttribute("aria-expanded", "false");
        }
    }

    function markControls() {
        document.querySelectorAll(".page-actions, .page-header > .d-flex, .app-form-actions, .form-actions, .table-actions, [data-row-actions]").forEach(function (group) {
            group.setAttribute("data-mobile-actions", "UI");
        });

        document.querySelectorAll("form[data-form-kind='filter'], .app-filter-form, .filter-bar, .filter-card form, .table-toolbar form").forEach(function (filter) {
            filter.setAttribute("data-mobile-filter", "UI");
        });

        document.querySelectorAll(".form-grid, .app-form-grid, .summary-grid, .kpi-grid, .info-grid, .detail-grid").forEach(function (grid) {
            grid.setAttribute("data-mobile-grid", "UI");
        });

        document.querySelectorAll(".btn, .dropdown-item, .form-control, .form-select, .sidebar-link, .sidebar-group-toggle").forEach(function (node) {
            node.setAttribute("data-mobile-touch-target", "UI");
        });
    }

    function strengthenTables() {
        document.querySelectorAll("table.app-data-table, .app-table-wrap table, .table-responsive table, .table-wrapper table, .data-table-wrapper table").forEach(function (table) {
            if (table.closest(".print-page, .print-sheet, [data-print-page], .print-container")) return;
            table.setAttribute("data-mobile-browser-checked", "UI");
            const wrapper = table.closest(".app-table-wrap, .table-responsive, .table-wrapper, .data-table-wrapper");
            const headerCount = table.querySelectorAll("thead tr:first-child th, thead tr:first-child td").length;
            const hasComplexSpan = !!table.querySelector("thead tr:nth-child(2), tbody td[rowspan], tbody th[rowspan], tbody td[colspan]:not([colspan='1']), tbody th[colspan]:not([colspan='1'])");
            const mode = hasComplexSpan || headerCount > 7 ? "scroll" : (table.getAttribute("data-mobile-table") || "card");
            table.setAttribute("data-mobile-table", mode);
            if (wrapper) {
                wrapper.setAttribute("data-mobile-table", mode);
                wrapper.setAttribute("data-mobile-browser-checked", "UI");
                if (mode === "scroll" && !wrapper.querySelector(":scope > .app-table-scroll-hint")) {
                    const hint = document.createElement("div");
                    hint.className = "app-table-scroll-hint";
                    hint.textContent = "Geser tabel ke samping untuk melihat detail lengkap.";
                    wrapper.insertBefore(hint, table);
                }
            }
        });
    }

    function closeSidebarOnMobileLink() {
        if (!sidebar) return;
        sidebar.querySelectorAll("a.sidebar-link").forEach(function (link) {
            if (link.getAttribute("data-mobile-close-bound") === "UI") return;
            link.setAttribute("data-mobile-close-bound", "UI");
            link.addEventListener("click", function () {
                if (!tabletQuery.matches) return;
                sidebar.classList.remove("is-open", "show");
                body.classList.remove("sidebar-open");
                if (backdrop) backdrop.classList.remove("is-visible");
                if (toggle) toggle.setAttribute("aria-expanded", "false");
            });
        });
    }

    function detectOverflowRisk() {
        if (!mobileQuery.matches) {
            body.removeAttribute("data-mobile-overflow-risk");
            return;
        }
        const root = document.documentElement;
        const hasRisk = root.scrollWidth > root.clientWidth + 2;
        body.toggleAttribute("data-mobile-overflow-risk", hasRisk);
        if (hasRisk && !document.querySelector(".mobile-overflow-warning")) {
            const main = document.getElementById("mainContent");
            if (main) {
                const warning = document.createElement("div");
                warning.className = "mobile-overflow-warning";
                warning.textContent = "Ada area data lebar. Gunakan geser tabel terkontrol untuk melihat detail.";
                main.insertBefore(warning, main.firstChild);
            }
        }
    }

    setMobileFlags();
    markControls();
    strengthenTables();
    closeSidebarOnMobileLink();
    window.setTimeout(detectOverflowRisk, 120);

    if (mobileQuery.addEventListener) {
        mobileQuery.addEventListener("change", function () {
            setMobileFlags();
            window.setTimeout(detectOverflowRisk, 80);
        });
        tabletQuery.addEventListener("change", setMobileFlags);
    } else if (mobileQuery.addListener) {
        mobileQuery.addListener(setMobileFlags);
        tabletQuery.addListener(setMobileFlags);
    }

    window.addEventListener("resize", function () {
        setMobileFlags();
        window.setTimeout(detectOverflowRisk, 80);
    });
});


// ==================================================
// Action Cleanup Batch Controller
// - Finalizes action dropdown consistency after N2N static check.
// - Marks print/export tables as controlled scroll on mobile.
// - Strengthens empty/error state visibility without changing routes or DB.
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    const body = document.body;
    if (body) body.setAttribute("data-ui-cleanup-batch", "UI");

    function actionText(node) {
        return (node && (node.innerText || node.textContent) || "").trim().toLowerCase();
    }

    function actionScore(node) {
        const text = actionText(node);
        const cls = (node.getAttribute && node.getAttribute("class") || "").toLowerCase();
        if (/simpan|buat|tambah|bayar|cetak|save pdf|generate/.test(text) || cls.includes("app-btn-primary")) return 100;
        if (/kembali|batal|tutup/.test(text) || cls.includes("app-btn-ghost")) return 80;
        if (/hapus|delete|batalkan|void/.test(text) || cls.includes("app-btn-danger")) return 10;
        return 60;
    }

    function directActions(group) {
        return Array.from(group.children).filter(function (node) {
            if (!node.matches) return false;
            if (node.matches(".dropdown, .app-action-dropdown, [data-action-dropdown]")) return false;
            if (node.querySelector && node.querySelector(".dropdown-menu")) return false;
            if (node.matches("a.btn, button.btn")) return true;
            return false;
        });
    }

    function dropdownItem(node) {
        const li = document.createElement("li");
        const clone = node.cloneNode(true);
        if (clone.matches && clone.matches("a.btn")) {
            clone.className = "dropdown-item";
        } else if (clone.matches && clone.matches("button.btn")) {
            clone.className = "dropdown-item";
            clone.type = clone.type || "button";
        } else if (clone.matches && clone.matches("form")) {
            clone.classList.add("m-0");
            const inner = clone.querySelector("button.btn, .btn");
            if (inner) inner.className = "dropdown-item";
        }
        li.appendChild(clone);
        return li;
    }

    function collapseActionGroup(group) {
        if (!group || group.getAttribute("data-action-collapse") === "done") return;
        const direct = directActions(group);
        if (direct.length <= 2) {
            group.setAttribute("data-action-collapse", "not-needed");
            return;
        }
        const ranked = direct.map(function (node, index) {
            return { node: node, index: index, score: actionScore(node) };
        }).sort(function (a, b) {
            if (b.score !== a.score) return b.score - a.score;
            return a.index - b.index;
        });
        const keep = new Set(ranked.slice(0, 2).map(function (x) { return x.node; }));
        const move = direct.filter(function (node) { return !keep.has(node); });
        if (!move.length) return;

        const dropdown = document.createElement("div");
        dropdown.className = "dropdown app-action-dropdown app-more-dropdown";
        dropdown.setAttribute("data-action-dropdown", "true");
        dropdown.innerHTML = '<button class="btn app-btn-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false"><i class="bi bi-three-dots"></i> Aksi lainnya</button><ul class="dropdown-menu dropdown-menu-end"></ul>';
        const menu = dropdown.querySelector(".dropdown-menu");
        move.forEach(function (node) {
            menu.appendChild(dropdownItem(node));
            node.remove();
        });
        group.appendChild(dropdown);
        group.setAttribute("data-action-collapse", "done");
        group.setAttribute("data-direct-action-count", String(keep.size));
        group.setAttribute("data-dropdown-action-count", String(move.length));
    }

    document.querySelectorAll(".page-actions, .page-header > .d-flex, .finance-header-actions, .accounting-header-actions, .logistics-hpp-header-actions, .op-prod-delivery-header-actions, .hr-master-settings-header-actions").forEach(collapseActionGroup);

    document.querySelectorAll(".print-report-shell table, .finance-print-shell table, .accounting-print-shell table, .print-page table").forEach(function (table) {
        table.classList.add("app-data-table");
        table.setAttribute("data-mobile-table", table.getAttribute("data-mobile-table") || "scroll");
        table.setAttribute("data-print-table-normalized", "true");
        const wrapper = table.closest(".table-responsive, .app-table-wrap, .print-table-wrap");
        if (wrapper) wrapper.setAttribute("data-mobile-table", "scroll");
    });

    document.querySelectorAll(".empty-state").forEach(function (state) {
        state.setAttribute("data-empty-state-normalized", "true");
    });
});


// ==================================================
// UI Catch-up Controller
// Auth/Error/Empty/Loading/Print/Export polish without changing business logic.
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    const body = document.body;
    if (body) body.setAttribute("data-ui-catchup", "UI");

    function textOf(node) {
        return (node && (node.innerText || node.textContent) || "").trim();
    }

    function markEmptyStates() {
        document.querySelectorAll(".app-empty-state, .empty-state, [data-empty-state='true']").forEach(function (state) {
            state.setAttribute("data-ui-empty-state", "UI");
        });

        document.querySelectorAll("table.app-data-table, .app-table-wrap table, .table-responsive table").forEach(function (table) {
            const tbody = table.querySelector("tbody");
            if (!tbody) return;
            const rows = Array.from(tbody.querySelectorAll("tr"));
            const meaningfulRows = rows.filter(function (row) {
                const content = textOf(row).toLowerCase();
                return content && !/belum ada|tidak ada data|data belum tersedia|kosong/.test(content);
            });
            if (rows.length === 0 || meaningfulRows.length === 0) {
                table.setAttribute("data-ui-empty-table", "UI");
                const wrapper = table.closest(".app-table-wrap, .table-responsive, .table-wrapper, .data-table-wrapper");
                const hasTemplateEmptyState = !!table.querySelector(".empty-state, .app-empty-state, [data-ui-empty-state]");
                if (wrapper) {
                    wrapper.setAttribute("data-ui-empty-wrapper", "UI");
                    if (hasTemplateEmptyState) {
                        wrapper.querySelectorAll(":scope > .app-empty-table-hint").forEach(function (hint) { hint.remove(); });
                        return;
                    }
                }
                if (wrapper && !wrapper.querySelector(":scope > .app-empty-table-hint")) {
                    const hint = document.createElement("div");
                    hint.className = "app-empty-state app-empty-table-hint";
                    hint.setAttribute("data-ui-empty-state", "UI");
                    hint.innerHTML = '<div class="empty-state-icon"><i class="bi bi-inbox" aria-hidden="true"></i></div><h3>Data belum ada</h3><p>Belum ada data yang bisa ditampilkan untuk filter atau periode ini.</p>';
                    wrapper.appendChild(hint);
                }
            }
        });
    }

    function markPrintExport() {
        document.querySelectorAll(".print-report-shell, .finance-print-shell, .accounting-print-shell, .print-page").forEach(function (node) {
            node.setAttribute("data-ui-print-export", "UI");
        });
        document.querySelectorAll("a[href*='export'], a[href*='csv'], a[href*='download'], button[onclick*='print'], .print-actions").forEach(function (node) {
            const group = node.closest(".page-actions, .print-actions, .no-print, .d-flex") || node.parentElement;
            if (group) group.setAttribute("data-ui-export-actions", "UI");
        });
    }

    function bindLoadingStates() {
        document.querySelectorAll("form").forEach(function (form) {
            if (form.getAttribute("data-loading-bound") === "true") return;
            form.setAttribute("data-loading-bound", "true");
            form.addEventListener("submit", function () {
                const button = form.querySelector("button[type='submit'], input[type='submit']");
                if (!button) return;
                const original = button.getAttribute("data-original-label") || textOf(button) || "Memproses...";
                button.setAttribute("data-original-label", original);
                button.setAttribute("data-submit-loading", "true");
                button.setAttribute("aria-busy", "true");
                const loadingLabel = button.getAttribute("data-submit-loading-label") || button.getAttribute("data-submit-loading") || "Memproses...";
                if (button.tagName.toLowerCase() === "button") {
                    button.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>' + loadingLabel;
                } else {
                    button.value = loadingLabel;
                }
            });
        });
    }

    markEmptyStates();
    markPrintExport();
    bindLoadingStates();
});


// ==================================================
// UI Dashboard Chart UI Partial Controller
// Marks Owner/Admin analytics charts as initialized and keeps chart overflow controlled.
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    const section = document.querySelector("[data-dashboard-bar-analytics='true']");
    if (!section) return;

    section.setAttribute("data-dashboard-bar-ready", "true");

    section.querySelectorAll(".dashboard-bar-plot").forEach(function (plot) {
        plot.setAttribute("data-mobile-table", "scroll");
        plot.setAttribute("tabindex", "0");
    });

    section.querySelectorAll(".dashboard-chart-card").forEach(function (card) {
        card.setAttribute("data-chart-ui", "UI");
    });
});


// ==================================================
// UI Revenue vs Spending Bar Chart Controller
// Keeps the grouped monthly bar chart scroll-safe, keyboard reachable, and tagged
// as read-only production analytics.
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    const section = document.querySelector("[data-revenue-spending-analytics='true']");
    if (!section) return;

    section.setAttribute("data-revenue-spending-ready", "true");

    section.querySelectorAll("[data-revenue-spending-bar-chart='true']").forEach(function (card) {
        card.setAttribute("data-chart-ui", "UI");
        card.setAttribute("data-chart-readonly", "true");
    });

    section.querySelectorAll(".dashboard-bar-plot-pro").forEach(function (plot) {
        plot.setAttribute("data-mobile-table", "scroll");
        plot.setAttribute("tabindex", "0");
        plot.setAttribute("aria-live", "polite");
    });

    section.querySelectorAll(".dashboard-bar").forEach(function (bar) {
        bar.setAttribute("data-dashboard-chart-bar", "true");
    });
});


// ==================================================
// UI Operational Efficiency Donut Chart Controller
// Read-only UI polish only: no data mutation, no network write.
// ==================================================
(function () {
    const analyticsSections = document.querySelectorAll('[data-operational-efficiency-analytics="true"]');
    analyticsSections.forEach((section) => {
        const donutCard = section.querySelector('[data-operational-efficiency-donut-chart="true"]');
        if (!donutCard) return;

        donutCard.querySelectorAll('.dashboard-donut-metric').forEach((metric) => {
            metric.setAttribute('data-ui-action', 'drilldown');
        });
    });
})();

// ==================================================
// UI Mobile + Theme Compliance Polish Controller
// Keeps dashboard analytics scroll-safe on Android/mobile and enforces 2-theme fallback.
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    const allowedThemes = ["dark-mono", "light-mono"];
    const legacyThemeMap = {
        "dark-enterprise": "dark-mono",
        "light-clean": "light-mono",
        "clear-focus": "light-mono",
        "azure-calm": "light-mono",
        "bright": "light-mono",
        "clear": "light-mono",
        "good": "light-mono"
    };
    const root = document.documentElement;
    const currentTheme = root.getAttribute("data-theme") || "light-mono";
    if (allowedThemes.indexOf(currentTheme) === -1) {
        root.setAttribute("data-theme", legacyThemeMap[currentTheme] || "light-mono");
    }

    document.body.setAttribute("data-mobile-theme-ready", "true");

    document.querySelectorAll('[data-mobile-theme="true"]').forEach(function (section) {
        section.setAttribute("data-mobile-theme-section-ready", "true");
        section.setAttribute("data-theme-compliance", "black-white-two-mode-token-system");

        section.querySelectorAll(".dashboard-chart-card").forEach(function (card) {
            card.setAttribute("data-theme-aware", "true");
            card.setAttribute("data-mobile-safe", "true");
        });

        section.querySelectorAll(".dashboard-bar-chart-pro, .dashboard-bar-plot-pro").forEach(function (node) {
            node.setAttribute("data-mobile-overflow", "contained-scroll");
            node.setAttribute("tabindex", "0");
        });

        section.querySelectorAll(".dashboard-filter-select, .dashboard-filter-submit, .dashboard-checkbox-chip, .dashboard-donut-metric, .dashboard-chart-menu .btn-icon").forEach(function (node) {
            node.setAttribute("data-touch-target", "44px");
        });
    });
});


// ==================================================
// UI Optional Advance / DP Flow Controller
// Menjaga pilihan pihak tetap sesuai dan field bank tetap bersih.
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    const advanceType = document.getElementById("advanceType");
    const paymentMethod = document.getElementById("advancePaymentMethod");
    const bankWrap = document.getElementById("advanceBankWrap");

    function updateAdvancePartyFields() {
        if (!advanceType) return;
        const selected = advanceType.options[advanceType.selectedIndex];
        const party = selected ? selected.getAttribute("data-party") : "";
        document.querySelectorAll("[data-party-field]").forEach(function (field) {
            const shouldShow = field.getAttribute("data-party-field") === party;
            field.style.display = shouldShow ? "" : "none";
            field.querySelectorAll("select, input").forEach(function (input) {
                input.required = shouldShow;
                if (!shouldShow) input.value = "";
            });
        });
    }

    function updateAdvanceBankField() {
        if (!paymentMethod || !bankWrap) return;
        const isTransfer = paymentMethod.value === "TRANSFER";
        bankWrap.style.display = isTransfer ? "" : "none";
        bankWrap.querySelectorAll("select, input").forEach(function (input) {
            input.required = isTransfer;
            if (!isTransfer) input.value = "";
        });
    }

    if (advanceType) {
        advanceType.addEventListener("change", updateAdvancePartyFields);
        updateAdvancePartyFields();
    }

    if (paymentMethod) {
        paymentMethod.addEventListener("change", updateAdvanceBankField);
        updateAdvanceBankField();
    }
});

// ==================================================
// UI Transport & Vehicle Fuel Expense COA Mapping Controller
// Menjaga field bank tetap kondisional dan penanda BBM tetap sesuai.
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    const expenseType = document.getElementById("transportExpenseType");
    const paymentMethod = document.getElementById("transportExpensePaymentMethod");
    const bankWrap = document.getElementById("transportExpenseBankWrap");

    function updateTransportBankField() {
        if (!paymentMethod || !bankWrap) return;
        const isTransfer = paymentMethod.value === "TRANSFER";
        bankWrap.style.display = isTransfer ? "" : "none";
        bankWrap.querySelectorAll("select, input").forEach(function (input) {
            input.required = isTransfer;
            if (!isTransfer) input.value = "";
        });
    }

    function updateFuelTraceHint() {
        if (!expenseType) return;
        const isFuel = expenseType.value === "VEHICLE_FUEL";
        document.querySelectorAll("input[name='vehicle_label'], select[name='driver_id'], select[name='delivery_id']").forEach(function (input) {
            input.setAttribute("data-trace-priority", isFuel ? "required-one-of" : "optional");
        });
    }

    if (paymentMethod) {
        paymentMethod.addEventListener("change", updateTransportBankField);
        updateTransportBankField();
    }

    if (expenseType) {
        expenseType.addEventListener("change", updateFuelTraceHint);
        updateFuelTraceHint();
    }
});


// ==================================================
// Accounting Precision Polish Controller
// UI-only: previews selected COA mapping and marks precision panels as ready.
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-accounting-precision]").forEach(function (panel) {
        panel.setAttribute("data-accounting-precision-ready", "true");
    });

    document.querySelectorAll("select option[data-account]").forEach(function (option) {
        const select = option.closest("select");
        if (select) {
            select.setAttribute("data-coa-resolver", "true");
        }
    });

    function updateCoaPreview(select) {
        if (!select) return;
        const group = select.closest(".col-md-4, .col-md-6, .col-12, .form-section, .app-card") || select.parentElement;
        const preview = group ? group.querySelector("[data-coa-preview]") : null;
        if (!preview) return;
        const selected = select.options[select.selectedIndex];
        const account = selected ? selected.getAttribute("data-account") : "";
        const label = selected ? selected.textContent.trim() : "";
        if (account) {
            preview.textContent = "Akun COA otomatis: " + account + " — " + label;
            preview.setAttribute("data-state", "ready");
        } else {
            preview.textContent = "Pilih kategori/jenis biaya untuk melihat akun COA otomatis.";
            preview.removeAttribute("data-state");
        }
    }

    document.querySelectorAll("select[data-coa-resolver='true']").forEach(function (select) {
        select.addEventListener("change", function () { updateCoaPreview(select); });
        updateCoaPreview(select);
    });

    document.querySelectorAll("[data-accounting-precision-ready='true'] table").forEach(function (table) {
        table.classList.add("app-table");
        const wrap = table.closest(".table-responsive");
        if (wrap && !wrap.hasAttribute("data-mobile-table")) {
            wrap.setAttribute("data-mobile-table", "scroll");
        }
    });
});

// ==================================================
// UI Unified Finance Transaction Input Controller
// UI-only: show the correct section, keep required fields precise, and prevent sidebar-style scattered input.
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    const form = document.querySelector("[data-unified-finance-form='true']");
    if (!form) return;

    const kindSelect = form.querySelector("#unifiedTransactionKind");
    const paymentMethod = form.querySelector("#unifiedPaymentMethod");
    const bankWrap = form.querySelector("#unifiedBankWrap");
    const advanceType = form.querySelector("#unifiedAdvanceType");

    function currentKind() {
        return kindSelect ? kindSelect.value : "ADVANCE";
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
        updateAdvancePartyFields();
    }

    function updateBankField() {
        if (!paymentMethod || !bankWrap) return;
        const isTransfer = paymentMethod.value === "TRANSFER";
        bankWrap.style.display = isTransfer ? "" : "none";
        bankWrap.querySelectorAll("select, input").forEach(function (input) {
            input.required = isTransfer;
            if (!isTransfer) input.value = "";
        });
    }

    function updateAdvancePartyFields() {
        if (!advanceType) return;
        const selected = advanceType.options[advanceType.selectedIndex];
        const party = selected ? selected.getAttribute("data-party") : "";
        const isAdvance = currentKind() === "ADVANCE";
        form.querySelectorAll(".unified-advance-party[data-party-field]").forEach(function (field) {
            const shouldShow = isAdvance && field.getAttribute("data-party-field") === party;
            field.hidden = !shouldShow;
            field.querySelectorAll("select, input").forEach(function (input) {
                input.required = shouldShow;
                if (!shouldShow) input.value = "";
            });
        });
    }

    if (kindSelect) kindSelect.addEventListener("change", updateSections);
    if (paymentMethod) paymentMethod.addEventListener("change", updateBankField);
    if (advanceType) advanceType.addEventListener("change", updateAdvancePartyFields);

    updateSections();
    updateBankField();
});

// ==================================================
// Motion and micro-interaction controller
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    const body = document.body;
    if (!body) return;

    const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) {
        body.setAttribute("data-motion-ready", "reduced");
        body.classList.add("ui-motion-reduced");
        return;
    }

    body.setAttribute("data-motion-ready", "true");

    window.requestAnimationFrame(function () {
        body.classList.add("ui-motion-ready");
    });

    const watchedSelectors = [
        ".app-page-header",
        ".app-stat-card",
        ".app-card",
        ".dashboard-chart-card",
        ".dashboard-summary-card",
        ".dashboard-table-card",
        ".table-responsive",
        ".form-section",
        ".filter-card",
        ".empty-state"
    ].join(",");

    const watchedNodes = Array.prototype.slice.call(document.querySelectorAll(watchedSelectors)).slice(0, 96);
    watchedNodes.forEach(function (node, index) {
        if (!node.classList.contains("motion-watch")) {
            node.classList.add("motion-watch");
        }
        node.style.setProperty("--motion-index", String(index % 9));
    });

    if ("IntersectionObserver" in window) {
        const observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add("is-motion-visible");
                    observer.unobserve(entry.target);
                }
            });
        }, { rootMargin: "0px 0px -6% 0px", threshold: 0.04 });

        watchedNodes.forEach(function (node) {
            observer.observe(node);
        });
    } else {
        watchedNodes.forEach(function (node) {
            node.classList.add("is-motion-visible");
        });
    }

    document.addEventListener("pointerdown", function (event) {
        const target = event.target.closest(".app-btn, .btn, button, .sidebar-link, .sidebar-group-toggle, .dropdown-item, .theme-mode-option, .page-link");
        if (!target) return;
        target.classList.add("is-pressing");
        window.setTimeout(function () {
            target.classList.remove("is-pressing");
        }, 140);
    }, { passive: true });

    document.addEventListener("pointerup", function (event) {
        const target = event.target.closest(".is-pressing");
        if (target) target.classList.remove("is-pressing");
    }, { passive: true });

    document.addEventListener("pointercancel", function () {
        document.querySelectorAll(".is-pressing").forEach(function (node) {
            node.classList.remove("is-pressing");
        });
    }, { passive: true });

    document.querySelectorAll("details.sidebar-group").forEach(function (group) {
        group.setAttribute("data-accordion-motion", "ready");
        group.addEventListener("toggle", function () {
            group.setAttribute("data-accordion-state", group.open ? "open" : "closed");
        });
        group.setAttribute("data-accordion-state", group.open ? "open" : "closed");
    });
});

// ==================================================
// Scroll Restoration + No-Jump Navigation Controller
// - preserves list position when returning from detail pages
// - keeps filter, pagination, tabs, and anchors near the active work area
// - uses session storage only and does not change routes or submitted data
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    const body = document.body;
    if (!body || !window.history) return;

    const SCROLL_PREFINAL = "idha_boga_scroll:";
    const TAB_PREFINAL = "idha_boga_tab:";
    const PENDING_KEY = "idha_boga_pending_scroll";
    const MAX_RESTORE_AGE = 30 * 60 * 1000;
    const SAVE_THROTTLE = 140;
    const TOP_OFFSET = 84;
    let saveTimer = null;
    let restored = false;

    try {
        if ("scrollRestoration" in window.history) {
            window.history.scrollRestoration = "manual";
        }
    } catch (error) {
        return;
    }

    function canStore() {
        try {
            const key = "idha_boga_storage_check";
            window.sessionStorage.setItem(key, "1");
            window.sessionStorage.removeItem(key);
            return true;
        } catch (error) {
            return false;
        }
    }

    if (!canStore()) return;

    function pageKey(urlValue) {
        const url = new URL(urlValue || window.location.href, window.location.href);
        return url.pathname + url.search;
    }

    function storageKey(urlValue) {
        return SCROLL_PREFINAL + pageKey(urlValue);
    }

    function now() {
        return Date.now ? Date.now() : new Date().getTime();
    }

    function clampScroll(value) {
        const maxY = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
        return Math.max(0, Math.min(Number(value) || 0, maxY));
    }

    function saveCurrentScroll() {
        try {
            window.sessionStorage.setItem(storageKey(window.location.href), JSON.stringify({
                y: Math.round(window.scrollY || window.pageYOffset || 0),
                ts: now()
            }));
        } catch (error) {
            return;
        }
    }

    function scheduleSave() {
        if (saveTimer) return;
        saveTimer = window.setTimeout(function () {
            saveTimer = null;
            saveCurrentScroll();
        }, SAVE_THROTTLE);
    }

    function setPendingScroll(payload) {
        try {
            payload.ts = now();
            window.sessionStorage.setItem(PENDING_KEY, JSON.stringify(payload));
        } catch (error) {
            return;
        }
    }

    function getPendingScroll() {
        try {
            const raw = window.sessionStorage.getItem(PENDING_KEY);
            if (!raw) return null;
            const payload = JSON.parse(raw);
            if (!payload || !payload.ts || now() - payload.ts > MAX_RESTORE_AGE) {
                window.sessionStorage.removeItem(PENDING_KEY);
                return null;
            }
            return payload;
        } catch (error) {
            return null;
        }
    }

    function clearPendingScroll() {
        try {
            window.sessionStorage.removeItem(PENDING_KEY);
        } catch (error) {
            return;
        }
    }

    function readSavedScroll(urlValue) {
        try {
            const raw = window.sessionStorage.getItem(storageKey(urlValue));
            if (!raw) return null;
            const payload = JSON.parse(raw);
            if (!payload || typeof payload.y === "undefined" || !payload.ts) return null;
            if (now() - payload.ts > MAX_RESTORE_AGE) return null;
            return payload;
        } catch (error) {
            return null;
        }
    }

    function navigationType() {
        try {
            const entries = window.performance && window.performance.getEntriesByType ? window.performance.getEntriesByType("navigation") : [];
            if (entries && entries.length && entries[0].type) return entries[0].type;
        } catch (error) {
            return "navigate";
        }
        return "navigate";
    }

    function findWorkArea(selector) {
        if (selector) {
            const selected = document.querySelector(selector);
            if (selected) return selected;
        }
        return document.querySelector(".filter-card, [data-filter], .app-table-wrap, .table-responsive, .app-stat-grid, main .card, main table");
    }

    function elementTop(element) {
        if (!element) return 0;
        return Math.max(0, Math.round(element.getBoundingClientRect().top + (window.scrollY || window.pageYOffset || 0) - TOP_OFFSET));
    }

    function restoreTo(y, source) {
        const targetY = clampScroll(y);
        window.scrollTo({ top: targetY, left: 0, behavior: "auto" });
        body.setAttribute("data-scroll-restored", source || "true");
        restored = true;
    }

    function restoreToElement(element, source) {
        if (!element) return false;
        restoreTo(elementTop(element), source || "anchor");
        element.classList.add("app-scroll-target-highlight");
        window.setTimeout(function () {
            element.classList.remove("app-scroll-target-highlight");
        }, 900);
        return true;
    }

    function restoreHashAnchor() {
        if (!window.location.hash) return false;
        try {
            const id = decodeURIComponent(window.location.hash.slice(1));
            if (!id) return false;
            const target = document.getElementById(id) || document.querySelector("[name='" + id.replace(/'/g, "\\'") + "']");
            if (!target) return false;
            return restoreToElement(target, "hash");
        } catch (error) {
            return false;
        }
    }

    function restorePendingOrSaved() {
        const currentKey = pageKey(window.location.href);
        const pending = getPendingScroll();

        if (pending && pending.key === currentKey) {
            clearPendingScroll();
            const area = findWorkArea(pending.selector);
            if (pending.mode === "area" && area && restoreToElement(area, "work-area")) return;
            if (typeof pending.y !== "undefined") {
                restoreTo(pending.y, "pending");
                return;
            }
        } else if (pending && pending.key !== currentKey) {
            clearPendingScroll();
        }

        if (restoreHashAnchor()) return;

        const type = navigationType();
        if (type === "back_forward" || type === "reload") {
            const saved = readSavedScroll(window.location.href);
            if (saved) restoreTo(saved.y, type === "reload" ? "reload" : "history");
        }
    }

    function selectorForElement(element) {
        if (!element) return "";
        if (element.id) return "#" + element.id;
        if (element.classList && element.classList.length) {
            const classes = Array.prototype.slice.call(element.classList).slice(0, 3).join(".");
            if (classes) return element.tagName.toLowerCase() + "." + classes;
        }
        return "";
    }

    function workAreaSelectorFromNode(node) {
        const area = node && node.closest ? node.closest(".filter-card, [data-filter], .app-table-wrap, .table-responsive, .card, section") : null;
        return selectorForElement(area) || ".app-table-wrap, .table-responsive, .filter-card, [data-filter]";
    }

    function isInternalUrl(url) {
        return url.origin === window.location.origin;
    }

    document.addEventListener("click", function (event) {
        const link = event.target.closest("a[href]");
        if (!link) return;
        if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        if (link.hasAttribute("download") || link.getAttribute("target") === "_blank") return;
        if (link.getAttribute("data-bs-toggle") === "tab" || link.getAttribute("data-bs-toggle") === "pill") return;

        let url;
        try {
            url = new URL(link.getAttribute("href"), window.location.href);
        } catch (error) {
            return;
        }

        if (!isInternalUrl(url)) return;

        saveCurrentScroll();

        const samePageHash = url.pathname === window.location.pathname && url.search === window.location.search && url.hash;
        if (samePageHash) {
            const target = document.getElementById(decodeURIComponent(url.hash.slice(1)));
            if (target) {
                event.preventDefault();
                window.history.pushState(null, "", url.hash);
                restoreToElement(target, "hash-click");
            }
            return;
        }

        const shouldPreserve = link.hasAttribute("data-preserve-scroll") ||
            !!link.closest(".pagination") ||
            link.classList.contains("page-link") ||
            !!link.closest(".app-table-wrap, .table-responsive, [data-preserve-scroll-area]");

        if (shouldPreserve) {
            setPendingScroll({
                key: pageKey(url.href),
                mode: link.closest(".pagination") || link.classList.contains("page-link") ? "area" : "position",
                y: Math.round(window.scrollY || window.pageYOffset || 0),
                selector: workAreaSelectorFromNode(link)
            });
        }
    }, true);

    document.addEventListener("submit", function (event) {
        const form = event.target;
        if (!form || !form.tagName || form.tagName.toLowerCase() !== "form") return;
        saveCurrentScroll();

        const method = (form.getAttribute("method") || "get").toLowerCase();
        if (method !== "get") return;

        let actionUrl;
        try {
            actionUrl = new URL(form.getAttribute("action") || window.location.href, window.location.href);
        } catch (error) {
            return;
        }

        const selector = workAreaSelectorFromNode(form);
        try {
            const params = new URLSearchParams();
            const formData = new FormData(form);
            formData.forEach(function (value, key) {
                params.append(key, value);
            });
            if (event.submitter && event.submitter.name) {
                params.append(event.submitter.name, event.submitter.value || "");
            }
            actionUrl.search = params.toString();
        } catch (error) {
            return;
        }
        setPendingScroll({
            key: actionUrl.pathname + actionUrl.search,
            mode: "area",
            y: Math.max(0, elementTop(form.closest(".filter-card, [data-filter], .card") || form)),
            selector: selector
        });
    }, true);

    function tabGroupKey(trigger) {
        const list = trigger.closest("[data-tab-state-id], .nav-tabs, .nav-pills, [role='tablist']");
        const listId = list ? (list.getAttribute("data-tab-state-id") || list.id || Array.prototype.indexOf.call(document.querySelectorAll(".nav-tabs, .nav-pills, [role='tablist']"), list)) : "default";
        return TAB_PREFINAL + pageKey(window.location.href) + ":" + listId;
    }

    function triggerTarget(trigger) {
        return trigger.getAttribute("data-bs-target") || trigger.getAttribute("href") || "";
    }

    function saveTab(trigger) {
        const target = triggerTarget(trigger);
        if (!target || target.charAt(0) !== "#") return;
        try {
            window.sessionStorage.setItem(tabGroupKey(trigger), target);
        } catch (error) {
            return;
        }
    }

    document.querySelectorAll("[data-bs-toggle='tab'], [data-bs-toggle='pill']").forEach(function (trigger) {
        trigger.addEventListener("shown.bs.tab", function () {
            saveTab(trigger);
            saveCurrentScroll();
        });
        trigger.addEventListener("click", function () {
            window.setTimeout(function () {
                saveTab(trigger);
            }, 0);
        });
    });

    document.querySelectorAll(".nav-tabs, .nav-pills, [role='tablist']").forEach(function (list, index) {
        const listId = list.getAttribute("data-tab-state-id") || list.id || index;
        const key = TAB_PREFINAL + pageKey(window.location.href) + ":" + listId;
        let target = "";
        try {
            target = window.sessionStorage.getItem(key) || "";
        } catch (error) {
            target = "";
        }
        if (!target) return;
        const trigger = list.querySelector("[data-bs-target='" + target + "'], [href='" + target + "']");
        if (!trigger) return;
        if (window.bootstrap && window.bootstrap.Tab) {
            try {
                window.bootstrap.Tab.getOrCreateInstance(trigger).show();
            } catch (error) {
                return;
            }
        } else {
            trigger.classList.add("active");
            trigger.setAttribute("aria-selected", "true");
            const pane = document.querySelector(target);
            if (pane) pane.classList.add("active", "show");
        }
    });

    window.addEventListener("scroll", scheduleSave, { passive: true });
    window.addEventListener("pagehide", saveCurrentScroll);
    window.addEventListener("beforeunload", saveCurrentScroll);
    document.addEventListener("visibilitychange", function () {
        if (document.visibilityState === "hidden") saveCurrentScroll();
    });

    window.setTimeout(function () {
        if (!restored) restorePendingOrSaved();
    }, 40);
    window.setTimeout(function () {
        if (!restored) restorePendingOrSaved();
    }, 220);
});

// ==================================================
// PRODUCTION Action Menu Hard Lock
// Final pass after all module-specific builders:
// - dropdown item never keeps button/card classes
// - dropdown menu gets app-action-menu
// - page action group is marked and aligned right by CSS
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    function cleanDropdownItem(item) {
        if (!item || !item.classList) return;
        item.classList.add("dropdown-item");
        [
            "btn", "btn-sm", "btn-lg", "btn-primary", "btn-secondary", "btn-success", "btn-info", "btn-warning", "btn-danger",
            "btn-outline-primary", "btn-outline-secondary", "btn-outline-success", "btn-outline-info", "btn-outline-warning", "btn-outline-danger",
            "app-btn-primary", "app-btn-secondary", "app-btn-outline", "app-btn-ghost", "app-btn-danger", "app-action-btn",
            "card", "app-card", "shadow", "shadow-sm", "border", "rounded", "rounded-3", "w-100"
        ].forEach(function (cls) {
            item.classList.remove(cls);
        });
        item.removeAttribute("data-action-tier");
    }

    function normalizeMenu(menu) {
        if (!menu || !menu.classList) return;
        if (menu.closest(".app-action-dropdown, .page-actions, .table-actions, [data-page-actions], [data-row-actions]")) {
            menu.classList.add("app-action-menu");
        }

        menu.querySelectorAll("a.dropdown-item, button.dropdown-item").forEach(cleanDropdownItem);
        menu.querySelectorAll("form").forEach(function (form) {
            form.classList.add("m-0");
            form.style.margin = "0";
            const button = form.querySelector("button.btn, button.dropdown-item, .btn");
            if (button) cleanDropdownItem(button);
        });
    }

    document.querySelectorAll(".page-header, .app-page-header, .content-header").forEach(function (header) {
        const actions = header.querySelector(":scope > .page-actions, :scope > [data-page-actions], :scope > .d-flex, :scope > .finance-header-actions, :scope > .logistics-hpp-header-actions, :scope > .op-prod-delivery-header-actions, :scope > .hr-master-settings-header-actions, :scope > .dashboard-page-actions");
        if (actions) {
            actions.classList.add("page-actions");
            actions.setAttribute("data-page-actions", "true");
            actions.setAttribute("aria-label", actions.getAttribute("aria-label") || "Aksi halaman");
        }
    });

    document.querySelectorAll(".dropdown-menu").forEach(normalizeMenu);
});



// ==================================================
// PRODUCTION Global Empty State + Card Precision Sweep
// - normalizes legacy empty states across all modules
// - table colspan empty rows become compact action-ready states
// - every empty state gets a contextual next action and SOP link when missing
// - no business data, route, or database behavior is changed
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    function cleanText(value) {
        return (value || "").replace(/\s+/g, " ").trim();
    }

    function safePath() {
        return (window.location && window.location.pathname) ? window.location.pathname : "/";
    }

    function contextForPath(path) {
        const contexts = [
            { match: /^\/accounting/, sop: "/sop/accounting", sopLabel: "SOP Accounting", action: "/accounting/journals", actionLabel: "Buka Jurnal", icon: "bi-calculator" },
            { match: /^\/finance\/invoice/, sop: "/sop/finance", sopLabel: "SOP Finance", action: "/finance/invoices", actionLabel: "Buka Invoice", icon: "bi-receipt" },
            { match: /^\/finance/, sop: "/sop/finance", sopLabel: "SOP Finance", action: "/finance", actionLabel: "Buka Finance", icon: "bi-cash-stack" },
            { match: /^\/canteen/, sop: "/sop/admin", sopLabel: "SOP Warung", action: "/canteen/quick", actionLabel: "Transaksi Cepat", icon: "bi-shop" },
            { match: /^\/hr/, sop: "/sop/hr", sopLabel: "SOP SDM", action: "/hr/payrolls", actionLabel: "Buka Payroll", icon: "bi-people" },
            { match: /^\/logistics/, sop: "/sop/logistics", sopLabel: "SOP Logistik", action: "/logistics", actionLabel: "Buka Stok", icon: "bi-box-seam" },
            { match: /^\/operational/, sop: "/sop/admin", sopLabel: "SOP Admin", action: "/operational/orders", actionLabel: "Buka Order", icon: "bi-journal-text" },
            { match: /^\/production/, sop: "/sop/dapur", sopLabel: "SOP Dapur", action: "/production", actionLabel: "Buka Produksi", icon: "bi-egg-fried" },
            { match: /^\/delivery/, sop: "/sop/delivery", sopLabel: "SOP Delivery", action: "/delivery/today", actionLabel: "Delivery Hari Ini", icon: "bi-truck" },
            { match: /^\/master/, sop: "/sop/master", sopLabel: "SOP Master", action: "/master", actionLabel: "Buka Master", icon: "bi-database" },
            { match: /^\/settings/, sop: "/sop/settings", sopLabel: "SOP Settings", action: "/settings/users", actionLabel: "Kelola User", icon: "bi-gear" },
            { match: /^\/dashboard/, sop: "/sop", sopLabel: "SOP Sistem", action: "/dashboard", actionLabel: "Dashboard", icon: "bi-grid-1x2" },
            { match: /^\/sop/, sop: "/sop", sopLabel: "Pusat SOP", action: "/dashboard", actionLabel: "Dashboard", icon: "bi-book" }
        ];
        for (let i = 0; i < contexts.length; i += 1) {
            if (contexts[i].match.test(path)) return contexts[i];
        }
        return { sop: "/sop", sopLabel: "Lihat SOP", action: "/dashboard", actionLabel: "Dashboard", icon: "bi-info-circle" };
    }

    function isHidden(node) {
        return !node || node.classList.contains("d-none") || node.hidden || node.getAttribute("aria-hidden") === "true";
    }

    function isPrintArea(node) {
        return !!node.closest(".print-page, .print-sheet, [data-print-page], .print-container");
    }

    function ensureIcon(state, context) {
        if (state.querySelector("i.bi, .empty-state-icon")) return;
        const iconWrap = document.createElement("div");
        iconWrap.className = "empty-state-icon";
        iconWrap.innerHTML = '<i class="bi ' + (context.icon || "bi-info-circle") + '" aria-hidden="true"></i>';
        state.insertBefore(iconWrap, state.firstChild);
    }

    function ensureTitleAndMessage(state) {
        const text = cleanText(state.textContent);
        const hasHeading = !!state.querySelector("h1, h2, h3, h4, h5, h6, strong");
        const hasParagraph = !!state.querySelector("p, span, small");
        if (!hasHeading && text) {
            const title = document.createElement("h5");
            title.textContent = text.length > 92 ? text.slice(0, 92) + "..." : text;
            state.innerHTML = "";
            state.appendChild(title);
        }
        if (!hasParagraph && state.querySelector("h1, h2, h3, h4, h5, h6, strong")) {
            const message = document.createElement("p");
            message.textContent = "Data akan muncul otomatis setelah alur input terkait dijalankan.";
            state.appendChild(message);
        }
    }

    function hasActions(state) {
        return !!state.querySelector(".empty-actions, .app-empty-actions, a.btn, button.btn, .dropdown, form");
    }

    function ensureActions(state, context) {
        if (isPrintArea(state) || state.closest(".error-page-shell") || hasActions(state)) return;
        const actions = document.createElement("div");
        actions.className = "empty-actions app-empty-actions";
        actions.innerHTML = '' +
            '<a class="btn app-btn-secondary btn-sm" href="' + context.action + '"><i class="bi ' + (context.icon || "bi-arrow-right") + '"></i> ' + context.actionLabel + '</a>' +
            '<a class="btn app-btn-ghost btn-sm" href="' + context.sop + '"><i class="bi bi-book"></i> ' + context.sopLabel + '</a>';
        state.appendChild(actions);
    }

    function normalizeEmptyState(state) {
        if (!state || isHidden(state)) return;
        const context = contextForPath(safePath());
        state.classList.add("app-empty-state");
        state.setAttribute("data-ui-empty-state", "PRODUCTION");
        state.setAttribute("data-empty-state-normalized", "true");
        ensureIcon(state, context);
        ensureTitleAndMessage(state);
        ensureActions(state, context);
    }

    function buildMiniEmptyState(cell) {
        const context = contextForPath(safePath());
        const text = cleanText(cell.textContent) || "Data belum tersedia.";
        if (!/(belum ada|tidak ada|kosong|belum tersedia|data belum)/i.test(text)) return;
        if (cell.querySelector(".empty-state, .dashboard-empty-state, .app-empty-state")) return;
        cell.innerHTML = '' +
            '<div class="empty-state app-empty-state table-empty-state" data-ui-empty-state="PRODUCTION" data-empty-state-normalized="true">' +
                '<div class="empty-state-icon"><i class="bi ' + (context.icon || "bi-info-circle") + '" aria-hidden="true"></i></div>' +
                '<h5>' + text + '</h5>' +
                '<p>Data akan muncul setelah input dan alur terkait selesai dijalankan.</p>' +
                '<div class="empty-actions app-empty-actions">' +
                    '<a class="btn app-btn-secondary btn-sm" href="' + context.action + '"><i class="bi ' + (context.icon || "bi-arrow-right") + '"></i> ' + context.actionLabel + '</a>' +
                    '<a class="btn app-btn-ghost btn-sm" href="' + context.sop + '"><i class="bi bi-book"></i> ' + context.sopLabel + '</a>' +
                '</div>' +
            '</div>';
    }

    document.querySelectorAll(".empty-state, .dashboard-empty-state, .ui-empty-state, [data-ui-empty-state]").forEach(normalizeEmptyState);

    document.querySelectorAll("tr.app-table-empty-row > td[colspan], tbody tr > td[colspan]").forEach(function (cell) {
        buildMiniEmptyState(cell);
    });

    document.querySelectorAll(".card, .app-card, .dashboard-panel, .dashboard-card, .info-card").forEach(function (card) {
        if (card.closest(".dropdown-menu")) return;
        const text = cleanText(card.textContent);
        if (!text && card.children.length === 0) {
            card.classList.add("app-card-empty-guard");
        }
        card.setAttribute("data-card-precision", card.getAttribute("data-card-precision") || "PRODUCTION");
    });
});

// ==================================================
// Tahap 10.15 — Atomic Select & Date Input Foundation
// - Progressive enhancement for all authenticated form select/date controls.
// - Keeps original field names/values/submission intact.
// - Avoids route/service/database changes; pure UI layer.
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    const body = document.body;
    if (!body || !body.classList.contains("is-authenticated")) return;

    const ENHANCED_SELECT = "data-atomic-select-enhanced";
    const ENHANCED_DATE = "data-atomic-date-enhanced";
    const MONTHS = [
        "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember"
    ];
    const WEEKDAYS = ["Min", "Sen", "Sel", "Rab", "Kam", "Jum", "Sab"];
    const DATE_JUMP_YEAR_RADIUS = 60;

    let activeSelect = null;
    let activeDate = null;
    let uidCounter = 0;
    const OVERLAY_MARGIN = 12;
    const OVERLAY_GAP = 8;

    function uid(prefix) {
        uidCounter += 1;
        return prefix + "-" + uidCounter;
    }

    function cleanText(value) {
        return (value || "").replace(/\s+/g, " ").trim();
    }

    function shouldSkipControl(field) {
        if (!field || field.closest("template, .print-page, .print-sheet, [data-print-page], [data-no-atomic-fields]")) return true;
        if (field.hasAttribute("data-native-ui") || field.getAttribute("data-atomic-ui") === "off") return true;
        if (field.closest(".app-atomic-field-shell")) return true;
        return false;
    }

    function notifyOverlayOpening(source) {
        document.dispatchEvent(new CustomEvent("app:atomic-overlay-opening", { detail: { source: source } }));
    }

    function portalOverlay(popover) {
        if (!popover) return;
        popover.classList.add("app-atomic-overlay-portal");
        if (popover.parentElement !== document.body) {
            document.body.appendChild(popover);
        }
    }

    function overlayWidth(popover, triggerRect) {
        const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
        const maxAllowed = Math.max(180, viewportWidth - (OVERLAY_MARGIN * 2));
        let preferred = 420;
        let minimum = Math.min(280, maxAllowed);
        if (popover.classList.contains("app-date-picker-popover")) {
            preferred = 340;
            minimum = Math.min(320, maxAllowed);
        }
        return Math.min(maxAllowed, Math.max(minimum, Math.min(preferred, Math.max(triggerRect.width, minimum))));
    }

    function positionOverlay(trigger, popover) {
        if (!trigger || !popover || !trigger.isConnected) {
            closeAll();
            return;
        }
        portalOverlay(popover);
        const triggerRect = trigger.getBoundingClientRect();
        if (!triggerRect.width && !triggerRect.height) {
            closeAll();
            return;
        }
        const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
        const viewportHeight = document.documentElement.clientHeight || window.innerHeight;
        const width = overlayWidth(popover, triggerRect);
        const spaceBelow = viewportHeight - triggerRect.bottom - OVERLAY_MARGIN - OVERLAY_GAP;
        const spaceAbove = triggerRect.top - OVERLAY_MARGIN - OVERLAY_GAP;
        const openAbove = spaceBelow < 260 && spaceAbove > spaceBelow;
        const maxHeight = Math.max(180, (openAbove ? spaceAbove : spaceBelow));

        popover.removeAttribute("data-align");
        popover.setAttribute("data-placement", openAbove ? "top" : "bottom");
        popover.style.position = "fixed";
        popover.style.width = width + "px";
        popover.style.minWidth = width + "px";
        popover.style.maxWidth = (viewportWidth - (OVERLAY_MARGIN * 2)) + "px";
        popover.style.maxHeight = maxHeight + "px";
        popover.style.left = Math.max(OVERLAY_MARGIN, Math.min(triggerRect.left, viewportWidth - width - OVERLAY_MARGIN)) + "px";
        popover.style.right = "auto";
        popover.style.bottom = "auto";
        popover.style.top = "0px";

        const overlayRect = popover.getBoundingClientRect();
        const top = openAbove
            ? Math.max(OVERLAY_MARGIN, triggerRect.top - OVERLAY_GAP - overlayRect.height)
            : Math.min(triggerRect.bottom + OVERLAY_GAP, viewportHeight - OVERLAY_MARGIN - overlayRect.height);
        popover.style.top = Math.max(OVERLAY_MARGIN, top) + "px";
    }

    function buildShell(field, shellClass) {
        const shell = document.createElement("div");
        shell.className = "app-atomic-field-shell " + shellClass;
        if (field.disabled) shell.classList.add("is-disabled");
        if (field.required) shell.classList.add("is-required");
        field.parentNode.insertBefore(shell, field);
        shell.appendChild(field);
        field.classList.add("app-atomic-native");
        field.setAttribute("data-atomic-native", "true");
        field.setAttribute("aria-hidden", "true");
        field.setAttribute("tabindex", "-1");
        return shell;
    }

    function validationMessage(field) {
        if (!field || !field.willValidate || field.validity.valid) return "";
        if (field.validity.valueMissing) {
            return field.tagName === "SELECT" ? "Pilih salah satu data." : "Bagian ini wajib diisi.";
        }
        if (field.validity.typeMismatch) return "Format isian belum benar.";
        if (field.validity.patternMismatch) return "Format isian belum sesuai.";
        if (field.validity.rangeUnderflow) return "Nilai terlalu kecil.";
        if (field.validity.rangeOverflow) return "Nilai terlalu besar.";
        if (field.validity.stepMismatch) return "Nilai tidak sesuai kelipatan yang diizinkan.";
        if (field.validity.tooShort) return "Isian terlalu pendek.";
        if (field.validity.tooLong) return "Isian terlalu panjang.";
        if (field.validity.badInput) return "Isian belum valid.";
        if (field.validity.customError && field.validationMessage) return field.validationMessage;
        return "Bagian ini perlu diisi dengan benar.";
    }

    function shouldShowInvalid(field, valid) {
        if (valid) return false;
        return field.dataset.atomicTouched === "true" ||
            !!(field.form && field.form.dataset.atomicSubmitted === "true");
    }

    function ensureFeedback(shell) {
        if (!shell) return null;
        let feedback = shell.querySelector(":scope > .app-atomic-feedback");
        if (!feedback) {
            feedback = document.createElement("div");
            feedback.className = "app-atomic-feedback";
            feedback.setAttribute("role", "alert");
            feedback.hidden = true;
            shell.appendChild(feedback);
        }
        return feedback;
    }

    function updateShellState(shell, field, root, trigger) {
        if (!shell || !field) return true;
        const isDisabled = !!(field.disabled || field.readOnly);
        const isRequired = !!field.required;
        const valid = !field.willValidate || field.validity.valid;
        const showInvalid = shouldShowInvalid(field, valid);
        const message = showInvalid ? validationMessage(field) : "";
        shell.classList.toggle("is-disabled", isDisabled);
        shell.classList.toggle("is-required", isRequired);
        shell.classList.toggle("is-invalid", showInvalid);
        if (root) root.classList.toggle("is-invalid", showInvalid);
        if (trigger) {
            trigger.setAttribute("aria-invalid", showInvalid ? "true" : "false");
            trigger.setAttribute("aria-required", isRequired ? "true" : "false");
            if (isDisabled) {
                trigger.setAttribute("aria-disabled", "true");
            }
        }
        const feedback = ensureFeedback(shell);
        if (feedback) {
            feedback.textContent = message;
            feedback.hidden = !message;
            if (message && trigger && !trigger.getAttribute("aria-describedby")) {
                if (!feedback.id) feedback.id = uid("appAtomicFeedback");
                trigger.setAttribute("aria-describedby", feedback.id);
            }
        }
        return valid;
    }

    function closeSelect() {
        if (!activeSelect) return;
        activeSelect.root.classList.remove("is-open");
        activeSelect.trigger.setAttribute("aria-expanded", "false");
        activeSelect.menu.hidden = true;
        activeSelect = null;
    }

    function closeDate() {
        if (!activeDate) return;
        activeDate.root.classList.remove("is-open");
        activeDate.trigger.setAttribute("aria-expanded", "false");
        activeDate.popover.hidden = true;
        activeDate = null;
    }

    function closeAll(except) {
        if (except !== "select") closeSelect();
        if (except !== "date") closeDate();
    }

    function repositionActiveOverlay() {
        if (activeSelect) positionOverlay(activeSelect.trigger, activeSelect.menu);
        if (activeDate) positionOverlay(activeDate.trigger, activeDate.popover);
    }

    function selectedOption(select) {
        return select.options[select.selectedIndex] || null;
    }

    function optionLabel(option) {
        return option ? cleanText(option.textContent) : "";
    }

    function selectedLabel(select) {
        const option = selectedOption(select);
        const label = optionLabel(option);
        return label || select.getAttribute("placeholder") || "Pilih data";
    }

    function isPlaceholderSelected(select) {
        const option = selectedOption(select);
        return !select.value || (option && !option.value && !option.defaultSelected && select.required);
    }

    function updateSelectControl(ctx) {
        const option = selectedOption(ctx.select);
        const label = selectedLabel(ctx.select);
        ctx.valueNode.textContent = label;
        ctx.valueNode.classList.toggle("app-atomic-field-placeholder", isPlaceholderSelected(ctx.select));
        ctx.trigger.setAttribute("title", label);
        ctx.root.classList.toggle("is-disabled", ctx.select.disabled);
        ctx.trigger.setAttribute("aria-disabled", ctx.select.disabled ? "true" : "false");
        ctx.trigger.disabled = ctx.select.disabled;
        ctx.optionsWrap.querySelectorAll(".app-atomic-option, .ui-select-option").forEach(function (button) {
            const isSelected = button.getAttribute("data-value") === ctx.select.value;
            button.classList.toggle("is-selected", isSelected);
            button.setAttribute("aria-selected", isSelected ? "true" : "false");
            if (option && button.getAttribute("data-option-index") === String(option.index)) {
                button.classList.add("is-selected");
                button.setAttribute("aria-selected", "true");
            }
        });
        validateSelect(ctx);
    }

    function validateSelect(ctx) {
        return updateShellState(ctx.shell, ctx.select, ctx.root, ctx.trigger);
    }

    function createSelectOptionButton(ctx, option) {
        const button = document.createElement(ctx.isUiSelect ? "div" : "button");
        if (!ctx.isUiSelect) button.type = "button";
        button.className = ctx.isUiSelect ? "ui-select-option" : "app-atomic-option";
        if (ctx.isUiSelect) button.tabIndex = 0;
        button.setAttribute("role", "option");
        button.setAttribute("data-value", option.value);
        button.setAttribute("data-option-index", String(option.index));
        button.textContent = optionLabel(option) || "—";
        if (ctx.isUiSelect) {
            const label = document.createElement("span");
            label.className = "ui-select-option-label";
            label.textContent = button.textContent;
            button.textContent = "";
            button.appendChild(label);
        }
        if (option.disabled) {
            if (!ctx.isUiSelect) button.disabled = true;
            button.tabIndex = -1;
            button.setAttribute("aria-disabled", "true");
        }
        function selectOption() {
            if (button.disabled || button.getAttribute("aria-disabled") === "true") return;
            ctx.select.selectedIndex = option.index;
            ctx.select.dispatchEvent(new Event("input", { bubbles: true }));
            ctx.select.dispatchEvent(new Event("change", { bubbles: true }));
            updateSelectControl(ctx);
            closeSelect();
            ctx.trigger.focus({ preventScroll: true });
        }
        button.addEventListener("click", selectOption);
        button.addEventListener("keydown", function (event) {
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            selectOption();
        });
        return button;
    }

    function renderSelectOptions(ctx) {
        const filter = ctx.search ? cleanText(ctx.search.value).toLowerCase() : "";
        ctx.optionsWrap.innerHTML = "";
        let count = 0;

        Array.from(ctx.select.children).forEach(function (child) {
            if (child.tagName && child.tagName.toLowerCase() === "optgroup") {
                const groupOptions = Array.from(child.querySelectorAll("option")).filter(function (option) {
                    return !filter || optionLabel(option).toLowerCase().includes(filter);
                });
                if (!groupOptions.length) return;
                const label = document.createElement("div");
                label.className = "app-atomic-optgroup-label";
                label.textContent = child.label || "Grup";
                ctx.optionsWrap.appendChild(label);
                groupOptions.forEach(function (option) {
                    ctx.optionsWrap.appendChild(createSelectOptionButton(ctx, option));
                    count += 1;
                });
                return;
            }

            if (child.tagName && child.tagName.toLowerCase() === "option") {
                if (filter && !optionLabel(child).toLowerCase().includes(filter)) return;
                ctx.optionsWrap.appendChild(createSelectOptionButton(ctx, child));
                count += 1;
            }
        });

        if (!count) {
            const empty = document.createElement("div");
            empty.className = "app-atomic-no-result";
            empty.textContent = "Tidak ada pilihan yang cocok.";
            ctx.optionsWrap.appendChild(empty);
        }
        updateSelectControl(ctx);
    }

    function moveSelectFocus(ctx, direction) {
        const options = Array.from(ctx.optionsWrap.querySelectorAll(".app-atomic-option:not(:disabled), .ui-select-option:not([aria-disabled='true'])"));
        if (!options.length) return;
        const current = document.activeElement && document.activeElement.matches(".app-atomic-option, .ui-select-option") ? document.activeElement : null;
        let index = current ? options.indexOf(current) : -1;
        index = Math.max(0, Math.min(options.length - 1, index + direction));
        options[index].focus({ preventScroll: true });
    }

    function openSelect(ctx) {
        if (ctx.select.disabled) return;
        if (activeSelect && activeSelect !== ctx) closeSelect();
        closeAll("select");
        notifyOverlayOpening("select");
        renderSelectOptions(ctx);
        portalOverlay(ctx.menu);
        ctx.menu.hidden = false;
        ctx.root.classList.add("is-open");
        ctx.trigger.setAttribute("aria-expanded", "true");
        activeSelect = ctx;
        positionOverlay(ctx.trigger, ctx.menu);
        window.setTimeout(function () {
            if (ctx.search) {
                ctx.search.focus({ preventScroll: true });
                ctx.search.select();
            } else {
                const selected = ctx.optionsWrap.querySelector(".app-atomic-option.is-selected:not(:disabled), .ui-select-option.is-selected:not([aria-disabled='true'])");
                if (selected && typeof selected.scrollIntoView === "function") {
                    selected.scrollIntoView({ block: "nearest" });
                }
                (selected || ctx.optionsWrap.querySelector(".app-atomic-option:not(:disabled), .ui-select-option:not([aria-disabled='true'])") || ctx.trigger).focus({ preventScroll: true });
            }
        }, 0);
    }

    function enhanceSelect(select) {
        if (shouldSkipControl(select) || select.hasAttribute(ENHANCED_SELECT) || select.multiple) return;
        select.setAttribute(ENHANCED_SELECT, "true");
        const isUiSelect = select.classList.contains("ui-select-control");

        const shell = buildShell(select, "app-atomic-select-shell");
        if (isUiSelect) shell.classList.add("ui-select-shell");
        const root = document.createElement("div");
        root.className = isUiSelect ? "ui-select-enhanced" : "app-atomic-select";
        root.setAttribute("data-atomic-select", "true");

        const triggerId = uid("appAtomicSelectTrigger");
        const menuId = uid("appAtomicSelectMenu");
        const trigger = document.createElement(isUiSelect ? "div" : "button");
        if (!isUiSelect) trigger.type = "button";
        if (isUiSelect) trigger.tabIndex = 0;
        trigger.id = triggerId;
        trigger.className = isUiSelect ? "ui-select-trigger" : "app-atomic-select-trigger";
        if (isUiSelect) trigger.setAttribute("role", "combobox");
        trigger.setAttribute("aria-haspopup", "listbox");
        trigger.setAttribute("aria-expanded", "false");
        trigger.setAttribute("aria-controls", menuId);
        trigger.innerHTML = isUiSelect
            ? '<span class="ui-select-value"></span><span class="ui-select-chevron" aria-hidden="true"><i class="bi bi-chevron-down"></i></span>'
            : '<span class="app-atomic-field-value"></span><span class="app-atomic-field-icon" aria-hidden="true"><i class="bi bi-chevron-down"></i></span>';

        const menu = document.createElement("div");
        menu.id = menuId;
        menu.className = isUiSelect ? "ui-select-menu" : "app-atomic-menu";
        menu.setAttribute("role", "listbox");
        menu.hidden = true;

        const searchWrap = document.createElement("div");
        searchWrap.className = isUiSelect ? "ui-select-search-wrap" : "app-atomic-search-wrap";
        const search = document.createElement("input");
        search.type = "search";
        search.className = isUiSelect ? "ui-select-search" : "app-atomic-search";
        search.placeholder = "Cari pilihan...";
        search.setAttribute("aria-label", "Cari pilihan");
        searchWrap.appendChild(search);

        const optionsWrap = document.createElement("div");
        optionsWrap.className = isUiSelect ? "ui-select-options" : "app-atomic-options";
        menu.appendChild(searchWrap);
        menu.appendChild(optionsWrap);
        root.appendChild(trigger);
        root.appendChild(menu);
        shell.appendChild(root);

        const ctx = {
            select: select,
            shell: shell,
            root: root,
            trigger: trigger,
            menu: menu,
            search: search,
            optionsWrap: optionsWrap,
            valueNode: trigger.querySelector(isUiSelect ? ".ui-select-value" : ".app-atomic-field-value"),
            isUiSelect: isUiSelect
        };
        if (isUiSelect) {
            ctx.valueNode.classList.add("ui-select-value");
        }
        select.__atomicSelectCtx = ctx;

        function syncSearchVisibility() {
            const optionCount = select.querySelectorAll("option").length;
            searchWrap.hidden = optionCount <= 8;
            if (searchWrap.hidden) search.value = "";
        }

        trigger.addEventListener("click", function () {
            if (root.classList.contains("is-open")) {
                closeSelect();
            } else {
                syncSearchVisibility();
                openSelect(ctx);
            }
        });

        trigger.addEventListener("keydown", function (event) {
            if (["ArrowDown", "Enter", " "].includes(event.key)) {
                event.preventDefault();
                syncSearchVisibility();
                openSelect(ctx);
            }
        });

        search.addEventListener("input", function () {
            renderSelectOptions(ctx);
        });

        menu.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                event.preventDefault();
                closeSelect();
                trigger.focus({ preventScroll: true });
            } else if (event.key === "ArrowDown") {
                event.preventDefault();
                moveSelectFocus(ctx, 1);
            } else if (event.key === "ArrowUp") {
                event.preventDefault();
                moveSelectFocus(ctx, -1);
            } else if (event.key === "Home") {
                event.preventDefault();
                const first = ctx.optionsWrap.querySelector(".app-atomic-option:not(:disabled), .ui-select-option:not([aria-disabled='true'])");
                if (first) first.focus({ preventScroll: true });
            } else if (event.key === "End") {
                event.preventDefault();
                const options = Array.from(ctx.optionsWrap.querySelectorAll(".app-atomic-option:not(:disabled), .ui-select-option:not([aria-disabled='true'])"));
                const last = options[options.length - 1];
                if (last) last.focus({ preventScroll: true });
            }
        });

        select.addEventListener("change", function () {
            select.dataset.atomicTouched = "true";
            updateSelectControl(ctx);
        });
        select.addEventListener("invalid", function (event) {
            event.preventDefault();
            select.dataset.atomicTouched = "true";
            validateSelect(ctx);
            trigger.focus({ preventScroll: true });
        });
        select.form && select.form.addEventListener("reset", function () {
            window.setTimeout(function () { updateSelectControl(ctx); }, 0);
        });

        syncSearchVisibility();
        renderSelectOptions(ctx);
    }

    function parseISODate(value) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(value || "")) return null;
        const parts = value.split("-").map(Number);
        const date = new Date(parts[0], parts[1] - 1, parts[2]);
        if (date.getFullYear() !== parts[0] || date.getMonth() !== parts[1] - 1 || date.getDate() !== parts[2]) return null;
        return date;
    }

    function isoDate(date) {
        const y = date.getFullYear();
        const m = String(date.getMonth() + 1).padStart(2, "0");
        const d = String(date.getDate()).padStart(2, "0");
        return y + "-" + m + "-" + d;
    }

    function displayDate(value) {
        const date = parseISODate(value);
        if (!date) return "";
        return String(date.getDate()).padStart(2, "0") + "/" + String(date.getMonth() + 1).padStart(2, "0") + "/" + date.getFullYear();
    }

    function sameDay(a, b) {
        return !!a && !!b && a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
    }

    function addMonths(date, diff) {
        const next = new Date(date.getFullYear(), date.getMonth() + diff, 1);
        return next;
    }

    function minDate(input) { return parseISODate(input.getAttribute("min") || ""); }
    function maxDate(input) { return parseISODate(input.getAttribute("max") || ""); }

    function firstDayOfMonth(year, month) { return new Date(year, month, 1); }
    function lastDayOfMonth(year, month) { return new Date(year, month + 1, 0); }

    function isDateAllowed(input, date) {
        const min = minDate(input);
        const max = maxDate(input);
        if (min && date < min) return false;
        if (max && date > max) return false;
        return true;
    }

    function isMonthAllowed(input, year, month) {
        const min = minDate(input);
        const max = maxDate(input);
        if (min && lastDayOfMonth(year, month) < min) return false;
        if (max && firstDayOfMonth(year, month) > max) return false;
        return true;
    }

    function clampDateView(input, viewDate) {
        const min = minDate(input);
        const max = maxDate(input);
        let view = new Date(viewDate.getFullYear(), viewDate.getMonth(), 1);
        if (min && lastDayOfMonth(view.getFullYear(), view.getMonth()) < min) {
            view = new Date(min.getFullYear(), min.getMonth(), 1);
        }
        if (max && firstDayOfMonth(view.getFullYear(), view.getMonth()) > max) {
            view = new Date(max.getFullYear(), max.getMonth(), 1);
        }
        return view;
    }

    function setDateView(ctx, year, month) {
        const safeYear = Number.isFinite(year) ? year : (new Date()).getFullYear();
        const safeMonth = Math.max(0, Math.min(11, Number.isFinite(month) ? month : 0));
        ctx.viewDate = clampDateView(ctx.input, new Date(safeYear, safeMonth, 1));
        renderDatePicker(ctx);
    }

    function updateDateControl(ctx) {
        const label = displayDate(ctx.input.value);
        ctx.valueNode.textContent = label || ctx.input.getAttribute("placeholder") || "Pilih tanggal";
        ctx.valueNode.classList.toggle("app-atomic-field-placeholder", !label);
        ctx.trigger.setAttribute("title", label || "Pilih tanggal");
        ctx.root.classList.toggle("is-disabled", ctx.input.disabled || ctx.input.readOnly);
        ctx.trigger.disabled = ctx.input.disabled || ctx.input.readOnly;
        ctx.trigger.setAttribute("aria-disabled", (ctx.input.disabled || ctx.input.readOnly) ? "true" : "false");
        if (ctx.clearButton) {
            ctx.clearButton.hidden = !!ctx.input.required;
            ctx.clearButton.disabled = !!ctx.input.required || !ctx.input.value;
        }
        if (ctx.todayButton) {
            ctx.todayButton.disabled = !isDateAllowed(ctx.input, new Date());
        }
        validateDate(ctx);
    }

    function validateDate(ctx) {
        return updateShellState(ctx.shell, ctx.input, ctx.root, ctx.trigger);
    }

    function selectDate(ctx, date) {
        if (!isDateAllowed(ctx.input, date)) return;
        ctx.input.value = isoDate(date);
        ctx.viewDate = new Date(date.getFullYear(), date.getMonth(), 1);
        ctx.input.dispatchEvent(new Event("input", { bubbles: true }));
        ctx.input.dispatchEvent(new Event("change", { bubbles: true }));
        updateDateControl(ctx);
        renderDatePicker(ctx);
        closeDate();
        ctx.trigger.focus({ preventScroll: true });
    }

    function focusDateButton(ctx, date) {
        if (!ctx || !date) return;
        window.setTimeout(function () {
            const button = ctx.grid.querySelector('[data-date-iso="' + isoDate(date) + '"]:not(:disabled)');
            if (button) button.focus({ preventScroll: true });
        }, 0);
    }

    function moveDateFocus(ctx, currentDate, diffDays, diffMonths) {
        let target = new Date(currentDate);
        if (diffMonths) {
            target = new Date(target.getFullYear(), target.getMonth() + diffMonths, target.getDate());
        }
        if (diffDays) {
            target.setDate(target.getDate() + diffDays);
        }
        if (!isDateAllowed(ctx.input, target)) return;
        ctx.viewDate = new Date(target.getFullYear(), target.getMonth(), 1);
        renderDatePicker(ctx);
        focusDateButton(ctx, target);
    }

    function handleDateDayKeydown(ctx, event, date) {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            selectDate(ctx, date);
            return;
        }
        if (event.key === "ArrowLeft") {
            event.preventDefault();
            moveDateFocus(ctx, date, -1, 0);
        } else if (event.key === "ArrowRight") {
            event.preventDefault();
            moveDateFocus(ctx, date, 1, 0);
        } else if (event.key === "ArrowUp") {
            event.preventDefault();
            moveDateFocus(ctx, date, -7, 0);
        } else if (event.key === "ArrowDown") {
            event.preventDefault();
            moveDateFocus(ctx, date, 7, 0);
        } else if (event.key === "Home") {
            event.preventDefault();
            moveDateFocus(ctx, date, -date.getDay(), 0);
        } else if (event.key === "End") {
            event.preventDefault();
            moveDateFocus(ctx, date, 6 - date.getDay(), 0);
        } else if (event.key === "PageUp") {
            event.preventDefault();
            moveDateFocus(ctx, date, 0, event.shiftKey ? -12 : -1);
        } else if (event.key === "PageDown") {
            event.preventDefault();
            moveDateFocus(ctx, date, 0, event.shiftKey ? 12 : 1);
        }
    }

    function renderDateJumpPanel(ctx, view) {
        if (!ctx.jumpPanel) return;
        ctx.jumpPanel.innerHTML = "";

        const yearRow = document.createElement("div");
        yearRow.className = "app-date-jump-year-row";

        const prevYear = document.createElement("button");
        prevYear.type = "button";
        prevYear.className = "app-date-jump-nav";
        prevYear.setAttribute("aria-label", "Tahun sebelumnya");
        prevYear.innerHTML = '<i class="bi bi-chevron-left" aria-hidden="true"></i>';

        const yearInput = document.createElement("input");
        yearInput.type = "number";
        yearInput.className = "app-date-jump-year";
        yearInput.inputMode = "numeric";
        yearInput.value = String(view.getFullYear());
        yearInput.setAttribute("aria-label", "Tahun");
        yearInput.min = String((minDate(ctx.input) || new Date(view.getFullYear() - DATE_JUMP_YEAR_RADIUS, 0, 1)).getFullYear());
        yearInput.max = String((maxDate(ctx.input) || new Date(view.getFullYear() + DATE_JUMP_YEAR_RADIUS, 0, 1)).getFullYear());

        const nextYear = document.createElement("button");
        nextYear.type = "button";
        nextYear.className = "app-date-jump-nav";
        nextYear.setAttribute("aria-label", "Tahun berikutnya");
        nextYear.innerHTML = '<i class="bi bi-chevron-right" aria-hidden="true"></i>';

        yearRow.appendChild(prevYear);
        yearRow.appendChild(yearInput);
        yearRow.appendChild(nextYear);
        ctx.jumpPanel.appendChild(yearRow);

        const monthGrid = document.createElement("div");
        monthGrid.className = "app-date-jump-months";
        MONTHS.forEach(function (monthName, monthIndex) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "app-date-jump-month";
            button.textContent = monthName.slice(0, 3);
            button.setAttribute("aria-label", monthName + " " + yearInput.value);
            button.classList.toggle("is-current", monthIndex === view.getMonth());
            button.disabled = !isMonthAllowed(ctx.input, Number(yearInput.value), monthIndex);
            button.addEventListener("click", function () {
                setDateView(ctx, Number(yearInput.value), monthIndex);
                ctx.jumpPanel.hidden = true;
                ctx.root.classList.remove("is-jump-open");
                if (ctx.title) ctx.title.setAttribute("aria-expanded", "false");
            });
            monthGrid.appendChild(button);
        });
        ctx.jumpPanel.appendChild(monthGrid);

        function applyYear(diff) {
            const raw = Number(yearInput.value || view.getFullYear()) + diff;
            const minYear = Number(yearInput.min);
            const maxYear = Number(yearInput.max);
            const nextYearValue = Math.max(minYear, Math.min(maxYear, raw));
            setDateView(ctx, nextYearValue, ctx.viewDate.getMonth());
            ctx.jumpPanel.hidden = false;
            ctx.root.classList.add("is-jump-open");
        }

        prevYear.addEventListener("click", function () { applyYear(-1); });
        nextYear.addEventListener("click", function () { applyYear(1); });
        yearInput.addEventListener("keydown", function (event) {
            if (event.key === "Enter") {
                event.preventDefault();
                setDateView(ctx, Number(yearInput.value), ctx.viewDate.getMonth());
                ctx.jumpPanel.hidden = false;
                ctx.root.classList.add("is-jump-open");
            }
        });
        yearInput.addEventListener("change", function () {
            setDateView(ctx, Number(yearInput.value), ctx.viewDate.getMonth());
            ctx.jumpPanel.hidden = false;
            ctx.root.classList.add("is-jump-open");
        });
    }

    function renderDatePicker(ctx) {
        const inputDate = parseISODate(ctx.input.value);
        const today = new Date();
        const view = clampDateView(ctx.input, ctx.viewDate || inputDate || today);
        ctx.viewDate = view;
        ctx.title.textContent = MONTHS[view.getMonth()] + " " + view.getFullYear();
        if (ctx.jumpPanel) {
            ctx.title.setAttribute("aria-expanded", ctx.jumpPanel.hidden ? "false" : "true");
        }
        ctx.grid.innerHTML = "";
        renderDateJumpPanel(ctx, view);

        const first = new Date(view.getFullYear(), view.getMonth(), 1);
        const start = new Date(first);
        start.setDate(first.getDate() - first.getDay());

        for (let index = 0; index < 42; index += 1) {
            const date = new Date(start);
            date.setDate(start.getDate() + index);
            const button = document.createElement("button");
            button.type = "button";
            button.className = "app-date-picker-day";
            button.textContent = String(date.getDate());
            button.setAttribute("data-date-iso", isoDate(date));
            button.setAttribute("aria-label", String(date.getDate()) + " " + MONTHS[date.getMonth()] + " " + date.getFullYear());
            if (date.getMonth() !== view.getMonth()) button.classList.add("is-outside");
            if (sameDay(date, today)) button.classList.add("is-today");
            if (sameDay(date, inputDate)) button.classList.add("is-selected");
            if (!isDateAllowed(ctx.input, date)) {
                button.disabled = true;
                button.setAttribute("tabindex", "-1");
            } else {
                button.setAttribute("tabindex", sameDay(date, inputDate || today) ? "0" : "-1");
            }
            button.addEventListener("click", function () { selectDate(ctx, date); });
            button.addEventListener("keydown", function (event) { handleDateDayKeydown(ctx, event, date); });
            ctx.grid.appendChild(button);
        }
    }

    function openDate(ctx) {
        if (ctx.input.disabled || ctx.input.readOnly) return;
        if (activeDate && activeDate !== ctx) closeDate();
        closeAll("date");
        notifyOverlayOpening("date");
        const selected = parseISODate(ctx.input.value);
        ctx.viewDate = selected || ctx.viewDate || new Date();
        ctx.viewDate = clampDateView(ctx.input, new Date(ctx.viewDate.getFullYear(), ctx.viewDate.getMonth(), 1));
        if (ctx.jumpPanel) {
            ctx.jumpPanel.hidden = true;
            ctx.root.classList.remove("is-jump-open");
            if (ctx.title) ctx.title.setAttribute("aria-expanded", "false");
        }
        renderDatePicker(ctx);
        portalOverlay(ctx.popover);
        ctx.popover.hidden = false;
        ctx.root.classList.add("is-open");
        ctx.trigger.setAttribute("aria-expanded", "true");
        activeDate = ctx;
        positionOverlay(ctx.trigger, ctx.popover);
        focusDateButton(ctx, parseISODate(ctx.input.value) || new Date());
    }

    function enhanceDateInput(input) {
        if (shouldSkipControl(input) || input.hasAttribute(ENHANCED_DATE)) return;
        if ((input.getAttribute("type") || "").toLowerCase() !== "date") return;
        input.setAttribute(ENHANCED_DATE, "true");

        const shell = buildShell(input, "app-atomic-date-shell");
        const root = document.createElement("div");
        root.className = "app-atomic-date";
        root.setAttribute("data-atomic-date", "true");

        const triggerId = uid("appAtomicDateTrigger");
        const popoverId = uid("appAtomicDatePicker");
        const trigger = document.createElement("button");
        trigger.type = "button";
        trigger.id = triggerId;
        trigger.className = "app-atomic-date-trigger";
        trigger.setAttribute("aria-haspopup", "dialog");
        trigger.setAttribute("aria-expanded", "false");
        trigger.setAttribute("aria-controls", popoverId);
        trigger.innerHTML = '<span class="app-atomic-field-value"></span><span class="app-atomic-field-icon" aria-hidden="true"><i class="bi bi-calendar3"></i></span>';

        const popover = document.createElement("div");
        popover.id = popoverId;
        popover.className = "app-date-picker-popover";
        popover.setAttribute("role", "dialog");
        popover.setAttribute("aria-label", "Pilih tanggal");
        popover.hidden = true;

        const head = document.createElement("div");
        head.className = "app-date-picker-head";
        head.innerHTML = '<button type="button" class="app-date-picker-nav" data-date-nav="prev" aria-label="Bulan sebelumnya"><i class="bi bi-chevron-left"></i></button><button type="button" class="app-date-picker-title" data-date-title aria-expanded="false" aria-label="Pilih bulan dan tahun"></button><button type="button" class="app-date-picker-nav" data-date-nav="next" aria-label="Bulan berikutnya"><i class="bi bi-chevron-right"></i></button>';

        const jumpPanel = document.createElement("div");
        jumpPanel.className = "app-date-jump-panel";
        jumpPanel.hidden = true;

        const weekdays = document.createElement("div");
        weekdays.className = "app-date-picker-weekdays";
        WEEKDAYS.forEach(function (day) {
            const cell = document.createElement("div");
            cell.textContent = day;
            weekdays.appendChild(cell);
        });

        const grid = document.createElement("div");
        grid.className = "app-date-picker-grid";

        const footer = document.createElement("div");
        footer.className = "app-date-picker-footer";
        footer.innerHTML = '<button type="button" class="app-date-clear">Clear</button><button type="button" class="app-date-today">Hari ini</button>';

        popover.appendChild(head);
        popover.appendChild(jumpPanel);
        popover.appendChild(weekdays);
        popover.appendChild(grid);
        popover.appendChild(footer);
        root.appendChild(trigger);
        root.appendChild(popover);
        shell.appendChild(root);

        const ctx = {
            input: input,
            shell: shell,
            root: root,
            trigger: trigger,
            popover: popover,
            title: head.querySelector(".app-date-picker-title"),
            jumpPanel: jumpPanel,
            grid: grid,
            viewDate: parseISODate(input.value) || new Date(),
            valueNode: trigger.querySelector(".app-atomic-field-value"),
            clearButton: footer.querySelector(".app-date-clear"),
            todayButton: footer.querySelector(".app-date-today")
        };
        input.__atomicDateCtx = ctx;

        trigger.addEventListener("click", function () {
            if (root.classList.contains("is-open")) closeDate(); else openDate(ctx);
        });

        trigger.addEventListener("keydown", function (event) {
            if (["ArrowDown", "Enter", " "].includes(event.key)) {
                event.preventDefault();
                openDate(ctx);
            }
        });

        popover.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                event.preventDefault();
                if (jumpPanel && !jumpPanel.hidden) {
                    jumpPanel.hidden = true;
                    root.classList.remove("is-jump-open");
                    ctx.title.setAttribute("aria-expanded", "false");
                    ctx.title.focus({ preventScroll: true });
                    return;
                }
                closeDate();
                trigger.focus({ preventScroll: true });
            }
        });

        head.querySelector('[data-date-nav="prev"]').addEventListener("click", function () {
            ctx.viewDate = clampDateView(ctx.input, addMonths(ctx.viewDate, -1));
            renderDatePicker(ctx);
        });
        head.querySelector('[data-date-nav="next"]').addEventListener("click", function () {
            ctx.viewDate = clampDateView(ctx.input, addMonths(ctx.viewDate, 1));
            renderDatePicker(ctx);
        });
        head.querySelector("[data-date-title]").addEventListener("click", function () {
            const willOpen = jumpPanel.hidden;
            jumpPanel.hidden = !willOpen;
            root.classList.toggle("is-jump-open", willOpen);
            ctx.title.setAttribute("aria-expanded", willOpen ? "true" : "false");
            if (willOpen) {
                renderDateJumpPanel(ctx, ctx.viewDate);
                const yearInput = jumpPanel.querySelector(".app-date-jump-year");
                if (yearInput) yearInput.focus({ preventScroll: true });
            }
        });
        ctx.clearButton.addEventListener("click", function () {
            if (input.required) return;
            input.value = "";
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.dispatchEvent(new Event("change", { bubbles: true }));
            updateDateControl(ctx);
            closeDate();
            trigger.focus({ preventScroll: true });
        });
        ctx.todayButton.addEventListener("click", function () {
            selectDate(ctx, new Date());
        });

        input.addEventListener("input", function () {
            input.dataset.atomicTouched = "true";
            updateDateControl(ctx);
        });
        input.addEventListener("change", function () {
            input.dataset.atomicTouched = "true";
            updateDateControl(ctx);
        });
        input.addEventListener("invalid", function (event) {
            event.preventDefault();
            input.dataset.atomicTouched = "true";
            validateDate(ctx);
            trigger.focus({ preventScroll: true });
        });
        input.form && input.form.addEventListener("reset", function () {
            window.setTimeout(function () { updateDateControl(ctx); }, 0);
        });

        updateDateControl(ctx);
    }

    function enhanceScope(scope) {
        if (!scope || !scope.querySelectorAll) return;
        scope.querySelectorAll("select").forEach(enhanceSelect);
        scope.querySelectorAll('input[type="date"]').forEach(enhanceDateInput);
    }

    enhanceScope(document);
    body.setAttribute("data-atomic-fields", "select-date");

    document.addEventListener("click", function (event) {
        const target = event.target;
        if (activeSelect && !activeSelect.root.contains(target) && !activeSelect.menu.contains(target)) closeSelect();
        if (activeDate && !activeDate.root.contains(target) && !activeDate.popover.contains(target)) closeDate();
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") closeAll();
    });

    document.addEventListener("app:atomic-overlay-opening", function (event) {
        const source = event.detail && event.detail.source;
        if (source !== "select") closeSelect();
        if (source !== "date") closeDate();
    });
    window.addEventListener("resize", repositionActiveOverlay);
    window.addEventListener("scroll", repositionActiveOverlay, true);

    document.querySelectorAll("form").forEach(function (form) {
        form.addEventListener("submit", function () {
            form.dataset.atomicSubmitted = "true";
            form.querySelectorAll("select[data-atomic-select-enhanced]").forEach(function (select) {
                const shell = select.closest(".app-atomic-field-shell");
                const root = shell ? shell.querySelector(".app-atomic-select") : null;
                const trigger = root ? root.querySelector(".app-atomic-select-trigger") : null;
                const invalid = select.willValidate && !select.validity.valid;
                if (root && trigger) {
                    select.dataset.atomicTouched = "true";
                    root.classList.toggle("is-invalid", invalid);
                    trigger.setAttribute("aria-invalid", invalid ? "true" : "false");
                }
            });
            form.querySelectorAll('input[type="date"][data-atomic-date-enhanced]').forEach(function (input) {
                const shell = input.closest(".app-atomic-field-shell");
                const root = shell ? shell.querySelector(".app-atomic-date") : null;
                const trigger = root ? root.querySelector(".app-atomic-date-trigger") : null;
                const invalid = input.willValidate && !input.validity.valid;
                if (root && trigger) {
                    input.dataset.atomicTouched = "true";
                    root.classList.toggle("is-invalid", invalid);
                    trigger.setAttribute("aria-invalid", invalid ? "true" : "false");
                }
            });
        }, true);
    });

    const observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
            if (mutation.type === "attributes") {
                const target = mutation.target;
                if (target && target.__atomicSelectCtx) {
                    renderSelectOptions(target.__atomicSelectCtx);
                    updateSelectControl(target.__atomicSelectCtx);
                }
                if (target && target.__atomicDateCtx) {
                    updateDateControl(target.__atomicDateCtx);
                    if (target.__atomicDateCtx.root.classList.contains("is-open")) {
                        renderDatePicker(target.__atomicDateCtx);
                    }
                }
                return;
            }
            mutation.addedNodes.forEach(function (node) {
                if (!(node instanceof Element)) return;
                if (node.matches && node.matches("select")) enhanceSelect(node);
                if (node.matches && node.matches('input[type="date"]')) enhanceDateInput(node);
                enhanceScope(node);
            });
        });
    });
    observer.observe(body, { childList: true, subtree: true, attributes: true, attributeFilter: ["disabled", "readonly", "required", "min", "max", "value"] });
});

// ==================================================
// Atomic Confirm, Alert & Toast UI Foundation
// - Replaces native browser confirm()/alert() with app-owned UI
// - Keeps legacy inline onsubmit/onclick handlers working safely
// - Does not alter form payloads, routes, or business logic
// ==================================================
(function () {
    if (window.__idhaBogaAtomicDialogInstalled) {
        return;
    }
    window.__idhaBogaAtomicDialogInstalled = true;

    const nativeConfirm = window.confirm.bind(window);
    const nativeAlert = window.alert.bind(window);
    const bypassUntil = new WeakMap();
    let pendingContext = null;
    let activeModal = null;
    let toastHost = null;

    function isAtomicDialogDisabled(element) {
        if (!element || !(element instanceof Element)) return false;
        return !!element.closest('[data-native-dialog], [data-atomic-dialog="off"], [data-no-atomic-dialog]');
    }

    function now() {
        return Date.now();
    }

    function setBypass(element) {
        if (element && (element instanceof Element)) {
            bypassUntil.set(element, now() + 2500);
        }
    }

    function hasBypass(element) {
        if (!element || !(element instanceof Element)) return false;
        const expiresAt = bypassUntil.get(element) || 0;
        if (expiresAt > now()) {
            return true;
        }
        bypassUntil.delete(element);
        return false;
    }

    function cleanupMessage(message) {
        return String(message || "").replace(/\s+/g, " ").trim() || "Lanjutkan aksi ini?";
    }

    function guessTone(message) {
        const text = cleanupMessage(message).toLowerCase();
        if (/hapus|delete|batalkan|batal|void|tolak|lunak|kunci|commit/.test(text)) return "danger";
        if (/bayar|payment|invoice|jurnal|saldo|posting|sync|generate|catat|penuhi|setujui|simpan|buat/.test(text)) return "warning";
        return "neutral";
    }

    function guessAlertTone(message) {
        const text = cleanupMessage(message).toLowerCase();
        if (/berhasil|tersalin|disalin|sukses|success/.test(text)) return "success";
        if (/gagal|error|tidak|belum|wajib|harus|kosong|minimal|lebih dari/.test(text)) return "danger";
        return "info";
    }

    function titleForTone(tone, fallback) {
        if (fallback) return fallback;
        if (tone === "danger") return "Konfirmasi Aksi Penting";
        if (tone === "warning") return "Konfirmasi Transaksi";
        return "Konfirmasi";
    }

    function ensureDialogRoot() {
        let root = document.getElementById("appAtomicDialogRoot");
        if (!root) {
            root = document.createElement("div");
            root.id = "appAtomicDialogRoot";
            root.className = "app-atomic-dialog-root";
            document.body.appendChild(root);
        }
        return root;
    }

    function ensureToastHost() {
        if (!toastHost) {
            toastHost = document.getElementById("appAtomicToastHost");
        }
        if (!toastHost) {
            toastHost = document.createElement("div");
            toastHost.id = "appAtomicToastHost";
            toastHost.className = "app-atomic-toast-host";
            toastHost.setAttribute("aria-live", "polite");
            toastHost.setAttribute("aria-atomic", "false");
            document.body.appendChild(toastHost);
        }
        return toastHost;
    }

    function trapFocus(modal, event) {
        if (!modal || event.key !== "Tab") return;
        const focusables = Array.from(modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'))
            .filter(function (node) {
                return !node.disabled && !!(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
            });
        if (!focusables.length) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    }

    function closeAtomicConfirm(result) {
        if (!activeModal) return;
        const modalState = activeModal;
        activeModal = null;
        document.body.classList.remove("app-atomic-dialog-open");
        if (modalState.keydownHandler) {
            document.removeEventListener("keydown", modalState.keydownHandler, true);
        }
        if (modalState.root && modalState.root.parentNode) {
            modalState.root.remove();
        }
        if (result && typeof modalState.onConfirm === "function") {
            modalState.onConfirm();
        } else if (!result && modalState.returnFocus && typeof modalState.returnFocus.focus === "function") {
            setTimeout(function () {
                try { modalState.returnFocus.focus({ preventScroll: true }); } catch (error) { /* noop */ }
            }, 10);
        }
    }

    function openAtomicConfirm(options) {
        const message = cleanupMessage(options && options.message);
        const tone = (options && options.tone) || guessTone(message);
        const title = titleForTone(tone, options && options.title);
        const root = ensureDialogRoot();
        root.innerHTML = "";
        root.className = "app-atomic-dialog-root is-visible";
        document.body.classList.add("app-atomic-dialog-open");

        const backdrop = document.createElement("div");
        backdrop.className = "app-atomic-dialog-backdrop";

        const modal = document.createElement("section");
        modal.className = "app-atomic-dialog app-atomic-dialog-" + tone;
        modal.setAttribute("role", "dialog");
        modal.setAttribute("aria-modal", "true");
        modal.setAttribute("aria-labelledby", "appAtomicDialogTitle");
        modal.setAttribute("aria-describedby", "appAtomicDialogMessage");
        modal.tabIndex = -1;

        const icon = document.createElement("div");
        icon.className = "app-atomic-dialog-icon";
        icon.setAttribute("aria-hidden", "true");
        icon.textContent = tone === "danger" ? "!" : (tone === "warning" ? "?" : "i");

        const content = document.createElement("div");
        content.className = "app-atomic-dialog-content";

        const titleNode = document.createElement("h2");
        titleNode.id = "appAtomicDialogTitle";
        titleNode.className = "app-atomic-dialog-title";
        titleNode.textContent = title;

        const messageNode = document.createElement("p");
        messageNode.id = "appAtomicDialogMessage";
        messageNode.className = "app-atomic-dialog-message";
        messageNode.textContent = message;

        const actions = document.createElement("div");
        actions.className = "app-atomic-dialog-actions";

        const cancelButton = document.createElement("button");
        cancelButton.type = "button";
        cancelButton.className = "btn app-btn-secondary app-atomic-dialog-cancel";
        cancelButton.textContent = (options && options.cancelText) || "Batal";

        const confirmButton = document.createElement("button");
        confirmButton.type = "button";
        confirmButton.className = "btn app-atomic-dialog-confirm " + (tone === "danger" ? "app-btn-danger" : "app-btn-primary");
        confirmButton.textContent = (options && options.confirmText) || "Ya, lanjutkan";

        actions.appendChild(cancelButton);
        actions.appendChild(confirmButton);
        content.appendChild(titleNode);
        content.appendChild(messageNode);
        content.appendChild(actions);
        modal.appendChild(icon);
        modal.appendChild(content);
        root.appendChild(backdrop);
        root.appendChild(modal);

        const state = {
            root: root,
            modal: modal,
            returnFocus: options && options.returnFocus,
            onConfirm: options && options.onConfirm,
            keydownHandler: null
        };
        activeModal = state;

        state.keydownHandler = function (event) {
            if (!activeModal) return;
            if (event.key === "Escape") {
                event.preventDefault();
                closeAtomicConfirm(false);
            } else if (event.key === "Enter" && document.activeElement === confirmButton) {
                event.preventDefault();
                closeAtomicConfirm(true);
            } else {
                trapFocus(modal, event);
            }
        };
        document.addEventListener("keydown", state.keydownHandler, true);

        backdrop.addEventListener("click", function () { closeAtomicConfirm(false); });
        cancelButton.addEventListener("click", function () { closeAtomicConfirm(false); });
        confirmButton.addEventListener("click", function () { closeAtomicConfirm(true); });

        setTimeout(function () {
            try { cancelButton.focus({ preventScroll: true }); } catch (error) { modal.focus(); }
        }, 10);
    }

    function showToast(message, tone, options) {
        const host = ensureToastHost();
        const safeTone = tone || guessAlertTone(message);
        const toast = document.createElement("div");
        toast.className = "app-atomic-toast app-atomic-toast-" + safeTone;
        toast.setAttribute("role", safeTone === "danger" ? "alert" : "status");

        const icon = document.createElement("span");
        icon.className = "app-atomic-toast-icon";
        icon.setAttribute("aria-hidden", "true");
        icon.textContent = safeTone === "success" ? "✓" : (safeTone === "danger" ? "!" : "i");

        const text = document.createElement("span");
        text.className = "app-atomic-toast-message";
        text.textContent = cleanupMessage(message);

        const close = document.createElement("button");
        close.type = "button";
        close.className = "app-atomic-toast-close";
        close.setAttribute("aria-label", "Tutup notifikasi");
        close.textContent = "×";

        toast.appendChild(icon);
        toast.appendChild(text);
        toast.appendChild(close);
        host.appendChild(toast);

        function dismiss() {
            toast.classList.add("is-hiding");
            setTimeout(function () {
                if (toast.parentNode) toast.remove();
            }, 220);
        }

        close.addEventListener("click", dismiss);
        const duration = options && Number.isFinite(options.duration) ? options.duration : (safeTone === "danger" ? 6000 : 3800);
        setTimeout(dismiss, duration);
        return toast;
    }

    function replayContext(context) {
        if (!context) return;
        if (context.form) setBypass(context.form);
        if (context.submitter) setBypass(context.submitter);
        if (context.element) setBypass(context.element);

        if (context.type === "submit" && context.form) {
            setTimeout(function () {
                try {
                    if (typeof context.form.requestSubmit === "function") {
                        if (context.submitter && context.submitter.form === context.form) {
                            context.form.requestSubmit(context.submitter);
                        } else {
                            context.form.requestSubmit();
                        }
                    } else if (typeof context.form.submit === "function") {
                        context.form.submit();
                    }
                } catch (error) {
                    if (typeof context.form.submit === "function") context.form.submit();
                }
            }, 10);
            return;
        }

        if (context.type === "click" && context.element && typeof context.element.click === "function") {
            setTimeout(function () {
                context.element.click();
            }, 10);
        }
    }

    document.addEventListener("submit", function (event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || isAtomicDialogDisabled(form)) return;
        pendingContext = {
            type: "submit",
            form: form,
            submitter: event.submitter || document.activeElement,
            element: form,
            returnFocus: event.submitter || form.querySelector('button[type="submit"], input[type="submit"], button:not([type])') || form
        };
        setTimeout(function () {
            if (pendingContext && pendingContext.form === form) pendingContext = null;
        }, 0);
    }, true);

    document.addEventListener("click", function (event) {
        const element = event.target && event.target.closest ? event.target.closest('button, input[type="submit"], input[type="button"], a, [role="button"]') : null;
        if (!element || isAtomicDialogDisabled(element)) return;
        const form = element.form || (element.closest ? element.closest("form") : null);
        pendingContext = {
            type: "click",
            form: form,
            submitter: element,
            element: element,
            returnFocus: element
        };
        setTimeout(function () {
            if (pendingContext && pendingContext.element === element) pendingContext = null;
        }, 0);
    }, true);

    window.appToast = function (message, tone, options) {
        return showToast(message, tone, options || {});
    };

    window.appConfirm = function (message, options) {
        return new Promise(function (resolve) {
            openAtomicConfirm({
                message: message,
                tone: options && options.tone,
                title: options && options.title,
                confirmText: options && options.confirmText,
                cancelText: options && options.cancelText,
                returnFocus: options && options.returnFocus,
                onConfirm: function () { resolve(true); }
            });
            const originalClose = closeAtomicConfirm;
            // Promise API is mostly for new code; legacy inline handlers use window.confirm override below.
            setTimeout(function () { void originalClose; }, 0);
        });
    };

    window.confirm = function (message) {
        const context = pendingContext;
        const contextElement = context && (context.element || context.form);
        const contextForm = context && context.form;

        if (contextElement && (hasBypass(contextElement) || hasBypass(contextForm))) {
            pendingContext = null;
            return true;
        }

        if (!document.body || (contextElement && isAtomicDialogDisabled(contextElement))) {
            return nativeConfirm(message);
        }

        openAtomicConfirm({
            message: message,
            tone: guessTone(message),
            returnFocus: context && context.returnFocus,
            onConfirm: function () {
                replayContext(context);
            }
        });
        pendingContext = null;
        return false;
    };

    window.alert = function (message) {
        if (!document.body) {
            return nativeAlert(message);
        }
        showToast(message, guessAlertTone(message));
        return undefined;
    };
})();

// ==================================================
// Tahap 10.19 — Atomic File, Checkbox & Numeric Input UI Polish
// - progressive enhancement only, native inputs remain source of truth
// - no route/service/database/business-flow changes
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    if (window.__idhaBogaAtomicMiscFieldsInstalled) {
        return;
    }
    window.__idhaBogaAtomicMiscFieldsInstalled = true;

    function isOptedOut(field) {
        return !!(field && (
            field.matches("[data-atomic-ui='off'], [data-native-ui], [data-no-atomic-field]") ||
            field.closest("[data-atomic-ui='off'], [data-native-ui], [data-no-atomic-fields], .print-page, .print-sheet")
        ));
    }

    function labelTextFor(field) {
        if (!field) return "File";
        const id = field.getAttribute("id");
        if (id) {
            const label = document.querySelector("label[for='" + cssEscape(id) + "']");
            if (label && label.textContent.trim()) return label.textContent.trim();
        }
        const nearestLabel = field.closest("label");
        if (nearestLabel && nearestLabel.textContent.trim()) return nearestLabel.textContent.trim();
        return field.getAttribute("aria-label") || field.getAttribute("name") || "File";
    }

    function cssEscape(value) {
        if (window.CSS && typeof window.CSS.escape === "function") {
            return window.CSS.escape(value);
        }
        return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
    }

    function filesLabel(input) {
        if (!input.files || input.files.length === 0) {
            return input.getAttribute("placeholder") || "Belum ada file dipilih";
        }
        if (input.files.length === 1) {
            return input.files[0].name;
        }
        return input.files.length + " file dipilih";
    }

    function syncFileShell(input) {
        const shell = input.closest(".app-file-field");
        if (!shell) return;
        const nameNode = shell.querySelector(".app-file-name");
        const button = shell.querySelector(".app-file-trigger");
        if (nameNode) {
            nameNode.textContent = filesLabel(input);
            nameNode.classList.toggle("is-empty", !input.files || input.files.length === 0);
        }
        shell.classList.toggle("is-disabled", input.disabled);
        shell.classList.toggle("is-required", input.required);
        shell.classList.toggle("is-invalid", input.matches(":invalid"));
        if (button) {
            button.disabled = input.disabled;
            button.setAttribute("aria-disabled", input.disabled ? "true" : "false");
        }
    }

    function enhanceFileInput(input) {
        if (!input || input.dataset.atomicFileReady === "true" || isOptedOut(input)) return;
        input.dataset.atomicFileReady = "true";

        const shell = document.createElement("div");
        shell.className = "app-file-field";
        shell.setAttribute("data-atomic-file", "true");
        input.parentNode.insertBefore(shell, input);
        shell.appendChild(input);

        const button = document.createElement("button");
        button.type = "button";
        button.className = "app-file-trigger";
        button.innerHTML = '<i class="bi bi-upload" aria-hidden="true"></i><span>Pilih File</span>';
        button.setAttribute("aria-label", "Pilih file untuk " + labelTextFor(input));

        const nameNode = document.createElement("span");
        nameNode.className = "app-file-name is-empty";
        nameNode.textContent = filesLabel(input);

        shell.appendChild(button);
        shell.appendChild(nameNode);

        button.addEventListener("click", function () {
            if (!input.disabled) input.click();
        });
        input.addEventListener("change", function () { syncFileShell(input); });
        input.addEventListener("invalid", function () { syncFileShell(input); });
        syncFileShell(input);
    }

    function enhanceCheckbox(input) {
        if (!input || input.dataset.atomicCheckboxReady === "true" || isOptedOut(input)) return;
        input.dataset.atomicCheckboxReady = "true";
        input.classList.add("app-checkbox-input");
        const holder = input.closest(".form-check, label, .form-group, .mb-3, .col-md-4, .col-md-6, .col-md-12") || input.parentElement;
        if (holder) {
            holder.classList.add("app-checkbox-field");
            holder.classList.toggle("is-checked", input.checked);
            holder.classList.toggle("is-disabled", input.disabled);
            holder.classList.toggle("is-required", input.required);
            input.addEventListener("change", function () {
                holder.classList.toggle("is-checked", input.checked);
                holder.classList.toggle("is-invalid", input.matches(":invalid"));
            });
            input.addEventListener("invalid", function () {
                holder.classList.add("is-invalid");
            });
        }
    }

    function enhanceNumericInput(input) {
        if (!input || input.dataset.atomicNumericReady === "true" || isOptedOut(input)) return;
        input.dataset.atomicNumericReady = "true";
        input.classList.add("app-numeric-input");
        if (!input.getAttribute("inputmode")) {
            input.setAttribute("inputmode", "decimal");
        }
        input.addEventListener("wheel", function (event) {
            if (document.activeElement === input) {
                event.preventDefault();
            }
        }, { passive: false });
    }

    function enhanceWithin(root) {
        const scope = root || document;
        scope.querySelectorAll("input[type='file']").forEach(enhanceFileInput);
        scope.querySelectorAll("input[type='checkbox']").forEach(enhanceCheckbox);
        scope.querySelectorAll("input[type='number']").forEach(enhanceNumericInput);
    }

    enhanceWithin(document);

    const observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
            mutation.addedNodes.forEach(function (node) {
                if (!(node instanceof Element)) return;
                if (node.matches && node.matches("input[type='file']")) enhanceFileInput(node);
                if (node.matches && node.matches("input[type='checkbox']")) enhanceCheckbox(node);
                if (node.matches && node.matches("input[type='number']")) enhanceNumericInput(node);
                enhanceWithin(node);
            });
            if (mutation.type === "attributes" && mutation.target instanceof HTMLInputElement) {
                const input = mutation.target;
                if (input.type === "file") syncFileShell(input);
                if (input.type === "checkbox") {
                    const holder = input.closest(".app-checkbox-field");
                    if (holder) {
                        holder.classList.toggle("is-checked", input.checked);
                        holder.classList.toggle("is-disabled", input.disabled);
                        holder.classList.toggle("is-required", input.required);
                    }
                }
            }
        });
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["disabled", "required", "checked", "class", "aria-invalid"]
    });
});

// ==================================================
// Tahap 10.20 — Centered Flash Notification Polish
// - Moves server-side Flask flash messages from page-top flow into a centered
//   app notification host so users immediately see the result of their action.
// - Does not change routes, flash categories, form payloads, or business flow.
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    if (window.__idhaBogaCenteredFlashInstalled) {
        return;
    }
    window.__idhaBogaCenteredFlashInstalled = true;

    const flashes = Array.from(document.querySelectorAll(".app-alert"))
        .filter(function (alert) {
            return alert instanceof HTMLElement && !alert.closest(".app-flash-center-host");
        });

    if (!flashes.length) {
        return;
    }

    let host = document.getElementById("appFlashCenterHost");
    if (!host) {
        host = document.createElement("div");
        host.id = "appFlashCenterHost";
        host.className = "app-flash-center-host";
        host.setAttribute("aria-live", "polite");
        host.setAttribute("aria-atomic", "false");
        document.body.appendChild(host);
    }

    let stack = host.querySelector(".app-flash-center-stack");
    if (!stack) {
        stack = document.createElement("div");
        stack.className = "app-flash-center-stack";
        host.appendChild(stack);
    }

    function dismiss(alert) {
        if (!alert || alert.dataset.flashDismissing === "true") {
            return;
        }
        alert.dataset.flashDismissing = "true";
        alert.classList.add("is-hiding");
        setTimeout(function () {
            if (alert.parentNode) {
                alert.remove();
            }
            if (stack && !stack.querySelector(".app-alert")) {
                host.remove();
            }
        }, 220);
    }

    flashes.forEach(function (alert) {
        alert.classList.add("app-flash-centered");
        alert.setAttribute("data-centered-flash", "true");

        const closeButton = alert.querySelector(".btn-close");
        const textNodes = Array.from(alert.childNodes).filter(function (node) {
            if (node.nodeType === Node.TEXT_NODE) {
                return String(node.textContent || "").trim().length > 0;
            }
            if (node.nodeType === Node.ELEMENT_NODE) {
                return node !== closeButton && !node.classList.contains("app-flash-message-text");
            }
            return false;
        });

        if (!alert.querySelector(".app-flash-message-text")) {
            const textWrap = document.createElement("span");
            textWrap.className = "app-flash-message-text";
            textNodes.forEach(function (node) {
                textWrap.appendChild(node);
            });
            alert.insertBefore(textWrap, closeButton || null);
        }

        stack.appendChild(alert);

        if (closeButton) {
            closeButton.addEventListener("click", function (event) {
                event.preventDefault();
                dismiss(alert);
            }, { once: true });
        }

        let timeoutId = null;
        const duration = alert.classList.contains("alert-danger") || alert.classList.contains("alert-warning") ? 7200 : 5200;
        function startTimer() {
            if (timeoutId) {
                clearTimeout(timeoutId);
            }
            timeoutId = setTimeout(function () { dismiss(alert); }, duration);
        }
        function stopTimer() {
            if (timeoutId) {
                clearTimeout(timeoutId);
                timeoutId = null;
            }
        }

        alert.addEventListener("mouseenter", stopTimer);
        alert.addEventListener("focusin", stopTimer);
        alert.addEventListener("mouseleave", startTimer);
        alert.addEventListener("focusout", startTimer);
        startTimer();
    });
});

// ==================================================
// Tahap 10.21 — Atomic Action Loading & Double Submit Guard
// - Adds visible processing feedback for form submits and page navigations
// - Prevents accidental double-submit without changing payload/route/service/DB
// - Keeps native form fields as source of truth; does not disable submitter before browser builds form data
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    if (window.__idhaBogaAtomicActionLoadingInstalled) {
        return;
    }
    window.__idhaBogaAtomicActionLoadingInstalled = true;

    const submittedForms = new WeakSet();
    let pageBusyTimer = null;
    let pageBusyVisible = false;

    function isElementDisabled(element) {
        return !!(element && (
            element.disabled ||
            element.getAttribute("aria-disabled") === "true" ||
            element.classList.contains("disabled")
        ));
    }

    function isOptedOut(element) {
        return !!(element && element.closest && element.closest([
            "[data-no-action-loading]",
            "[data-action-loading='off']",
            "[data-native-loading]",
            ".print-page",
            ".print-sheet"
        ].join(", ")));
    }

    function shouldSkipForm(form) {
        if (!form || isOptedOut(form)) return true;
        const method = String(form.getAttribute("method") || "get").toLowerCase();
        const target = String(form.getAttribute("target") || "").toLowerCase();
        const enctype = String(form.getAttribute("enctype") || "").toLowerCase();
        return method === "dialog" || target === "_blank" || enctype.includes("multipart/mixed");
    }

    function isNavigatingLink(link) {
        if (!link || isOptedOut(link) || isElementDisabled(link)) return false;
        const href = link.getAttribute("href");
        if (!href || href === "#" || href.startsWith("javascript:")) return false;
        if (link.hasAttribute("download")) return false;
        if (String(link.getAttribute("target") || "").toLowerCase() === "_blank") return false;
        if (link.closest("[data-bs-toggle], [data-toggle], .dropdown-toggle, .sidebar-group-toggle")) return false;
        if (href.startsWith("#")) return false;
        try {
            const url = new URL(href, window.location.href);
            return url.origin === window.location.origin;
        } catch (error) {
            return false;
        }
    }

    function ensurePageBusy() {
        let host = document.getElementById("appActionLoadingHost");
        if (!host) {
            host = document.createElement("div");
            host.id = "appActionLoadingHost";
            host.className = "app-action-loading-host";
            host.setAttribute("role", "status");
            host.setAttribute("aria-live", "polite");
            host.innerHTML = '<div class="app-action-loading-pill"><span class="app-action-loading-spinner" aria-hidden="true"></span><span class="app-action-loading-text">Memproses aksi...</span></div>';
            document.body.appendChild(host);
        }
        return host;
    }

    function showPageBusy(message) {
        if (pageBusyTimer) {
            clearTimeout(pageBusyTimer);
        }
        pageBusyTimer = setTimeout(function () {
            const host = ensurePageBusy();
            const text = host.querySelector(".app-action-loading-text");
            if (text) text.textContent = message || "Memproses aksi...";
            document.body.classList.add("app-action-loading-active");
            pageBusyVisible = true;
        }, 120);
    }

    function hidePageBusy() {
        if (pageBusyTimer) {
            clearTimeout(pageBusyTimer);
            pageBusyTimer = null;
        }
        if (pageBusyVisible) {
            document.body.classList.remove("app-action-loading-active");
            pageBusyVisible = false;
        }
    }

    function labelForSubmitter(submitter) {
        if (!submitter) return "Memproses...";
        const explicit = submitter.getAttribute("data-loading-text");
        if (explicit) return explicit;
        const text = String(submitter.textContent || submitter.value || "").trim().toLowerCase();
        if (/hapus|delete|void|batal|tolak/.test(text)) return "Memproses...";
        if (/bayar|payment|lunas|cicilan/.test(text)) return "Mencatat pembayaran...";
        if (/invoice|tagih/.test(text)) return "Membuat invoice...";
        if (/simpan|save|update|ubah|edit/.test(text)) return "Menyimpan...";
        if (/login|masuk/.test(text)) return "Masuk...";
        if (/export|unduh|download/.test(text)) return "Menyiapkan file...";
        return "Memproses...";
    }

    function setSubmitterLoading(submitter, loadingText) {
        if (!submitter || !(submitter instanceof HTMLElement) || submitter.dataset.actionLoadingReady === "true") {
            return;
        }
        submitter.dataset.actionLoadingReady = "true";
        submitter.dataset.originalHtml = submitter.innerHTML;
        submitter.classList.add("is-action-loading");
        submitter.setAttribute("aria-disabled", "true");
        submitter.setAttribute("data-action-loading", "true");
        submitter.innerHTML = '<span class="app-button-spinner" aria-hidden="true"></span><span class="app-button-loading-text">' + escapeHtml(loadingText || "Memproses...") + '</span>';
    }

    function escapeHtml(text) {
        return String(text || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function markFormControls(form, submitter) {
        if (!form) return;
        const loadingText = labelForSubmitter(submitter);
        form.classList.add("is-submitting");
        form.setAttribute("aria-busy", "true");
        if (submitter) {
            setSubmitterLoading(submitter, loadingText);
        }
        Array.from(form.querySelectorAll('button[type="submit"], input[type="submit"], button:not([type])')).forEach(function (button) {
            if (button !== submitter) {
                button.setAttribute("aria-disabled", "true");
                button.classList.add("is-submit-locked");
            }
        });
        showPageBusy(loadingText);
    }

    function toastDuplicate() {
        if (typeof window.appToast === "function") {
            window.appToast("Aksi sedang diproses. Tunggu sampai selesai agar data tidak dobel.", "warning", { duration: 4200 });
        }
    }

    document.addEventListener("submit", function (event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || shouldSkipForm(form)) {
            return;
        }

        if (submittedForms.has(form)) {
            event.preventDefault();
            event.stopImmediatePropagation();
            toastDuplicate();
            return;
        }

        // If another validator or atomic confirm cancelled the submit, do not show loading.
        setTimeout(function () {
            if (event.defaultPrevented || !document.body.contains(form)) {
                return;
            }
            submittedForms.add(form);
            markFormControls(form, event.submitter || document.activeElement);
        }, 0);
    }, false);

    document.addEventListener("click", function (event) {
        const submitter = event.target && event.target.closest ? event.target.closest('button[type="submit"], input[type="submit"], button:not([type])') : null;
        if (submitter && submitter.form && submittedForms.has(submitter.form)) {
            event.preventDefault();
            event.stopImmediatePropagation();
            toastDuplicate();
            return;
        }

        const link = event.target && event.target.closest ? event.target.closest("a[href]") : null;
        if (!link || !isNavigatingLink(link)) {
            return;
        }
        if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
            return;
        }
        link.classList.add("is-action-loading");
        link.setAttribute("aria-busy", "true");
        showPageBusy("Membuka halaman...");
    }, true);

    window.addEventListener("pageshow", function () {
        hidePageBusy();
        document.querySelectorAll("form.is-submitting").forEach(function (form) {
            form.classList.remove("is-submitting");
            form.removeAttribute("aria-busy");
        });
        document.querySelectorAll("[data-action-loading='true']").forEach(function (button) {
            if (button.dataset.originalHtml) {
                button.innerHTML = button.dataset.originalHtml;
            }
            button.classList.remove("is-action-loading");
            button.removeAttribute("aria-disabled");
            button.removeAttribute("data-action-loading");
            delete button.dataset.actionLoadingReady;
        });
        document.querySelectorAll(".is-submit-locked").forEach(function (button) {
            button.classList.remove("is-submit-locked");
            button.removeAttribute("aria-disabled");
        });
    });
});

// ==================================================
// Tahap 10.22 — Atomic Time, Password & Action Dropdown UI Polish
// - Adds app-owned time picker for type=time fields while preserving native source input.
// - Adds show/hide password controls without changing field names or submission.
// - Hardens Bootstrap/action dropdown visuals and keyboard fallback behavior.
// ==================================================
(function () {
    if (window.__idhaBogaAtomicTimePasswordDropdownInstalled) {
        return;
    }
    window.__idhaBogaAtomicTimePasswordDropdownInstalled = true;

    const body = document.body;
    if (!body) return;

    let uidCounter = 0;
    let activeTime = null;
    let activeDropdown = null;
    const OVERLAY_MARGIN = 12;
    const OVERLAY_GAP = 8;
    const DROPDOWN_MIN_WIDTH = 220;
    const DROPDOWN_MAX_WIDTH = 360;

    function uid(prefix) {
        uidCounter += 1;
        return prefix + "-" + uidCounter;
    }

    function cleanText(value) {
        return String(value || "").replace(/\s+/g, " ").trim();
    }

    function isElement(node) {
        return node instanceof Element;
    }

    function escapeHtml(value) {
        const div = document.createElement("div");
        div.textContent = String(value || "");
        return div.innerHTML;
    }

    function shouldSkipAtomicField(field) {
        if (!field || !isElement(field)) return true;
        if (field.closest("template, .print-page, .print-sheet, [data-print-page], [data-no-atomic-fields]")) return true;
        if (field.hasAttribute("data-native-ui") || field.getAttribute("data-atomic-ui") === "off") return true;
        if (field.closest("[data-native-ui], [data-atomic-ui='off'], .app-atomic-field-shell, .app-password-field")) return true;
        return false;
    }

    function labelTextFor(field) {
        if (!field) return "field";
        if (field.id) {
            const label = document.querySelector('label[for="' + field.id.replace(/"/g, '\\"') + '"]');
            if (label) return cleanText(label.textContent);
        }
        const wrapped = field.closest("label");
        if (wrapped) return cleanText(wrapped.textContent);
        const group = field.closest(".mb-3, .form-group, .col, .col-12, [class*='col-md'], [class*='col-lg'], .app-field");
        const label = group ? group.querySelector("label") : null;
        return label ? cleanText(label.textContent) : (field.name || field.id || "field");
    }

    function parseTime(value) {
        const match = String(value || "").match(/^(\d{1,2}):(\d{2})(?::\d{2})?$/);
        if (!match) return null;
        const hour = Number(match[1]);
        const minute = Number(match[2]);
        if (!Number.isInteger(hour) || !Number.isInteger(minute) || hour < 0 || hour > 23 || minute < 0 || minute > 59) return null;
        return { hour: hour, minute: minute };
    }

    function pad2(value) {
        return String(value).padStart(2, "0");
    }

    function timeValue(hour, minute) {
        return pad2(hour) + ":" + pad2(minute);
    }

    function isTimeAllowed(input, value) {
        if (!value) return !input.required;
        const min = input.getAttribute("min");
        const max = input.getAttribute("max");
        if (min && value < min.slice(0, 5)) return false;
        if (max && value > max.slice(0, 5)) return false;
        return true;
    }

    function validationMessage(field) {
        if (!field || !field.willValidate || field.validity.valid) return "";
        if (field.validity.valueMissing) {
            return field.tagName === "SELECT" ? "Pilih salah satu data." : "Bagian ini wajib diisi.";
        }
        if (field.validity.typeMismatch) return "Format isian belum benar.";
        if (field.validity.patternMismatch) return "Format isian belum sesuai.";
        if (field.validity.rangeUnderflow) return "Nilai terlalu kecil.";
        if (field.validity.rangeOverflow) return "Nilai terlalu besar.";
        if (field.validity.stepMismatch) return "Nilai tidak sesuai kelipatan yang diizinkan.";
        if (field.validity.tooShort) return "Isian terlalu pendek.";
        if (field.validity.tooLong) return "Isian terlalu panjang.";
        if (field.validity.badInput) return "Isian belum valid.";
        if (field.validity.customError && field.validationMessage) return field.validationMessage;
        return "Bagian ini perlu diisi dengan benar.";
    }

    function shouldShowInvalid(field, valid) {
        if (valid) return false;
        return field.dataset.atomicTouched === "true" ||
            !!(field.form && field.form.dataset.atomicSubmitted === "true");
    }

    function ensureAtomicFeedback(shell) {
        if (!shell) return null;
        let feedback = shell.querySelector(":scope > .app-atomic-feedback");
        if (!feedback) {
            feedback = document.createElement("div");
            feedback.className = "app-atomic-feedback";
            feedback.setAttribute("role", "alert");
            feedback.hidden = true;
            shell.appendChild(feedback);
        }
        return feedback;
    }

    function updateTimeShellState(ctx) {
        if (!ctx || !ctx.input) return true;
        const input = ctx.input;
        const valid = !input.willValidate || input.validity.valid;
        const showInvalid = shouldShowInvalid(input, valid);
        const disabled = !!(input.disabled || input.readOnly);
        const required = !!input.required;
        ctx.shell.classList.toggle("is-disabled", disabled);
        ctx.shell.classList.toggle("is-required", required);
        ctx.shell.classList.toggle("is-invalid", showInvalid);
        ctx.root.classList.toggle("is-disabled", disabled);
        ctx.root.classList.toggle("is-invalid", showInvalid);
        ctx.trigger.disabled = disabled;
        ctx.trigger.setAttribute("aria-disabled", disabled ? "true" : "false");
        ctx.trigger.setAttribute("aria-required", required ? "true" : "false");
        ctx.trigger.setAttribute("aria-invalid", showInvalid ? "true" : "false");
        if (ctx.clearButton) {
            ctx.clearButton.disabled = required || disabled || !input.value;
            ctx.clearButton.hidden = required;
        }
        const feedback = ensureAtomicFeedback(ctx.shell);
        const message = showInvalid ? validationMessage(input) : "";
        if (feedback) {
            feedback.textContent = message;
            feedback.hidden = !message;
            if (message && !feedback.id) feedback.id = uid("appAtomicTimeFeedback");
            if (message) ctx.trigger.setAttribute("aria-describedby", feedback.id);
        }
        return valid;
    }

    function updateTimeControl(ctx) {
        if (!ctx || !ctx.input) return;
        const parsed = parseTime(ctx.input.value);
        const label = parsed ? timeValue(parsed.hour, parsed.minute) : (ctx.input.getAttribute("placeholder") || "Pilih jam");
        ctx.valueNode.textContent = label;
        ctx.valueNode.classList.toggle("app-atomic-field-placeholder", !parsed);
        ctx.trigger.setAttribute("title", label);
        if (ctx.hourInput && ctx.minuteInput && parsed && !ctx.root.classList.contains("is-open")) {
            ctx.hourInput.value = pad2(parsed.hour);
            ctx.minuteInput.value = pad2(parsed.minute);
        }
        updateTimeShellState(ctx);
    }

    function closeTime() {
        if (!activeTime) return;
        activeTime.root.classList.remove("is-open");
        activeTime.trigger.setAttribute("aria-expanded", "false");
        activeTime.popover.hidden = true;
        activeTime = null;
    }

    function notifyOverlayOpening(source) {
        document.dispatchEvent(new CustomEvent("app:atomic-overlay-opening", { detail: { source: source } }));
    }

    function portalTimeOverlay(popover) {
        if (!popover) return;
        popover.classList.add("app-atomic-overlay-portal");
        if (popover.parentElement !== document.body) {
            document.body.appendChild(popover);
        }
    }

    function positionTimeOverlay(ctx) {
        if (!ctx || !ctx.trigger || !ctx.popover || !ctx.trigger.isConnected) {
            closeTime();
            return;
        }
        portalTimeOverlay(ctx.popover);
        const triggerRect = ctx.trigger.getBoundingClientRect();
        if (!triggerRect.width && !triggerRect.height) {
            closeTime();
            return;
        }
        const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
        const viewportHeight = document.documentElement.clientHeight || window.innerHeight;
        const width = Math.min(
            Math.max(180, viewportWidth - (OVERLAY_MARGIN * 2)),
            Math.max(Math.min(280, viewportWidth - (OVERLAY_MARGIN * 2)), Math.min(360, Math.max(triggerRect.width, 280)))
        );
        const spaceBelow = viewportHeight - triggerRect.bottom - OVERLAY_MARGIN - OVERLAY_GAP;
        const spaceAbove = triggerRect.top - OVERLAY_MARGIN - OVERLAY_GAP;
        const openAbove = spaceBelow < 240 && spaceAbove > spaceBelow;
        const maxHeight = Math.max(180, (openAbove ? spaceAbove : spaceBelow));

        ctx.popover.removeAttribute("data-align");
        ctx.popover.setAttribute("data-placement", openAbove ? "top" : "bottom");
        ctx.popover.style.position = "fixed";
        ctx.popover.style.width = width + "px";
        ctx.popover.style.minWidth = width + "px";
        ctx.popover.style.maxWidth = (viewportWidth - (OVERLAY_MARGIN * 2)) + "px";
        ctx.popover.style.maxHeight = maxHeight + "px";
        ctx.popover.style.left = Math.max(OVERLAY_MARGIN, Math.min(triggerRect.left, viewportWidth - width - OVERLAY_MARGIN)) + "px";
        ctx.popover.style.right = "auto";
        ctx.popover.style.bottom = "auto";
        ctx.popover.style.top = "0px";

        const overlayRect = ctx.popover.getBoundingClientRect();
        const top = openAbove
            ? Math.max(OVERLAY_MARGIN, triggerRect.top - OVERLAY_GAP - overlayRect.height)
            : Math.min(triggerRect.bottom + OVERLAY_GAP, viewportHeight - OVERLAY_MARGIN - overlayRect.height);
        ctx.popover.style.top = Math.max(OVERLAY_MARGIN, top) + "px";
    }

    function repositionActiveTime() {
        if (activeTime) positionTimeOverlay(activeTime);
    }

    function setTimeValue(ctx, value) {
        if (!ctx || !ctx.input || !value) return false;
        if (!isTimeAllowed(ctx.input, value)) {
            if (typeof window.appToast === "function") {
                window.appToast("Jam di luar batas yang diizinkan.", "danger");
            }
            updateTimeShellState(ctx);
            return false;
        }
        ctx.input.value = value;
        ctx.input.dispatchEvent(new Event("input", { bubbles: true }));
        ctx.input.dispatchEvent(new Event("change", { bubbles: true }));
        updateTimeControl(ctx);
        return true;
    }

    function applyTimeFromFields(ctx) {
        const hourText = String(ctx.hourInput.value || "").trim();
        const minuteText = String(ctx.minuteInput.value || "").trim();
        const hour = Number(hourText);
        const minute = Number(minuteText);
        if (!Number.isInteger(hour) || !Number.isInteger(minute) || hour < 0 || hour > 23 || minute < 0 || minute > 59) {
            ctx.root.classList.add("is-invalid");
            if (typeof window.appToast === "function") {
                window.appToast("Jam harus diisi dalam format 00:00 sampai 23:59.", "danger");
            }
            (Number.isInteger(hour) && hour >= 0 && hour <= 23 ? ctx.minuteInput : ctx.hourInput).focus({ preventScroll: true });
            return false;
        }
        const ok = setTimeValue(ctx, timeValue(hour, minute));
        if (ok) {
            closeTime();
            ctx.trigger.focus({ preventScroll: true });
        }
        return ok;
    }

    function openTime(ctx) {
        if (!ctx || ctx.input.disabled || ctx.input.readOnly) return;
        closeTime();
        notifyOverlayOpening("time");
        const parsed = parseTime(ctx.input.value);
        ctx.hourInput.value = parsed ? pad2(parsed.hour) : "";
        ctx.minuteInput.value = parsed ? pad2(parsed.minute) : "";
        portalTimeOverlay(ctx.popover);
        ctx.popover.hidden = false;
        ctx.root.classList.add("is-open");
        ctx.trigger.setAttribute("aria-expanded", "true");
        activeTime = ctx;
        positionTimeOverlay(ctx);
        window.setTimeout(function () {
            (ctx.hourInput || ctx.trigger).focus({ preventScroll: true });
        }, 0);
    }

    function enhanceTimeInput(input) {
        if (shouldSkipAtomicField(input) || input.dataset.atomicTimeReady === "true") return;
        if ((input.getAttribute("type") || "").toLowerCase() !== "time") return;
        input.dataset.atomicTimeReady = "true";

        const shell = document.createElement("div");
        shell.className = "app-atomic-field-shell app-atomic-time-shell";
        input.parentNode.insertBefore(shell, input);
        shell.appendChild(input);
        input.classList.add("app-atomic-native");
        input.setAttribute("data-atomic-native", "true");
        input.setAttribute("aria-hidden", "true");
        input.setAttribute("tabindex", "-1");

        const root = document.createElement("div");
        root.className = "app-atomic-time";
        root.setAttribute("data-atomic-time", "true");

        const triggerId = uid("appAtomicTimeTrigger");
        const popoverId = uid("appAtomicTimePicker");
        const trigger = document.createElement("button");
        trigger.type = "button";
        trigger.id = triggerId;
        trigger.className = "app-atomic-time-trigger";
        trigger.setAttribute("aria-haspopup", "dialog");
        trigger.setAttribute("aria-expanded", "false");
        trigger.setAttribute("aria-controls", popoverId);
        trigger.innerHTML = '<span class="app-atomic-field-value"></span><span class="app-atomic-field-icon" aria-hidden="true"><i class="bi bi-clock"></i></span>';

        const popover = document.createElement("div");
        popover.id = popoverId;
        popover.className = "app-time-picker-popover";
        popover.setAttribute("role", "dialog");
        popover.setAttribute("aria-label", "Pilih jam");
        popover.hidden = true;
        popover.innerHTML = '' +
            '<div class="app-time-picker-title">Pilih Jam</div>' +
            '<div class="app-time-picker-inputs">' +
            '  <label><span>Jam</span><input type="number" inputmode="numeric" min="0" max="23" step="1" class="app-time-hour" placeholder="HH"></label>' +
            '  <span class="app-time-separator">:</span>' +
            '  <label><span>Menit</span><input type="number" inputmode="numeric" min="0" max="59" step="1" class="app-time-minute" placeholder="MM"></label>' +
            '</div>' +
            '<div class="app-time-quick-grid" aria-label="Pilihan jam cepat">' +
            '  <button type="button" data-time-value="06:00">06:00</button>' +
            '  <button type="button" data-time-value="07:00">07:00</button>' +
            '  <button type="button" data-time-value="08:00">08:00</button>' +
            '  <button type="button" data-time-value="12:00">12:00</button>' +
            '  <button type="button" data-time-value="17:00">17:00</button>' +
            '  <button type="button" data-time-value="20:00">20:00</button>' +
            '</div>' +
            '<div class="app-time-picker-footer">' +
            '  <button type="button" class="app-time-clear">Clear</button>' +
            '  <button type="button" class="app-time-apply">Terapkan</button>' +
            '</div>';

        root.appendChild(trigger);
        root.appendChild(popover);
        shell.appendChild(root);

        const ctx = {
            input: input,
            shell: shell,
            root: root,
            trigger: trigger,
            popover: popover,
            valueNode: trigger.querySelector(".app-atomic-field-value"),
            hourInput: popover.querySelector(".app-time-hour"),
            minuteInput: popover.querySelector(".app-time-minute"),
            clearButton: popover.querySelector(".app-time-clear"),
            applyButton: popover.querySelector(".app-time-apply")
        };
        input.__atomicTimeCtx = ctx;

        trigger.addEventListener("click", function () {
            if (root.classList.contains("is-open")) closeTime(); else openTime(ctx);
        });
        trigger.addEventListener("keydown", function (event) {
            if (["ArrowDown", "Enter", " "].includes(event.key)) {
                event.preventDefault();
                openTime(ctx);
            }
        });
        popover.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                event.preventDefault();
                closeTime();
                trigger.focus({ preventScroll: true });
            }
            if (event.key === "Enter") {
                event.preventDefault();
                applyTimeFromFields(ctx);
            }
        });
        popover.querySelectorAll("[data-time-value]").forEach(function (button) {
            button.addEventListener("click", function () {
                if (setTimeValue(ctx, button.getAttribute("data-time-value"))) {
                    closeTime();
                    trigger.focus({ preventScroll: true });
                }
            });
        });
        ctx.applyButton.addEventListener("click", function () { applyTimeFromFields(ctx); });
        ctx.clearButton.addEventListener("click", function () {
            if (input.required) return;
            input.value = "";
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.dispatchEvent(new Event("change", { bubbles: true }));
            updateTimeControl(ctx);
            closeTime();
            trigger.focus({ preventScroll: true });
        });
        input.addEventListener("input", function () { updateTimeControl(ctx); });
        input.addEventListener("change", function () { updateTimeControl(ctx); });
        input.addEventListener("invalid", function (event) {
            event.preventDefault();
            updateTimeShellState(ctx);
            trigger.focus({ preventScroll: true });
        });
        input.form && input.form.addEventListener("reset", function () {
            window.setTimeout(function () { updateTimeControl(ctx); }, 0);
        });

        updateTimeControl(ctx);
    }

    function enhancePasswordInput(input) {
        if (shouldSkipAtomicField(input) || input.dataset.atomicPasswordReady === "true") return;
        if ((input.getAttribute("type") || "").toLowerCase() !== "password") return;
        input.dataset.atomicPasswordReady = "true";

        const shell = document.createElement("div");
        shell.className = "app-password-field";
        input.parentNode.insertBefore(shell, input);
        shell.appendChild(input);
        input.classList.add("app-password-input");

        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "app-password-toggle";
        toggle.setAttribute("aria-label", "Tampilkan password untuk " + labelTextFor(input));
        toggle.setAttribute("aria-pressed", "false");
        toggle.innerHTML = '<i class="bi bi-eye" aria-hidden="true"></i><span class="visually-hidden">Tampilkan password</span>';
        shell.appendChild(toggle);

        toggle.addEventListener("click", function () {
            const showing = input.type === "text";
            input.type = showing ? "password" : "text";
            toggle.setAttribute("aria-pressed", showing ? "false" : "true");
            toggle.setAttribute("aria-label", (showing ? "Tampilkan" : "Sembunyikan") + " password untuk " + labelTextFor(input));
            toggle.innerHTML = showing ? '<i class="bi bi-eye" aria-hidden="true"></i><span class="visually-hidden">Tampilkan password</span>' : '<i class="bi bi-eye-slash" aria-hidden="true"></i><span class="visually-hidden">Sembunyikan password</span>';
            input.focus({ preventScroll: true });
        });
    }

    function dropdownMenuFor(toggle) {
        const explicit = toggle.getAttribute("data-bs-target") || toggle.getAttribute("data-target");
        if (explicit) {
            try {
                const found = document.querySelector(explicit);
                if (found) return found;
            } catch (error) { /* ignore invalid selector */ }
        }
        const parent = toggle.closest(".dropdown, .btn-group, .topbar-user, .page-actions, [data-page-actions]") || toggle.parentElement;
        if (!parent) return null;
        return parent.querySelector(":scope > .dropdown-menu, .dropdown-menu");
    }

    function closeDropdown(ctx) {
        if (!ctx) return;
        if (window.bootstrap && window.bootstrap.Dropdown && ctx.menu.classList.contains("show")) {
            try {
                window.bootstrap.Dropdown.getOrCreateInstance(ctx.toggle).hide();
            } catch (error) { /* Bootstrap may already be closing. */ }
        }
        ctx.toggle.classList.remove("show", "is-open");
        ctx.toggle.setAttribute("aria-expanded", "false");
        ctx.menu.classList.remove("show", "is-open");
        ctx.menu.setAttribute("data-atomic-dropdown-open", "false");
        if (activeDropdown === ctx) activeDropdown = null;
    }

    function portalDropdownMenu(ctx) {
        if (!ctx || !ctx.menu) return;
        ctx.menu.classList.add("app-atomic-dropdown-portal");
        if (!ctx.placeholder) {
            ctx.placeholder = document.createComment("app-atomic-dropdown-placeholder");
        }
        if (ctx.menu.parentNode !== document.body) {
            ctx.originalParent = ctx.menu.parentNode;
            if (ctx.originalParent) ctx.originalParent.insertBefore(ctx.placeholder, ctx.menu);
            document.body.appendChild(ctx.menu);
        }
    }

    function positionDropdownMenu(ctx) {
        if (!ctx || !ctx.toggle || !ctx.menu || !ctx.toggle.isConnected) {
            closeDropdown(ctx);
            return;
        }
        portalDropdownMenu(ctx);
        const triggerRect = ctx.toggle.getBoundingClientRect();
        if (!triggerRect.width && !triggerRect.height) {
            closeDropdown(ctx);
            return;
        }
        const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
        const viewportHeight = document.documentElement.clientHeight || window.innerHeight;
        const maxAllowed = Math.max(DROPDOWN_MIN_WIDTH, viewportWidth - (OVERLAY_MARGIN * 2));
        const width = Math.min(maxAllowed, Math.max(DROPDOWN_MIN_WIDTH, Math.min(DROPDOWN_MAX_WIDTH, Math.max(triggerRect.width, DROPDOWN_MIN_WIDTH))));
        const spaceBelow = viewportHeight - triggerRect.bottom - OVERLAY_MARGIN - OVERLAY_GAP;
        const spaceAbove = triggerRect.top - OVERLAY_MARGIN - OVERLAY_GAP;
        const openAbove = spaceBelow < 180 && spaceAbove > spaceBelow;
        const maxHeight = Math.max(120, openAbove ? spaceAbove : spaceBelow);
        const alignEnd = ctx.menu.classList.contains("dropdown-menu-end") || ctx.menu.classList.contains("dropdown-menu-right");
        const preferredLeft = alignEnd ? triggerRect.right - width : triggerRect.left;
        const left = Math.max(OVERLAY_MARGIN, Math.min(preferredLeft, viewportWidth - width - OVERLAY_MARGIN));

        ctx.menu.setAttribute("data-placement", openAbove ? "top" : "bottom");
        ctx.menu.style.position = "fixed";
        ctx.menu.style.inset = "auto";
        ctx.menu.style.margin = "0";
        ctx.menu.style.transform = "none";
        ctx.menu.style.width = width + "px";
        ctx.menu.style.minWidth = width + "px";
        ctx.menu.style.maxWidth = (viewportWidth - (OVERLAY_MARGIN * 2)) + "px";
        ctx.menu.style.maxHeight = maxHeight + "px";
        ctx.menu.style.overflowY = "auto";
        ctx.menu.style.left = left + "px";
        ctx.menu.style.right = "auto";
        ctx.menu.style.bottom = "auto";
        ctx.menu.style.top = "0px";

        const menuRect = ctx.menu.getBoundingClientRect();
        const top = openAbove
            ? Math.max(OVERLAY_MARGIN, triggerRect.top - OVERLAY_GAP - menuRect.height)
            : Math.min(triggerRect.bottom + OVERLAY_GAP, viewportHeight - OVERLAY_MARGIN - menuRect.height);
        ctx.menu.style.top = Math.max(OVERLAY_MARGIN, top) + "px";
    }

    function repositionActiveDropdown() {
        if (activeDropdown) positionDropdownMenu(activeDropdown);
    }

    function openDropdown(ctx) {
        if (!ctx || ctx.toggle.disabled) return;
        if (activeDropdown && activeDropdown !== ctx) closeDropdown(activeDropdown);
        notifyOverlayOpening("dropdown");
        portalDropdownMenu(ctx);
        ctx.toggle.classList.add("show", "is-open");
        ctx.toggle.setAttribute("aria-expanded", "true");
        ctx.menu.classList.add("show", "is-open");
        ctx.menu.setAttribute("data-atomic-dropdown-open", "true");
        activeDropdown = ctx;
        positionDropdownMenu(ctx);
    }

    function focusMenuItem(menu, direction) {
        const items = Array.from(menu.querySelectorAll(".dropdown-item, a, button"))
            .filter(function (item) { return !item.disabled && item.getAttribute("aria-disabled") !== "true" && !!(item.offsetWidth || item.offsetHeight || item.getClientRects().length); });
        if (!items.length) return;
        const currentIndex = items.indexOf(document.activeElement);
        let nextIndex = 0;
        if (direction === "last") nextIndex = items.length - 1;
        if (direction === "next") nextIndex = currentIndex >= 0 ? (currentIndex + 1) % items.length : 0;
        if (direction === "prev") nextIndex = currentIndex >= 0 ? (currentIndex - 1 + items.length) % items.length : items.length - 1;
        items[nextIndex].focus({ preventScroll: true });
    }

    function enhanceDropdownToggle(toggle) {
        if (!toggle || toggle.dataset.atomicDropdownReady === "true") return;
        const menu = dropdownMenuFor(toggle);
        if (!menu) return;
        toggle.dataset.atomicDropdownReady = "true";
        toggle.classList.add("app-atomic-dropdown-toggle");
        menu.classList.add("app-atomic-dropdown-menu");
        if (!menu.getAttribute("role")) menu.setAttribute("role", "menu");
        menu.querySelectorAll(".dropdown-item, a, button").forEach(function (item) {
            if (!item.getAttribute("role")) item.setAttribute("role", "menuitem");
        });
        if (!toggle.id) toggle.id = uid("appAtomicDropdownToggle");
        if (!menu.id) menu.id = uid("appAtomicDropdownMenu");
        toggle.setAttribute("aria-controls", menu.id);

        const ctx = { toggle: toggle, menu: menu };
        toggle.__atomicDropdownCtx = ctx;

        toggle.addEventListener("shown.bs.dropdown", function () {
            if (activeDropdown && activeDropdown !== ctx) closeDropdown(activeDropdown);
            notifyOverlayOpening("dropdown");
            ctx.toggle.classList.add("show", "is-open");
            ctx.toggle.setAttribute("aria-expanded", "true");
            ctx.menu.classList.add("show", "is-open");
            ctx.menu.setAttribute("data-atomic-dropdown-open", "true");
            activeDropdown = ctx;
            positionDropdownMenu(ctx);
        });
        toggle.addEventListener("hidden.bs.dropdown", function () {
            ctx.toggle.classList.remove("show", "is-open");
            ctx.toggle.setAttribute("aria-expanded", "false");
            ctx.menu.classList.remove("show", "is-open");
            ctx.menu.setAttribute("data-atomic-dropdown-open", "false");
            if (activeDropdown === ctx) activeDropdown = null;
        });

        toggle.addEventListener("click", function (event) {
            if (window.bootstrap && window.bootstrap.Dropdown) return;
            event.preventDefault();
            event.stopPropagation();
            if (menu.classList.contains("show")) closeDropdown(ctx); else openDropdown(ctx);
        });
        toggle.addEventListener("keydown", function (event) {
            if (["ArrowDown", "Enter", " "].includes(event.key)) {
                event.preventDefault();
                if (window.bootstrap && window.bootstrap.Dropdown) {
                    const instance = window.bootstrap.Dropdown.getOrCreateInstance(toggle);
                    instance.show();
                } else {
                    openDropdown(ctx);
                }
                window.setTimeout(function () { focusMenuItem(menu, "next"); }, 0);
            }
        });
        menu.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                event.preventDefault();
                if (window.bootstrap && window.bootstrap.Dropdown) {
                    const instance = window.bootstrap.Dropdown.getOrCreateInstance(toggle);
                    instance.hide();
                } else {
                    closeDropdown(ctx);
                }
                toggle.focus({ preventScroll: true });
            } else if (event.key === "ArrowDown") {
                event.preventDefault();
                focusMenuItem(menu, "next");
            } else if (event.key === "ArrowUp") {
                event.preventDefault();
                focusMenuItem(menu, "prev");
            } else if (event.key === "Home") {
                event.preventDefault();
                focusMenuItem(menu, "next");
            } else if (event.key === "End") {
                event.preventDefault();
                focusMenuItem(menu, "last");
            }
        });
        menu.addEventListener("click", function (event) {
            const item = event.target.closest(".dropdown-item, a, button");
            if (!item || item.disabled || item.getAttribute("aria-disabled") === "true") return;
            window.setTimeout(function () {
                if (activeDropdown === ctx) closeDropdown(ctx);
            }, 0);
        });
    }

    function enhanceScope(scope) {
        if (!scope || !scope.querySelectorAll) return;
        scope.querySelectorAll('input[type="time"]').forEach(enhanceTimeInput);
        scope.querySelectorAll('input[type="password"]').forEach(enhancePasswordInput);
        scope.querySelectorAll('[data-bs-toggle="dropdown"], .dropdown-toggle').forEach(enhanceDropdownToggle);
    }

    enhanceScope(document);
    body.setAttribute("data-atomic-time-password-dropdown", "true");

    document.addEventListener("click", function (event) {
        const target = event.target;
        if (activeTime && !activeTime.root.contains(target) && !activeTime.popover.contains(target)) closeTime();
        if (activeDropdown && !activeDropdown.menu.contains(target) && !activeDropdown.toggle.contains(target)) closeDropdown(activeDropdown);
    });
    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
            closeTime();
            if (activeDropdown) closeDropdown(activeDropdown);
        }
    });
    document.addEventListener("app:atomic-overlay-opening", function (event) {
        const source = event.detail && event.detail.source;
        if (source !== "time") closeTime();
        if (source !== "dropdown" && activeDropdown) closeDropdown(activeDropdown);
    });
    window.addEventListener("resize", repositionActiveTime);
    window.addEventListener("scroll", repositionActiveTime, true);
    window.addEventListener("resize", repositionActiveDropdown);
    window.addEventListener("scroll", repositionActiveDropdown, true);

    const observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
            if (mutation.type === "attributes") {
                const target = mutation.target;
                if (target && target.__atomicTimeCtx) {
                    updateTimeControl(target.__atomicTimeCtx);
                }
                return;
            }
            mutation.addedNodes.forEach(function (node) {
                if (!isElement(node)) return;
                if (node.matches && node.matches('input[type="time"]')) enhanceTimeInput(node);
                if (node.matches && node.matches('input[type="password"]')) enhancePasswordInput(node);
                if (node.matches && node.matches('[data-bs-toggle="dropdown"], .dropdown-toggle')) enhanceDropdownToggle(node);
                enhanceScope(node);
            });
        });
    });
    observer.observe(body, { childList: true, subtree: true, attributes: true, attributeFilter: ["disabled", "readonly", "required", "min", "max", "value", "type"] });
}());

// ==================================================
// Tahap 10.23 - Atomic Static Alert + Empty State Polish
// - Decorates legacy static Bootstrap alerts and empty states consistently
// - Does not intercept submit/navigation/business logic
// ==================================================
(function () {
    const body = document.body;
    if (!body || body.dataset.atomicStaticPanelsReady === "true") return;
    body.dataset.atomicStaticPanelsReady = "true";

    function isElement(node) {
        return node && node.nodeType === 1;
    }

    function isFlashOrToast(alert) {
        return alert.classList.contains("app-alert") ||
            alert.classList.contains("app-flash-centered") ||
            alert.classList.contains("app-atomic-toast") ||
            alert.closest(".app-flash-center-host, .app-atomic-toast-host");
    }

    function enhanceStaticAlert(alert) {
        if (!isElement(alert) || alert.dataset.atomicStaticAlertReady === "true") return;
        if (!alert.classList.contains("alert") || isFlashOrToast(alert)) return;
        alert.dataset.atomicStaticAlertReady = "true";
        alert.classList.add("app-static-alert");
        if (!alert.getAttribute("role")) {
            const isDanger = alert.classList.contains("alert-danger") || alert.classList.contains("alert-error") || alert.classList.contains("alert-warning");
            alert.setAttribute("role", isDanger ? "alert" : "note");
        }
    }

    function enhanceEmptyState(node) {
        if (!isElement(node) || node.dataset.atomicEmptyStateReady === "true") return;
        const matchesEmpty = node.matches(".empty-state, .app-empty-state, .dashboard-empty-state, .dashboard-chart-empty, [data-empty-state='true'], [data-ui-empty-state]");
        if (!matchesEmpty) return;
        node.dataset.atomicEmptyStateReady = "true";
        node.classList.add("app-empty-state-polished");
        if (!node.getAttribute("role")) node.setAttribute("role", "status");
        if (!node.querySelector(":scope > .empty-state-icon") && !node.querySelector(":scope > i:first-child")) {
            const icon = document.createElement("div");
            icon.className = "empty-state-icon";
            icon.setAttribute("aria-hidden", "true");
            icon.innerHTML = '<i class="bi bi-inbox"></i>';
            node.insertBefore(icon, node.firstChild);
        }
    }

    function enhanceScope(scope) {
        if (!scope || !scope.querySelectorAll) return;
        if (scope.matches && scope.matches(".alert")) enhanceStaticAlert(scope);
        if (scope.matches && scope.matches(".empty-state, .app-empty-state, .dashboard-empty-state, .dashboard-chart-empty, [data-empty-state='true'], [data-ui-empty-state]")) enhanceEmptyState(scope);
        scope.querySelectorAll(".alert").forEach(enhanceStaticAlert);
        scope.querySelectorAll(".empty-state, .app-empty-state, .dashboard-empty-state, .dashboard-chart-empty, [data-empty-state='true'], [data-ui-empty-state]").forEach(enhanceEmptyState);
    }

    enhanceScope(document);

    const observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
            mutation.addedNodes.forEach(function (node) {
                if (!isElement(node)) return;
                enhanceScope(node);
            });
        });
    });
    observer.observe(body, { childList: true, subtree: true });
}());

// ==================================================
// Tahap 10.24 - Atomic Table, Scroll & Data Density Polish
// - Decorates legacy tables and responsive wrappers consistently
// - Keeps original markup/data/business flow untouched
// ==================================================
(function () {
    const body = document.body;
    if (!body || body.dataset.atomicTablesReady === "true") return;
    body.dataset.atomicTablesReady = "true";

    function isElement(node) {
        return node && node.nodeType === 1;
    }

    function isPrintContext(node) {
        return !!(node && node.closest && node.closest(".print-page, .print-shell, [data-print-page], .invoice-print, .receipt-print"));
    }

    function closestHeadingText(node) {
        const card = node.closest(".card, .app-card, .content-card, section, main");
        const heading = card ? card.querySelector("h1, h2, h3, h4, h5, .card-title, .section-title, .content-title") : null;
        return heading ? heading.textContent.trim().replace(/\s+/g, " ") : "Tabel data";
    }

    function looksNumeric(text) {
        const value = (text || "").trim();
        if (!value || value.length > 32) return false;
        return /^(Rp\s*)?[\-+]?\d{1,3}([.,]\d{3})*([.,]\d+)?(%|\s*x)?$/.test(value) || /^[\-+]?\d+([.,]\d+)?(%|\s*x)?$/.test(value);
    }

    function markCells(table) {
        table.querySelectorAll("td, th").forEach(function (cell) {
            if (cell.dataset.atomicTableCellReady === "true") return;
            cell.dataset.atomicTableCellReady = "true";

            if (cell.classList.contains("text-end") || cell.classList.contains("money-cell") || cell.classList.contains("table-money") || looksNumeric(cell.textContent)) {
                cell.classList.add("app-table-number-cell");
            }

            const hasActions = cell.querySelector(".btn, .app-btn, .dropdown, .dropdown-toggle, form[action], button, a[href]") &&
                (cell.cellIndex === cell.parentElement.children.length - 1 || cell.classList.contains("text-end") || cell.classList.contains("actions") || cell.classList.contains("table-actions"));
            if (hasActions) {
                cell.classList.add("app-table-action-cell");
            }
        });
    }

    function updateScrollState(shell) {
        if (!shell) return;
        const maxScroll = shell.scrollWidth - shell.clientWidth;
        shell.classList.toggle("is-scrollable", maxScroll > 2);
        shell.classList.toggle("is-scroll-start", shell.scrollLeft <= 2);
        shell.classList.toggle("is-scroll-end", shell.scrollLeft >= maxScroll - 2);
        shell.classList.toggle("is-scroll-middle", maxScroll > 2 && shell.scrollLeft > 2 && shell.scrollLeft < maxScroll - 2);
    }

    function enhanceScrollShell(shell) {
        if (!isElement(shell) || shell.dataset.atomicTableShellReady === "true") return;
        shell.dataset.atomicTableShellReady = "true";
        shell.classList.add("app-table-scroll-shell");
        if (!shell.hasAttribute("tabindex")) shell.setAttribute("tabindex", "0");
        if (!shell.hasAttribute("role")) shell.setAttribute("role", "region");
        if (!shell.hasAttribute("aria-label")) {
            shell.setAttribute("aria-label", closestHeadingText(shell));
        }
        updateScrollState(shell);
        shell.addEventListener("scroll", function () { updateScrollState(shell); }, { passive: true });
        window.addEventListener("resize", function () { updateScrollState(shell); }, { passive: true });
    }

    function wrapNakedTable(table) {
        if (!isElement(table) || isPrintContext(table)) return null;
        const parent = table.parentElement;
        if (!parent || parent.classList.contains("table-responsive") || parent.classList.contains("app-table-scroll-shell")) return parent;
        if (table.closest(".table-responsive, .app-table-scroll-shell, .dropdown-menu, .app-atomic-select-menu, .app-date-picker-popover")) return parent;
        const wrapper = document.createElement("div");
        wrapper.className = "table-responsive app-table-scroll-shell app-table-auto-wrapper";
        parent.insertBefore(wrapper, table);
        wrapper.appendChild(table);
        return wrapper;
    }

    function enhanceTable(table) {
        if (!isElement(table) || table.dataset.atomicTableReady === "true") return;
        if (!table.matches("table")) return;
        if (table.matches(".ui-data-table, [data-ui-table]")) return;
        table.dataset.atomicTableReady = "true";
        table.classList.add("app-atomic-table");
        if (!table.querySelector("thead")) table.classList.add("app-table-no-head");
        if (table.querySelector("tbody tr") && table.querySelectorAll("tbody tr").length <= 3) {
            table.classList.add("app-table-short");
        }
        markCells(table);
        const shell = wrapNakedTable(table) || table.closest(".table-responsive, .app-table-scroll-shell");
        if (shell) enhanceScrollShell(shell);
    }

    function enhanceScope(scope) {
        if (!scope || !scope.querySelectorAll) return;
        if (scope.matches && scope.matches("table")) enhanceTable(scope);
        scope.querySelectorAll("table").forEach(enhanceTable);
        if (scope.matches && scope.matches(".table-responsive, .app-table-scroll-shell")) enhanceScrollShell(scope);
        scope.querySelectorAll(".table-responsive, .app-table-scroll-shell").forEach(enhanceScrollShell);
    }

    enhanceScope(document);
    window.setTimeout(function () {
        document.querySelectorAll(".app-table-scroll-shell").forEach(updateScrollState);
    }, 250);

    const observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
            mutation.addedNodes.forEach(function (node) {
                if (!isElement(node)) return;
                enhanceScope(node);
            });
        });
    });
    observer.observe(body, { childList: true, subtree: true });
}());

// ==================================================
// Tahap 10.25 - Atomic Print & Export Action UI Polish
// - Normalizes print/export actions and print lifecycle feedback
// - UI layer only; no route/service/database/business-flow changes
// ==================================================
(function () {
    const body = document.body;
    if (!body || body.dataset.atomicPrintExportReady === "true") return;
    body.dataset.atomicPrintExportReady = "true";

    const nativePrint = typeof window.print === "function" ? window.print.bind(window) : null;
    let printStatusTimer = null;

    function isElement(node) {
        return node && node.nodeType === 1;
    }

    function normalizedText(node) {
        return (node && node.textContent ? node.textContent : "").replace(/\s+/g, " ").trim();
    }

    function hrefValue(node) {
        return String(node && node.getAttribute ? (node.getAttribute("href") || "") : "").toLowerCase();
    }

    function isPrintPage() {
        const path = String(window.location && window.location.pathname ? window.location.pathname : "").toLowerCase();
        return /(^|\/)print(\/|_|-|$)/.test(path) || /(^|\/)[^/]*print[^/]*$/.test(path) || !!document.querySelector(".print-page, .print-shell, .invoice-print, .receipt-print, [data-print-page]");
    }

    function isInlinePrintAction(node) {
        const attr = String(node && node.getAttribute ? (node.getAttribute("onclick") || "") : "").toLowerCase();
        return attr.indexOf("window.print") !== -1 || attr.indexOf("print()") !== -1;
    }

    function isPrintAction(node) {
        if (!isElement(node)) return false;
        if (node.matches && node.matches("[data-native-print], [data-app-print-action='off']")) return false;
        if (isInlinePrintAction(node)) return true;
        const href = hrefValue(node);
        const text = normalizedText(node).toLowerCase();
        if (href.indexOf("/print") !== -1 || href.indexOf("print_") !== -1 || href.indexOf("_print") !== -1) return true;
        return /\b(cetak|print|save pdf|pdf browser|kwitansi)\b/.test(text) && !isExportAction(node);
    }

    function isExportAction(node) {
        if (!isElement(node)) return false;
        if (node.matches && node.matches("[data-native-export], [data-app-export-action='off']")) return false;
        const href = hrefValue(node);
        const text = normalizedText(node).toLowerCase();
        return href.indexOf("export") !== -1 || href.indexOf("download") !== -1 || /\b(export|csv|excel|xlsx|download|unduh)\b/.test(text);
    }

    function ensureStatusHost() {
        let host = document.getElementById("appPrintExportStatusHost");
        if (!host) {
            host = document.createElement("div");
            host.id = "appPrintExportStatusHost";
            host.className = "app-print-export-status-host";
            host.setAttribute("aria-live", "polite");
            host.setAttribute("aria-atomic", "true");
            document.body.appendChild(host);
        }
        return host;
    }

    function showStatus(message, tone) {
        const host = ensureStatusHost();
        host.innerHTML = "";
        const pill = document.createElement("div");
        pill.className = "app-print-export-status app-print-export-status-" + (tone || "info");
        pill.innerHTML = '<span class="app-print-export-spinner" aria-hidden="true"></span><span></span>';
        const text = pill.querySelector("span:last-child");
        if (text) text.textContent = message || "Menyiapkan dokumen...";
        host.appendChild(pill);
        host.classList.add("is-visible");
        window.clearTimeout(printStatusTimer);
        printStatusTimer = window.setTimeout(function () {
            host.classList.remove("is-visible");
        }, 4500);
    }

    function hideStatus(delay) {
        window.clearTimeout(printStatusTimer);
        printStatusTimer = window.setTimeout(function () {
            const host = document.getElementById("appPrintExportStatusHost");
            if (host) host.classList.remove("is-visible");
        }, Number.isFinite(delay) ? delay : 500);
    }

    function markAction(node) {
        if (!isElement(node) || node.dataset.atomicPrintExportActionReady === "true") return;
        const print = isPrintAction(node);
        const exportAction = isExportAction(node);
        if (!print && !exportAction) return;
        node.dataset.atomicPrintExportActionReady = "true";
        node.classList.add("app-print-export-action");
        node.classList.toggle("app-print-action", print);
        node.classList.toggle("app-export-action", exportAction);
        if (!node.hasAttribute("aria-label")) {
            node.setAttribute("aria-label", print ? "Cetak atau simpan PDF" : "Export atau download data");
        }
        if (print && !node.querySelector(".bi-printer, [data-print-icon]") && !/bi-printer/.test(node.innerHTML || "")) {
            node.dataset.printActionNoIcon = "true";
        }
    }

    function enhanceScope(scope) {
        if (!scope || !scope.querySelectorAll) return;
        const selector = "a, button, input[type='button'], input[type='submit']";
        if (scope.matches && scope.matches(selector)) markAction(scope);
        scope.querySelectorAll(selector).forEach(markAction);
    }

    function preparePrint(message) {
        body.classList.add("app-print-preparing");
        showStatus(message || "Menyiapkan dokumen untuk cetak / save PDF...", "print");
        if (typeof window.appToast === "function") {
            window.appToast("Menyiapkan tampilan cetak / save PDF.", "info", { duration: 2200 });
        }
    }

    if (isPrintPage()) {
        body.classList.add("app-print-page");
    }

    if (nativePrint && window.__idhaBogaPrintWrapped !== true) {
        window.__idhaBogaPrintWrapped = true;
        window.print = function () {
            preparePrint("Membuka dialog cetak / save PDF...");
            window.setTimeout(function () {
                try {
                    nativePrint();
                } finally {
                    hideStatus(1200);
                }
            }, 80);
        };
    }

    window.addEventListener("beforeprint", function () {
        body.classList.add("app-is-printing");
        body.classList.remove("app-print-preparing");
        showStatus("Mode cetak aktif...", "print");
    });

    window.addEventListener("afterprint", function () {
        body.classList.remove("app-is-printing", "app-print-preparing");
        hideStatus(350);
    });

    document.addEventListener("click", function (event) {
        const action = event.target && event.target.closest ? event.target.closest("a, button, input[type='button'], input[type='submit']") : null;
        if (!action || !isElement(action)) return;
        if (action.matches("[data-native-print], [data-native-export], [data-app-print-action='off'], [data-app-export-action='off']")) return;

        if (isPrintAction(action)) {
            action.classList.add("is-printing-action");
            preparePrint(action.tagName === "A" && hrefValue(action) ? "Membuka halaman cetak / save PDF..." : "Membuka dialog cetak / save PDF...");
            window.setTimeout(function () { action.classList.remove("is-printing-action"); }, 1800);
            return;
        }

        if (isExportAction(action)) {
            action.classList.add("is-exporting-action");
            showStatus("Menyiapkan export / download data...", "export");
            if (typeof window.appToast === "function") {
                window.appToast("Menyiapkan export/download data.", "info", { duration: 2200 });
            }
            window.setTimeout(function () {
                action.classList.remove("is-exporting-action");
                hideStatus(300);
            }, 2500);
        }
    }, true);

    enhanceScope(document);
    const observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
            mutation.addedNodes.forEach(function (node) {
                if (!isElement(node)) return;
                enhanceScope(node);
            });
        });
    });
    observer.observe(body, { childList: true, subtree: true });
}());

// ==================================================
// Tahap 10.26 - Atomic Textarea, Text Input & Filter UI Polish
// - Normalizes text-like controls and textarea helper UX globally
// - UI layer only; original form fields remain the source of truth
// ==================================================
(function () {
    const body = document.body;
    if (!body || body.dataset.atomicTextInputReady === "true") return;
    body.dataset.atomicTextInputReady = "true";

    const TEXT_TYPES = new Set(["", "text", "email", "tel", "url", "search"]);
    const FILTER_HINTS = /(cari|search|filter|nama|kode|nomor|no\.|no_|no-|keyword|q\b|query)/i;

    function isElement(node) {
        return node && node.nodeType === 1;
    }

    function shouldSkip(control) {
        return !control || control.closest("[data-no-atomic-fields], [data-atomic-ui='off']") || control.matches("[data-native-ui], [data-app-text-ui='off']");
    }

    function controlText(control) {
        return [
            control.getAttribute("name"),
            control.getAttribute("id"),
            control.getAttribute("placeholder"),
            control.getAttribute("aria-label"),
            control.getAttribute("data-label")
        ].filter(Boolean).join(" ");
    }

    function syncValueState(control) {
        control.dataset.hasValue = control.value && String(control.value).trim() !== "" ? "true" : "false";
        if (typeof control.checkValidity === "function") {
            const hasUserValue = !!(control.value && String(control.value).trim() !== "");
            const isRequiredEmpty = control.required && !hasUserValue;
            control.classList.toggle("is-app-invalid", !control.checkValidity() && (hasUserValue || !isRequiredEmpty));
        }
    }

    function enhanceTextInput(input) {
        if (!input || shouldSkip(input) || input.dataset.atomicTextFieldReady === "true") return;
        const type = String(input.getAttribute("type") || "text").toLowerCase();
        if (!TEXT_TYPES.has(type)) return;
        input.dataset.atomicTextFieldReady = "true";
        input.classList.add("app-text-field");
        if (FILTER_HINTS.test(controlText(input)) || input.closest("form") && /filter|search|cari/i.test(controlText(input.closest("form")))) {
            input.classList.add("app-filter-text-field");
        }
        syncValueState(input);
        input.addEventListener("input", function () { syncValueState(input); });
        input.addEventListener("change", function () { syncValueState(input); });
        input.addEventListener("invalid", function () { input.classList.add("is-app-invalid"); }, true);
    }

    function footerFor(textarea) {
        const next = textarea.nextElementSibling;
        if (next && next.classList && next.classList.contains("app-textarea-footer")) return next;
        const footer = document.createElement("div");
        footer.className = "app-textarea-footer";
        footer.setAttribute("aria-live", "polite");
        footer.innerHTML = '<span class="app-textarea-count"></span>';
        textarea.insertAdjacentElement("afterend", footer);
        return footer;
    }

    function updateTextareaMetrics(textarea) {
        syncValueState(textarea);
        if (textarea.classList.contains("app-textarea-autosize")) {
            textarea.style.height = "auto";
            textarea.style.height = Math.max(textarea.scrollHeight, 96) + "px";
        }
        const footer = textarea._appTextareaFooter;
        if (!footer) return;
        const counter = footer.querySelector(".app-textarea-count");
        if (!counter) return;
        const length = textarea.value ? textarea.value.length : 0;
        const max = Number.parseInt(textarea.getAttribute("maxlength") || "", 10);
        if (Number.isFinite(max) && max > 0) {
            counter.textContent = length + " / " + max + " karakter";
            const ratio = length / max;
            footer.classList.toggle("is-warning", ratio >= 0.85 && ratio < 1);
            footer.classList.toggle("is-danger", ratio >= 1);
        } else {
            counter.textContent = length ? length + " karakter" : "Catatan kosong";
            footer.classList.remove("is-warning", "is-danger");
        }
    }

    function enhanceTextarea(textarea) {
        if (!textarea || shouldSkip(textarea) || textarea.dataset.atomicTextareaReady === "true") return;
        textarea.dataset.atomicTextareaReady = "true";
        textarea.classList.add("app-textarea-field");
        const isLongFreeText = !textarea.closest(".input-group") && !textarea.matches("[data-no-autosize], [rows='1'], [rows='2']");
        if (isLongFreeText) {
            textarea.classList.add("app-textarea-autosize");
        }
        if (!textarea.matches("[data-no-textarea-footer]") && !textarea.closest(".input-group")) {
            textarea._appTextareaFooter = footerFor(textarea);
        }
        updateTextareaMetrics(textarea);
        textarea.addEventListener("input", function () { updateTextareaMetrics(textarea); });
        textarea.addEventListener("change", function () { updateTextareaMetrics(textarea); });
        textarea.addEventListener("invalid", function () { textarea.classList.add("is-app-invalid"); }, true);
    }

    function enhanceScope(scope) {
        if (!scope || !scope.querySelectorAll) return;
        if (scope.matches && scope.matches("input")) enhanceTextInput(scope);
        if (scope.matches && scope.matches("textarea")) enhanceTextarea(scope);
        scope.querySelectorAll("input").forEach(enhanceTextInput);
        scope.querySelectorAll("textarea").forEach(enhanceTextarea);
    }

    enhanceScope(document);
    window.setTimeout(function () {
        document.querySelectorAll("textarea.app-textarea-field").forEach(updateTextareaMetrics);
    }, 120);

    const observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
            mutation.addedNodes.forEach(function (node) {
                if (!isElement(node)) return;
                enhanceScope(node);
            });
            if (mutation.type === "attributes" && isElement(mutation.target)) {
                enhanceScope(mutation.target);
            }
        });
    });
    observer.observe(body, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["value", "class", "disabled", "readonly", "required", "maxlength", "placeholder"]
    });
}());

// ==================================================
// Tahap 10.27 - Atomic Page Header & Navigation Context Polish
// - Normalizes page headers, adds lightweight breadcrumb context, and keeps active sidebar visible
// - UI layer only; no route/service/model/database/realtime/payment/manual billing changes
// ==================================================
(function () {
    const body = document.body;
    if (!body || body.dataset.pageNavPolishReady === "true") return;
    if (!body.classList.contains("is-authenticated")) return;
    body.dataset.pageNavPolishReady = "true";

    function isElement(node) {
        return node && node.nodeType === 1;
    }

    function cleanText(value) {
        return String(value || "").replace(/\s+/g, " ").trim();
    }

    function textOf(node) {
        return cleanText(node ? node.textContent : "");
    }

    function firstVisibleText(nodes) {
        for (const node of nodes) {
            const text = textOf(node);
            if (text) return text;
        }
        return "";
    }

    function activeSidebarLink() {
        return document.querySelector("#appSidebar .sidebar-link[aria-current='page'], #appSidebar .sidebar-link.active");
    }

    function activeModuleName(link) {
        if (!link) return "";
        const group = link.closest("details.sidebar-group");
        if (!group) return "";
        const title = group.querySelector(".sidebar-group-title span:last-child, .sidebar-group-title");
        return textOf(title);
    }

    function pageTitleFromHeader(header) {
        const preferred = header.querySelector("h1, h2, h3, .page-title, .app-page-title, [data-page-title]");
        return textOf(preferred) || firstVisibleText(header.children) || document.title || "Halaman";
    }

    function markHeaderParts(header) {
        if (!header || header.dataset.pageHeaderAtomicReady === "true") return;
        header.dataset.pageHeaderAtomicReady = "true";
        header.classList.add("app-page-header-atomic");

        const title = header.querySelector("h1, h2, h3, .page-title, .app-page-title, [data-page-title]");
        if (title) title.classList.add("app-page-title-atomic");

        header.querySelectorAll("p, small, .text-muted, .page-subtitle, .app-page-subtitle").forEach(function (node) {
            node.classList.add("app-page-subtitle-atomic");
        });

        Array.from(header.children).forEach(function (child) {
            if (!isElement(child)) return;
            const hasActions = child.matches(".page-actions, .action-bar, .btn-toolbar, .form-actions") ||
                !!child.querySelector(".btn, .app-btn, button, a[href], form, .dropdown, [data-bs-toggle='dropdown']");
            const hasHeading = !!child.querySelector("h1, h2, h3, .page-title, .app-page-title");
            if (hasActions && !hasHeading) {
                child.classList.add("app-page-actions-atomic");
            } else if (hasHeading || child.matches(".page-header-main")) {
                child.classList.add("app-page-header-main-atomic");
            }
        });
    }

    function makeCrumb(label, className, href) {
        const node = href ? document.createElement("a") : document.createElement("span");
        node.className = className;
        node.textContent = label;
        if (href) node.href = href;
        return node;
    }

    function makeSeparator() {
        const sep = document.createElement("span");
        sep.className = "app-context-separator";
        sep.setAttribute("aria-hidden", "true");
        sep.textContent = "›";
        return sep;
    }

    function ensureContextBar(header, title) {
        if (!header || header.classList.contains("no-print") || header.closest("[data-no-auto-breadcrumb], .print-page, .print-sheet")) return;
        const previous = header.previousElementSibling;
        if (previous && previous.classList && previous.classList.contains("app-page-context-bar")) return;
        if (document.querySelector(".app-page-context-bar[data-generated='true']")) return;

        const active = activeSidebarLink();
        const moduleName = activeModuleName(active);
        const currentLabel = textOf(active) || title || "Halaman";
        const dashboard = document.querySelector("#appSidebar a.sidebar-link[href*='dashboard']");
        const nav = document.createElement("nav");
        nav.className = "app-page-context-bar";
        nav.dataset.generated = "true";
        nav.setAttribute("aria-label", "Konteks halaman");

        nav.appendChild(makeCrumb("Dashboard", "app-context-home", dashboard ? dashboard.href : "#"));
        if (moduleName) {
            nav.appendChild(makeSeparator());
            nav.appendChild(makeCrumb(moduleName, "app-context-module"));
        }
        nav.appendChild(makeSeparator());
        nav.appendChild(makeCrumb(title || currentLabel, "app-context-current"));

        header.insertAdjacentElement("beforebegin", nav);
    }

    function decorateHeaders() {
        const headers = Array.from(document.querySelectorAll("main .page-header:not(.no-print), main .app-page-header:not(.no-print)"));
        headers.forEach(markHeaderParts);
        const firstHeader = headers.find(function (header) { return !header.closest(".print-page, .print-sheet"); });
        if (firstHeader) {
            ensureContextBar(firstHeader, pageTitleFromHeader(firstHeader));
        }
    }

    function polishSidebarContext() {
        const sidebar = document.getElementById("appSidebar");
        if (!sidebar) return;
        sidebar.dataset.sidebarNavPolished = "true";
        const active = activeSidebarLink();
        if (!active) return;
        active.setAttribute("aria-current", "page");
        const group = active.closest("details.sidebar-group");
        if (group) group.open = true;
        window.setTimeout(function () {
            try {
                active.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" });
            } catch (error) {
                active.scrollIntoView(false);
            }
        }, 180);

        const moduleName = activeModuleName(active);
        const topbarHeading = document.querySelector(".topbar-heading");
        const topbarSubtitle = topbarHeading ? topbarHeading.querySelector(".topbar-subtitle") : null;
        if (topbarHeading && topbarSubtitle && moduleName) {
            topbarHeading.dataset.topbarContext = "true";
            topbarSubtitle.setAttribute("data-current-context", moduleName);
        }
    }

    function enhanceScope(scope) {
        if (!scope || !scope.querySelectorAll) return;
        if (scope.matches && (scope.matches(".page-header") || scope.matches(".app-page-header"))) markHeaderParts(scope);
        scope.querySelectorAll(".page-header:not(.no-print), .app-page-header:not(.no-print)").forEach(markHeaderParts);
    }

    decorateHeaders();
    polishSidebarContext();

    const observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
            mutation.addedNodes.forEach(function (node) {
                if (!isElement(node)) return;
                enhanceScope(node);
            });
        });
    });
    observer.observe(body, { childList: true, subtree: true });
}());

// ==================================================
// Atomic Badge, KPI Metric & Progress UI Polish
// - Normalizes status badges and KPI cards without changing backend data
// - Adds consistent progress/metric semantics for visual audit coverage
// ==================================================
(function () {
    const body = document.body;
    if (!body || body.dataset.badgeMetricPolishReady === "true") return;
    body.dataset.badgeMetricPolishReady = "true";

    const DONE_WORDS = ["paid", "lunas", "done", "settled", "complete", "completed", "selesai", "approved", "terbayar", "aktif", "success", "sesuai", "seimbang", "masuk"];
    const PROGRESS_WORDS = ["partial", "partially", "sebagian", "progress", "in_progress", "pending", "draft", "locked", "open", "on the way", "proses", "siap tagih", "belum dibuat", "hutang", "invoice", "periode", "rekap", "transfer", "bill"];
    const WARNING_WORDS = ["warning", "rendah", "menipis", "perlu cek", "belum", "cek", "mismatch", "shortage", "kurang", "jatuh tempo", "overdue", "moved"];
    const DANGER_WORDS = ["void", "batal", "cancel", "cancelled", "rejected", "tolak", "danger", "error", "gagal", "rusak", "hilang", "minus", "unpaid"];

    function isElement(node) {
        return node && node.nodeType === 1;
    }

    function cleanText(value) {
        return String(value || "").replace(/\s+/g, " ").trim();
    }

    function includesAny(text, words) {
        return words.some(function (word) { return text.indexOf(word) !== -1; });
    }

    function toneForBadge(badge) {
        const text = cleanText(badge.textContent).toLowerCase();
        const className = String(badge.className || "").toLowerCase();
        const haystack = `${className} ${text}`;

        if (includesAny(haystack, DANGER_WORDS) || /bg-danger|text-bg-danger|status-danger/.test(haystack)) return "danger";
        if (includesAny(haystack, WARNING_WORDS) || /bg-warning|text-bg-warning|status-warning/.test(haystack)) return "warning";
        if (includesAny(haystack, DONE_WORDS) || /bg-success|text-bg-success|status-done|status-success/.test(haystack)) return "success";
        if (includesAny(haystack, PROGRESS_WORDS) || /status-progress|bg-info|text-bg-info/.test(haystack)) return "progress";
        if (/bg-primary|text-bg-primary/.test(haystack)) return "primary";
        return "neutral";
    }

    function decorateBadge(badge) {
        if (!isElement(badge) || badge.dataset.atomicBadgeReady === "true") return;
        if (badge.closest(".app-toast, .app-confirm-modal, .app-select-menu, .app-date-popover, .app-time-popover")) return;
        badge.dataset.atomicBadgeReady = "true";
        badge.classList.add("app-atomic-badge");
        const tone = toneForBadge(badge);
        badge.dataset.badgeTone = tone;
        const text = cleanText(badge.textContent);
        if (text && !badge.getAttribute("title")) {
            badge.setAttribute("title", text);
        }
        if (!badge.getAttribute("aria-label") && text) {
            badge.setAttribute("aria-label", `Status: ${text}`);
        }
    }

    function valueText(card) {
        const node = card.querySelector(".stat-value, .metric-value, .kpi-value, h3, h2, strong");
        return cleanText(node ? node.textContent : "");
    }

    function labelText(card) {
        const node = card.querySelector(".stat-label, .metric-label, .kpi-label, p, small, .text-muted");
        return cleanText(node ? node.textContent : "");
    }

    function decorateMetricCard(card) {
        if (!isElement(card) || card.dataset.atomicMetricReady === "true") return;
        if (card.closest(".print-page, .print-sheet, .invoice-print")) return;
        card.dataset.atomicMetricReady = "true";
        card.classList.add("app-atomic-metric-card");

        const value = valueText(card);
        const label = labelText(card);
        if (value.length > 13) card.dataset.metricValueSize = "compact";
        if (value && !card.getAttribute("aria-label")) {
            card.setAttribute("aria-label", label ? `${label}: ${value}` : value);
        }

        const icon = card.querySelector("i, .app-stat-icon, .kpi-icon, .metric-icon, .stat-icon");
        if (icon) {
            icon.classList.add("app-atomic-metric-icon");
            icon.setAttribute("aria-hidden", "true");
        }
    }

    function decorateMetricGrids(scope) {
        const cards = scope.querySelectorAll(".app-atomic-metric-card");
        cards.forEach(function (card) {
            const parent = card.parentElement;
            if (!parent || parent.dataset.atomicMetricGridReady === "true") return;
            const siblingCount = parent.querySelectorAll(".app-atomic-metric-card").length;
            if (siblingCount >= 2) {
                parent.dataset.atomicMetricGridReady = "true";
                parent.classList.add("app-atomic-metric-grid");
            }
        });
    }

    function decorateProgress(progress) {
        if (!isElement(progress) || progress.dataset.atomicProgressReady === "true") return;
        progress.dataset.atomicProgressReady = "true";
        progress.classList.add("app-atomic-progress");
        if (!progress.getAttribute("role") && progress.matches(".progress, .expense-progress")) {
            progress.setAttribute("role", "progressbar");
        }
        const bar = progress.matches(".progress-bar") ? progress : progress.querySelector(".progress-bar, [style*='width']");
        if (bar) {
            bar.classList.add("app-atomic-progress-bar");
        }
    }

    function enhanceScope(scope) {
        if (!scope || !scope.querySelectorAll) return;
        const badgeSelector = ".status-badge, .status-pill, .badge-soft, .badge:not(.dropdown-toggle):not(.sidebar-badge):not(.app-toast)";
        if (scope.matches && scope.matches(badgeSelector)) decorateBadge(scope);
        scope.querySelectorAll(badgeSelector).forEach(decorateBadge);

        const metricSelector = ".app-stat-card, .app-stat-card-compact, .kpi-card, .summary-card, .stat-card, .metric-card, .dashboard-stat-card, .dashboard-kpi-card, .revenue-stat-card, .receivables-kpi-card, .sla-summary-card";
        if (scope.matches && scope.matches(metricSelector)) decorateMetricCard(scope);
        scope.querySelectorAll(metricSelector).forEach(decorateMetricCard);
        decorateMetricGrids(document);

        const progressSelector = ".progress, .progress-bar, .expense-progress, [role='progressbar']";
        if (scope.matches && scope.matches(progressSelector)) decorateProgress(scope);
        scope.querySelectorAll(progressSelector).forEach(decorateProgress);
    }

    enhanceScope(document);

    const observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
            mutation.addedNodes.forEach(function (node) {
                if (isElement(node)) enhanceScope(node);
            });
        });
    });
    observer.observe(body, { childList: true, subtree: true });
}());

// ==================================================
// Atomic Card, Panel & Section Layout UI Polish
// - Normalizes high-volume cards/panels/sections without changing markup contracts
// - Adds safe visual hooks only; original content/actions remain source-of-truth
// ==================================================
(function () {
    const body = document.body;
    if (!body || body.dataset.cardSectionPolishReady === "true") return;
    body.dataset.cardSectionPolishReady = "true";

    function isElement(node) {
        return node && node.nodeType === 1;
    }

    function cleanText(value) {
        return String(value || "").replace(/\s+/g, " ").trim();
    }

    function isExcluded(node) {
        return Boolean(node.closest(".print-page, .print-sheet, .invoice-print, .app-toast, .app-confirm-modal, .app-select-menu, .app-date-popover, .app-time-popover, .dropdown-menu, .modal"));
    }

    function firstHeadingText(container) {
        const heading = container.querySelector("h1, h2, h3, h4, h5, h6, .card-title, .app-card-title, .section-title");
        return heading ? cleanText(heading.textContent) : "";
    }

    function decorateHeader(header) {
        if (!isElement(header) || header.dataset.atomicCardHeaderReady === "true" || isExcluded(header)) return;
        header.dataset.atomicCardHeaderReady = "true";
        header.classList.add("app-atomic-card-header");

        const title = header.querySelector("h1, h2, h3, h4, h5, h6, .card-title, .app-card-title, strong");
        if (title) title.classList.add("app-atomic-card-title");

        const actions = header.querySelector(".btn, .btn-group, .dropdown, form, a[href]");
        if (actions) header.classList.add("app-atomic-card-header-with-actions");
    }

    function decorateBody(node) {
        if (!isElement(node) || node.dataset.atomicCardBodyReady === "true" || isExcluded(node)) return;
        node.dataset.atomicCardBodyReady = "true";
        node.classList.add("app-atomic-card-body");
    }

    function decorateCard(card) {
        if (!isElement(card) || card.dataset.atomicCardReady === "true" || isExcluded(card)) return;
        card.dataset.atomicCardReady = "true";
        card.classList.add("app-atomic-card");

        if (card.matches(".metric-card, .kpi-card, .summary-card, .stat-card, .app-stat-card, .receivables-kpi-card")) {
            card.dataset.cardKind = "metric";
        } else if (card.querySelector("table, .table-responsive")) {
            card.dataset.cardKind = "table";
        } else if (card.querySelector("form")) {
            card.dataset.cardKind = "form";
        } else {
            card.dataset.cardKind = "content";
        }

        const title = firstHeadingText(card);
        if (title && !card.getAttribute("aria-label")) {
            card.setAttribute("aria-label", title);
        }

        card.querySelectorAll(":scope > .card-header, :scope > .app-card-header, :scope > header, :scope > .section-header").forEach(decorateHeader);
        card.querySelectorAll(":scope > .card-body, :scope > .app-card-body").forEach(decorateBody);

        const footer = card.querySelector(":scope > .card-footer, :scope > .app-card-footer, :scope > footer");
        if (footer) footer.classList.add("app-atomic-card-footer");
    }

    function decorateSection(section) {
        if (!isElement(section) || section.dataset.atomicSectionReady === "true" || isExcluded(section)) return;
        if (!section.closest("main, .app-main, .main-content, .content-wrapper")) return;
        section.dataset.atomicSectionReady = "true";
        section.classList.add("app-atomic-section");

        const title = firstHeadingText(section);
        if (title && !section.getAttribute("aria-label")) {
            section.setAttribute("aria-label", title);
        }
        if (title && !section.getAttribute("role")) {
            section.setAttribute("role", "region");
        }

        const sectionHeader = section.querySelector(":scope > header, :scope > .section-header, :scope > .app-section-header");
        if (sectionHeader) decorateHeader(sectionHeader);
    }

    function decorateActionCluster(cluster) {
        if (!isElement(cluster) || cluster.dataset.atomicActionClusterReady === "true" || isExcluded(cluster)) return;
        cluster.dataset.atomicActionClusterReady = "true";
        cluster.classList.add("app-atomic-action-cluster");
    }

    function decorateCardGrids(scope) {
        const cards = Array.from(scope.querySelectorAll ? scope.querySelectorAll(".app-atomic-card") : []);
        cards.forEach(function (card) {
            const parent = card.parentElement;
            if (!parent || parent.dataset.atomicCardGridReady === "true") return;
            const siblingCards = Array.from(parent.children).filter(function (child) {
                return child.classList && child.classList.contains("app-atomic-card");
            });
            if (siblingCards.length >= 2) {
                parent.dataset.atomicCardGridReady = "true";
                parent.classList.add("app-atomic-card-grid");
            }
        });
    }

    function enhanceScope(scope) {
        if (!scope || !scope.querySelectorAll) return;
        const cardSelector = ".card, .app-card, .panel, .dashboard-panel, .finance-card, .module-card";
        const headerSelector = ".card-header, .app-card-header, .section-header, .app-section-header";
        const bodySelector = ".card-body, .app-card-body";
        const actionSelector = ".card-actions, .app-card-actions, .page-actions, .section-actions, .filter-actions";

        if (scope.matches && scope.matches(cardSelector)) decorateCard(scope);
        scope.querySelectorAll(cardSelector).forEach(decorateCard);

        if (scope.matches && scope.matches(headerSelector)) decorateHeader(scope);
        scope.querySelectorAll(headerSelector).forEach(decorateHeader);

        if (scope.matches && scope.matches(bodySelector)) decorateBody(scope);
        scope.querySelectorAll(bodySelector).forEach(decorateBody);

        if (scope.matches && scope.matches("section")) decorateSection(scope);
        scope.querySelectorAll("main section, .app-main section, .main-content section").forEach(decorateSection);

        if (scope.matches && scope.matches(actionSelector)) decorateActionCluster(scope);
        scope.querySelectorAll(actionSelector).forEach(decorateActionCluster);

        decorateCardGrids(document);
    }

    enhanceScope(document);

    const observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
            mutation.addedNodes.forEach(function (node) {
                if (isElement(node)) enhanceScope(node);
            });
        });
    });
    observer.observe(body, { childList: true, subtree: true });
}());

// ==================================================
// Tahap 10.30 — UI Regression Sweep & Legacy Inline JS Cleanup
// - Centralizes remaining print/back/close/call/confirm/change/input handlers
// - Keeps existing routes, payloads, source fields, and business flow unchanged
// ==================================================
document.addEventListener("DOMContentLoaded", function () {
    if (window.__idhaBogaUiRegressionSweepInstalled) {
        return;
    }
    window.__idhaBogaUiRegressionSweepInstalled = true;

    const confirmBypass = new WeakMap();

    function isElement(node) {
        return node && node.nodeType === 1;
    }

    function cleanText(value) {
        return String(value || "").replace(/\s+/g, " ").trim();
    }

    function isDisabled(element) {
        return !!(element && (
            element.disabled ||
            element.getAttribute("aria-disabled") === "true" ||
            element.classList.contains("disabled")
        ));
    }

    function setBypass(element) {
        if (isElement(element)) {
            confirmBypass.set(element, Date.now() + 2500);
        }
    }

    function hasBypass(element) {
        if (!isElement(element)) return false;
        const until = confirmBypass.get(element) || 0;
        if (until > Date.now()) return true;
        confirmBypass.delete(element);
        return false;
    }

    function toast(message, tone) {
        if (typeof window.appToast === "function") {
            window.appToast(message, tone || "info", { duration: 4200 });
        }
    }

    function confirmAction(message, returnFocus) {
        const safeMessage = cleanText(message) || "Lanjutkan aksi ini?";
        if (typeof window.appConfirm === "function") {
            return window.appConfirm(safeMessage, { returnFocus: returnFocus });
        }
        return Promise.resolve(window.confirm(safeMessage));
    }

    function requestSubmitSafely(form, submitter) {
        if (!form) return;
        setBypass(form);
        if (submitter) setBypass(submitter);
        setTimeout(function () {
            try {
                if (typeof form.requestSubmit === "function") {
                    if (submitter && submitter.form === form) {
                        form.requestSubmit(submitter);
                    } else {
                        form.requestSubmit();
                    }
                } else if (typeof form.submit === "function") {
                    form.submit();
                }
            } catch (error) {
                if (typeof form.submit === "function") form.submit();
            }
        }, 10);
    }

    function cssEscape(value) {
        if (window.CSS && typeof window.CSS.escape === "function") {
            return window.CSS.escape(value);
        }
        return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
    }

    function parseSingleArg(raw, element) {
        const value = cleanText(raw);
        if (!value) return undefined;
        if (value === "this") return element;
        if (value === "true") return true;
        if (value === "false") return false;
        if (/^-?\d+(?:\.\d+)?$/.test(value)) return Number(value);
        const target = document.getElementById(value) || document.querySelector("#" + cssEscape(value));
        return target || value;
    }

    function buildArgs(element, index) {
        const argMode = element.getAttribute("data-app-call-arg");
        if (argMode === "this" && index === 0) {
            return [element];
        }
        const rawArgs = element.getAttribute("data-app-call-args");
        if (!rawArgs) return [];
        return [parseSingleArg(rawArgs, element)];
    }

    function callNamedFunctions(element, names, eventType) {
        const list = String(names || "")
            .split(",")
            .map(function (name) { return cleanText(name); })
            .filter(Boolean);
        if (!list.length) return false;

        let called = false;
        list.forEach(function (name, index) {
            const fn = window[name];
            if (typeof fn !== "function") {
                toast("Handler UI tidak ditemukan: " + name, "danger");
                return;
            }
            try {
                fn.apply(element, buildArgs(element, index));
                called = true;
            } catch (error) {
                console.error("Atomic UI handler failed", { name: name, eventType: eventType, error: error });
                toast("Aksi UI gagal dijalankan. Cek console browser.", "danger");
            }
        });
        return called;
    }

    function decorateLegacyAction(element) {
        if (!isElement(element) || element.dataset.uiRegressionReady === "true") return;
        element.dataset.uiRegressionReady = "true";
        element.classList.add("app-ui-regression-action");
        if (element.hasAttribute("data-app-confirm")) element.classList.add("app-ui-confirm-action");
        if (element.hasAttribute("data-app-action")) element.classList.add("app-ui-simple-action");
        if (element.hasAttribute("data-app-call") || element.hasAttribute("data-app-change-call") || element.hasAttribute("data-app-input-call")) {
            element.classList.add("app-ui-call-action");
        }
    }

    function decorateScope(scope) {
        if (!scope || !scope.querySelectorAll) return;
        const selector = "[data-app-confirm], [data-app-action], [data-app-call], [data-app-change-call], [data-app-input-call], [data-app-temp-label], [data-app-select-navigate]";
        if (scope.matches && scope.matches(selector)) decorateLegacyAction(scope);
        scope.querySelectorAll(selector).forEach(decorateLegacyAction);
    }

    document.addEventListener("click", function (event) {
        const target = event.target && event.target.closest ? event.target.closest("[data-app-action], [data-app-call], [data-app-confirm], [data-app-temp-label]") : null;
        if (!target || isDisabled(target)) return;

        if (target.hasAttribute("data-app-temp-label")) {
            const temporary = target.getAttribute("data-app-temp-label") || "Memproses...";
            target.dataset.originalText = target.dataset.originalText || cleanText(target.textContent);
            target.textContent = temporary;
            setTimeout(function () {
                if (target.dataset.originalText) target.textContent = target.dataset.originalText;
            }, 1800);
        }

        const action = target.getAttribute("data-app-action");
        if (action === "print") {
            event.preventDefault();
            event.stopImmediatePropagation();
            window.print();
            return;
        }
        if (action === "back") {
            event.preventDefault();
            event.stopImmediatePropagation();
            window.history.back();
            return;
        }
        if (action === "close") {
            event.preventDefault();
            event.stopImmediatePropagation();
            window.close();
            return;
        }

        if (target.hasAttribute("data-app-call")) {
            event.preventDefault();
            event.stopImmediatePropagation();
            callNamedFunctions(target, target.getAttribute("data-app-call"), "click");
            return;
        }

        const message = target.getAttribute("data-app-confirm");
        const form = target.form || (target.closest ? target.closest("form") : null);
        const isSubmitter = !!(form && target.matches && target.matches('button[type="submit"], input[type="submit"], button:not([type])'));
        if (message && isSubmitter && !hasBypass(target) && !hasBypass(form)) {
            event.preventDefault();
            event.stopImmediatePropagation();
            confirmAction(message, target).then(function (confirmed) {
                if (confirmed) requestSubmitSafely(form, target);
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
            if (confirmed) requestSubmitSafely(form, submitter && submitter.form === form ? submitter : null);
        });
    }, true);

    document.addEventListener("change", function (event) {
        const element = event.target;
        if (!isElement(element)) return;
        if (element.hasAttribute("data-app-select-navigate")) {
            const value = cleanText(element.value);
            if (value) {
                const base = element.getAttribute("data-app-select-navigate") || window.location.pathname;
                const param = element.getAttribute("data-app-select-param") || "value";
                const url = new URL(base, window.location.href);
                url.searchParams.set(param, value);
                window.location.href = url.toString();
            }
            return;
        }
        if (element.hasAttribute("data-app-change-call")) {
            callNamedFunctions(element, element.getAttribute("data-app-change-call"), "change");
        }
    }, false);

    document.addEventListener("input", function (event) {
        const element = event.target;
        if (isElement(element) && element.hasAttribute("data-app-input-call")) {
            callNamedFunctions(element, element.getAttribute("data-app-input-call"), "input");
        }
    }, false);

    function updatePortalOrderPreview(form) {
        if (!form || !form.matches || !form.matches("[data-portal-order-form]")) return;
        const dateInput = form.querySelector("[data-portal-order-date]");
        const mealInput = form.querySelector("[data-portal-meal-type]");
        const locationInput = form.querySelector("[data-portal-location-select]");
        const portionInput = form.querySelector("[data-portal-portion-input]");
        const timeInput = form.querySelector("[data-portal-time-input]");
        const contactInput = form.querySelector("[data-portal-contact-input]");
        const phoneInput = form.querySelector("[data-portal-phone-input]");
        const title = form.querySelector("[data-portal-preview-title]");
        const detail = form.querySelector("[data-portal-preview-detail]");
        if (!title || !detail) return;

        const selectedLocation = locationInput && locationInput.selectedOptions ? locationInput.selectedOptions[0] : null;
        const locationName = selectedLocation ? cleanText(selectedLocation.textContent) : "";
        const clientName = selectedLocation ? cleanText(selectedLocation.getAttribute("data-client-name")) : "";
        const mandorName = selectedLocation ? cleanText(selectedLocation.getAttribute("data-mandor-name")) : "";
        const locationDescription = selectedLocation ? cleanText(selectedLocation.getAttribute("data-location-description")) : "";
        const orderDate = cleanText(dateInput && dateInput.value);
        const mealType = cleanText(mealInput && mealInput.options && mealInput.selectedIndex >= 0 ? mealInput.options[mealInput.selectedIndex].textContent : mealInput && mealInput.value);
        const portion = cleanText(portionInput && portionInput.value);
        const deliveryTime = cleanText(timeInput && timeInput.value);
        const contactName = cleanText(contactInput && contactInput.value);
        const contactPhone = cleanText(phoneInput && phoneInput.value);

        if (!orderDate || !locationName || !portion) {
            title.textContent = "Pilih tanggal, lokasi, dan jumlah porsi";
            detail.textContent = "Draft ini belum membuat produksi, pengiriman, tagihan, pembayaran, stok, atau jurnal.";
            return;
        }

        title.textContent = portion + " porsi " + mealType + " untuk " + locationName;
        detail.textContent = [
            "Tanggal " + orderDate,
            deliveryTime ? "Jam kirim " + deliveryTime : "",
            clientName ? "Client/PT " + clientName : "",
            mandorName ? "Mandor " + mandorName : "",
            contactName ? "Penerima " + contactName : "",
            contactPhone ? "HP " + contactPhone : "",
            locationDescription ? "Catatan lokasi: " + locationDescription : ""
        ].filter(Boolean).join(" | ");
    }

    function bindPortalOrderForm(form) {
        if (!form || form.dataset.portalOrderReady === "true") return;
        form.dataset.portalOrderReady = "true";
        form.querySelectorAll("[data-portal-order-date], [data-portal-meal-type], [data-portal-location-select], [data-portal-portion-input], [data-portal-time-input], [data-portal-contact-input], [data-portal-phone-input]").forEach(function (field) {
            field.addEventListener("change", function () { updatePortalOrderPreview(form); });
            field.addEventListener("input", function () { updatePortalOrderPreview(form); });
        });
        form.addEventListener("submit", function (event) {
            if (form.dataset.portalSubmitting === "true") {
                event.preventDefault();
                event.stopPropagation();
                return false;
            }
            form.dataset.portalSubmitting = "true";
            const button = form.querySelector("[data-portal-submit-label]");
            if (button) {
                button.disabled = true;
                button.dataset.originalHtml = button.innerHTML;
                button.innerHTML = '<i class="bi bi-hourglass-split"></i><span>Mengirim draft...</span>';
            }
            setTimeout(function () {
                form.dataset.portalSubmitting = "false";
                if (button) {
                    button.disabled = false;
                    if (button.dataset.originalHtml) button.innerHTML = button.dataset.originalHtml;
                }
            }, 12000);
        }, false);
        updatePortalOrderPreview(form);
    }

    function bindPortalOrderForms(scope) {
        if (!scope || !scope.querySelectorAll) return;
        if (scope.matches && scope.matches("[data-portal-order-form]")) bindPortalOrderForm(scope);
        scope.querySelectorAll("[data-portal-order-form]").forEach(bindPortalOrderForm);
    }

    decorateScope(document);
    bindPortalOrderForms(document);
    const observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
            mutation.addedNodes.forEach(function (node) {
                if (isElement(node)) {
                    decorateScope(node);
                    bindPortalOrderForms(node);
                }
            });
        });
    });
    observer.observe(document.body, { childList: true, subtree: true });
});

// Opt-in Atomic UI row action menu. Non-ui markup is never selected here.
document.addEventListener("DOMContentLoaded", function () {
    let activeMenu = null;
    const narrowViewport = window.matchMedia("(max-width: 991.98px)");

    document.querySelectorAll("[data-ui-table]").forEach(function (table) {
        const codeCell = table.querySelector(".ui-table-cell--sticky-code");
        if (!codeCell) return;
        function syncStickyOffset() {
            table.style.setProperty("--ui-sticky-code-offset", codeCell.getBoundingClientRect().width + "px");
        }
        syncStickyOffset();
        window.addEventListener("resize", syncStickyOffset, { passive: true });
    });

    function closeMenu() {
        if (!activeMenu) return;
        const state = activeMenu;
        state.menu.classList.remove("ui-action-menu-popover", "ui-scope");
        state.menu.removeAttribute("style");
        state.marker.parentNode.insertBefore(state.menu, state.marker);
        state.marker.remove();
        state.trigger.setAttribute("aria-expanded", "false");
        activeMenu = null;
    }

    function positionMenu(trigger, menu) {
        const margin = 12;
        const gap = 6;
        const triggerRect = trigger.getBoundingClientRect();
        const menuRect = menu.getBoundingClientRect();
        const left = Math.max(margin, Math.min(window.innerWidth - menuRect.width - margin, triggerRect.right - menuRect.width));
        const fitsBelow = triggerRect.bottom + gap + menuRect.height <= window.innerHeight - margin;
        const top = fitsBelow
            ? triggerRect.bottom + gap
            : Math.max(margin, triggerRect.top - menuRect.height - gap);
        menu.style.left = left + "px";
        menu.style.top = top + "px";
    }

    document.querySelectorAll("[data-ui-row-actions]").forEach(function (root) {
        const trigger = root.querySelector("[data-ui-action-menu-trigger]");
        const menu = root.querySelector("[data-ui-action-menu]");
        if (!trigger || !menu) return;

        const triggerMarker = document.createComment("ui-action-trigger-position");
        trigger.parentNode.insertBefore(triggerMarker, trigger);
        function syncTrigger() {
            closeMenu();
            if (narrowViewport.matches) {
                if (!trigger.isConnected) triggerMarker.parentNode.insertBefore(trigger, triggerMarker.nextSibling);
            } else if (trigger.isConnected) {
                trigger.remove();
            }
        }
        syncTrigger();
        narrowViewport.addEventListener("change", syncTrigger);

        trigger.addEventListener("click", function (event) {
            event.preventDefault();
            if (activeMenu && activeMenu.trigger === trigger) {
                closeMenu();
                return;
            }
            closeMenu();
            const marker = document.createComment("ui-action-menu-position");
            menu.parentNode.insertBefore(marker, menu.nextSibling);
            document.body.appendChild(menu);
            menu.classList.add("ui-action-menu-popover", "ui-scope");
            trigger.setAttribute("aria-expanded", "true");
            activeMenu = { trigger: trigger, menu: menu, marker: marker };
            positionMenu(trigger, menu);
            const firstAction = menu.querySelector(".ui-button");
            if (firstAction) firstAction.focus({ preventScroll: true });
        });
    });

    document.addEventListener("click", function (event) {
        if (!activeMenu) return;
        if (activeMenu.menu.contains(event.target) || activeMenu.trigger.contains(event.target)) return;
        closeMenu();
    });

    document.addEventListener("keydown", function (event) {
        if (event.key !== "Escape" || !activeMenu) return;
        const trigger = activeMenu.trigger;
        closeMenu();
        trigger.focus({ preventScroll: true });
    });

    window.addEventListener("resize", closeMenu, { passive: true });
    window.addEventListener("scroll", closeMenu, { passive: true, capture: true });
});
