import vertexai
from vertexai.generative_models import GenerativeModel

# SDK will try to use Application Default Credentials (ADC)
vertexai.init(project="project-2bdf5ad0-a50b-4dd6-95d", location="asia-southeast1")

model = GenerativeModel("gemini-1.5-flash")

try:
    response = model.generate_content("Kiem tra ket noi Vertex AI")
    print("Ket noi thanh cong! Gemini tra loi:", response.text)
except Exception as e:
    print("Loi xac thuc hoac cau hinh:", e)
