# app.py
from flask import Flask, jsonify, abort, request, send_file
import os
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError
from markupsafe import escape

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

def render_study_cards_html(title, items):
    html = [f"<html><head><title>{escape(title)}</title><style>body{{font-family:sans-serif;}} .card{{border:1px solid #ccc;padding:1em;margin:1em 0;border-radius:8px;}} .card h3{{margin:0 0 0.5em 0;}} .meta{{color:#555;font-size:0.95em;}}</style></head><body>"]
    html.append(f"<h2>{escape(title)}</h2>")
    if not items:
        html.append("<p>No results found.</p>")
    for item in items:
        html.append("<div class='card'>")
        html.append(f"<h3>{escape(item.get('title','(no title)'))}</h3>")
        html.append(f"<div class='meta'>Study ID: {escape(str(item.get('study_id','')))}<br>Journal: {escape(str(item.get('journal','')))}<br>Year: {escape(str(item.get('year','')))}")
        if 'weight_a' in item:
            html.append(f"<br>Weight: {escape(str(item['weight_a']))}")
        if 'any_example_coordinate_from_a' in item and item['any_example_coordinate_from_a']:
            c = item['any_example_coordinate_from_a']
            html.append(f"<br>Example coordinate: ({escape(str(c.get('x')))}, {escape(str(c.get('y')))}, {escape(str(c.get('z')))})")
        html.append("</div></div>")
    html.append("</body></html>")
    return "".join(html)

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
        # 讀 limit（防爆表）
        try:
            limit = int(request.args.get("limit", 50))
        except ValueError:
            limit = 50
        limit = max(1, min(limit, 500))

        # 規範化：大小寫不敏感、空白/底線互通
        t = term.strip().lower()
        t_us = t.replace(" ", "_")
        t_sp = t.replace("_", " ")

        eng = get_engine()
        out = {"ok": False, "term_input": term, "count": 0, "items": []}
        try:
            with eng.begin() as conn:
                conn.execute(text("SET search_path TO ns, public;"))
                # 針對「去前綴」後的詞做比對（精準 + 輕度前綴模糊）
                sql = text("""
                    SELECT
                        m.study_id, m.title, m.journal, m.year,
                        a.term AS raw_term,                      -- 原始有前綴的樣子
                        split_part(a.term,'__',2) AS clean_term, -- 去前綴後的字
                        a.weight
                    FROM ns.annotations_terms AS a
                    JOIN ns.metadata         AS m USING (study_id)
                    WHERE
                        split_part(lower(a.term),'__',2) IN (:t_us, :t_sp)
                        OR split_part(lower(a.term),'__',2) ILIKE :prefix
                    ORDER BY a.weight DESC NULLS LAST, m.year DESC, m.study_id
                    LIMIT :limit
                """)
                rows = conn.execute(sql, {
                    "t_us": t_us,
                    "t_sp": t_sp,
                    "prefix": f"{t_us}%",
                    "limit": limit
                }).mappings().all()

                out["items"] = [dict(r) for r in rows]
                out["count"] = len(out["items"])
                out["ok"] = True
                return jsonify(out), 200

        except Exception as e:
            out["error"] = str(e)
            return jsonify(out), 500

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

    @app.get("/dissociate/terms/<term_a>/<term_b>", endpoint="dissociate_terms")
    def dissociate_terms(term_a: str, term_b: str):
        # Parse limit and offset
        try:
            limit = int(request.args.get("limit", 50))
        except ValueError:
            limit = 50
        limit = max(1, min(limit, 500))
        try:
            offset = int(request.args.get("offset", 0))
        except ValueError:
            offset = 0
        offset = max(0, offset)

        # Normalize terms: lower, strip, space/underscore equivalence
        ta = term_a.strip().lower()
        tb = term_b.strip().lower()
        ta_us = ta.replace(" ", "_")
        ta_sp = ta.replace("_", " ")
        tb_us = tb.replace(" ", "_")
        tb_sp = tb.replace("_", " ")

        eng = get_engine()
        out = {"ok": False, "term_a": term_a, "term_b": term_b, "count": 0, "items": []}
        try:
            with eng.begin() as conn:
                conn.execute(text("SET search_path TO ns, public;"))
                sql = text("""
                    SELECT m.study_id, m.title, m.journal, m.year,
                           a.weight AS weight_a
                    FROM ns.metadata m
                    JOIN ns.annotations_terms a ON m.study_id = a.study_id
                    WHERE (
                        split_part(lower(a.term),'__',2) IN (:ta_us, :ta_sp)
                        OR split_part(lower(a.term),'__',2) ILIKE :ta_prefix
                    )
                    AND EXISTS (
                        SELECT 1 FROM ns.annotations_terms a2
                        WHERE a2.study_id = m.study_id
                        AND (
                            split_part(lower(a2.term),'__',2) IN (:ta_us, :ta_sp)
                            OR split_part(lower(a2.term),'__',2) ILIKE :ta_prefix
                        )
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM ns.annotations_terms b2
                        WHERE b2.study_id = m.study_id
                        AND (
                            split_part(lower(b2.term),'__',2) IN (:tb_us, :tb_sp)
                            OR split_part(lower(b2.term),'__',2) ILIKE :tb_prefix
                        )
                    )
                    ORDER BY a.weight DESC NULLS LAST, m.year DESC, m.study_id
                    LIMIT :limit OFFSET :offset
                """)
                rows = conn.execute(sql, {
                    "ta_us": ta_us,
                    "ta_sp": ta_sp,
                    "ta_prefix": f"{ta_us}%",
                    "tb_us": tb_us,
                    "tb_sp": tb_sp,
                    "tb_prefix": f"{tb_us}%",
                    "limit": limit,
                    "offset": offset
                }).mappings().all()
                out["items"] = [dict(r) for r in rows]
                out["count"] = len(out["items"])
                out["ok"] = True
                # HTML branch
                if request.args.get("format") == "html":
                    title = f"Studies with '{term_a}' but not '{term_b}'"
                    return render_study_cards_html(title, out["items"])
                return jsonify(out), 200
        except Exception as e:
            out["error"] = str(e)
            return jsonify(out), 500

    @app.get("/dissociate/locations/<coords_a>/<coords_b>", endpoint="dissociate_locations")
    def dissociate_locations(coords_a, coords_b):
        # Parse query params
        try:
            r = float(request.args.get("r", 0))
        except ValueError:
            r = 0.0
        r = max(0.0, r)
        try:
            limit = int(request.args.get("limit", 50))
        except ValueError:
            limit = 50
        limit = max(1, min(limit, 500))
        try:
            offset = int(request.args.get("offset", 0))
        except ValueError:
            offset = 0
        offset = max(0, offset)

        # Parse coords_a and coords_b
        def parse_coords(s):
            try:
                x, y, z = map(float, s.split("_"))
                return {"x": x, "y": y, "z": z}
            except Exception:
                return None
        a = parse_coords(coords_a)
        b = parse_coords(coords_b)
        if a is None or b is None:
            return jsonify({"ok": False, "error": "Coordinates must be in x_y_z format (e.g., -22_0_-20)"}), 400

        eng = get_engine()
        out = {"ok": False, "a": a, "b": b, "r": r, "count": 0, "items": []}
        try:
            with eng.begin() as conn:
                conn.execute(text("SET search_path TO ns, public;"))
                # Compose spatial conditions
                if r == 0:
                    cond_a = "ST_X(ca.geom)=:ax AND ST_Y(ca.geom)=:ay AND ST_Z(ca.geom)=:az"
                    cond_b = "ST_X(cb.geom)=:bx AND ST_Y(cb.geom)=:by AND ST_Z(cb.geom)=:bz"
                    cond_c2 = "ST_X(c2.geom)=:ax AND ST_Y(c2.geom)=:ay AND ST_Z(c2.geom)=:az"
                else:
                    probe_a = "ST_SetSRID(ST_MakePoint(:ax,:ay,:az), ST_SRID(ca.geom))"
                    probe_b = "ST_SetSRID(ST_MakePoint(:bx,:by,:bz), ST_SRID(cb.geom))"
                    probe_c2 = "ST_SetSRID(ST_MakePoint(:ax,:ay,:az), ST_SRID(c2.geom))"
                    # Try 3D, fallback to 2D+Z
                    cond_a = f"(ST_3DDWithin(ca.geom, {probe_a}, :r) OR (ST_DWithin(ca.geom, {probe_a}, :r) AND ABS(ST_Z(ca.geom)-:az)<=:r))"
                    cond_b = f"(ST_3DDWithin(cb.geom, {probe_b}, :r) OR (ST_DWithin(cb.geom, {probe_b}, :r) AND ABS(ST_Z(cb.geom)-:bz)<=:r))"
                    cond_c2 = f"(ST_3DDWithin(c2.geom, {probe_c2}, :r) OR (ST_DWithin(c2.geom, {probe_c2}, :r) AND ABS(ST_Z(c2.geom)-:az)<=:r))"
                sql = text(f"""
                    SELECT m.study_id, m.title, m.journal, m.year,
                        (
                            SELECT json_build_object('x', ST_X(c2.geom), 'y', ST_Y(c2.geom), 'z', ST_Z(c2.geom))
                            FROM ns.coordinates c2
                            WHERE c2.study_id = m.study_id AND {cond_c2}
                            LIMIT 1
                        ) AS any_example_coordinate_from_a
                    FROM ns.metadata m
                    WHERE EXISTS (
                        SELECT 1 FROM ns.coordinates ca
                        WHERE ca.study_id = m.study_id AND {cond_a}
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM ns.coordinates cb
                        WHERE cb.study_id = m.study_id AND {cond_b}
                    )
                    ORDER BY m.year DESC, m.study_id
                    LIMIT :limit OFFSET :offset
                """)
                rows = conn.execute(sql, {
                    "ax": a["x"], "ay": a["y"], "az": a["z"],
                    "bx": b["x"], "by": b["y"], "bz": b["z"],
                    "r": r,
                    "limit": limit,
                    "offset": offset
                }).mappings().all()
                out["items"] = [dict(r) for r in rows]
                out["count"] = len(out["items"])
                out["ok"] = True
                # HTML branch
                if request.args.get("format") == "html":
                    title = f"Studies with location {coords_a} but not {coords_b} (r={r})"
                    return render_study_cards_html(title, out["items"])
                return jsonify(out), 200
        except Exception as e:
            out["error"] = str(e)
            return jsonify(out), 500

    return app

# WSGI entry point (no __main__)
app = create_app()
