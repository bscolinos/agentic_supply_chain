"""Test SingleStore Analyst API integration directly."""
import asyncio
import os
import httpx
import json
import re
from dotenv import load_dotenv

load_dotenv()

analyst_api_url = os.getenv("ANALYST_API_URL", "").rstrip("/")
for suffix in ("/analyst/chat", "/analyst/query"):
    if analyst_api_url.endswith(suffix):
        analyst_api_url = analyst_api_url[:-len(suffix)]
        break

analyst_api_key = os.getenv("ANALYST_API_KEY", "")

async def test_analyst_chat(message: str):
    """Test the /analyst/chat endpoint."""
    chat_url = f"{analyst_api_url}/analyst/chat"

    print(f"🔍 Testing Analyst API")
    print(f"   URL: {chat_url}")
    print(f"   Question: {message}\n")

    payload = {"message": message}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                chat_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {analyst_api_key}",
                    "Content-Type": "application/json",
                },
            )

            print(f"✅ Status: {response.status_code}")
            print(f"   Response length: {len(response.text)} bytes\n")

            if response.status_code != 200:
                print(f"❌ Error response:")
                print(response.text[:500])
                return

            # Parse SSE stream
            session_id = None
            completed = {}

            for line in response.text.splitlines():
                if not line.startswith("data: "):
                    continue
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue

                event_type = data.get("type", "")
                if event_type == "response.created":
                    session_id = data.get("response", {}).get("session_id")
                    print(f"📝 Session ID: {session_id}")
                elif event_type == "response.completed":
                    completed = data.get("response", {})

            if not completed:
                print("❌ No completed response found in SSE stream")
                print("\nRaw response (first 1000 chars):")
                print(response.text[:1000])
                return

            # Extract SQL and text
            sql_command = None
            text_response = None

            for item in completed.get("output", []):
                if item.get("type") == "thinking":
                    for part in item.get("content", []):
                        if part.get("error"):
                            print(f"⚠️  Thinking error: {part.get('error')}")
                            continue
                        raw = part.get("text", "")
                        blocks = re.findall(r"```sql\s*(.*?)\s*```", raw, re.DOTALL)
                        if blocks:
                            sql_command = blocks[-1].strip()

                elif item.get("type") == "message":
                    for part in item.get("content", []):
                        if part.get("type") == "output_text":
                            text_response = part.get("text")

            print("\n📊 Results:")
            if text_response:
                print(f"   Text: {text_response}")
            if sql_command:
                print(f"\n   SQL Generated:")
                print(f"   {sql_command[:200]}{'...' if len(sql_command) > 200 else ''}")

            if not sql_command and not text_response:
                print("   ⚠️  No SQL or text response extracted")
                print("\n   Completed output structure:")
                print(f"   {json.dumps(completed.get('output', [])[:2], indent=2)[:500]}")

    except httpx.TimeoutException:
        print("❌ Request timed out")
    except httpx.HTTPStatusError as exc:
        print(f"❌ HTTP Error: {exc.response.status_code}")
        print(exc.response.text[:500])
    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")

async def main():
    test_questions = [
        "How many shipments are in the database?",
        "Show me all active disruptions",
        "What is the total value at risk?",
    ]

    for q in test_questions:
        await test_analyst_chat(q)
        print("\n" + "="*80 + "\n")
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
