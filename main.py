from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class AuditRequest(BaseModel):
    url: str
    persona: str

@app.post("/audit")
async def run_audit(request: AuditRequest, x_token: str = Header(None)):
    if x_token != os.getenv("ACCESS_TOKEN"):
        raise HTTPException(status_code=403, detail="Contraseña incorrecta")
    
    try:
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=os.getenv("GEMINI_API_KEY"))
        prompt = f"Actúa como un experto en UX especializado en el perfil: {request.persona}. Analiza la URL {request.url} y genera una auditoría heurística B2B detallada. Enfócate en la conversión y usabilidad profesional."
        response = llm.invoke(prompt)
        return {"report": response.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def home():
    return {"status": "Servidor UX Auditor Pro Activo"}
