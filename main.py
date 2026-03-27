from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import os, requests, base64
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import asyncio

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class AuditRequest(BaseModel):
    url: str
    persona: str

class ChatRequest(BaseModel):
    message: str
    report_context: str
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

def extract_key_pages(base_url, soup):
    base = urlparse(base_url)
    base_root = f"{base.scheme}://{base.netloc}"
    patterns = {
        'Blog': ['/blog', '/noticias', '/novedades', '/articles', '/recursos'],
        'Nosotros': ['/nosotros', '/about', '/quienes-somos', '/empresa', '/conocenos'],
        'Tienda': ['/tienda', '/shop', '/catalogo', '/productos', '/store'],
        'Categoria': ['/categoria', '/category', '/coleccion', '/collections', '/c/'],
        'Producto': ['/producto', '/product', '/p/', '/item/'],
        'Carrito o Políticas': ['/carrito', '/cart', '/checkout', '/politicas', '/devoluciones', '/envios']
    }
    found_urls = []
    seen = {base_url.rstrip('/'), base_root}
    
    if soup:
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('/'):
                full = base_root + href
            elif href.startswith('http') and base.netloc in href:
                full = href
            else:
                continue
                
            full_clean = full.split('?')[0].split('#')[0].rstrip('/')
            if full_clean in seen: continue
            
            for cat, kws in patterns.items():
                if cat not in [x[0] for x in found_urls]:
                    if any(kw in full_clean.lower() for kw in kws):
                        found_urls.append((cat, full_clean))
                        seen.add(full_clean)
                        break
    return found_urls

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

        # 1. Scrape Home
        home_soup, home_content = scrape_page(request.url)
        
        # 2. Extract specific page types
        key_pages = extract_key_pages(request.url, home_soup)
        
        all_content_parts = [f"=== PÁGINA PRINCIPAL (Home) ===\n{home_content}"]
        pages_info = [{"type": "Home", "url": request.url, "screenshot_url": None}]
        
        # Screenshot Home
        home_b64, home_ss_url = take_screenshot(request.url, access_key)
        pages_info[0]["screenshot_url"] = home_ss_url
        
        user_content = []
        if home_b64:
            user_content.append({"type":"text","text":f"CAPTURA DE HOME ({request.url}):"})
            user_content.append({"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{home_b64}","detail":"high"}})

        # Scrape and Screenshot Sub-pages
        for p_type, sub_url in key_pages:
            _, content = scrape_page(sub_url)
            ss_b64, ss_url = take_screenshot(sub_url, access_key)
            
            all_content_parts.append(f"=== {p_type.upper()} ({sub_url}) ===\n{content}")
            pages_info.append({"type": p_type, "url": sub_url, "screenshot_url": ss_url})
            
            if ss_b64:
                user_content.append({"type":"text","text":f"CAPTURA DE {p_type.upper()} ({sub_url}):"})
                user_content.append({"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{ss_b64}","detail":"high"}})

        all_content = "\n\n".join(all_content_parts)

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        user_content.append({"type":"text","text":f"""Contenido de {len(pages_info)} páginas clave extraídas:

{all_content}

---

Genera una AUDITORÍA UX B2B ULTRA-DETALLADA desde la perspectiva exclusiva del Buyer Persona: **{request.persona}**

REGLA ESTRUCTURAL DE ORO PARA LA REDACCIÓN (SECCIÓN 4):
En CADA UNO de los 5 Módulos a continuación, tu redacción DEBE incluir de forma clara los siguientes apartados:
1. **Cómo lo percibe el buyer persona**: Tu perspectiva sobre este módulo al navegar.
2. **Desglose de Puntos de Evaluación**: Es vital que a continuación evalúes, listes y comentes TODOS los PUNTOS DE VALIDACIÓN indicados para cada módulo. Explica directamente por qué le das la calificación que veré más abajo en tus notas breves de las Tarjetas Pivotales (ej. explicando por qué Identidad es profesional y por qué Diseño debe revisarse). Haz referencias cruzadas hacia las capturas de pantalla de las páginas visitadas.
3. **✅ Fortalezas**
4. **❌ Debilidades**
5. **💡 Recomendaciones**

## MÓDULO 1: Identidad Visual y Marca
Puntos de Validación a desarrollar y comentar obligatoriamente uno por uno: Identidad de Marca, Diseño Gráfico, Paleta de Colores, Tipografías.
Considera todo el sitio (Home, Nosotros, Blog, Tienda, Producto).

## MÓDULO 2: Experiencia de Usuario y Usabilidad UX/UI
Puntos de Validación a desarrollar y comentar obligatoriamente uno por uno: Navegación, Arquitectura, Facilidad de Uso.

## MÓDULO 3: Calidad y Relevancia del Contenido
Puntos de Validación a desarrollar y comentar obligatoriamente uno por uno: Calidad de Contenido, Interlinking, Lenguaje B2B.

## MÓDULO 4: Proceso de Compra y E-commerce
Puntos de Validación a desarrollar y comentar obligatoriamente uno por uno: Accesibilidad de Productos, Carrito, Checkout, Políticas.
Construye el viaje desde el home hasta la compra/producto analizando los fricciones de este flujo con las capturas de Tienda, Producto y Carrito.

## MÓDULO 5: Arquitectura y Estructura SEO
Puntos de Validación a desarrollar y comentar obligatoriamente uno por uno: Keywords Menú, Keywords Long-tail, Jerarquía.

---

Al FINAL del análisis, incluye OBLIGATORIAMENTE este bloque JSON exacto con las evaluaciones reales. Lo que escribas en las notas debe coincidir con el desarrollo profundo hecho arriba:

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
    "actual": "Resumen del estado real del sitio.",
    "expected": "Lo esperado por el buyer persona."
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
      {{"name":"Identidad de Marca","status":"cumple","note":"Evaluación corta (ej. Profesional)"}},
      {{"name":"Diseño Gráfico","status":"parcial","note":"Revisar"}},
      {{"name":"Paleta de Colores","status":"cumple","note":"Correcta"}},
      {{"name":"Tipografías","status":"parcial","note":"Legibilidad"}}
    ],
    "Exp. Usabilidad": [
      {{"name":"Navegación","status":"cumple","note":"Fluida"}},
      {{"name":"Arquitectura","status":"parcial","note":"Mejorar"}},
      {{"name":"Facilidad de Uso","status":"parcial","note":"Revisar"}}
    ],
    "Relevancia Contenido": [
      {{"name":"Calidad Contenido","status":"parcial","note":"Incompleto"}},
      {{"name":"Interlinking","status":"falla","note":"Sin links"}},
      {{"name":"Lenguaje B2B","status":"cumple","note":"Adecuado"}}
    ],
    "Proceso de Compra": [
      {{"name":"Accesibilidad","status":"falla","note":"Barrera"}},
      {{"name":"Carrito","status":"parcial","note":"Mejorar"}},
      {{"name":"Checkout","status":"falla","note":"Complejo"}},
      {{"name":"Políticas","status":"cumple","note":"Visibles"}}
    ],
    "Estructura SEO": [
      {{"name":"Keywords Menú","status":"cumple","note":"Relevantes"}},
      {{"name":"Keywords Long-tail","status":"cumple","note":"Buenas"}},
      {{"name":"Jerarquía","status":"falla","note":"Revisar"}}
    ]
  }},
  "seo_proposals": [
    {{"url":"/propuesta-1/","type":"Clúster B2B Central","color":"purple","desc":"Estrategia."}},
    {{"url":"/propuesta-2/","type":"Transaccional/Cotización","color":"red","desc":"Estrategia."}},
    {{"url":"/propuesta-3/","type":"Inbound / Informativa","color":"green","desc":"Estrategia."}}
  ],
  "action_plan": {{
    "now": ["Acción 1.", "Acción 2.", "Acción 3."],
    "next": ["Acción 1.", "Acción 2.", "Acción 3."],
    "later": ["Acción 1.", "Acción 2.", "Acción 3."]
  }}
}}
---END_JSON---
"""})

        response = client.chat.completions.create(
            model="gpt-4o",
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

@app.post("/chat")
async def run_chat(request: ChatRequest, x_token: str = Header(None)):
    if x_token != os.getenv("ACCESS_TOKEN"):
        raise HTTPException(status_code=403, detail="Token inválido")
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        system_prompt = f"""Eres el buyer persona: "{request.persona}".
Acabas de visitar una página web y estas son TUS impresiones y fricciones basadas ESTRICTAMENTE en este reporte:

=== CONTEXTO DEL REPORTE ===
{request.report_context}
=============================

REGLAS ESTRICTAS:
1. Responde SIEMPRE en primera persona como el buyer persona.
2. NUNCA inventes información que no esté en el reporte proporcionado. Si te preguntan algo fuera de este contexto, responde que no lo experimentaste o no lo recuerdas.
3. Tus respuestas deben ser hiper concretas, conversacionales y directas (no actúes como un analista UX, actúa como el cliente que tuvo problemas o le gustó algo de esa página específica).
4. No menciones "según el reporte". Háblalo como tu propia experiencia visitando la web."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role":"system","content":system_prompt},
                {"role":"user","content":request.message}
            ],
            max_completion_tokens=500
        )
        
        return {"reply": response.choices[0].message.content}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def home():
    return {"status": "UX Auditor Pro — Reporte B2B Estructurado ✅"}
