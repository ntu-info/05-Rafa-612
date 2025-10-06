# app.py
from flask import Flask, jsonify, abort, request, send_file
import os
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError

_engine = None

def get_engine():
    global _engine
    if _engine is not None:
        return _engine
    db_url = os.getenv("DB_URL")
    if not db_url:
        raise RuntimeError("Missing DB_URL (or DATABASE_URL) environment variable.")
    # Normalize old 'postgres://' scheme to 'postgresql://'
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]
    _engine = create_engine(
        db_url,
        pool_pre_ping=True,
    )
    return _engine

def create_app():
    app = Flask(__name__)

    @app.get("/", endpoint="health")
    def health():
        return "<p>Server working!</p>"

    @app.get("/img", endpoint="show_img")
    def show_img():
        return send_file("amygdala.gif", mimetype="image/gif")

    @app.get("/terms/<term>/studies", endpoint="terms_studies")
    def get_studies_by_term(term: str):
        """
        依術語 term 回傳相關的 studies。
        用法：
        /terms/fear/studies
        /terms/amygdala/studies?limit=50
        規則：
        - 忽略大小寫
        - 空白與底線互通（"alpha band" ≈ "alpha_band"）
        - 預設回傳 50 筆，可用 ?limit=100 調整（上限 500）
        """
        # 讀 limit（有上限，避免炸資料庫）
        try:
            limit = int(request.args.get("limit", 50))
        except ValueError:
            limit = 50
        limit = max(1, min(limit, 500))

        # 規範化 term：小寫；支援「空白/底線」兩種變形
        t_raw = term.strip()
        t_lower = t_raw.lower()
        t_us   = t_lower.replace(" ", "_")
        t_sp   = t_lower.replace("_", " ")

        eng = get_engine()
        payload = {
            "ok": False,
            "term_input": t_raw,
            "normalized_candidates": [t_us, t_sp],
            "count": 0,
            "items": []
        }

        try:
            with eng.begin() as conn:
                # 用 ns schema
                conn.execute(text("SET search_path TO ns, public;"))
                # 直接從標註表 join metadata 撈資料
                # 說明：
                # - 以 term 等於（忽略大小寫）t_us 或 t_sp 為準
                # - 如果 annotations_terms 有 weight，就依 weight 排序
                sql = text("""
                    SELECT
                        m.study_id,
                        m.title,
                        m.journal,
                        m.year,
                        a.term,
                        a.weight
                    FROM ns.annotations_terms AS a
                    JOIN ns.metadata         AS m
                    ON m.study_id = a.study_id
                    WHERE lower(a.term) = :t_us
                    OR lower(a.term) = :t_sp
                    ORDER BY a.weight DESC NULLS LAST, m.year DESC, m.study_id
                    LIMIT :limit
                """)
                rows = conn.execute(sql, {"t_us": t_us, "t_sp": t_sp, "limit": limit}).mappings().all()
                payload["items"] = [dict(r) for r in rows]
                payload["count"] = len(payload["items"])
                payload["ok"] = True
                return jsonify(payload), 200

        except Exception as e:
            payload["error"] = str(e)
            return jsonify(payload), 500

    @app.get("/locations/<coords>/studies", endpoint="locations_studies")
    def get_studies_by_coordinates(coords):
        x, y, z = map(int, coords.split("_"))
        return jsonify([x, y, z])

    @app.get("/test_db", endpoint="test_db")
    
    def test_db():
        eng = get_engine()
        payload = {"ok": False, "dialect": eng.dialect.name}

        try:
            with eng.begin() as conn:
                # Ensure we are in the correct schema
                conn.execute(text("SET search_path TO ns, public;"))
                payload["version"] = conn.exec_driver_sql("SELECT version()").scalar()

                # Counts
                payload["coordinates_count"] = conn.execute(text("SELECT COUNT(*) FROM ns.coordinates")).scalar()
                payload["metadata_count"] = conn.execute(text("SELECT COUNT(*) FROM ns.metadata")).scalar()
                payload["annotations_terms_count"] = conn.execute(text("SELECT COUNT(*) FROM ns.annotations_terms")).scalar()

                # Samples
                try:
                    rows = conn.execute(text(
                        "SELECT study_id, ST_X(geom) AS x, ST_Y(geom) AS y, ST_Z(geom) AS z FROM ns.coordinates LIMIT 3"
                    )).mappings().all()
                    payload["coordinates_sample"] = [dict(r) for r in rows]
                except Exception:
                    payload["coordinates_sample"] = []

                try:
                    # Select a few columns if they exist; otherwise select a generic subset
                    rows = conn.execute(text("SELECT * FROM ns.metadata LIMIT 3")).mappings().all()
                    payload["metadata_sample"] = [dict(r) for r in rows]
                except Exception:
                    payload["metadata_sample"] = []

                try:
                    rows = conn.execute(text(
                        "SELECT study_id, contrast_id, term, weight FROM ns.annotations_terms LIMIT 3"
                    )).mappings().all()
                    payload["annotations_terms_sample"] = [dict(r) for r in rows]
                except Exception:
                    payload["annotations_terms_sample"] = []

            payload["ok"] = True
            return jsonify(payload), 200

        except Exception as e:
            payload["error"] = str(e)
            return jsonify(payload), 500

    return app

# WSGI entry point (no __main__)
app = create_app()
