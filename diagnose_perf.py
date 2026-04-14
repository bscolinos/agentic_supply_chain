#!/usr/bin/env python3
"""
Performance diagnostic script for NERVE database.
"""

import os
import sys
import time
from dotenv import load_dotenv
import singlestoredb as s2

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("SINGLESTORE_HOST", "127.0.0.1"),
    "port": int(os.getenv("SINGLESTORE_PORT", "3306")),
    "user": os.getenv("SINGLESTORE_USER", "root"),
    "password": os.getenv("SINGLESTORE_PASSWORD", "password"),
    "database": os.getenv("SINGLESTORE_DATABASE", "nerve"),
}

def run_query(conn, sql, params=None):
    """Run a query and return results with timing."""
    start = time.perf_counter()
    cur = conn.cursor()
    cur.execute(sql, params or ())
    rows = cur.fetchall()
    elapsed = (time.perf_counter() - start) * 1000
    return rows, elapsed

def main():
    print("=" * 80)
    print("NERVE Performance Diagnostic")
    print("=" * 80)

    conn = s2.connect(**DB_CONFIG)

    # 1. Table sizes
    print("\n1. Table sizes:")
    rows, ms = run_query(conn, """
        SELECT TABLE_NAME, TABLE_ROWS,
               ROUND((DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024, 2) AS Size_MB
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = 'nerve'
        ORDER BY (DATA_LENGTH + INDEX_LENGTH) DESC
    """)
    for row in rows:
        print(f"  {row[0]:30s} {row[1]:>10,} rows  {row[2]:>8.2f} MB")
    print(f"  Query time: {ms:.1f}ms")

    # 2. Audit trail count
    print("\n2. Audit trail entries:")
    rows, ms = run_query(conn, "SELECT COUNT(*) FROM audit_trail")
    print(f"  Total: {rows[0][0]:,} entries  (Query time: {ms:.1f}ms)")

    # 3. Interventions by status
    print("\n3. Interventions by status:")
    rows, ms = run_query(conn, """
        SELECT status, COUNT(*) AS cnt
        FROM interventions
        GROUP BY status
        ORDER BY cnt DESC
    """)
    for row in rows:
        print(f"  {row[0]:20s} {row[1]:>10,}")
    print(f"  Query time: {ms:.1f}ms")

    # 4. Disruptions by status
    print("\n4. Disruptions by status:")
    rows, ms = run_query(conn, """
        SELECT status, COUNT(*) AS cnt
        FROM disruptions
        GROUP BY status
        ORDER BY cnt DESC
    """)
    for row in rows:
        print(f"  {row[0]:20s} {row[1]:>10,}")
    print(f"  Query time: {ms:.1f}ms")

    # 5. Shipment events count
    print("\n5. Shipment events:")
    rows, ms = run_query(conn, """
        SELECT event_type, COUNT(*) AS cnt
        FROM shipment_events
        GROUP BY event_type
        ORDER BY cnt DESC
    """)
    for row in rows:
        print(f"  {row[0]:20s} {row[1]:>10,}")
    print(f"  Query time: {ms:.1f}ms")

    # 6. Check indexes on key tables
    print("\n6. Indexes on audit_trail:")
    rows, ms = run_query(conn, "SHOW INDEX FROM audit_trail")
    for row in rows:
        print(f"  Key: {row[2]:30s} Column: {row[4]}")
    print(f"  Query time: {ms:.1f}ms")

    print("\n7. Indexes on interventions:")
    rows, ms = run_query(conn, "SHOW INDEX FROM interventions")
    for row in rows:
        print(f"  Key: {row[2]:30s} Column: {row[4]}")
    print(f"  Query time: {ms:.1f}ms")

    print("\n8. Indexes on disruptions:")
    rows, ms = run_query(conn, "SHOW INDEX FROM disruptions")
    for row in rows:
        print(f"  Key: {row[2]:30s} Column: {row[4]}")
    print(f"  Query time: {ms:.1f}ms")

    # 9. Test the most expensive query (completed interventions with response time)
    print("\n9. Testing expensive query pattern (get_savings_report):")
    rows, ms = run_query(conn, """
        SELECT i.intervention_id, i.disruption_id, d.detected_at, i.completed_at,
               TIMESTAMPDIFF(SECOND, d.detected_at, i.completed_at) AS response_seconds
        FROM interventions i
        JOIN disruptions d ON i.disruption_id = d.disruption_id
        WHERE i.status = 'completed'
        ORDER BY i.intervention_id DESC
        LIMIT 10
    """)
    print(f"  Found {len(rows)} completed interventions")
    for row in rows:
        resp_seconds = row[4] if row[4] is not None else 0
        print(f"    Intervention #{row[0]:5d}  Disruption #{row[1]:5d}  Response time: {resp_seconds:>8,}s")
    print(f"  Query time: {ms:.1f}ms")

    # 10. Check for missing indexes
    print("\n10. Testing slow query patterns:")

    # Test audit trail query without index on disruption_id
    print("  a) Audit trail by disruption_id:")
    rows, ms = run_query(conn, """
        SELECT COUNT(*)
        FROM audit_trail
        WHERE disruption_id = 1
    """)
    print(f"     Query time: {ms:.1f}ms")

    # Test intervention query without index on disruption_id
    print("  b) Interventions by disruption_id:")
    rows, ms = run_query(conn, """
        SELECT COUNT(*)
        FROM interventions
        WHERE disruption_id = 1
    """)
    print(f"     Query time: {ms:.1f}ms")

    # Test shipment_events by shipment_id
    print("  c) Shipment events by shipment_id:")
    rows, ms = run_query(conn, """
        SELECT COUNT(*)
        FROM shipment_events
        WHERE shipment_id = 1
    """)
    print(f"     Query time: {ms:.1f}ms")

    # 11. Check if there are crazy response times
    print("\n11. Checking for extreme response times:")
    rows, ms = run_query(conn, """
        SELECT MIN(TIMESTAMPDIFF(SECOND, d.detected_at, i.completed_at)) AS min_seconds,
               MAX(TIMESTAMPDIFF(SECOND, d.detected_at, i.completed_at)) AS max_seconds,
               AVG(TIMESTAMPDIFF(SECOND, d.detected_at, i.completed_at)) AS avg_seconds
        FROM interventions i
        JOIN disruptions d ON i.disruption_id = d.disruption_id
        WHERE i.status = 'completed'
    """)
    if rows:
        min_s, max_s, avg_s = rows[0]
        print(f"  Min: {min_s:>10,}s")
        print(f"  Max: {max_s:>10,}s")
        print(f"  Avg: {avg_s:>10.1f}s")
    print(f"  Query time: {ms:.1f}ms")

    conn.close()
    print("\n" + "=" * 80)
    print("Diagnostic complete")
    print("=" * 80)

if __name__ == "__main__":
    main()
