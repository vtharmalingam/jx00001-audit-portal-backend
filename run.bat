uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload


@REM Seed Data
python -m app.etl.s3.scripts.seed_synthetic_bucket --bucket audit-system-data-dev   
python -m app.etl.s3.scripts.seed_synthetic_bucket --firm-demo