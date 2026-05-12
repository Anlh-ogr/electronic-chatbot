from app.application.ai.googlecloud_client import GoogleCloudClient, GoogleCloudMessage

# Test pro model riêng
client = GoogleCloudClient(
    api_key="",
    model="gemini-2.5-pro",
    timeout_sec=60,
    project_id="project-2bdf5ad0-a50b-4dd6-95d",
    location="us-central1",
)
try:
    result = client.chat_json(
        [GoogleCloudMessage(role="user", content="hello")],
        system_instruction='Reply JSON only: {"ok": true}',
        temperature=0.0,
        max_tokens=50,
    )
    print("PRO SUCCESS:", result)
except Exception as e:
    import traceback
    traceback.print_exc()