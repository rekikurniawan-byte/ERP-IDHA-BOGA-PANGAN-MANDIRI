"""
Routes untuk ML Prediction — Prediksi Permintaan Catering.

Menu: Prediksi Catering
Role: OWNER, ADMIN
"""
from datetime import date, timedelta

from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from app.utils.clock import today_wib

from app.services.ml_prediction_service import (
    get_data_summary,
    get_model_status,
    train_model,
    predict_demand,
    estimate_materials_from_prediction,
    evaluate_model_detailed,
    get_active_mandors,
)

prediction_bp = Blueprint("prediction", __name__, url_prefix="/prediction")


def _require_role(*roles):
    if current_user.role not in roles:
        flash("Akses ditolak.", "danger")
        return redirect(url_for("dashboard.index"))
    return None


@prediction_bp.route("/")
@login_required
def index():
    """Halaman utama prediksi catering — dashboard overview."""
    denied = _require_role("OWNER", "ADMIN")
    if denied:
        return denied

    branch_id = current_user.branch_id

    data_summary = get_data_summary(branch_id)
    model_status = get_model_status()
    mandors = get_active_mandors(branch_id)

    return render_template(
        "prediction/index.html",
        data_summary=data_summary,
        model_status=model_status,
        mandors=mandors,
    )


@prediction_bp.route("/train", methods=["POST"])
@login_required
def train():
    """Training model Random Forest."""
    denied = _require_role("OWNER", "ADMIN")
    if denied:
        return denied

    branch_id = current_user.branch_id
    result = train_model(branch_id)

    if result["success"]:
        flash(result["message"], "success")
    else:
        flash(result["message"], "danger")

    return redirect(url_for("prediction.index"))


@prediction_bp.route("/predict", methods=["GET", "POST"])
@login_required
def predict():
    """Halaman prediksi — form + hasil."""
    denied = _require_role("OWNER", "ADMIN")
    if denied:
        return denied

    branch_id = current_user.branch_id
    model_status = get_model_status()
    mandors = get_active_mandors(branch_id)

    prediction_result = None
    material_result = None
    prediction_date = None
    selected_mandor_ids = None

    if request.method == "POST":
        # Parse form
        date_str = request.form.get("prediction_date", "")
        mandor_ids_raw = request.form.getlist("mandor_ids")

        try:
            prediction_date = date.fromisoformat(date_str)
        except (ValueError, TypeError):
            prediction_date = today_wib() + timedelta(days=1)

        # Parse mandor IDs
        if mandor_ids_raw and "all" not in mandor_ids_raw:
            try:
                selected_mandor_ids = [int(m) for m in mandor_ids_raw if m]
            except (ValueError, TypeError):
                selected_mandor_ids = None

        prediction_result = predict_demand(branch_id, prediction_date, selected_mandor_ids)

        if prediction_result["success"]:
            material_result = estimate_materials_from_prediction(branch_id, prediction_result)

    return render_template(
        "prediction/predict.html",
        model_status=model_status,
        mandors=mandors,
        prediction_result=prediction_result,
        material_result=material_result,
        prediction_date=prediction_date,
        selected_mandor_ids=selected_mandor_ids,
    )


@prediction_bp.route("/evaluate")
@login_required
def evaluate():
    """Halaman evaluasi model — untuk laporan skripsi."""
    denied = _require_role("OWNER", "ADMIN")
    if denied:
        return denied

    branch_id = current_user.branch_id
    model_status = get_model_status()

    test_days = request.args.get("test_days", 14, type=int)
    test_days = max(7, min(test_days, 60))

    evaluation = None
    if model_status["trained"]:
        evaluation = evaluate_model_detailed(branch_id, test_days=test_days)

    return render_template(
        "prediction/evaluate.html",
        model_status=model_status,
        evaluation=evaluation,
        test_days=test_days,
    )


@prediction_bp.route("/api/predict", methods=["POST"])
@login_required
def api_predict():
    """API endpoint untuk prediksi (JSON response)."""
    denied = _require_role("OWNER", "ADMIN")
    if denied:
        return jsonify({"success": False, "message": "Akses ditolak."}), 403

    branch_id = current_user.branch_id
    data = request.get_json(silent=True) or {}

    date_str = data.get("prediction_date", "")
    try:
        prediction_date = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        prediction_date = today_wib() + timedelta(days=1)

    mandor_ids = data.get("mandor_ids")
    if mandor_ids and not isinstance(mandor_ids, list):
        mandor_ids = None

    result = predict_demand(branch_id, prediction_date, mandor_ids)

    if result["success"]:
        material = estimate_materials_from_prediction(branch_id, result)
        result["materials"] = material

    # Convert date to string for JSON
    if "prediction_date" in result and isinstance(result["prediction_date"], date):
        result["prediction_date"] = result["prediction_date"].isoformat()

    return jsonify(result)
