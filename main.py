from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI
import os
import requests
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
    """Entra a la web real y extrae su contenido de texto."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Eliminar scripts y estilos que ensucian el texto
        for tag in soup(["script", "style", "noscript", "meta", "link"]):
            tag.decompose()
        
        # Extraer textos importantes
        title = soup.title.string if soup.title else "Sin título"
        
        # Extraer encabezados
        headings = [h.get_text(strip=True) for h in soup.find_all(['h1','h2','h3']) if h.get_text(strip=True)]
        
        # Extraer textos de navegación
        nav_texts = [a.get_text(strip=True) for a in soup.find_all('a') if a.get_text(strip=True)][:50]
        
        # Extraer texto general (limitado para no exceder tokens)
        body_text = soup.get_text(separator='\n', strip=True)
        # Limitar a 4000 caracteres para no saturar la IA
        body_text = body_text[:4000]
        
        return f"""
=== TÍTULO DE LA PÁGINA ===
{title}

=== ENCABEZADOS ENCONTRADOS ===
{chr(10).join(headings[:20])}

=== ENLACES DE NAVEGACIÓN ===
{chr(10).join(nav_texts[:30])}

=== CONTENIDO GENERAL (primeros 4000 caracteres) ===
{body_text}
        """
    except Exception as e:
        return f"[ADVERTENCIA: No se pudo acceder al sitio directamente. Error: {str(e)}. Gemini analizará con su conocimiento propio.]"

@app.post("/audit")
async def run_audit(request: AuditRequest, x_token: str = Header(None)):
    if x_token != os.getenv("ACCESS_TOKEN"):
        raise HTTPException(status_code=403, detail="Contraseña incorrecta")
    
    try:
        # 1. Scraping REAL de la web
        site_content = scrape_website(request.url)
        
        # 2. Mandar contenido REAL a Gemini
        llm = ChatGoogleGenerativeAI(
            model="gemini-3.1-flash-lite-preview",
            google_api_key=os.getenv("GEMINI_API_KEY")
        )
        
        prompt = f"""Eres un experto en UX y experiencia B2B. 
Debes analizar el siguiente contenido REAL extraído del sitio web: {request.url}
Perfil del usuario evaluador: {request.persona}

CONTENIDO REAL DEL SITIO:
{site_content}

Con base en este contenido real, genera una auditoría heurística B2B completa usando las 10 Heurísticas de Nielsen adaptadas al perfil de {request.persona}.

Para cada heurística incluye:
- ✅ Qué hace bien el sitio (basado en lo que encontraste)
- ❌ Qué falla o falta (basado en el contenido real)
- 💡 Recomendación específica y accionable

Sé muy específico citando elementos reales que encontraste en el sitio."""

        response = llm.invoke(prompt)
        return {"report": response.content}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def home():
    return {"status": "UX Auditor Pro con Scraping Real - Activo ✅"}
