# Neurosynth Functional Dissociation API

A lightweight Flask backend for querying functional dissociation in a Neurosynth-backed PostgreSQL database.

## Quick Start

### 1. Requirements
- Python 3.10+
- PostgreSQL 12+
- Python packages: `Flask`, `SQLAlchemy`, `psycopg2-binary`, `gunicorn`, `markupsafe`

### 2. Set up your database
Provision a PostgreSQL database and note the connection string (e.g., on Render, Supabase, or local).

### 3. Set environment variable
Set the database URL as an environment variable:

```bash
export DB_URL=postgresql://<USER>:<PASSWORD>@<HOST>:5432/<DBNAME>
```

### 4. Run the app

For development:
```bash
python app.py
```

For production (recommended):
```bash
gunicorn app:app --bind 0.0.0.0:$PORT
```

---

## API Endpoints

### 1. Dissociate by Terms

```
GET /dissociate/terms/<term_a>/<term_b>
```

Returns studies that mention **`term_a`** but **not** `term_b`.

#### Query Parameters
- `limit` (int, default 50, max 500): Max results
- `offset` (int, default 0): Pagination offset
- `format` (string, optional): `html` for HTML cards, default is JSON

#### Example (JSON)
```
curl "<RENDER_URL>/dissociate/terms/amygdala/insula?limit=10"
```

#### Example (HTML)
```
curl "<RENDER_URL>/dissociate/terms/amygdala/insula?format=html"
```

#### Response (JSON)
```json
{
  "ok": true,
  "term_a": "amygdala",
  "term_b": "insula",
  "count": 2,
  "items": [
    {"study_id": "123", "title": "Amygdala Study", "journal": "Brain", "year": 2018, "weight_a": 0.57}
  ]
}
```

#### Response (HTML)
A web page with a list of study cards.

---

### 2. Dissociate by MNI Coordinates

```
GET /dissociate/locations/<x1_y1_z1>/<x2_y2_z2>
```

Returns studies that mention coordinate **A** but **not** **B**.

#### Path Parameters
- `<x1_y1_z1>`: e.g., `0_-52_26` (underscores, not commas)
- `<x2_y2_z2>`: e.g., `-2_50_-6`

#### Query Parameters
- `r` (float, default 0): Tolerance in mm. `r=0` for exact match; `r>0` for 3D tolerance.
- `limit` (int, default 50, max 500): Max results
- `offset` (int, default 0): Pagination offset
- `format` (string, optional): `html` for HTML cards, default is JSON

#### Example (JSON)
```
curl "<RENDER_URL>/dissociate/locations/0_-52_26/-2_50_-6?r=2&limit=5"
```

#### Example (HTML)
```
curl "<RENDER_URL>/dissociate/locations/0_-52_26/-2_50_-6?format=html"
```

#### Response (JSON)
```json
{
  "ok": true,
  "a": {"x": 0, "y": -52, "z": 26},
  "b": {"x": -2, "y": 50, "z": -6},
  "r": 2.0,
  "count": 1,
  "items": [
    {"study_id": "456", "title": "DMN Study", "journal": "NeuroImage", "year": 2020, "any_example_coordinate_from_a": {"x": 0, "y": -52, "z": 26}}
  ]
}
```

#### Response (HTML)
A web page with a list of study cards.

---

## Pagination & Tolerance
- Use `limit` and `offset` for paging through results.
- Use `r` (tolerance) for fuzzy coordinate matching (in mm, 3D Euclidean).

---

## Example Usage

**By terms:**
```bash
curl "<RENDER_URL>/dissociate/terms/posterior_cingulate/ventromedial_prefrontal"
curl "<RENDER_URL>/dissociate/terms/ventromedial_prefrontal/posterior_cingulate?format=html"
```

**By coordinates:**
```bash
curl "<RENDER_URL>/dissociate/locations/0_-52_26/-2_50_-6?r=1"
curl "<RENDER_URL>/dissociate/locations/-2_50_-6/0_-52_26?format=html"
```

---

## Troubleshooting
- Ensure your `DB_URL` is set and the database is accessible.
- For deployment, set the environment variable in your hosting provider's dashboard.
- For errors, check the `/test_db` endpoint: `curl <RENDER_URL>/test_db`

---

## License
MIT
