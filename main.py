from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import os, requests, base64
from bs4 import BeautifulSoup

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class AuditRequest(BaseModel):
    url: str
    persona: str

def scrape_website(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
        r = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        for tag in soup(["script","style","noscript"]): tag.decompose()
        title = soup.title.string if soup.title else "Sin título"
        headings = [h.get_text(strip=True) for h in soup.find_all(['h1','h2','h3'])][:15]
        links = [a.get_text(strip=True) for a in soup.find_all('a') if a.get_text(strip=True)][:40]
        body = soup.get_text(separator='\n', strip=True)[:3000]
        return f"TÍTULO: {title}\n\nENCEBEZADOS:\n{chr(10).join(headings)}\n\nNAVEGACIÓN:\n{chr(10).join(links)}\n\nCONTENIDO:\n{body}"
    except Exception as e:
        return f"[No se pudo acceder al sitio: {e}]"

def take_screenshot(url):
    try:
        access_key = os.getenv("SCREENSHOTONE_KEY")
        if not access_key: return None, None
        params = f"?access_key={access_key}&url={url}&format=jpg&viewport_width=1024&viewport_height=768&full_page=false&image_quality=60"
        screenshot_url = f"https://api.screenshotone.com/take{params}"
        r = requests.get(screenshot_url, timeout=30)
        if r.status_code == 200:
            return base64.b64encode(r.content).decode('utf-8'), screenshot_url
        return None, None
    except Exception as e:
        return None, None

@app.post("/audit")
async def run_audit(request: AuditRequest, x_token: str = Header(None)):
    if x_token != os.getenv("ACCESS_TOKEN"):
        raise HTTPException(status_code=403, detail="Token inválido")
    try:
        site_content = scrape_website(request.url)
        screenshot_b64, screenshot_url = take_screenshot(request.url)

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        user_content = []
        if screenshot_b64:
            user_content.append({"type":"text","text":f"Captura de pantalla REAL del sitio {request.url}:"})
            user_content.append({"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{screenshot_b64}","detail":"high"}})

        user_content.append({"type":"text","text":f"""Contenido extraído del sitio:
{site_content}

Genera una auditoría heurística B2B completa de {request.url} para el perfil: {request.persona}.

Analiza las 10 Heurísticas de Nielsen. Para cada una incluye:
- ✅ **Qué hace bien** (con ejemplos específicos del sitio)
- ❌ **Qué falla** (con referencias a elementos reales vistos)
- 💡 **Recomendación específica y accionable**

Al final de toda tu respuesta, añade EXACTAMENTE este bloque (con puntuaciones reales del 1 al 10):
---SCORES---
{{"Visibilidad": 7, "Control Usuario": 6, "Consistencia": 7, "Prevención Errores": 5, "Reconocimiento": 6, "Flexibilidad": 5, "Estética": 7, "Diagnóstico Errores": 5, "Ayuda": 4, "Global": 5.8}}

(Reemplaza los números con las puntuaciones reales que asignes según tu análisis)"""})

        response = client.chat.completions.create(
            model="gpt-5.4-nano",
            messages=[
                {"role":"system","content":f"Eres un experto en UX y usabilidad B2B. Analizas sitios web desde la perspectiva del perfil: {request.persona}. Respondes en español con formato Markdown."},
                {"role":"user","content":user_content}
            ],
            max_completion_tokens=4000
        )

        return {
            "report": response.choices[0].message.content,
            "screenshot_url": screenshot_url
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def home():
    return {"status": "UX Auditor Pro Visual - Activo ✅"}
