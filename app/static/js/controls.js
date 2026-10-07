// ==================================================
// controls.js -- dropdown, kalender, dan grafik.
//
// Pustaka lokal di app/static/vendor (tanpa CDN):
//   - Tom Select  : semua <select> jadi dropdown bergaya sama, bisa dicari
//                   kalau pilihannya banyak;
//   - Flatpickr   : semua <input type="date"> jadi kalender berbahasa
//                   Indonesia (tampil "3 Okt 2026", terkirim "2026-10-03");
//   - ApexCharts  : elemen [data-apex-chart] jadi grafik interaktif. Dimuat
//                   hanya di halaman yang punya grafik.
//
// Elemen asli tetap ada di form (tersembunyi) dan tetap yang dikirim ke
// server. Skrip halaman yang membaca atau MENGUBAH .value / .selectedIndex,
// mengganti <option>, menonaktifkan, me-reset form, atau menggandakan baris
// tetap bekerja: perubahan itu dicerminkan ke tampilan (lihat mirror*).
// Keluar dari peningkatan: atribut data-native pada elemen atau leluhurnya.
// ==================================================
(function () {
    "use strict";

    const SEARCH_THRESHOLD = 8;
    const SKIP = "[data-native], template, .flatpickr-calendar, .ts-wrapper, .ts-dropdown, .apexcharts-canvas";

    function skipped(element) {
        return Boolean(element.closest(SKIP));
    }

    function labelFor(element) {
        if (!element.id) return null;
        return document.querySelector('label[for="' + CSS.escape(element.id) + '"]');
    }

    // --- Dropdown --------------------------------------------------------------
    function setupSelect(select) {
        if (!window.TomSelect || select.tomselect || select.size > 1 || skipped(select)) return;

        // Baris hasil cloneNode membawa pembungkus lama tanpa instance: buang.
        const stale = select.nextElementSibling;
        if (stale && stale.classList.contains("ts-wrapper")) stale.remove();
        select.classList.remove("tomselected", "ts-hidden-accessible");
        if (select.getAttribute("tabindex") === "-1") select.removeAttribute("tabindex");

        const searchable = select.multiple || select.options.length > SEARCH_THRESHOLD || select.hasAttribute("data-searchable");
        const plugins = [];
        if (searchable && !select.multiple) plugins.push("dropdown_input");
        if (select.multiple) plugins.push("remove_button");
        const settings = {
            plugins: plugins,
            allowEmptyOption: true,
            maxOptions: null,
            hideSelected: select.multiple,
            dropdownParent: "body",
            closeAfterSelect: !select.multiple,
            render: {
                no_results: function () { return '<div class="no-results">Tidak ada yang cocok</div>'; },
            },
        };
        if (!searchable) settings.controlInput = null;

        let ts;
        try {
            ts = new TomSelect(select, settings);
        } catch (error) {
            return; // gagal = tetap select bawaan, form tetap jalan
        }
        if (select.classList.contains("form-select-sm")) ts.wrapper.classList.add("is-sm");
        ts.dropdown.classList.add("app-dropdown");
        const dropdownInput = ts.dropdown.querySelector(".dropdown-input");
        if (dropdownInput) dropdownInput.placeholder = "Cari...";
        const label = labelFor(select);
        if (label) {
            label.addEventListener("click", function (event) {
                event.preventDefault();
                ts.focus();
            });
        }
        mirrorSelect(select, ts);
    }

    function mirrorSelect(select, ts) {
        let syncing = false;
        const observer = new MutationObserver(function (records) {
            if (syncing) return;
            resync(records.some(function (record) { return record.type === "childList"; }));
        });

        function resync(rebuildOptions) {
            syncing = true;
            try {
                if (rebuildOptions) ts.clearOptions(function () { return false; });
                ts.sync();
            } finally {
                observer.takeRecords();
                syncing = false;
            }
        }

        // Tom Select memindahkan <option> terpilih di select asli; mutasi itu
        // miliknya sendiri, bukan perubahan dari skrip halaman.
        const updateOriginalInput = ts.updateOriginalInput.bind(ts);
        ts.updateOriginalInput = function (options) {
            updateOriginalInput(options);
            observer.takeRecords();
        };
        observer.observe(select, {
            childList: true,
            subtree: true,
            characterData: true,
            attributes: true,
            attributeFilter: ["disabled"],
        });

        ["value", "selectedIndex"].forEach(function (property) {
            const native = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, property);
            Object.defineProperty(select, property, {
                configurable: true,
                get: function () { return native.get.call(select); },
                set: function (value) {
                    native.set.call(select, value);
                    if (!syncing) resync(false);
                },
            });
        });
    }

    // --- Kalender --------------------------------------------------------------
    function setupDate(input) {
        if (!window.flatpickr || input._flatpickr || skipped(input)) return;

        const fp = window.flatpickr(input, {
            locale: (window.flatpickr.l10ns && window.flatpickr.l10ns.id) || "default",
            dateFormat: "Y-m-d",
            altInput: true,
            altFormat: "j M Y",
            altInputClass: (input.className + " app-date-input").trim(),
            allowInput: false,
            disableMobile: true,
            clickOpens: !input.readOnly,
            minDate: input.min || null,
            maxDate: input.max || null,
            onReady: function (selectedDates, dateString, instance) { addDateFooter(instance); },
        });
        if (!fp || !fp.altInput) return;
        fp.altInput.placeholder = input.placeholder || "Pilih tanggal";
        const label = labelFor(input);
        if (label) {
            fp.altInput.setAttribute("aria-label", label.textContent.trim());
            label.addEventListener("click", function (event) {
                event.preventDefault();
                fp.altInput.focus();
                if (!input.readOnly && !input.disabled) fp.open();
            });
        }
        mirrorDate(input, fp);
    }

    function addDateFooter(fp) {
        const footer = document.createElement("div");
        footer.className = "app-date-footer";
        footer.innerHTML = '<button type="button" data-date-action="today">Hari ini</button>'
            + (fp.input.required ? "" : '<button type="button" data-date-action="clear">Kosongkan</button>');
        footer.addEventListener("click", function (event) {
            const button = event.target.closest("button");
            if (!button) return;
            if (button.dataset.dateAction === "today") fp.setDate(new Date(), true);
            else fp.clear();
            fp.close();
        });
        fp.calendarContainer.appendChild(footer);
    }

    function mirrorDate(input, fp) {
        const native = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
        Object.defineProperty(input, "value", {
            configurable: true,
            get: function () { return native.get.call(input); },
            set: function (value) {
                native.set.call(input, value);
                const shown = fp.selectedDates[0] ? fp.formatDate(fp.selectedDates[0], "Y-m-d") : "";
                if ((value || "") !== shown) fp.setDate(value || null, false);
            },
        });
        new MutationObserver(function () {
            fp.altInput.disabled = input.disabled;
            fp.set("clickOpens", !input.readOnly && !input.disabled);
            fp.set("minDate", input.min || null);
            fp.set("maxDate", input.max || null);
        }).observe(input, { attributes: true, attributeFilter: ["disabled", "readonly", "min", "max"] });
    }

    // --- Pasang, termasuk konten yang ditambahkan belakangan --------------------
    function enhance(root) {
        if (root.matches && root.matches("select")) setupSelect(root);
        else if (root.matches && root.matches('input[type="date"]')) setupDate(root);
        if (!root.querySelectorAll) return;
        root.querySelectorAll("select").forEach(setupSelect);
        root.querySelectorAll('input[type="date"]').forEach(setupDate);
    }

    document.addEventListener("DOMContentLoaded", function () {
        enhance(document.body);

        new MutationObserver(function (records) {
            records.forEach(function (record) {
                record.addedNodes.forEach(function (node) {
                    if (node.nodeType === 1 && !skipped(node)) enhance(node);
                });
            });
        }).observe(document.body, { childList: true, subtree: true });

        // form.reset() tidak memicu event pada select/input asli.
        document.addEventListener("reset", function (event) {
            const form = event.target;
            setTimeout(function () {
                form.querySelectorAll("select").forEach(function (select) {
                    if (select.tomselect) select.tomselect.sync();
                });
                form.querySelectorAll('input[type="hidden"].flatpickr-input').forEach(function (input) {
                    if (input._flatpickr) input._flatpickr.setDate(input.defaultValue || null, false);
                });
            }, 0);
        }, true);

        // Dropdown dipasang di <body>; ikut bergeser kalau wadahnya digulir.
        document.addEventListener("scroll", function (event) {
            if (event.target === document || (event.target.closest && event.target.closest(".ts-dropdown, .flatpickr-calendar"))) return;
            document.querySelectorAll("select.tomselected").forEach(function (select) {
                const ts = select.tomselect;
                if (ts && ts.isOpen) ts.positionDropdown();
            });
        }, true);
    });

    // --- Grafik ----------------------------------------------------------------
    const LOCALE_ID = {
        name: "id",
        options: {
            months: ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"],
            shortMonths: ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"],
            days: ["Minggu", "Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"],
            shortDays: ["Min", "Sen", "Sel", "Rab", "Kam", "Jum", "Sab"],
            toolbar: {
                exportToSVG: "Unduh SVG", exportToPNG: "Unduh PNG", exportToCSV: "Unduh CSV",
                menu: "Menu", selection: "Pilihan", selectionZoom: "Perbesar pilihan",
                zoomIn: "Perbesar", zoomOut: "Perkecil", pan: "Geser", reset: "Atur ulang",
            },
        },
    };
    const NUMBER = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 });
    const DECIMAL = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 1 });

    function rupiah(value) {
        const amount = Number(value) || 0;
        return (amount < 0 ? "-Rp " : "Rp ") + NUMBER.format(Math.abs(amount));
    }

    function rupiahShort(value) {
        const amount = Number(value) || 0;
        const sign = amount < 0 ? "-" : "";
        const abs = Math.abs(amount);
        if (abs >= 1e9) return sign + DECIMAL.format(abs / 1e9) + " M";
        if (abs >= 1e6) return sign + DECIMAL.format(abs / 1e6) + " jt";
        if (abs >= 1e3) return sign + DECIMAL.format(abs / 1e3) + " rb";
        return sign + NUMBER.format(abs);
    }

    function formatter(kind) {
        if (kind === "rupiah") return rupiah;
        if (kind === "percent") return function (value) { return DECIMAL.format(Number(value) || 0) + "%"; };
        return function (value) { return NUMBER.format(Number(value) || 0); };
    }

    function token(name) {
        return getComputedStyle(document.documentElement).getPropertyValue("--" + name).trim() || name;
    }

    function chartOptions(spec, element) {
        const format = formatter(spec.format);
        const colors = spec.series.map(function (series) { return token(series.color || "brand-600"); });
        const base = {
            chart: {
                fontFamily: token("font-sans"),
                foreColor: token("text-secondary"),
                height: spec.height || 300,
                toolbar: { show: false },
                zoom: { enabled: false },
                locales: [LOCALE_ID],
                defaultLocale: "id",
                animations: { enabled: true, speed: 450 },
                events: {},
            },
            colors: colors,
            dataLabels: { enabled: false },
            legend: { show: spec.legend !== false, position: "top", horizontalAlign: "left", fontSize: "13px", markers: { size: 6 }, itemMargin: { horizontal: 10 } },
            tooltip: { theme: "light", shared: spec.kind !== "donut", intersect: false, y: { formatter: format } },
            states: { hover: { filter: { type: "none" } }, active: { filter: { type: "none" } } },
        };

        if (spec.kind === "donut") {
            const total = spec.series.reduce(function (sum, series) { return sum + (Number(series.value) || 0); }, 0);
            return Object.assign(base, {
                chart: Object.assign(base.chart, { type: "donut" }),
                series: spec.series.map(function (series) { return Number(series.value) || 0; }),
                labels: spec.series.map(function (series) { return series.name; }),
                legend: { show: false },
                stroke: { width: 2, colors: [token("surface")] },
                plotOptions: {
                    pie: {
                        expandOnClick: false,
                        donut: {
                            size: "72%",
                            labels: {
                                show: true,
                                name: { show: true, fontSize: "12px", color: token("text-muted"), offsetY: 18 },
                                value: {
                                    show: true, fontSize: "22px", fontWeight: 700, color: token("text"), offsetY: -14,
                                    formatter: function (value) {
                                        if (spec.center_format === "percent") return DECIMAL.format(total ? value / total * 100 : 0) + "%";
                                        return spec.format === "rupiah" ? "Rp " + rupiahShort(value) : format(value);
                                    },
                                },
                                total: {
                                    show: true,
                                    showAlways: false,
                                    label: spec.center_label || "Total",
                                    fontSize: "12px",
                                    color: token("text-muted"),
                                    formatter: function () { return spec.center_value || format(total); },
                                },
                            },
                        },
                    },
                },
                tooltip: { theme: "light", y: { formatter: function (value) { return format(value) + (total ? " (" + DECIMAL.format(value / total * 100) + "%)" : ""); } } },
            });
        }

        if (spec.kind === "spark") {
            const unit = spec.unit ? " " + spec.unit : "";
            return Object.assign(base, {
                // Batang per hari: hari libur tampil kosong, bukan lembah grafik.
                chart: Object.assign(base.chart, { type: "bar", sparkline: { enabled: true } }),
                series: spec.series.map(function (series) { return { name: series.name, data: series.data }; }),
                labels: spec.categories,
                plotOptions: { bar: { columnWidth: "62%", borderRadius: 2, borderRadiusApplication: "end" } },
                states: { hover: { filter: { type: "darken", value: 0.85 } }, active: { filter: { type: "none" } } },
                tooltip: {
                    theme: "light",
                    x: { show: true, formatter: function (value, context) { return spec.categories[context.dataPointIndex] || value; } },
                    y: { title: { formatter: function () { return ""; } }, formatter: function (value) { return format(value) + unit; } },
                },
            });
        }

        const axisFormat = spec.format === "rupiah" ? rupiahShort : format;
        const hasLine = spec.series.some(function (series) { return series.type === "line"; });
        return Object.assign(base, {
            chart: Object.assign(base.chart, { type: spec.kind === "area" ? "area" : "bar", stacked: false }),
            series: spec.series.map(function (series) {
                return { name: series.name, type: series.type || (spec.kind === "area" ? "area" : "column"), data: series.data };
            }),
            xaxis: {
                categories: spec.categories,
                axisBorder: { show: false },
                axisTicks: { show: false },
                tooltip: { enabled: false },
                labels: { rotate: 0, hideOverlappingLabels: true, style: { fontSize: "12px" } },
            },
            yaxis: { labels: { formatter: axisFormat, style: { fontSize: "12px" } }, forceNiceScale: true },
            grid: { borderColor: token("border"), strokeDashArray: 4, padding: { left: 4, right: 8 } },
            plotOptions: { bar: { columnWidth: spec.column_width || "58%", borderRadius: 4, borderRadiusApplication: "end" } },
            stroke: {
                width: spec.series.map(function (series) { return (series.type || "") === "line" || spec.kind === "area" ? 2.5 : 0; }),
                curve: "monotoneCubic", // tidak melampaui titik data seperti "smooth"
            },
            fill: spec.kind === "area"
                ? { type: spec.series.map(function (series) { return series.type === "line" ? "solid" : "gradient"; }), gradient: { shadeIntensity: 0.4, opacityFrom: 0.32, opacityTo: 0.02, stops: [0, 95] } }
                : { opacity: 1 },
            markers: { size: hasLine ? spec.series.map(function (series) { return series.type === "line" ? 3.5 : 0; }) : 0, strokeWidth: 2, strokeColors: token("surface"), hover: { sizeOffset: 2 } },
        });
    }

    function renderChart(element) {
        if (element.dataset.chartReady) return;
        const source = element.querySelector('script[type="application/json"]');
        if (!source) return;
        let spec;
        try {
            spec = JSON.parse(source.textContent);
        } catch (error) {
            return;
        }
        element.dataset.chartReady = "1";
        const mount = document.createElement("div");
        mount.className = "app-chart-canvas";
        element.appendChild(mount);
        const options = chartOptions(spec, element);
        if (spec.links || spec.point_links) {
            // Klik = buka rincian: links[i] per seri (batang), point_links[i]
            // per irisan donat.
            options.chart.events.dataPointSelection = function (event, context, config) {
                const url = spec.point_links ? spec.point_links[config.dataPointIndex] : spec.links[config.seriesIndex];
                if (typeof url === "string" && url) window.location.href = url;
            };
            element.classList.add("is-clickable");
        }
        const chart = new window.ApexCharts(mount, options);
        chart.render();
        element.classList.add("is-rendered");
    }

    function loadCharts() {
        const charts = document.querySelectorAll("[data-apex-chart]");
        if (!charts.length) return;
        const start = function () { charts.forEach(renderChart); };
        if (window.ApexCharts) return start();
        const script = document.querySelector("script[data-apex-src]");
        if (!script) return;
        const loader = document.createElement("script");
        loader.src = script.dataset.apexSrc;
        loader.onload = start;
        document.head.appendChild(loader);
    }

    document.addEventListener("DOMContentLoaded", loadCharts);
    window.appCharts = { rupiah: rupiah, rupiahShort: rupiahShort, render: loadCharts };

    // --- Titik lokasi (Leaflet + GPS HP) -----------------------------------------
    // [data-geo-picker] dari components/location_picker.html. Peta dimuat hanya
    // di halaman yang memakainya. Perkiraan ongkir di sini meniru geo_service:
    // jarak = garis lurus x faktor jalan (dibulatkan 0,1 km), ongkir =
    // max(minimal, jarak x tarif/km dibulatkan ke atas Rp 500). Nilai final
    // tetap dihitung server.
    const OKI_AREA = [-2.985, 105.728];
    let leafletLoading = null;

    function loadLeaflet() {
        if (window.L) return Promise.resolve(window.L);
        if (leafletLoading) return leafletLoading;
        const source = document.querySelector("script[data-leaflet-src]");
        if (!source) return Promise.reject(new Error("leaflet"));
        leafletLoading = new Promise(function (resolve, reject) {
            const css = document.createElement("link");
            css.rel = "stylesheet";
            css.href = source.dataset.leafletCss;
            document.head.appendChild(css);
            const loader = document.createElement("script");
            loader.src = source.dataset.leafletSrc;
            loader.onload = function () { resolve(window.L); };
            loader.onerror = reject;
            document.head.appendChild(loader);
        });
        return leafletLoading;
    }

    function pinIcon(L, kind) {
        return L.divIcon({ className: "geo-pin geo-pin--" + kind, html: "<span></span>", iconSize: [30, 38], iconAnchor: [15, 36], tooltipAnchor: [0, -30] });
    }

    function haversineKm(a, b) {
        const rad = Math.PI / 180;
        const dLat = (b[0] - a[0]) * rad;
        const dLng = (b[1] - a[1]) * rad;
        const h = Math.pow(Math.sin(dLat / 2), 2) + Math.cos(a[0] * rad) * Math.cos(b[0] * rad) * Math.pow(Math.sin(dLng / 2), 2);
        return 6371.0088 * 2 * Math.asin(Math.sqrt(h));
    }

    function setupGeoPicker(picker) {
        if (picker.dataset.geoReady) return;
        picker.dataset.geoReady = "1";
        const field = function (name) { return picker.querySelector("[data-geo-" + name + "]"); };
        const latInput = field("lat");
        const lngInput = field("lng");
        const accInput = field("accuracy");
        const status = field("status");
        const estimate = field("estimate");
        const locate = field("locate");
        const readonly = picker.hasAttribute("data-readonly");
        const data = picker.dataset;
        const origin = data.originLat ? [Number(data.originLat), Number(data.originLng)] : null;
        const perKm = Number(data.perKm) || 0;
        const feeMin = Number(data.feeMin) || 0;
        const freeFrom = Number(data.freeFrom) || 0;
        const roadFactor = Number(data.roadFactor) || 1.3;

        function describe(point) {
            if (!estimate) return;
            if (!origin || !point) { estimate.textContent = ""; return; }
            const km = Math.round(haversineKm(origin, point) * roadFactor * 10) / 10;
            let text = "± " + DECIMAL.format(km) + " km dari " + (data.originLabel || "dapur");
            if (perKm > 0 || feeMin > 0) {
                const fee = Math.max(feeMin, Math.ceil(km * perKm / 500) * 500);
                text += " · ongkir " + rupiah(fee) + "/kiriman" + (freeFrom ? " (gratis mulai " + freeFrom + " porsi)" : "");
            }
            estimate.textContent = text;
        }

        loadLeaflet().then(function (L) {
            const saved = latInput.value && lngInput.value ? [Number(latInput.value), Number(lngInput.value)] : null;
            const map = L.map(field("map"), { scrollWheelZoom: false, tap: true }).setView(saved || origin || OKI_AREA, saved ? 15 : 12);
            L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
                maxZoom: 19,
                attribution: "&copy; <a href=\"https://www.openstreetmap.org/copyright\" target=\"_blank\" rel=\"noopener\">OpenStreetMap</a>",
            }).addTo(map);
            if (origin) {
                L.marker(origin, { icon: pinIcon(L, "origin"), keyboard: false }).addTo(map)
                    .bindTooltip(data.originLabel || "Dapur", { direction: "top" });
            }
            let marker = null;
            let ring = null;

            function place(point, accuracy, message) {
                const lat = Number(point[0]).toFixed(7);
                const lng = Number(point[1]).toFixed(7);
                latInput.value = lat;
                lngInput.value = lng;
                if (accInput) accInput.value = accuracy ? Math.round(accuracy) : "";
                if (!marker) {
                    marker = L.marker(point, { icon: pinIcon(L, "target"), draggable: !readonly }).addTo(map);
                    marker.on("dragend", function () {
                        const moved = marker.getLatLng();
                        if (ring) { map.removeLayer(ring); ring = null; }
                        place([moved.lat, moved.lng], null, "Titik digeser manual.");
                    });
                } else {
                    marker.setLatLng(point);
                }
                if (ring) { map.removeLayer(ring); ring = null; }
                if (accuracy) ring = L.circle(point, { radius: accuracy, color: token("brand-600"), weight: 1, fillOpacity: 0.08, interactive: false }).addTo(map);
                status.textContent = (message || "Titik dipilih.") + " " + lat.replace(".", ",") + "; " + lng.replace(".", ",");
                picker.classList.add("has-point");
                describe(point);
                latInput.dispatchEvent(new Event("change", { bubbles: true }));
            }

            if (saved) place(saved, Number(accInput && accInput.value) || null, "Titik tersimpan.");
            if (!readonly) {
                map.on("click", function (event) { place([event.latlng.lat, event.latlng.lng], null, "Titik dipilih di peta."); });
            }
            if (origin && saved) map.fitBounds([origin, saved], { padding: [36, 36], maxZoom: 15 });

            if (locate) {
                locate.addEventListener("click", function () {
                    if (!navigator.geolocation) {
                        status.textContent = "Perangkat ini tidak mendukung GPS. Tandai titik langsung di peta.";
                        return;
                    }
                    if (!window.isSecureContext) {
                        status.textContent = "GPS hanya jalan di alamat https. Tandai titik langsung di peta.";
                        return;
                    }
                    locate.disabled = true;
                    status.textContent = "Mencari lokasi Anda…";
                    navigator.geolocation.getCurrentPosition(function (position) {
                        locate.disabled = false;
                        const point = [position.coords.latitude, position.coords.longitude];
                        map.setView(point, 17);
                        place(point, position.coords.accuracy, "Lokasi GPS (akurasi ± " + Math.round(position.coords.accuracy) + " m).");
                    }, function (error) {
                        locate.disabled = false;
                        status.textContent = error.code === 1
                            ? "Izin lokasi ditolak. Izinkan lokasi di browser, atau tandai titik di peta."
                            : "Lokasi belum didapat. Coba lagi di tempat terbuka, atau tandai titik di peta.";
                    }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
                });
            }

            // Peta di dalam tab/collapse yang awalnya tersembunyi perlu dihitung ulang ukurannya.
            if (window.ResizeObserver) new ResizeObserver(function () { map.invalidateSize(); }).observe(field("map"));
        }).catch(function () {
            status.textContent = "Peta gagal dimuat. Periksa koneksi internet lalu muat ulang halaman.";
        });

        if (picker.dataset.required) {
            const form = picker.closest("form");
            if (form) form.addEventListener("submit", function (event) {
                if (latInput.value && lngInput.value) return;
                event.preventDefault();
                picker.classList.add("is-invalid");
                status.textContent = "Titik lokasi wajib dipilih: ketuk peta atau pakai tombol GPS.";
                picker.scrollIntoView({ behavior: "smooth", block: "center" });
            });
        }
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll("[data-geo-picker]").forEach(setupGeoPicker);
    });

    // --- Halaman pesan portal: stepper porsi + ringkasan biaya langsung -------
    // Ongkir mengikuti server: per kiriman, gratis bila porsi >= ambang lokasi.
    function setupOrderBuilder(form) {
        const qty = form.querySelector("[name=portion_qty]");
        const out = function (name) { return form.querySelector("[data-sum-" + name + "]"); };
        const hint = form.querySelector("[data-free-hint]");
        const dateInput = form.querySelector("[name=order_date]");
        const quick = form.querySelectorAll("[data-qty-set]");

        const step1 = form.querySelector(".po-step[data-today]");
        const todayStr = step1 ? (step1.dataset.today || "") : "";
        let todaySessions = {};
        let lockedDates = [];
        try {
            if (step1 && step1.dataset.todaySessions) todaySessions = JSON.parse(step1.dataset.todaySessions);
            if (step1 && step1.dataset.lockedDates) lockedDates = JSON.parse(step1.dataset.lockedDates);
        } catch (e) {}

        function updateSessions() {
            if (!dateInput) return;
            const chosenDate = dateInput.value;
            const isToday = chosenDate === todayStr;
            const isLocked = lockedDates.indexOf(chosenDate) !== -1;
            const isPast = Boolean(chosenDate && todayStr && chosenDate < todayStr);

            const mealLabels = form.querySelectorAll(".po-seg[data-meal-type]");
            let hasChecked = false;
            mealLabels.forEach(function (label) {
                const mealType = label.dataset.mealType;
                const radio = label.querySelector("input[name=meal_type]");
                const badge = label.querySelector(".po-seg-badge");
                let closed = false;
                let badgeText = "Sudah tutup";

                if (isPast) {
                    closed = true;
                } else if (isLocked) {
                    closed = true;
                    badgeText = "Sudah tutup";
                } else if (isToday && todaySessions[mealType] && todaySessions[mealType].closed) {
                    closed = true;
                }

                if (radio) {
                    radio.disabled = closed;
                    if (closed && radio.checked) {
                        radio.checked = false;
                    }
                    if (!closed && radio.checked) {
                        hasChecked = true;
                    }
                }
                label.classList.toggle("is-disabled", closed);
                if (badge) {
                    badge.textContent = badgeText;
                    badge.classList.toggle("d-none", !closed);
                }
            });

            if (!hasChecked) {
                const firstOpen = form.querySelector(".po-seg[data-meal-type] input[name=meal_type]:not(:disabled)");
                if (firstOpen) firstOpen.checked = true;
            }
        }

        function selectedLocation() { return form.querySelector("[name=delivery_location_id]:checked"); }
        function selectedMeal() { return form.querySelector("[name=meal_type]:checked"); }

        function update() {
            const loc = selectedLocation();
            const meal = selectedMeal();
            const portions = Math.max(Math.round(Number(qty.value) || 0), 0);
            quick.forEach(function (button) { button.classList.toggle("is-active", Number(button.dataset.qtySet) === portions); });
            if (!loc) {
                out("title").textContent = "Pilih lokasi pengiriman";
                return;
            }
            const price = Number(loc.dataset.price) || 0;
            const feeRaw = loc.dataset.fee;
            const freeFrom = Number(loc.dataset.freeFrom) || 0;
            const included = loc.dataset.included === "1";
            const free = freeFrom > 0 && portions >= freeFrom;
            const fee = feeRaw === "" ? null : (free ? 0 : Number(feeRaw) || 0);
            const food = price * portions;
            const mealLabel = meal ? meal.dataset.mealLabel : "";
            const dateText = dateInput && dateInput.value
                ? new Date(dateInput.value + "T00:00:00").toLocaleDateString("id-ID", { weekday: "long", day: "numeric", month: "long" })
                : "tanggal belum dipilih";
            out("title").textContent = portions + " porsi " + mealLabel.toLowerCase() + " · " + loc.dataset.name + ", " + dateText;
            out("food-label").textContent = NUMBER.format(portions) + " × " + rupiah(price);
            out("food").textContent = rupiah(food);
            out("fee").textContent = included ? "Termasuk" : (fee === null ? "Belum tersedia" : (fee === 0 ? "Gratis" : rupiah(fee)));
            out("total").textContent = rupiah(food + (fee || 0));
            if (hint) {
                hint.classList.toggle("is-free", free);
                if (included || !freeFrom || feeRaw === "") hint.textContent = "";
                else if (free) hint.textContent = "Gratis ongkir untuk " + portions + " porsi.";
                else hint.textContent = "Tambah " + (freeFrom - portions) + " porsi lagi untuk gratis ongkir (mulai " + freeFrom + " porsi).";
            }
        }

        form.querySelectorAll("[data-qty-step]").forEach(function (button) {
            button.addEventListener("click", function () {
                const min = Number(qty.min) || 1;
                qty.value = Math.max(min, (Math.round(Number(qty.value) || 0)) + Number(button.dataset.qtyStep));
                update();
            });
        });
        quick.forEach(function (button) {
            button.addEventListener("click", function () { qty.value = button.dataset.qtySet; update(); });
        });
        if (dateInput) {
            dateInput.addEventListener("change", updateSessions);
        }
        form.addEventListener("input", update);
        form.addEventListener("change", update);
        updateSessions();
        update();
    }

    // Tab sederhana: [data-tabs] > button[data-tab] + [data-tab-panel].
    function setupTabs(root) {
        const buttons = root.querySelectorAll("[data-tab]");
        buttons.forEach(function (button) {
            button.addEventListener("click", function () {
                buttons.forEach(function (other) {
                    const active = other === button;
                    other.classList.toggle("is-active", active);
                    other.setAttribute("aria-selected", active ? "true" : "false");
                });
                root.querySelectorAll("[data-tab-panel]").forEach(function (panel) {
                    const active = panel.dataset.tabPanel === button.dataset.tab;
                    panel.hidden = !active;
                    panel.classList.toggle("is-active", active);
                });
            });
        });
    }

    // Saring daftar di tempat: [data-filter-group] > button[data-filter],
    // item [data-filter-item] dalam [data-filter-list] berikutnya.
    function setupFilterGroup(group) {
        const list = group.parentElement.querySelector("[data-filter-list]");
        if (!list) return;
        const empty = list.querySelector("[data-filter-empty]");
        group.querySelectorAll("[data-filter]").forEach(function (button) {
            button.addEventListener("click", function () {
                const key = button.dataset.filter;
                group.querySelectorAll("[data-filter]").forEach(function (other) { other.classList.toggle("is-active", other === button); });
                let shown = 0;
                list.querySelectorAll("[data-filter-item]").forEach(function (item) {
                    const visible = key === "all" || item.dataset.filterItem === key;
                    item.hidden = !visible;
                    if (visible) shown += 1;
                });
                if (empty) empty.hidden = shown > 0;
            });
        });
    }

    // Foto lokasi: pratinjau sebelum unggah (maks 3) dan unggah langsung di galeri.
    function setupPhotoInput(input) {
        const holder = input.closest("[data-photo-input]");
        const preview = holder ? holder.querySelector("[data-photo-preview]") : null;
        input.addEventListener("change", function () {
            if (input.files.length > 3) {
                window.alert("Maksimal 3 foto per lokasi.");
                input.value = "";
            }
            if (!preview) return;
            preview.replaceChildren();
            Array.prototype.slice.call(input.files, 0, 3).forEach(function (file) {
                const img = document.createElement("img");
                img.alt = file.name;
                img.src = URL.createObjectURL(file);
                img.onload = function () { URL.revokeObjectURL(img.src); };
                preview.appendChild(img);
            });
        });
    }

    document.addEventListener("change", function (event) {
        const input = event.target;
        if (input && input.matches && input.matches("[data-photo-autosubmit]") && input.files.length) {
            input.form.submit();
        }
    });

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll("[data-photo-files]").forEach(setupPhotoInput);
        document.querySelectorAll("[data-order-builder]").forEach(setupOrderBuilder);
        document.querySelectorAll("[data-tabs]").forEach(setupTabs);
        document.querySelectorAll("[data-filter-group]").forEach(setupFilterGroup);
    });

    // --- Halaman publik ----------------------------------------------------------
    function setupPublicPage() {
        const header = document.querySelector("[data-pub-header]");
        if (header) {
            const onScroll = function () { header.classList.toggle("is-scrolled", window.scrollY > 8); };
            onScroll();
            window.addEventListener("scroll", onScroll, { passive: true });
        }

        // Angka naik sekali saat terlihat (dilewati bila pengguna minta gerak dikurangi).
        const counters = document.querySelectorAll(".pub [data-count]");
        const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        if (counters.length && !reduced && "IntersectionObserver" in window) {
            const observer = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (!entry.isIntersecting) return;
                    observer.unobserve(entry.target);
                    const target = Number(entry.target.dataset.count) || 0;
                    const started = performance.now();
                    const tick = function (now) {
                        const progress = Math.min(1, (now - started) / 900);
                        const eased = 1 - Math.pow(1 - progress, 3);
                        entry.target.textContent = NUMBER.format(Math.round(target * eased));
                        if (progress < 1) requestAnimationFrame(tick);
                    };
                    requestAnimationFrame(tick);
                });
            }, { threshold: 0.4 });
            counters.forEach(function (counter) { observer.observe(counter); });
        }

        document.querySelectorAll("[data-estimate]").forEach(setupEstimate);
        document.querySelectorAll("[data-pub-board]").forEach(setupBoard);

        // Bagian muncul halus saat digulir ke layar.
        const revealTargets = document.querySelectorAll(".pub [data-reveal]");
        if (revealTargets.length && !reduced && "IntersectionObserver" in window) {
            document.querySelector(".pub").classList.add("pub-anim");
            const revealer = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (!entry.isIntersecting) return;
                    entry.target.classList.add("is-revealed");
                    revealer.unobserve(entry.target);
                });
            }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
            revealTargets.forEach(function (target) { revealer.observe(target); });
        }
    }

    // Papan hari ini: jam WIB berjalan, yang sudah lewat dicentang, yang
    // berikutnya berdenyut dengan hitung mundur.
    function setupBoard(board) {
        const clock = board.querySelector("[data-board-clock]");
        const dateLabel = board.querySelector("[data-board-date]");
        const status = board.querySelector("[data-board-status]");
        const items = Array.prototype.slice.call(board.querySelectorAll("li[data-at]"));
        const timeFormat = new Intl.DateTimeFormat("id-ID", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "Asia/Jakarta" });
        const dateFormat = new Intl.DateTimeFormat("id-ID", { weekday: "long", day: "numeric", month: "long", timeZone: "Asia/Jakarta" });
        const minutesOf = function (text) { const parts = String(text).split(":"); return Number(parts[0]) * 60 + Number(parts[1]); };
        const pad = function (value) { return String(value).padStart(2, "0"); };
        const duration = function (minutes) {
            const hours = Math.floor(minutes / 60);
            const rest = minutes % 60;
            return (hours ? hours + " jam " : "") + (rest || !hours ? rest + " menit" : "");
        };

        function tick() {
            const now = new Date();
            const parts = timeFormat.formatToParts(now);
            const hour = Number((parts.find(function (part) { return part.type === "hour"; }) || {}).value || 0) % 24;
            const minute = Number((parts.find(function (part) { return part.type === "minute"; }) || {}).value || 0);
            const current = hour * 60 + minute;
            if (clock) clock.textContent = pad(hour) + "." + pad(minute);
            if (dateLabel) dateLabel.textContent = dateFormat.format(now) + " · WIB";
            let next = null;
            items.forEach(function (item) {
                const at = minutesOf(item.dataset.at);
                item.classList.toggle("is-done", at <= current);
                item.classList.remove("is-next");
                if (!next && at > current) next = item;
            });
            if (!status) return;
            if (next) {
                next.classList.add("is-next");
                const label = next.querySelector("span").textContent;
                status.innerHTML = "Berikutnya: <strong></strong> dalam " + duration(minutesOf(next.dataset.at) - current) + ".";
                status.querySelector("strong").textContent = label.charAt(0).toLowerCase() + label.slice(1);
            } else {
                status.textContent = "Layanan hari ini sudah selesai. Pesanan untuk hari berikutnya bisa dibuat dari portal.";
            }
        }

        tick();
        setInterval(tick, 20000);
    }

    // Perkiraan biaya pelanggan umum: harga standar x porsi x waktu makan +
    // ongkir per kiriman (gratis bila porsi per kiriman >= ambang).
    function setupEstimate(form) {
        const price = Number(form.dataset.price) || 0;
        const minimum = Number(form.dataset.min) || 1;
        const freeFrom = Number(form.dataset.free) || 0;
        const qtyInput = form.querySelector("#estimateQty");
        const range = form.querySelector("#estimateRange");
        const zone = form.querySelector("#estimateZone");
        // Ongkir jarak (bila diatur): max(minimal, km x tarif/km dibulatkan ke atas Rp 500).
        const perKm = Number(form.dataset.perKm) || 0;
        const feeMin = Number(form.dataset.feeMin) || 0;
        const kmInput = form.querySelector("#estimateKm");
        const kmRange = form.querySelector("#estimateKmRange");
        const out = function (name) { return form.querySelector("[data-estimate-" + name + "]"); };

        function tripFee() {
            if (kmInput) {
                const km = Math.max(Number(String(kmInput.value).replace(",", ".")) || 0, 0);
                return Math.max(feeMin, Math.ceil(km * perKm / 500) * 500);
            }
            return zone ? Number(zone.value) || 0 : 0;
        }


        function update(source) {
            let qty = Math.round(Number(source === "range" ? range.value : qtyInput.value) || 0);
            if (source === "range") qtyInput.value = qty;
            else if (range) range.value = Math.min(Number(range.max), Math.max(Number(range.min), qty));
            const valid = qty >= minimum;
            qtyInput.classList.toggle("is-invalid", !valid && qtyInput.value !== "");
            qty = Math.max(qty, 0);
            const meals = Number((form.querySelector("input[name=estimateMeals]:checked") || {}).value || 1);
            const trips = meals;
            const free = freeFrom > 0 && qty >= freeFrom;
            const feePerTrip = tripFee();
            const food = price * qty * meals;
            const fee = free ? 0 : feePerTrip * trips;
            out("food-label").textContent = NUMBER.format(qty) + " porsi × " + rupiah(price) + (meals > 1 ? " × 2" : "");
            out("food").textContent = rupiah(food);
            out("fee-label").textContent = "Ongkir " + trips + " kiriman";
            out("fee").textContent = free ? "Gratis" : rupiah(fee);
            out("total").textContent = valid ? rupiah(food + fee) : "Minimal " + minimum + " porsi";
            const whole = food + fee;
            const barFood = out("bar-food");
            const barFee = out("bar-fee");
            if (barFood && barFee) {
                barFood.style.width = (whole ? food / whole * 100 : 0) + "%";
                barFee.style.width = (whole ? fee / whole * 100 : 0) + "%";
            }
            out("free").classList.toggle("is-visible", free && valid);
        }

        if (range) range.addEventListener("input", function () { update("range"); });
        qtyInput.addEventListener("input", function () { update("qty"); });
        form.querySelectorAll("input[name=estimateMeals]").forEach(function (radio) {
            radio.addEventListener("change", function () { update("qty"); });
        });
        if (zone) zone.addEventListener("change", function () { update("qty"); });
        if (kmInput) {
            kmInput.addEventListener("input", function () {
                if (kmRange) kmRange.value = Math.min(Number(kmRange.max), Math.max(Number(kmRange.min), Number(kmInput.value) || 0));
                update("qty");
            });
            if (kmRange) kmRange.addEventListener("input", function () { kmInput.value = kmRange.value; update("qty"); });
        }
        update("qty");
    }

    // --- Payment Inbox (Antrean Pembayaran Masuk) -----------------------------
    function setupPaymentInbox() {
        const root = document.querySelector("[data-payment-inbox]");
        if (!root) return;

        // 1. Filter Chips
        const chips = root.querySelectorAll(".pin-chip");
        const cards = root.querySelectorAll(".pin-card");

        chips.forEach(function (chip) {
            chip.addEventListener("click", function () {
                chips.forEach(function (c) { c.classList.remove("is-active"); });
                chip.classList.add("is-active");
                const filter = chip.getAttribute("data-filter");

                cards.forEach(function (card) {
                    let show = true;
                    if (filter === "today") {
                        show = card.getAttribute("data-is-today") === "1";
                    } else if (filter === "exact") {
                        show = card.getAttribute("data-match") === "EXACT";
                    } else if (filter === "check") {
                        show = card.getAttribute("data-has-warning") === "1";
                    }
                    card.style.display = show ? "" : "none";
                });
            });
        });

        // 2. Form Interactions (dynamic button label, note requirement, prevent double submit)
        cards.forEach(function (card) {
            const form = card.querySelector(".pin-approve-form");
            if (!form) return;

            const amountInput = form.querySelector(".pin-input-amount");
            const noteInput = form.querySelector(".pin-input-note");
            const noteLabel = form.querySelector(".pin-note-label");
            const submitBtn = form.querySelector(".pin-btn-approve");
            const btnText = form.querySelector(".pin-btn-text");

            const outstanding = Number(amountInput.getAttribute("data-outstanding")) || 0;
            const expected = Number(amountInput.getAttribute("data-expected")) || 0;

            function updateAmount() {
                const val = Number(amountInput.value) || 0;
                const diff = outstanding - val;

                if (diff > 0) {
                    const formatted = new Intl.NumberFormat("id-ID").format(Math.round(diff));
                    if (btnText) btnText.textContent = "Catat & Tahan (kurang Rp " + formatted + ")";
                } else {
                    if (btnText) btnText.textContent = "Terima & Konfirmasi";
                }

                const mismatch = Math.abs(val - expected) > 0.009 && Math.abs(val - outstanding) > 0.009;
                if (noteInput) {
                    noteInput.required = mismatch;
                    if (noteLabel) {
                        noteLabel.innerHTML = mismatch
                            ? 'Catat Alasan <span class="text-danger">*</span>'
                            : 'Catatan Tambahan';
                    }
                }
            }

            if (amountInput) {
                amountInput.addEventListener("input", updateAmount);
                updateAmount();
            }

            form.addEventListener("submit", function () {
                if (submitBtn) {
                    setTimeout(function () {
                        submitBtn.disabled = true;
                    }, 50);
                }
            });
        });

        // Double submit protection on reject forms
        root.querySelectorAll(".pin-reject-form").forEach(function (rejForm) {
            rejForm.addEventListener("submit", function () {
                const btn = rejForm.querySelector("button[type=submit]");
                if (btn) {
                    setTimeout(function () {
                        btn.disabled = true;
                    }, 50);
                }
            });
        });
    }

    document.addEventListener("DOMContentLoaded", setupPublicPage);
    document.addEventListener("DOMContentLoaded", setupPaymentInbox);
})();
