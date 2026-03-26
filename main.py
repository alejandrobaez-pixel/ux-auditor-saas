from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import os, requests, base64
from bs4 import BeautifulSoup
from urllib.parse import urlparse

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class AuditRequest(BaseModel):
    url: str
    persona: str

def scrape_page(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
        r = requests.get(url, headers=headers, timeout=12)
        soup = BeautifulSoup(r.text, 'html.parser')
        for tag in soup(["script","style","noscript"]): tag.decompose()
        title = soup.title.string.strip() if soup.title else "Sin título"
        headings = [h.get_text(strip=True) for h in soup.find_all(['h1','h2','h3'])][:12]
        links = [a.get_text(strip=True) for a in soup.find_all('a') if a.get_text(strip=True)][:30]
        body = soup.get_text(separator='\n', strip=True)[:2500]
        return soup, f"URL: {url}\nTÍTULO: {title}\nENCEBEZADOS:\n{chr(10).join(headings)}\nNAVEGACIÓN:\n{chr(10).join(links)}\nCONTENIDO:\n{body}"
    except Exception as e:
        return None, f"[Error accediendo a {url}: {e}]"

def extract_menu_links(base_url, soup, max_links=3):
    if not soup: return []
    base = urlparse(base_url)
    base_root = f"{base.scheme}://{base.netloc}"
    found = set()
    priority_kw = ['producto','product','tienda','shop','nosotros','about','contacto',
                   'contact','blog','catalogo','catalog','servicio','service','categoria','category']
    for a in soup.find_all('a', href=True):
        href = a['href']
        if href.startswith('/'):
            full = base_root + href
        elif href.startswith('http') and base.netloc in href:
            full = href
        else:
            continue
        full = full.split('?')[0].split('#')[0].rstrip('/')
        if full == base_url.rstrip('/') or full == base_root: continue
        if any(kw in full.lower() for kw in priority_kw):
            found.add(full)
        if len(found) >= max_links * 2: break
    return list(found)[:max_links]

def take_screenshot(url, access_key):
    try:
        if not access_key: return None, None
        encoded_url = requests.utils.quote(url, safe='')
        params = f"?access_key={access_key}&url={encoded_url}&format=jpg&viewport_width=1280&viewport_height=800&full_page=true&image_quality=65"
        screenshot_url = f"https://api.screenshotone.com/take{params}"
        r = requests.get(screenshot_url, timeout=25)
        if r.status_code == 200:
            return base64.b64encode(r.content).decode('utf-8'), screenshot_url
        return None, None
    except:
        return None, None

@app.post("/audit")
async def run_audit(request: AuditRequest, x_token: str = Header(None)):
    if x_token != os.getenv("ACCESS_TOKEN"):
        raise HTTPException(status_code=403, detail="Token inválido")
    try:
        access_key = os.getenv("SCREENSHOTONE_KEY", "")

        home_soup, home_content = scrape_page(request.url)
        sub_urls = extract_menu_links(request.url, home_soup, max_links=3)

        all_content_parts = [f"=== PÁGINA PRINCIPAL ===\n{home_content}"]
        pages_info = [{"url": request.url, "screenshot_url": None}]

        for sub_url in sub_urls:
            _, content = scrape_page(sub_url)
            all_content_parts.append(f"=== SUBPÁGINA: {sub_url} ===\n{content}")
            pages_info.append({"url": sub_url, "screenshot_url": None})

        all_content = "\n\n".join(all_content_parts)

        home_b64, home_ss_url = take_screenshot(request.url, access_key)
        pages_info[0]["screenshot_url"] = home_ss_url

        for idx, sub_url in enumerate(sub_urls[:2]):
            _, ss_url = take_screenshot(sub_url, access_key)
            if idx + 1 < len(pages_info):
                pages_info[idx + 1]["screenshot_url"] = ss_url

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        user_content = []

        if home_b64:
            user_content.append({"type":"text","text":f"CAPTURA REAL de la página principal ({request.url}):"})
            user_content.append({"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{home_b64}","detail":"high"}})

        user_content.append({"type":"text","text":f"""Contenido extraído de {len(pages_info)} páginas del sitio:

{all_content}

---

Genera una AUDITORÍA UX B2B ULTRA-DETALLADA desde la perspectiva exclusiva del Buyer Persona: **{request.persona}**

## MÓDULO 1: Identidad Visual y Marca
Evalúa cómo percibe el Buyer Persona:
- **Identidad de Marca**: Logos, tono (¿B2B o B2C?), voz de marca
- **Diseño Gráfico**: Disposición, espacios, estilo de fotografía
- **Paleta de Colores**: Primarios/secundarios (hex si posible), contraste, impacto psicológico
- **Tipografías**: Familia, jerarquía, legibilidad para el perfil
✅ Fortalezas ❌ Debilidades 💡 Recomendaciones

## MÓDULO 2: Experiencia de Usuario y Usabilidad UX/UI
- **Navegación y Arquitectura**: Facilidad para el perfil de encontrar lo que busca
- **Facilidad de Uso**: CTAs, formularios, fluidez
- **Coherencia Heurística**: Visibilidad, prevención de errores, control
✅ Fortalezas ❌ Debilidades 💡 Recomendaciones

## MÓDULO 3: Calidad y Relevancia del Contenido
- **Calidad del Contenido**: Profundidad, valor para el perfil
- **Interlinking y Semántica**: Clústeres, navegación entre contenidos
- **Lenguaje y Tono B2B**: ¿El contenido habla al perfil?
✅ Fortalezas ❌ Debilidades 💡 Recomendaciones

## MÓDULO 4: Proceso de Compra y E-commerce
- **Accesibilidad de Productos**: Clics para llegar al producto
- **Carrito / Cotizador**: Facilidad de compra B2B
- **Proceso de Checkout**: Rapidez, registro, métodos pago
- **Políticas Logísticas**: Transparencia de envíos y devoluciones
✅ Fortalezas ❌ Debilidades 💡 Recomendaciones

## MÓDULO 5: Arquitectura y Estructura SEO
- **Keywords del Menú**: Palabras clave en navegación
- **Keywords Long-tail**: Cobertura de búsquedas específicas del perfil
- **Jerarquía y Sitemap**: Estructura de URLs, profundidad
✅ Fortalezas ❌ Debilidades 💡 Recomendaciones

---

Al FINAL de todo el análisis, incluye OBLIGATORIAMENTE este bloque JSON con tus evaluaciones reales:

---JSON_DATA---
{{
  "scores": {{
    "Identidad Visual": 6,
    "UX Usabilidad": 5,
    "Contenido": 5,
    "Proceso Compra": 4,
    "SEO": 5
  }},
  "gap": {{
    "actual": "Descripción concisa del estado real del sitio (1-2 oraciones con hallazgos clave).",
    "expected": "Lo que el buyer persona espera encontrar en este tipo de sitio (1-2 oraciones)."
  }},
  "matrix": {{
    "Identidad Visual": {{"base":4,"cumple":2,"parcial":1,"falla":1}},
    "Exp. Usabilidad": {{"base":3,"cumple":2,"parcial":1,"falla":0}},
    "Relevancia Contenido": {{"base":3,"cumple":1,"parcial":1,"falla":1}},
    "Proceso de Compra": {{"base":4,"cumple":1,"parcial":1,"falla":2}},
    "Estructura SEO": {{"base":3,"cumple":2,"parcial":0,"falla":1}}
  }},
  "criteria_status": {{
    "Identidad Visual": [
      {{"name":"Identidad de Marca","status":"cumple","note":"Descripción breve"}},
      {{"name":"Diseño Gráfico","status":"parcial","note":"Descripción breve"}},
      {{"name":"Paleta de Colores","status":"cumple","note":"Descripción breve"}},
      {{"name":"Tipografías","status":"parcial","note":"Descripción breve"}}
    ],
    "Exp. Usabilidad": [
      {{"name":"Navegación","status":"cumple","note":"Descripción breve"}},
      {{"name":"Arquitectura","status":"parcial","note":"Descripción breve"}},
      {{"name":"Facilidad de Uso","status":"parcial","note":"Descripción breve"}}
    ],
    "Relevancia Contenido": [
      {{"name":"Calidad de contenido","status":"parcial","note":"Descripción breve"}},
      {{"name":"Interlinking","status":"falla","note":"Descripción breve"}},
      {{"name":"Lenguaje B2B","status":"cumple","note":"Descripción breve"}}
    ],
    "Proceso de Compra": [
      {{"name":"Accesibilidad","status":"falla","note":"Descripción breve"}},
      {{"name":"Carrito","status":"parcial","note":"Descripción breve"}},
      {{"name":"Checkout","status":"falla","note":"Descripción breve"}},
      {{"name":"Políticas","status":"cumple","note":"Descripción breve"}}
    ],
    "Estructura SEO": [
      {{"name":"Keywords Menú","status":"cumple","note":"Descripción breve"}},
      {{"name":"Keywords Long-tail","status":"cumple","note":"Descripción breve"}},
      {{"name":"Jerarquía","status":"falla","note":"Descripción breve"}}
    ]
  }},
  "seo_proposals": [
    {{"url":"/propuesta-url-b2b/","type":"Clúster B2B Central","color":"purple","desc":"Descripción estratégica de la página propuesta."}},
    {{"url":"/propuesta-url-transaccional/","type":"Transaccional/Cotización","color":"red","desc":"Descripción estratégica."}},
    {{"url":"/propuesta-url-inbound/","type":"Inbound / Informativa","color":"green","desc":"Descripción estratégica."}}
  ],
  "action_plan": {{
    "now": [
      "Acción inmediata 1 (0-30 días, alto impacto, bajo costo).",
      "Acción inmediata 2.",
      "Acción inmediata 3."
    ],
    "next": [
      "Mejora estructural 1 (30-90 días).",
      "Mejora estructural 2.",
      "Mejora estructural 3."
    ],
    "later": [
      "Inversión estratégica 1 (90+ días, SEO).",
      "Inversión estratégica 2.",
      "Inversión estratégica 3."
    ]
  }}
}}
---END_JSON---

IMPORTANTE: Sustituye TODOS los valores del JSON con los datos reales del análisis. El JSON debe estar completo y válido."""})

        response = client.chat.completions.create(
            model="gpt-5.4-nano",
            messages=[
                {"role":"system","content":f"Eres un experto en UX y marketing B2B. Analizas sitios exclusivamente desde la perspectiva del Buyer Persona: {request.persona}. Respondes en español con Markdown profesional. Al final SIEMPRE incluyes el bloque JSON estructurado exactamente como se solicita."},
                {"role":"user","content":user_content}
            ],
            max_completion_tokens=6000
        )

        return {
            "report": response.choices[0].message.content,
            "pages": pages_info,
            "pages_analyzed": len(pages_info),
            "screenshot_url": home_ss_url
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def home():
    return {"status": "UX Auditor Pro — Reporte B2B Estructurado ✅"}
