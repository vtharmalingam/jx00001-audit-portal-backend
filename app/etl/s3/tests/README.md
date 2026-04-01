## Run All Tests

$env:RUN_REAL_S3_LIFECYCLE="1"
python -m pytest app/etl/s3/tests/test_lifecycle_flow.py -q -k real_s3
Or run both fake + real in one go:

$env:RUN_REAL_S3_LIFECYCLE="1"
python -m pytest app/etl/s3/tests/test_lifecycle_flow.py -q
