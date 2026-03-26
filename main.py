from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import os, requests
from bs4 import BeautifulSoup

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

def scrape_website(url: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
        r = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        for tag in soup(["script","style","noscript"]): tag.decompose()
        title = soup.title.string if soup.title else "Sin título"
        headings = [h.get_text(strip=True) for h in soup.find_all(['h1','h2','h3'])][:15]
        links = [a.get_text(strip=True) for a in soup.find_all('a') if a.get_text(strip=True)][:40]
        body = soup.get_text(separator='\n', strip=True)[:3500]
        return f"TÍTULO: {title}\n\nENCEBEZADOS:\n{chr(10).join(headings)}\n\nNAVEGACIÓN:\n{chr(10).join(links)}\n\nCONTENIDO:\n{body}"
    except Exception as e:
        return f"[No se pudo acceder al sitio: {e}. Usa conocimiento propio.]"

@app.post("/audit")
async def run_audit(request: AuditRequest, x_token: str = Header(None)):
    if x_token != os.getenv("ACCESS_TOKEN"):
        raise HTTPException(status_code=403, detail="Token inválido")
    try:
        site_content = scrape_website(request.url)
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model="gpt-5.4-nano",
            messages=[
                {"role": "system", "content": f"Eres un experto en UX y usabilidad B2B. Analizas sitios web desde la perspectiva del perfil: {request.persona}. Siempre respondes en español con formato Markdown."},
                {"role": "user", "content": f"Analiza este sitio web: {request.url}\n\nContenido real extraído:\n{site_content}\n\nGenera una auditoría heurística B2B completa basada en las 10 Heurísticas de Nielsen. Para cada heurística incluye: ✅ qué hace bien, ❌ qué falla, y 💡 recomendación específica."}
            ],
            max_completion_tokens
        )
        return {"report": response.choices[0].message.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def home():
    return {"status": "UX Auditor Pro con OpenAI - Activo ✅"}
