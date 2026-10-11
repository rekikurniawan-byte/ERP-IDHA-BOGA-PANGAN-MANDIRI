"""
ML Prediction Service — Random Forest Regression untuk prediksi jumlah_bungkus.

Alur kerja:
1. Ambil data historis dari daily_order_details (join daily_orders)
2. Feature engineering: mandor_id, waktu_makan (lunch/dinner), day_of_week, month, week_of_month,
   lag features (jumlah kemarin, rata-rata 7 hari, rata-rata 14 hari)
3. Training Random Forest Regression
4. Prediksi jumlah bungkus per mandor per waktu makan untuk tanggal tertentu
5. Konversi prediksi bungkus → estimasi bahan baku via Recipe/BOM
"""
import logging
import os
import pickle
from datetime import date, timedelta
from collections import OrderedDict

from app.utils.clock import today_wib

from sqlalchemy import text

from app.extensions import db
from app.utils.terms import T

logger = logging.getLogger(__name__)


# Path untuk menyimpan trained model
MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "ml_models")
MODEL_FILENAME = "rf_demand_model.pkl"
METADATA_FILENAME = "rf_demand_metadata.pkl"


def _ensure_model_dir():
    os.makedirs(MODEL_DIR, exist_ok=True)


def _model_path():
    return os.path.join(MODEL_DIR, MODEL_FILENAME)


def _metadata_path():
    return os.path.join(MODEL_DIR, METADATA_FILENAME)


# ==============================================================================
# DATA EXTRACTION
# ==============================================================================

def get_historical_data(branch_id, min_date=None, max_date=None):
    """
    Ambil data historis order detail dengan join ke daily_orders.
    Returns list of dicts: [{order_date, mandor_id, mandor_name, lunch_qty, dinner_qty}, ...]
    """
    where_clauses = ["do2.branch_id = :branch_id", "do2.is_locked = TRUE"]
    params = {"branch_id": branch_id}

    if min_date:
        where_clauses.append("do2.order_date >= :min_date")
        params["min_date"] = min_date
    if max_date:
        where_clauses.append("do2.order_date <= :max_date")
        params["max_date"] = max_date

    where_sql = " AND ".join(where_clauses)

    sql = f"""
        SELECT
            do2.order_date,
            dod.mandor_id,
            m.name AS mandor_name,
            dod.lunch_qty,
            dod.dinner_qty,
            dod.total_qty
        FROM daily_order_details dod
        JOIN daily_orders do2 ON do2.id = dod.daily_order_id
        JOIN mandors m ON m.id = dod.mandor_id
        WHERE {where_sql}
        ORDER BY do2.order_date ASC, dod.mandor_id ASC
    """

    try:
        rows = db.session.execute(text(sql), params).mappings().all()
        return [dict(row) for row in rows]
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/ml_prediction_service.py:79")
        db.session.rollback()
        return []


def get_active_mandors(branch_id):
    """Ambil daftar mandor aktif."""
    sql = """
        SELECT id, name
        FROM mandors
        WHERE branch_id = :branch_id AND is_active = TRUE
        ORDER BY name ASC
    """
    try:
        rows = db.session.execute(text(sql), {"branch_id": branch_id}).mappings().all()
        return [dict(row) for row in rows]
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/ml_prediction_service.py:95")
        db.session.rollback()
        return []


def get_data_summary(branch_id):
    """Ringkasan data historis untuk UI info panel."""
    sql = """
        SELECT
            COUNT(*) AS total_rows,
            MIN(do2.order_date) AS earliest_date,
            MAX(do2.order_date) AS latest_date,
            COUNT(DISTINCT dod.mandor_id) AS mandor_count,
            COUNT(DISTINCT do2.order_date) AS day_count
        FROM daily_order_details dod
        JOIN daily_orders do2 ON do2.id = dod.daily_order_id
        WHERE do2.branch_id = :branch_id AND do2.is_locked = TRUE
    """
    try:
        row = db.session.execute(text(sql), {"branch_id": branch_id}).mappings().first()
        if row:
            return dict(row)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/ml_prediction_service.py:117")
        db.session.rollback()

    return {
        "total_rows": 0,
        "earliest_date": None,
        "latest_date": None,
        "mandor_count": 0,
        "day_count": 0,
    }


# ==============================================================================
# FEATURE ENGINEERING
# ==============================================================================

def _build_features_dataframe(historical_data):
    """
    Dari data historis, buat feature matrix untuk training.
    Setiap row order detail dipecah jadi 2 baris (lunch + dinner).

    Features:
    - mandor_id (encoded)
    - meal_type (0=lunch, 1=dinner)
    - day_of_week (0=Monday..6=Sunday)
    - month (1-12)
    - week_of_month (1-5)
    - day_of_month (1-31)
    - lag_1 (jumlah kemarin untuk mandor+meal yang sama)
    - lag_7_avg (rata-rata 7 hari terakhir)
    - lag_14_avg (rata-rata 14 hari terakhir)

    Returns: (feature_list, target_list, mandor_ids_set)
    """
    if not historical_data:
        return [], [], set()

    # Bangun time-series per mandor per meal_type
    # Key: (mandor_id, meal_type) → list of (order_date, qty)
    series = {}
    for row in historical_data:
        mandor_id = row["mandor_id"]
        order_date = row["order_date"]

        # Lunch
        lunch_qty = int(row.get("lunch_qty") or 0)
        if lunch_qty > 0:
            key = (mandor_id, 0)  # 0 = lunch
            if key not in series:
                series[key] = []
            series[key].append((order_date, lunch_qty))

        # Dinner
        dinner_qty = int(row.get("dinner_qty") or 0)
        if dinner_qty > 0:
            key = (mandor_id, 1)  # 1 = dinner
            if key not in series:
                series[key] = []
            series[key].append((order_date, dinner_qty))

    # Sort each series by date
    for key in series:
        series[key].sort(key=lambda x: x[0])

    # Build features
    features = []
    targets = []
    mandor_ids = set()

    for (mandor_id, meal_type), data_points in series.items():
        mandor_ids.add(mandor_id)

        for i, (order_date, qty) in enumerate(data_points):
            # Date features
            day_of_week = order_date.weekday()  # 0=Monday
            month = order_date.month
            day_of_month = order_date.day
            week_of_month = (day_of_month - 1) // 7 + 1

            # Lag features
            lag_1 = data_points[i - 1][1] if i >= 1 else qty
            lag_7_values = [dp[1] for dp in data_points[max(0, i - 7):i]]
            lag_14_values = [dp[1] for dp in data_points[max(0, i - 14):i]]

            lag_7_avg = sum(lag_7_values) / len(lag_7_values) if lag_7_values else float(qty)
            lag_14_avg = sum(lag_14_values) / len(lag_14_values) if lag_14_values else float(qty)

            feature_row = [
                mandor_id,
                meal_type,
                day_of_week,
                month,
                week_of_month,
                day_of_month,
                lag_1,
                lag_7_avg,
                lag_14_avg,
            ]

            features.append(feature_row)
            targets.append(qty)

    return features, targets, mandor_ids


def _build_prediction_features(branch_id, prediction_date, mandor_ids=None, meal_types=None):
    """
    Build feature vectors for prediction.
    Requires historical data to compute lag features.
    """
    # Get last 30 days of history for lag computation
    history_start = prediction_date - timedelta(days=30)
    historical = get_historical_data(branch_id, min_date=history_start, max_date=prediction_date - timedelta(days=1))

    if not historical:
        return [], []

    # Build series for lag computation
    series = {}
    for row in historical:
        mandor_id = row["mandor_id"]
        order_date = row["order_date"]

        lunch_qty = int(row.get("lunch_qty") or 0)
        if lunch_qty > 0:
            key = (mandor_id, 0)
            if key not in series:
                series[key] = []
            series[key].append((order_date, lunch_qty))

        dinner_qty = int(row.get("dinner_qty") or 0)
        if dinner_qty > 0:
            key = (mandor_id, 1)
            if key not in series:
                series[key] = []
            series[key].append((order_date, dinner_qty))

    for key in series:
        series[key].sort(key=lambda x: x[0])

    # Determine mandors and meals to predict
    if mandor_ids is None:
        mandor_ids = list(set(k[0] for k in series.keys()))

    if meal_types is None:
        meal_types = [0, 1]  # lunch and dinner

    # Date features for prediction_date
    day_of_week = prediction_date.weekday()
    month = prediction_date.month
    day_of_month = prediction_date.day
    week_of_month = (day_of_month - 1) // 7 + 1

    features = []
    labels = []  # (mandor_id, meal_type) for each feature row

    for mandor_id in mandor_ids:
        for meal_type in meal_types:
            key = (mandor_id, meal_type)
            data_points = series.get(key, [])

            if not data_points:
                continue

            # Lag features from most recent data
            lag_1 = data_points[-1][1] if data_points else 0
            lag_7_values = [dp[1] for dp in data_points[-7:]]
            lag_14_values = [dp[1] for dp in data_points[-14:]]

            lag_7_avg = sum(lag_7_values) / len(lag_7_values) if lag_7_values else 0
            lag_14_avg = sum(lag_14_values) / len(lag_14_values) if lag_14_values else 0

            feature_row = [
                mandor_id,
                meal_type,
                day_of_week,
                month,
                week_of_month,
                day_of_month,
                lag_1,
                lag_7_avg,
                lag_14_avg,
            ]

            features.append(feature_row)
            labels.append((mandor_id, meal_type))

    return features, labels


# ==============================================================================
# MODEL TRAINING
# ==============================================================================

def train_model(branch_id):
    """
    Train Random Forest Regression model dari data historis.

    Returns dict with training results:
    - success: bool
    - message: str
    - metrics: dict (MAE, RMSE, data_points, etc.)
    """
    try:
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import mean_absolute_error, mean_squared_error
        import numpy as np
    except ImportError:
        return {
            "success": False,
            "message": "Library scikit-learn belum terinstall. Jalankan: pip install scikit-learn numpy",
            "metrics": {},
        }

    historical = get_historical_data(branch_id)

    if not historical:
        return {
            "success": False,
            "message": "Tidak ada data historis (order terkunci) untuk training.",
            "metrics": {},
        }

    features, targets, mandor_ids = _build_features_dataframe(historical)

    if len(features) < 20:
        return {
            "success": False,
            "message": f"Data terlalu sedikit untuk training ({len(features)} baris). Minimal 20 data point.",
            "metrics": {},
        }

    X = np.array(features, dtype=float)
    y = np.array(targets, dtype=float)

    # Split data: 80% training, 20% testing
    test_size = min(0.2, max(0.1, 10 / len(features)))
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=42
    )

    # Train Random Forest
    model = RandomForestRegressor(
        n_estimators=100,
        max_depth=15,
        min_samples_split=3,
        min_samples_leaf=2,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    # Evaluate
    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))

    # WMAPE (Weighted Mean Absolute Percentage Error)
    total_actual = float(np.sum(y_test))
    wmape = (float(np.sum(np.abs(y_test - y_pred))) / total_actual * 100) if total_actual > 0 else 0

    # Feature importance
    feature_names = [
        "mandor_id", "meal_type", "day_of_week", "month",
        "week_of_month", "day_of_month", "lag_1", "lag_7_avg", "lag_14_avg"
    ]
    importances = model.feature_importances_
    feature_importance = sorted(
        zip(feature_names, importances),
        key=lambda x: x[1],
        reverse=True,
    )

    # Save model
    _ensure_model_dir()
    with open(_model_path(), "wb") as f:
        pickle.dump(model, f)

    metadata = {
        "branch_id": branch_id,
        "trained_at": today_wib().isoformat(),
        "data_points": len(features),
        "train_size": len(X_train),
        "test_size": len(X_test),
        "mandor_count": len(mandor_ids),
        "mandor_ids": list(mandor_ids),
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "wmape": round(wmape, 2),
        "feature_importance": feature_importance,
    }

    with open(_metadata_path(), "wb") as f:
        pickle.dump(metadata, f)

    return {
        "success": True,
        "message": f"Model berhasil ditraining dengan {len(features)} data points. MAE: {mae:.2f} bungkus.",
        "metrics": metadata,
    }


def get_model_status():
    """Cek status model yang tersimpan."""
    model_file = _model_path()
    metadata_file = _metadata_path()

    if not os.path.exists(model_file):
        return {
            "trained": False,
            "message": "Model belum di-training.",
            "metadata": None,
        }

    try:
        with open(metadata_file, "rb") as f:
            metadata = pickle.load(f)

        return {
            "trained": True,
            "message": f"Model tersedia. Trained: {metadata.get('trained_at', '-')}. MAE: {metadata.get('mae', '-')} bungkus.",
            "metadata": metadata,
        }
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/ml_prediction_service.py:441")
        return {
            "trained": True,
            "message": "Model file ditemukan tapi metadata tidak bisa dibaca.",
            "metadata": None,
        }


def _load_model():
    """Load trained model dari disk."""
    model_file = _model_path()
    if not os.path.exists(model_file):
        return None

    try:
        with open(model_file, "rb") as f:
            return pickle.load(f)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/ml_prediction_service.py:458")
        return None


# ==============================================================================
# PREDICTION
# ==============================================================================

def predict_demand(branch_id, prediction_date, mandor_ids=None):
    """
    Prediksi jumlah bungkus per mandor per waktu makan untuk tanggal tertentu.

    Returns:
    {
        "success": bool,
        "message": str,
        "prediction_date": date,
        "predictions": [
            {"mandor_id": int, "mandor_name": str, "meal_type": str,
             "predicted_qty": int, "confidence_note": str}
        ],
        "totals": {"lunch": int, "dinner": int, "total": int}
    }
    """
    try:
        import numpy as np
    except ImportError:
        return {
            "success": False,
            "message": "Library numpy belum terinstall.",
            "predictions": [],
            "totals": {"lunch": 0, "dinner": 0, "total": 0},
        }

    model = _load_model()
    if model is None:
        return {
            "success": False,
            "message": "Model belum di-training. Silakan training terlebih dahulu.",
            "predictions": [],
            "totals": {"lunch": 0, "dinner": 0, "total": 0},
        }

    features, labels = _build_prediction_features(branch_id, prediction_date, mandor_ids)

    if not features:
        return {
            "success": False,
            "message": "Tidak ada data historis yang cukup untuk membuat prediksi. Pastikan ada order terkunci sebelum tanggal prediksi.",
            "predictions": [],
            "totals": {"lunch": 0, "dinner": 0, "total": 0},
        }

    X = np.array(features, dtype=float)
    y_pred = model.predict(X)

    # Get mandor names
    mandor_map = {}
    mandors = get_active_mandors(branch_id)
    for m in mandors:
        mandor_map[m["id"]] = m["name"]

    predictions = []
    total_lunch = 0
    total_dinner = 0

    for i, (mandor_id, meal_type) in enumerate(labels):
        predicted_qty = max(0, round(y_pred[i]))
        meal_label = "Siang" if meal_type == 0 else "Sore"

        if meal_type == 0:
            total_lunch += predicted_qty
        else:
            total_dinner += predicted_qty

        predictions.append({
            "mandor_id": mandor_id,
            "mandor_name": mandor_map.get(mandor_id, f"{T.sub_client} #{mandor_id}"),
            "meal_type": meal_label,
            "meal_type_code": meal_type,
            "predicted_qty": predicted_qty,
        })

    # Sort by mandor_name, then meal_type
    predictions.sort(key=lambda x: (x["mandor_name"], x["meal_type_code"]))

    return {
        "success": True,
        "message": f"Prediksi berhasil untuk {prediction_date.isoformat()} — {len(predictions)} prediksi.",
        "prediction_date": prediction_date,
        "predictions": predictions,
        "totals": {
            "lunch": total_lunch,
            "dinner": total_dinner,
            "total": total_lunch + total_dinner,
        },
    }


# ==============================================================================
# MATERIAL ESTIMATION (Prediksi → Bahan Baku via Recipe/BOM)
# ==============================================================================

def estimate_materials_from_prediction(branch_id, prediction_result):
    """
    Konversi prediksi jumlah bungkus → estimasi kebutuhan bahan baku.

    Menggunakan recipe/BOM standar dari menu default branch.
    Jika belum ada menu default, gunakan recipe terakhir yang aktif.

    Returns:
    {
        "success": bool,
        "message": str,
        "materials": [
            {"item_name": str, "unit": str, "qty_needed": float}
        ],
        "total_portions": int,
        "recipe_source": str
    }
    """
    if not prediction_result.get("success"):
        return {
            "success": False,
            "message": "Prediksi belum berhasil, tidak bisa estimasi bahan.",
            "materials": [],
            "total_portions": 0,
            "recipe_source": None,
        }

    total_portions = prediction_result["totals"]["total"]

    if total_portions <= 0:
        return {
            "success": True,
            "message": "Total prediksi 0 bungkus, tidak ada kebutuhan bahan.",
            "materials": [],
            "total_portions": 0,
            "recipe_source": None,
        }

    # Ambil recipe aktif yang punya BOM
    sql = """
        SELECT
            ri.item_id,
            i.item_name,
            i.unit,
            ri.qty_per_portion,
            ri.unit AS recipe_unit,
            rh.recipe_name,
            rh.base_portion
        FROM recipe_items ri
        JOIN recipe_headers rh ON rh.id = ri.recipe_id
        JOIN items i ON i.id = ri.item_id
        WHERE rh.branch_id = :branch_id
          AND rh.is_active = TRUE
          AND rh.recipe_status = 'FINAL'
          AND i.is_active = TRUE
        ORDER BY i.item_name ASC
    """

    try:
        rows = db.session.execute(text(sql), {"branch_id": branch_id}).mappings().all()
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/ml_prediction_service.py:621")
        db.session.rollback()
        return {
            "success": False,
            "message": "Gagal membaca data resep dari database.",
            "materials": [],
            "total_portions": total_portions,
            "recipe_source": None,
        }

    if not rows:
        return {
            "success": False,
            "message": "Belum ada resep FINAL yang aktif dengan BOM. Isi resep terlebih dahulu.",
            "materials": [],
            "total_portions": total_portions,
            "recipe_source": None,
        }

    # Aggregate material needs
    # Group by item_id, sum qty_per_portion × total_portions / base_portion
    material_map = OrderedDict()
    recipe_names = set()

    for row in rows:
        row = dict(row)
        item_id = row["item_id"]
        qty_per_portion = float(row.get("qty_per_portion") or 0)
        base_portion = float(row.get("base_portion") or 1) or 1
        recipe_names.add(row.get("recipe_name", ""))

        # qty_needed = qty_per_portion × (total_portions / base_portion)
        qty_needed = qty_per_portion * (total_portions / base_portion)

        if item_id in material_map:
            material_map[item_id]["qty_needed"] += qty_needed
        else:
            material_map[item_id] = {
                "item_id": item_id,
                "item_name": row["item_name"],
                "unit": row.get("recipe_unit") or row["unit"],
                "qty_needed": qty_needed,
            }

    materials = sorted(material_map.values(), key=lambda x: x["item_name"])

    # Round quantities
    for mat in materials:
        mat["qty_needed"] = round(mat["qty_needed"], 2)

    return {
        "success": True,
        "message": f"Estimasi bahan untuk {total_portions} bungkus dari {len(recipe_names)} resep.",
        "materials": materials,
        "total_portions": total_portions,
        "recipe_source": ", ".join(sorted(recipe_names)) if recipe_names else None,
    }


# ==============================================================================
# EVALUATION (untuk report skripsi)
# ==============================================================================

def evaluate_model_detailed(branch_id, test_days=14):
    """
    Evaluasi model dengan detail per-hari untuk laporan skripsi.
    Ambil data test_days terakhir, prediksi satu per satu, bandingkan.

    Returns:
    {
        "success": bool,
        "message": str,
        "evaluation": [
            {"date": str, "mandor_name": str, "meal": str, "actual": int, "predicted": int, "error": int}
        ],
        "summary": {"mae": float, "rmse": float, "wmape": float, "data_points": int}
    }
    """
    try:
        import numpy as np
    except ImportError:
        return {"success": False, "message": "numpy belum terinstall.", "evaluation": [], "summary": {}}

    model = _load_model()
    if model is None:
        return {"success": False, "message": "Model belum di-training.", "evaluation": [], "summary": {}}

    # Get all historical data
    historical = get_historical_data(branch_id)
    if len(historical) < 30:
        return {"success": False, "message": "Data terlalu sedikit untuk evaluasi.", "evaluation": [], "summary": {}}

    # Determine test period (last test_days days of data)
    all_dates = sorted(set(row["order_date"] for row in historical))
    if len(all_dates) <= test_days:
        return {"success": False, "message": "Tidak cukup hari untuk testing.", "evaluation": [], "summary": {}}

    test_dates = all_dates[-test_days:]

    # Get mandor names
    mandor_map = {}
    mandors = get_active_mandors(branch_id)
    for m in mandors:
        mandor_map[m["id"]] = m["name"]

    evaluation_rows = []
    all_actuals = []
    all_predictions = []

    for test_date in test_dates:
        # Build features for this date
        features, labels = _build_prediction_features(branch_id, test_date)
        if not features:
            continue

        X = np.array(features, dtype=float)
        y_pred = model.predict(X)

        # Get actual values for this date
        actual_map = {}
        for row in historical:
            if row["order_date"] == test_date:
                mandor_id = row["mandor_id"]
                actual_map[(mandor_id, 0)] = int(row.get("lunch_qty") or 0)
                actual_map[(mandor_id, 1)] = int(row.get("dinner_qty") or 0)

        for i, (mandor_id, meal_type) in enumerate(labels):
            actual = actual_map.get((mandor_id, meal_type), 0)
            predicted = max(0, round(y_pred[i]))

            if actual > 0:  # Only evaluate where we have real data
                all_actuals.append(actual)
                all_predictions.append(predicted)

                evaluation_rows.append({
                    "date": test_date.isoformat(),
                    "mandor_name": mandor_map.get(mandor_id, f"#{mandor_id}"),
                    "meal": "Siang" if meal_type == 0 else "Sore",
                    "actual": actual,
                    "predicted": predicted,
                    "error": abs(actual - predicted),
                })

    if not all_actuals:
        return {"success": False, "message": "Tidak ada data aktual untuk dibandingkan.", "evaluation": [], "summary": {}}

    actuals = np.array(all_actuals, dtype=float)
    preds = np.array(all_predictions, dtype=float)

    mae = float(np.mean(np.abs(actuals - preds)))
    rmse = float(np.sqrt(np.mean((actuals - preds) ** 2)))
    total_actual = float(np.sum(actuals))
    wmape = (float(np.sum(np.abs(actuals - preds))) / total_actual * 100) if total_actual > 0 else 0

    return {
        "success": True,
        "message": f"Evaluasi {len(evaluation_rows)} prediksi selama {test_days} hari.",
        "evaluation": evaluation_rows[:100],  # Limit for UI display
        "summary": {
            "mae": round(mae, 2),
            "rmse": round(rmse, 2),
            "wmape": round(wmape, 2),
            "data_points": len(all_actuals),
            "test_days": test_days,
        },
    }
