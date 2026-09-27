"""Istilah bisnis yang bisa diatur per cabang.

Keputusan owner 2026-09-26: sistem dipakai untuk pelanggan katering di luar
proyek -- sekolah, kantor, rumah sakit, event. Kata yang terlihat pengguna
untuk empat konsep ini tidak lagi ditulis mati di layar, tapi dibaca dari
Pengaturan Perusahaan cabang itu. Cabang proyek bisa tetap memakai "Mandor",
cabang sekolah memakai "Kelas", tanpa perubahan kode.

Nama di kode dan database TIDAK ikut berubah (tabel `mandors`, kolom
`mandor_id`, URL `/portal/mandor`): pengguna tidak pernah melihatnya, dan
mengganti 507 referensi di 62 file hanya menambah risiko.

Pola yang sama dengan app/utils/roles.py: satu tabel, dibaca template dan
kode Python sekaligus.
"""

# nama konsep -> (key di branch_settings, istilah bawaan)
TERMS = {
    "client": ("term_client", "Client"),
    "sub_client": ("term_sub_client", "Sub Client"),
    "location": ("term_location", "Lokasi Antar"),
    "worker": ("term_worker", "Pekerja"),
}

DEFAULT_TERMS = {name: default for name, (_, default) in TERMS.items()}
TERM_SETTING_KEYS = {name: key for name, (key, _) in TERMS.items()}


def _lower(value):
    """Huruf kecil untuk dipakai di tengah kalimat, tapi singkatan tetap.

    "Sub Client" -> "sub client", "Mandor" -> "mandor", tapi "PT" tetap "PT"
    dan "RS Harapan" -> "RS harapan": kata yang seluruhnya huruf besar
    dianggap singkatan.
    """
    return " ".join(
        word if (word.isupper() and len(word) <= 4) else word.lower()
        for word in str(value).split(" ")
    )


def _branch_settings(branch_id):
    from app.services.company_settings_service import get_company_settings
    from app.services.ttl_cache_service import get_cached_value

    # Kunci cache yang sama dengan context processor company settings, jadi
    # menyimpan pengaturan (clear_cache("company_settings")) ikut
    # menyegarkan istilah.
    return get_cached_value(
        ("company_settings", branch_id),
        lambda: get_company_settings(branch_id),
        ttl_seconds=30,
    )


def _current_branch_id():
    try:
        from flask import has_request_context
        from flask_login import current_user

        if has_request_context() and current_user.is_authenticated:
            return getattr(current_user, "branch_id", None)
    except Exception:
        return None
    return None


class _Terms:
    """Istilah tanpa tanda kutip, untuk f-string di kode Python.

        flash(f"Data {T.sub_client_lower} tidak sesuai cabang user.")

    Setiap akses dibaca saat itu juga (cabang pengguna yang sedang login),
    jadi aman di dalam fungsi. Jangan dipakai di konstanta tingkat modul:
    di sana belum ada pengguna, dan istilahnya akan terkunci ke bawaan.
    """

    client = property(lambda self: term("client"))
    client_lower = property(lambda self: term("client", lower=True))
    sub_client = property(lambda self: term("sub_client"))
    sub_client_lower = property(lambda self: term("sub_client", lower=True))
    location = property(lambda self: term("location"))
    location_lower = property(lambda self: term("location", lower=True))
    worker = property(lambda self: term("worker"))
    worker_lower = property(lambda self: term("worker", lower=True))


T = _Terms()


def _term_tokens():
    return {
        "client": term("client"),
        "client_lower": term("client", lower=True),
        "sub_client": term("sub_client"),
        "sub_client_lower": term("sub_client", lower=True),
        "location": term("location"),
        "location_lower": term("location", lower=True),
        "worker": term("worker"),
        "worker_lower": term("worker", lower=True),
    }


class L(str):
    """Teks label tingkat modul yang istilahnya dirangkai saat ditampilkan.

        ADVANCE_TYPES = {"X": {"label": L("Panjar Operasional {sub_client}")}}

    Konstanta tingkat modul dibuat sekali saat aplikasi start, sebelum ada
    pengguna -- f-string biasa akan mengunci istilah bawaan. Objek ini tetap
    sebuah str bernilai istilah bawaan (aman untuk JSON, perbandingan, dan
    kunci), tapi saat dicetak di template ({{ }}), di f-string, atau lewat
    str(), istilah cabang pengguna yang sedang login yang dipakai.
    """

    def __new__(cls, template):
        value = super().__new__(cls, template.format(**_default_tokens()))
        value._template = template
        return value

    def _render(self):
        return self._template.format(**_term_tokens())

    def __str__(self):
        return self._render()

    def __format__(self, spec):
        return format(self._render(), spec)

    def __html__(self):
        from markupsafe import escape

        return str(escape(self._render()))

    def __reduce__(self):
        return (L, (self._template,))


def _default_tokens():
    tokens = {}
    for name, value in DEFAULT_TERMS.items():
        tokens[name] = value
        tokens[f"{name}_lower"] = _lower(value)
    return tokens


def term(name, lower=False, branch_id=None):
    """Istilah untuk satu konsep: "client", "sub_client", "location", "worker".

    Tanpa branch_id, dipakai cabang pengguna yang sedang login. Tanpa
    pengguna (tugas latar, CLI) atau tanpa isian, dipakai istilah bawaan.
    """
    if name not in TERMS:
        raise KeyError(f"Istilah tidak dikenal: {name}")

    value = DEFAULT_TERMS[name]
    branch_id = branch_id if branch_id is not None else _current_branch_id()
    if branch_id:
        try:
            configured = str(_branch_settings(branch_id).get(TERM_SETTING_KEYS[name]) or "").strip()
        except Exception:
            configured = ""
        if configured:
            value = configured
    return _lower(value) if lower else value
