from app.application.ai.googlecloud_client import GoogleCloudClient, GoogleCloudMessage
import traceback

client = GoogleCloudClient(
    api_key="",
    model="gemini-2.5-flash",
    timeout_sec=30,
    project_id="project-2bdf5ad0-a50b-4dd6-95d",
    location="asia-southeast1",
)
try:
    result = client.chat_json(
        [GoogleCloudMessage(role="user", content="hello")],
        system_instruction='Reply with JSON only: {"greeting": "hello"}',
        temperature=0.0,
        max_tokens=100,
    )
    print("SUCCESS:", result)
except Exception as e:
    traceback.print_exc()
    print("FAILED:", type(e).__name__, str(e)[:500])
