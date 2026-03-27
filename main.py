from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import os, base64, asyncio
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from playwright.async_api import async_playwright

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class AuditRequest(BaseModel):
    url: str
    persona: str

class ChatRequest(BaseModel):
    message: str
    report_context: str
    persona: str

async def scrape_and_screenshot(page, url):
    """
    Usa el motor Chromium de Playwright abierto para extraer el HTML renderizado 
    por Javascript y simultáneamente tomar la foto HQ en Base64. 
    """
    try:
        # Ir a la página y esperar que el DOM se cargue.
        await page.goto(url, timeout=25000, wait_until="domcontentloaded")
        await asyncio.sleep(1)
        
        # 1. Extracción de Contenido
        html_content = await page.content()
        soup = BeautifulSoup(html_content, 'html.parser')
        
        for tag in soup(["script", "style", "noscript"]): tag.decompose()
        title = soup.title.string.strip() if soup.title else "Sin título"
        headings = [h.get_text(strip=True) for h in soup.find_all(['h1','h2','h3'])][:12]
        links = [a.get_text(strip=True) for a in soup.find_all('a') if a.get_text(strip=True)][:30]
        body = soup.get_text(separator='\n', strip=True)[:2500]
        
        content_text = f"URL: {url}\nTÍTULO: {title}\nENCEBEZADOS:\n{chr(10).join(headings)}\nNAVEGACIÓN:\n{chr(10).join(links)}\nCONTENIDO:\n{body}"
        
        # 2. Captura solo del VIEWPORT (mucho más liviana en RAM que full_page)
        ss_bytes = await page.screenshot(full_page=False, type="jpeg", quality=50)
        ss_b64 = base64.b64encode(ss_bytes).decode('utf-8')
        
        return soup, content_text, ss_b64
    except Exception as e:
        print(f"[ERROR scrape_and_screenshot] {url}: {e}")
        return None, f"[Error extrayendo datos de {url}: {e}]", None

def extract_key_pages(base_url, soup):
    base = urlparse(base_url)
    base_root = f"{base.scheme}://{base.netloc}"
    patterns = {
        'Blog o Novedades': ['/blog', '/noticias', '/novedades', '/articles', '/recursos', '/recetas', '/recetario'],
        'Nosotros': ['/nosotros', '/about', '/quienes-somos', '/empresa', '/conocenos', '/historia', '/equipo'],
        'Tienda': ['/tienda', '/shop', '/catalogo', '/productos', '/store', '/productos-chantilly'],
        'Categoria': ['/categoria', '/category', '/coleccion', '/collections', '/c/', '/toppings', '/cremas', '/ganashes', '/harinas'],
        'Producto': ['/producto', '/product', '/p/', '/item/', '/crema-batida', '/top-cream', '/chanty-wip'],
        'Políticas o Privacidad': ['/carrito', '/cart', '/checkout', '/politicas', '/politica', '/devoluciones', '/envios', '/privacidad']
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

@app.post("/audit")
async def run_audit(request: AuditRequest, x_token: str = Header(None)):
    if x_token != os.getenv("ACCESS_TOKEN"):
        raise HTTPException(status_code=403, detail="Token inválido")
    try:
        pages_info = []
        all_content_parts = []
        
        # Iniciamos el Motor Playwright UNA SOLA VEZ para ahorrar memoria RAM en Render
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-sync",
                "--metrics-recording-only",
                "--mute-audio",
                "--no-first-run",
                "--single-process",  # Ahorra ~100MB en entornos con poca RAM
            ])
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
            )
            page = await context.new_page()

            # 1. Scrape y Captura del Home
            home_soup, home_content, home_b64 = await scrape_and_screenshot(page, request.url)
            
            all_content_parts.append(f"=== PÁGINA PRINCIPAL (Home) ===\n{home_content}")
            pages_info.append({
                "type": "Home", "url": request.url, 
                "screenshot_url": f"data:image/jpeg;base64,{home_b64}" if home_b64 else None
            })
            
            user_content = []
            if home_b64:
                user_content.append({"type":"text","text":f"CAPTURA DE HOME ({request.url}):"})
                user_content.append({"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{home_b64}","detail":"high"}})

            # 2. Extract specific page types
            key_pages = extract_key_pages(request.url, home_soup)
            
            # 3. Scrape and Screenshot Sub-pages secuencialmente reusando la pestaña
            for p_type, sub_url in key_pages:
                _, content, ss_b64 = await scrape_and_screenshot(page, sub_url)
                
                all_content_parts.append(f"=== {p_type.upper()} ({sub_url}) ===\n{content}")
                pages_info.append({
                    "type": p_type, "url": sub_url, 
                    "screenshot_url": f"data:image/jpeg;base64,{ss_b64}" if ss_b64 else None
                })
                
                if ss_b64:
                    user_content.append({"type":"text","text":f"CAPTURA DE {p_type.upper()} ({sub_url}):"})
                    user_content.append({"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{ss_b64}","detail":"high"}})

            await browser.close() # Apagamos el motor para liberar RAM

        all_content = "\n\n".join(all_content_parts)

        # 4. Invocación de OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        user_content.append({"type":"text","text":f"""Contenido de {len(pages_info)} páginas clave extraídas:

{all_content}

---

Genera una AUDITORÍA UX B2B ULTRA-DETALLADA desde la perspectiva exclusiva del Buyer Persona: **{request.persona}**

REGLA ESTRUCTURAL DE ORO PARA LA REDACCIÓN (SECCIÓN 4):
En CADA UNO de los 5 Módulos a continuación, tu redacción DEBE incluir de forma clara los siguientes apartados:
1. **Cómo lo percibe el buyer persona**: Tu perspectiva sobre este módulo al navegar.
2. **Puntos de Validación Específicos**: DEBES EXPLICAR por qué otorgas la calificación ('cumple', 'parcial', o 'falla') y tu evaluación a los siguientes puntos de cada módulo. Basándote en las evidencias de los textos y capturas envíadas.
3. **✅ Fortalezas**
4. **❌ Debilidades**
5. **💡 Recomendaciones**

¡MUY IMPORTANTE!: NO escribas en tu texto cosas como "📸 TESTIGO VISUAL" o textos con URLs para simular imágenes. LA INTERFAZ FÍSICA YA INSERTARÁ LAS IMÁGENES AUTOMÁTICAMENTE; tú únicamente desarrolla los puntos.

## MÓDULO 1: Identidad Visual y Marca
Puntos de Validación a escribir obligatoriamente: Identidad de Marca, Diseño Gráfico, Paleta de Colores, Tipografías.

## MÓDULO 2: Experiencia de Usuario y Usabilidad UX/UI
Puntos de Validación a escribir obligatoriamente: Navegación, Arquitectura, Facilidad de Uso.

## MÓDULO 3: Calidad y Relevancia del Contenido
Puntos de Validación a escribir obligatoriamente: Calidad de Contenido, Interlinking, Lenguaje B2B.

## MÓDULO 4: Proceso de Compra y E-commerce
Puntos de Validación a escribir obligatoriamente: Accesibilidad de Productos, Carrito, Checkout, Políticas.
Construye el viaje desde el home hasta la compra/producto analizando los fricciones de este flujo con las capturas de Tienda, Producto y Carrito.

## MÓDULO 5: Arquitectura y Estructura SEO
Puntos de Validación a escribir obligatoriamente: Keywords Menú, Keywords Long-tail, Jerarquía.

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
    "actual": "Resumen.",
    "expected": "Lo esperado."
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
            "screenshot_url": home_b64 if "home_b64" in locals() and home_b64 is not None else None
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
3. Tus respuestas deben ser hiper concretas, directas y conversacionales."""

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
    return {"status": "UX Auditor Pro — Motor Playwright Activo ✅"}

@app.get("/debug")
async def debug_crawl(url: str):
    """Endpoint de diagnóstico: devuelve qué subpáginas detecta el crawler sin tomar screenshots."""
    try:
        import requests as req_lib
        from bs4 import BeautifulSoup as BS
        r = req_lib.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BS(r.text, 'html.parser')
        key_pages = extract_key_pages(url, soup)
        all_links = [a['href'] for a in soup.find_all('a', href=True)][:50]
        return {
            "base_url": url,
            "total_links_found": len(all_links),
            "sample_links": all_links[:20],
            "key_pages_detected": key_pages
        }
    except Exception as e:
        return {"error": str(e)}
