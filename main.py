from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import os, requests, base64
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
    """Extrae el texto real de la web."""
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

def take_screenshot(url: str) -> str | None:
    """Toma una captura de pantalla real de la web y la devuelve en base64."""
    try:
        access_key = os.getenv("SCREENSHOTONE_KEY")
        if not access_key:
            return None
        
        screenshot_url = (
            f"https://api.screenshotone.com/take"
            f"?access_key={access_key}"
            f"&url={url}"
            f"&format=jpg"
            f"&viewport_width=1280"
            f"&viewport_height=900"
            f"&full_page=false"
            f"&image_quality=80"
        )
        
        response = requests.get(screenshot_url, timeout=30)
        if response.status_code == 200:
            # Convertir imagen a base64 para mandársela a GPT-5.4-mini
            image_base64 = base64.b64encode(response.content).decode('utf-8')
            return image_base64
        return None
    except Exception as e:
        print(f"Error en screenshot: {e}")
        return None

@app.post("/audit")
async def run_audit(request: AuditRequest, x_token: str = Header(None)):
    if x_token != os.getenv("ACCESS_TOKEN"):
        raise HTTPException(status_code=403, detail="Token inválido")
    
    try:
        # 1. Scraping de texto real
        site_content = scrape_website(request.url)
        
        # 2. Captura de pantalla real
        screenshot_b64 = take_screenshot(request.url)
        
        # 3. Preparar mensaje para GPT-5.4-mini (con visión)
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        system_msg = f"""Eres un experto en UX y usabilidad B2B.
Analizas sitios web desde la perspectiva del perfil: {request.persona}.
Tienes acceso tanto al contenido textual extraído como a una captura de pantalla real del sitio.
Siempre respondes en español con formato Markdown detallado."""

        user_content = []
        
        # Agregar imagen si está disponible
        if screenshot_b64:
            user_content.append({
                "type": "text",
                "text": f"Aquí tienes una captura de pantalla REAL y actual del sitio {request.url}. Analízala visualmente:"
            })
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{screenshot_b64}",
                    "detail": "high"
                }
            })
        
        user_content.append({
            "type": "text",
            "text": f"""Contenido de texto extraído del sitio:
{site_content}

Genera una auditoría heurística B2B completa basada en las 10 Heurísticas de Nielsen para el perfil de {request.persona}.

Para cada heurística incluye:
- ✅ **Qué hace bien** (con ejemplos visuales específicos si aplica)
- ❌ **Qué falla** (con referencias a elementos visuales reales)
- 💡 **Recomendación específica y accionable**

Al final, incluye una sección de **Puntuación General** del 1 al 10 por cada criterio."""
        })
        
        response = client.chat.completions.create(
            model="gpt-5.4-mini",  # gpt-5.4-mini tiene visión incluida
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_content}
            ],
            max_completion_tokens=3000
        )
        
        screenshot_note = "📸 *Análisis basado en captura de pantalla real + texto extraído*" if screenshot_b64 else "📝 *Análisis basado en texto extraído (screenshot no disponible)*"
        
        return {"report": screenshot_note + "\n\n" + response.choices[0].message.content}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def home():
    return {"status": "UX Auditor Pro con Visión Real - Activo ✅"}
