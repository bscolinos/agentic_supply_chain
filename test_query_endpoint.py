"""Test the /api/query endpoint with mock SQL execution."""
import asyncio
import httpx

async def test():
    url = "http://localhost:8000/api/query"

    questions = [
        "How many shipments are in the database?",
        "Show me all active disruptions",
    ]

    for q in questions:
        print(f"\n{'='*80}")
        print(f"Question: {q}")
        print('='*80)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    url,
                    json={"question": q},
                )

                if response.status_code == 200:
                    result = response.json()
                    print(f"\n✅ Status: {response.status_code}")
                    print(f"Session ID: {result.get('session_id')}")

                    for r in result.get('results', []):
                        if r.get('text'):
                            print(f"\nText Response:\n{r['text']}")
                        if r.get('sql', {}).get('command'):
                            print(f"\nSQL Generated:\n{r['sql']['command'][:300]}...")
                        if r.get('error'):
                            print(f"\n⚠️  Execution Error: {r['error']}")
                        if r.get('data'):
                            print(f"\nData: {r['data']['row_count']} rows returned")
                else:
                    print(f"\n❌ Status: {response.status_code}")
                    print(response.text[:500])

        except Exception as e:
            print(f"\n❌ Error: {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(test())
