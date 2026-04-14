#!/usr/bin/env python3
from api.services.db import Database
from api.services.intervention import generate_options, auto_select_best_option
import traceback

db = Database()
db.connect()

# Get first unhandled disruption
rows, _ = db.execute_query('''
    SELECT d.disruption_id
    FROM disruptions d
    WHERE d.status = "detected"
      AND NOT EXISTS (SELECT 1 FROM interventions i WHERE i.disruption_id = d.disruption_id)
    LIMIT 1
''')

if rows:
    disruption_id = rows[0]['disruption_id']
    print(f'Testing intervention generation for disruption #{disruption_id}...')

    try:
        options = generate_options(db, disruption_id)
        print(f'  ✓ Generated {len(options)} options')

        best = auto_select_best_option(options)
        if best:
            print(f'  ✓ Auto-selected: {best["option_label"]} (savings: ${best["estimated_savings_cents"]/100:.2f})')
        else:
            print('  ✗ No best option found')
    except Exception as e:
        print(f'  ✗ Error: {e}')
        traceback.print_exc()
else:
    print('No unhandled disruptions found')

db.close()
