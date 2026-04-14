-- NERVE: Network Event Response & Visibility Engine
-- SingleStore Schema

CREATE DATABASE IF NOT EXISTS nerve;
USE nerve;

-- Reference data: facilities (hubs, stations, sort centers)
CREATE TABLE IF NOT EXISTS facilities (
    facility_code VARCHAR(10) PRIMARY KEY,
    facility_name VARCHAR(100) NOT NULL,
    facility_type VARCHAR(20) NOT NULL,
    city VARCHAR(100) NOT NULL,
    state VARCHAR(2) NOT NULL,
    latitude DECIMAL(9,6) NOT NULL,
    longitude DECIMAL(9,6) NOT NULL,
    capacity_packages_per_hour INT NOT NULL DEFAULT 50000,
    is_active TINYINT NOT NULL DEFAULT 1
);

-- Core entity: shipments (rowstore for point lookups + frequent updates)
CREATE TABLE IF NOT EXISTS shipments (
    shipment_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    tracking_number VARCHAR(30) NOT NULL,
    origin_facility VARCHAR(10) NOT NULL,
    destination_facility VARCHAR(10) NOT NULL,
    current_facility VARCHAR(10),
    priority VARCHAR(20) NOT NULL DEFAULT 'standard',
    status VARCHAR(20) NOT NULL DEFAULT 'created',
    sla_deadline DATETIME NOT NULL,
    estimated_arrival DATETIME,
    actual_arrival DATETIME,
    customer_id VARCHAR(20) NOT NULL,
    customer_name VARCHAR(100) NOT NULL,
    customer_email VARCHAR(100),
    package_weight_lbs DECIMAL(8,2),
    declared_value_cents BIGINT DEFAULT 0,
    risk_score DECIMAL(5,2) DEFAULT 0.00,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_tracking (tracking_number),
    KEY idx_current_facility (current_facility),
    KEY idx_status_sla (status, sla_deadline),
    KEY idx_priority_risk (priority, risk_score),
    SHARD KEY (shipment_id)
);

-- Event log: shipment scan/status events (columnstore for analytics)
CREATE TABLE IF NOT EXISTS shipment_events (
    event_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    shipment_id BIGINT NOT NULL,
    tracking_number VARCHAR(30) NOT NULL,
    event_type VARCHAR(20) NOT NULL,
    facility_code VARCHAR(10),
    event_timestamp DATETIME NOT NULL,
    description VARCHAR(255),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_shipment (shipment_id),
    KEY idx_facility_time (facility_code, event_timestamp),
    KEY idx_timestamp (event_timestamp),
    SHARD KEY (event_id),
    SORT KEY (event_timestamp)
);

-- Weather events (columnstore)
CREATE TABLE IF NOT EXISTS weather_events (
    weather_event_id BIGINT AUTO_INCREMENT,
    event_name TEXT,
    event_type VARCHAR(50),
    severity VARCHAR(20),
    affected_region VARCHAR(100),
    affected_facilities JSON,
    latitude DOUBLE,
    longitude DOUBLE,
    radius_miles INT,
    start_time DATETIME,
    end_time DATETIME,
    wind_speed_knots INT,
    precipitation_inches DOUBLE,
    temperature_f INT,
    description TEXT,
    is_active TINYINT,
    ai_operational_impact VARCHAR(64),
    ai_ops_summary TEXT,
    ingested_at DATETIME,
    PRIMARY KEY (weather_event_id),
    SORT KEY (start_time, affected_region)
);

-- Disruptions detected by the system
CREATE TABLE IF NOT EXISTS disruptions (
    disruption_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    weather_event_id BIGINT,
    disruption_type VARCHAR(20) NOT NULL DEFAULT 'weather',
    status VARCHAR(20) NOT NULL DEFAULT 'detected',
    affected_facility VARCHAR(10),
    affected_shipment_count INT NOT NULL DEFAULT 0,
    critical_shipment_count INT NOT NULL DEFAULT 0,
    estimated_delay_hours DECIMAL(4,1),
    estimated_cost_cents BIGINT DEFAULT 0,
    risk_score DECIMAL(5,2) DEFAULT 0.00,
    ai_explanation TEXT,
    detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME,
    SHARD KEY (disruption_id)
);

-- Interventions (operator actions)
CREATE TABLE IF NOT EXISTS interventions (
    intervention_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    disruption_id BIGINT NOT NULL,
    option_label VARCHAR(50) NOT NULL,
    option_description TEXT,
    action_type VARCHAR(20) NOT NULL,
    estimated_cost_cents BIGINT NOT NULL DEFAULT 0,
    estimated_savings_cents BIGINT NOT NULL DEFAULT 0,
    affected_shipment_count INT NOT NULL DEFAULT 0,
    shipments_saved_count INT NOT NULL DEFAULT 0,
    customer_notifications_count INT NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'proposed',
    selected_at DATETIME,
    completed_at DATETIME,
    selected_by VARCHAR(50) DEFAULT 'operator',
    SHARD KEY (intervention_id)
);

-- Audit trail for all system actions
CREATE TABLE IF NOT EXISTS audit_trail (
    audit_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    disruption_id BIGINT,
    intervention_id BIGINT,
    action_type VARCHAR(50) NOT NULL,
    description TEXT NOT NULL,
    metadata JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    SORT KEY (created_at)
);

-- Historical disruption embeddings for vector similarity search
CREATE TABLE IF NOT EXISTS disruption_history (
    history_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    disruption_type VARCHAR(50) NOT NULL,
    affected_facility VARCHAR(10),
    weather_type VARCHAR(50),
    severity VARCHAR(20),
    month_of_year INT,
    shipments_affected INT,
    delay_hours DECIMAL(4,1),
    resolution_action VARCHAR(50),
    cost_cents BIGINT,
    savings_cents BIGINT,
    outcome_description TEXT,
    embedding VECTOR(1536),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
