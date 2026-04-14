"""Test SingleStore Analyst API /analyst/query endpoint directly."""
import asyncio
import os
import httpx
import json
from dotenv import load_dotenv

load_dotenv()

analyst_api_base = os.getenv("ANALYST_API_URL", "").rstrip("/")
# Strip endpoint suffix
for suffix in ("/analyst/chat", "/analyst/query"):
    if analyst_api_base.endswith(suffix):
        analyst_api_base = analyst_api_base[:-len(suffix)]
        break

analyst_api_key = os.getenv("ANALYST_API_KEY", "")

async def test_analyst_query(message: str):
    """Test the /analyst/query endpoint with output_modes."""
    query_url = f"{analyst_api_base}/analyst/query"

    print(f"🔍 Testing Analyst API /analyst/query")
    print(f"   URL: {query_url}")
    print(f"   Question: {message}\n")

    payload = {
        "message": message,
        "output_modes": ["sql", "data", "text"],  # Request SQL + executed data + text
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                query_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {analyst_api_key}",
                    "Content-Type": "application/json",
                },
            )

            print(f"📊 Status: {response.status_code}")
            print(f"   Headers: {dict(response.headers)}")
            print()

            if response.status_code != 200:
                print(f"❌ Error response:")
                print(response.text)
                print()
                return

            result = response.json()
            print(f"✅ Success! Response structure:")
            print(f"   Keys: {list(result.keys())}")
            print(f"   Number of results: {len(result.get('results', []))}")
            print()

            for idx, r in enumerate(result.get("results", []), 1):
                print(f"Result {idx}:")

                if r.get("text"):
                    print(f"  📝 Text: {r['text'][:200]}...")
                    print()

                if r.get("sql"):
                    print(f"  🔧 SQL:")
                    print(f"     Command: {r['sql'].get('command', '')[:150]}...")
                    print(f"     Confidence: {r['sql'].get('confidence_score')}")
                    print(f"     Tables: {r['sql'].get('tables_used')}")
                    print()

                if r.get("data"):
                    data = r["data"]
                    print(f"  📊 Data:")
                    print(f"     Columns: {data.get('columns')}")
                    print(f"     Row count: {data.get('row_count')}")
                    if data.get("rows"):
                        print(f"     First 3 rows: {json.dumps(data['rows'][:3], indent=6)}")
                    print()

                if r.get("error"):
                    print(f"  ❌ Error: {r['error']}")
                    print()

            return result

    except httpx.TimeoutException:
        print("❌ Request timed out after 30s")
    except httpx.HTTPStatusError as exc:
        print(f"❌ HTTP Error: {exc.response.status_code}")
        print(exc.response.text)
    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

async def main():
    test_questions = [
        "How many shipments are in the database?",
        "Show me the top 5 facilities by shipment volume",
        "What is the total value at risk across all active disruptions?",
    ]

    for q in test_questions:
        result = await test_analyst_query(q)
        print("\n" + "="*80 + "\n")
        if result:
            # Test passed
            pass
        await asyncio.sleep(1)

    print("\n📋 SUMMARY:")
    print(f"   Endpoint: {analyst_api_base}/analyst/query")
    print(f"   API Key: {'✅ Set' if analyst_api_key else '❌ Missing'}")
    print(f"   Method: POST with output_modes=['sql', 'data', 'text']")

if __name__ == "__main__":
    asyncio.run(main())
