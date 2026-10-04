"""Halaman publik selain beranda: penjelasan & formulir kerja sama proyek."""
from __future__ import annotations

import os

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from app.extensions import limiter
from app.services.partnership_service import (
    MEAL_LABELS,
    PAYMENT_LABELS,
    PartnershipError,
    submit_partnership_request,
)
from app.services.public_site_service import partnership_context

public_bp = Blueprint("public", __name__)


def _page_context():
    return partnership_context()


@public_bp.route("/kerja-sama")
def partnership():
    return render_template("public/partnership.html", site=_page_context(), public_view=True,
                           page_title="Kerja Sama Katering Proyek")


@public_bp.route("/kerja-sama/ajukan", methods=["GET", "POST"])
@limiter.limit(os.getenv("PARTNERSHIP_RATE_LIMIT", "5 per 10 minutes"), methods=["POST"])
def partnership_apply():
    form = {}
    if request.method == "POST":
        form = request.form
        # Kolom jebakan: manusia tidak melihatnya, bot pengisi formulir mengisinya.
        if form.get("website"):
            return redirect(url_for("public.partnership_sent"))
        try:
            row = submit_partnership_request(form, source_ip=request.remote_addr)
        except PartnershipError as exc:
            flash(str(exc), "danger")
            return render_template(
                "public/partnership_apply.html", site=_page_context(), form=form,
                meals=MEAL_LABELS, payments=PAYMENT_LABELS, public_view=True, page_title="Ajukan Kerja Sama",
            ), 400
        session["partnership_number"] = row.request_number
        current_app.logger.info("Pengajuan kerja sama masuk: %s", row.request_number)
        return redirect(url_for("public.partnership_sent"))
    return render_template(
        "public/partnership_apply.html", site=_page_context(), form=form,
        meals=MEAL_LABELS, payments=PAYMENT_LABELS, public_view=True, page_title="Ajukan Kerja Sama",
    )


@public_bp.route("/kerja-sama/terkirim")
def partnership_sent():
    number = session.get("partnership_number")
    return render_template("public/partnership_sent.html", site=_page_context(), number=number,
                           public_view=True, page_title="Pengajuan Terkirim")
