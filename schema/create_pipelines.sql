-- NERVE: S3 Pipeline Definitions
-- Ingest shipment events and weather events from S3 in real time.
--
-- Prerequisites:
--   - S3 bucket with /shipment_events/ and /weather_events/ prefixes
--   - AWS credentials configured via LINK or env vars
--   - Tables from create_tables.sql must exist
--
-- Usage:
--   Replace <S3_BUCKET_PATH>, <S3_REGION>, <AWS_ACCESS_KEY_ID>, <AWS_SECRET_ACCESS_KEY>
--   with actual values before executing, or run via the deploy script which
--   performs envsubst.

USE nerve;

-- ---------------------------------------------------------------------------
-- Shipment Events Pipeline
-- ---------------------------------------------------------------------------

CREATE PIPELINE IF NOT EXISTS shipment_events_pipeline AS
LOAD DATA S3 '${S3_BUCKET_PATH}/shipment_events/'
CONFIG '{"region": "${S3_REGION}"}'
CREDENTIALS '{"aws_access_key_id": "${AWS_ACCESS_KEY_ID}", "aws_secret_access_key": "${AWS_SECRET_ACCESS_KEY}"}'
INTO TABLE shipment_events
FORMAT JSON (
    shipment_id <- shipment_id,
    tracking_number <- tracking_number,
    event_type <- event_type,
    facility_code <- facility_code,
    event_timestamp <- event_timestamp,
    description <- description
);

-- ---------------------------------------------------------------------------
-- Weather Events Pipeline
-- ---------------------------------------------------------------------------

CREATE PIPELINE IF NOT EXISTS weather_events_pipeline AS
LOAD DATA S3 '${S3_BUCKET_PATH}/weather_events/'
CONFIG '{"region": "${S3_REGION}"}'
CREDENTIALS '{"aws_access_key_id": "${AWS_ACCESS_KEY_ID}", "aws_secret_access_key": "${AWS_SECRET_ACCESS_KEY}"}'
INTO TABLE weather_events
FORMAT JSON (
    event_name <- event_name,
    event_type <- event_type,
    severity <- severity,
    affected_region <- affected_region,
    affected_facilities <- affected_facilities,
    latitude <- latitude,
    longitude <- longitude,
    radius_miles <- radius_miles,
    start_time <- start_time,
    end_time <- end_time,
    wind_speed_knots <- wind_speed_knots,
    precipitation_inches <- precipitation_inches,
    temperature_f <- temperature_f,
    description <- description,
    is_active <- is_active
);

-- ---------------------------------------------------------------------------
-- Start Pipelines
-- ---------------------------------------------------------------------------

START PIPELINE IF NOT RUNNING shipment_events_pipeline;
START PIPELINE IF NOT RUNNING weather_events_pipeline;
