import json, os, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from redis import Redis
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import select
from .database import Base, SessionLocal, engine, ensure_runtime_columns
from .models import AnalysisJob, DelayCase

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
SHARED_DIR = Path(os.getenv("SHARED_DIR", "/shared"))
queue = Redis.from_url(REDIS_URL, decode_responses=True)

FEATURE_KEYS = ["container_count", "avg_gate_dwell_min", "max_gate_dwell_min", "reefer_ratio", "hazmat_ratio", "customs_open_count", "gate_event_count", "dry_count", "reefer_count", "hazmat_count", "port_call_hour", "window_minutes", "dwell_x_reefer", "gate_x_count"]

def vector(f):
    return np.array([[f[k] for k in FEATURE_KEYS]], dtype=float)

def train_model():
    rows = [
        ([4, 8, 12, .0, .0, 0, 4, 4, 0, 0, 6, 480], "normal"),
        ([6, 16, 22, .17, .0, 0, 6, 5, 1, 0, 8, 420], "watch"),
        ([8, 28, 40, .25, .12, 0, 8, 5, 2, 1, 10, 360], "major"),
        ([9, 42, 66, .33, .22, 1, 9, 4, 3, 2, 13, 300], "critical"),
        ([5, 10, 18, .2, .0, 0, 5, 4, 1, 0, 7, 520], "normal"),
        ([7, 22, 31, .29, .0, 0, 7, 4, 2, 0, 9, 390], "watch"),
        ([10, 35, 51, .3, .1, 0, 10, 6, 3, 1, 11, 330], "major"),
        ([12, 50, 78, .42, .17, 0, 12, 6, 5, 2, 14, 280], "critical"),
        ([3, 7, 10, .0, .0, 0, 3, 3, 0, 0, 5, 600], "normal"),
        ([8, 25, 36, .38, .0, 0, 8, 5, 3, 0, 12, 360], "major"),
        ([5, 18, 24, .2, .2, 0, 5, 3, 1, 1, 9, 440], "watch"),
        ([11, 45, 70, .45, .25, 0, 11, 4, 5, 2, 15, 260], "critical"),
    ]
    x = []
    y = []
    for base, label in rows:
        f = dict(zip(FEATURE_KEYS[:12], base))
        f["dwell_x_reefer"] = f["avg_gate_dwell_min"] * f["reefer_ratio"]
        f["gate_x_count"] = f["gate_event_count"] * f["container_count"]
        x.append([f[k] for k in FEATURE_KEYS]); y.append(label)
    model = Pipeline([("scale", StandardScaler()), ("lr", LogisticRegression(max_iter=500, random_state=42, multi_class="auto"))])
    model.fit(x, y)
    return model

MODEL = train_model()

def model_evidence():
    """冻结本次推理所用的 scaler 与 LR 参数，供分级说明脱离模型重训独立复核。"""
    scaler = MODEL.named_steps["scale"]
    lr = MODEL.named_steps["lr"]
    return {
        "classes": list(lr.classes_),
        "feature_keys": list(FEATURE_KEYS),
        "scaler_mean": [float(v) for v in scaler.mean_],
        "scaler_scale": [float(v) for v in scaler.scale_],
        "intercept": [float(v) for v in lr.intercept_],
        "coef": [[float(v) for v in row] for row in lr.coef_],
    }

def run_job(job_id):
    db = SessionLocal()
    job = db.get(AnalysisJob, int(job_id))
    if not job:
        db.close(); return
    case = db.get(DelayCase, job.case_id)
    try:
        job.status = "running"; db.commit()
        f = dict(job.input_summary or {})
        f["dwell_x_reefer"] = round(f.get("avg_gate_dwell_min", 0) * f.get("reefer_ratio", 0), 3)
        f["gate_x_count"] = f.get("gate_event_count", 0) * f.get("container_count", 0)
        x = vector(f)
        label = MODEL.predict(x)[0]
        probs = MODEL.predict_proba(x)[0]
        classes = MODEL.named_steps["lr"].classes_
        confidence = float(max(probs))
        result = {"label": label, "confidence": round(confidence, 4), "probabilities": {c: round(float(p), 4) for c, p in zip(classes, probs)}, "feature_keys": FEATURE_KEYS, "features": f, "model_evidence": model_evidence(), "formula": "手工交叉特征 = avg_gate_dwell_min×reefer_ratio, gate_event_count×container_count；StandardScaler + LogisticRegression(random_state=42)"}
        job.result = result; job.status = "succeeded"; job.finished_at = datetime.now(timezone.utc)
        case.model_output = result; case.final_level = label; case.status = "classified"; case.exception_reason = None
        db.commit()
    except Exception as exc:
        job.status = "failed"; job.error = str(exc); job.finished_at = datetime.now(timezone.utc); db.commit()
    finally:
        db.close()

def main():
    Base.metadata.create_all(engine)
    ensure_runtime_columns()
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        Path(SHARED_DIR / "worker-heartbeat").touch()
        item = queue.blpop("container_delay_triage_jobs", timeout=3)
        if item:
            run_job(item[1])
        time.sleep(1)

if __name__ == "__main__":
    main()
