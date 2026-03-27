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

def take_screenshot(url, access_key):
    try:
        if not access_key:
            return None
        encoded_url = requests.utils.quote(url, safe='')
        api_url = (
            f"https://api.screenshotone.com/take"
            f"?access_key={access_key}"
            f"&url={encoded_url}"
            f"&format=jpg"
            f"&viewport_width=1280"
            f"&viewport_height=800"
            f"&full_page=false"
            f"&image_quality=60"
        )
        r = requests.get(api_url, timeout=30)
        if r.status_code == 200:
            return base64.b64encode(r.content).decode('utf-8')
        print(f"[SCREENSHOT ERROR] {url} → HTTP {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        print(f"[SCREENSHOT EXCEPTION] {url}: {e}")
        return None

@app.post("/audit")
async def run_audit(request: AuditRequest, x_token: str = Header(None)):
    if x_token != os.getenv("ACCESS_TOKEN"):
        raise HTTPException(status_code=403, detail="Token inválido")
    try:
        access_key = os.getenv("SCREENSHOTONE_KEY", "")

        home_soup, home_content = scrape_page(request.url)
        home_b64 = take_screenshot(request.url, access_key)

        all_content_parts = [f"=== PÁGINA PRINCIPAL (Home) ===\n{home_content}"]
        pages_info = [{"type": "Home", "url": request.url,
            "screenshot_url": f"data:image/jpeg;base64,{home_b64}" if home_b64 else None}]

        user_content = []
        if home_b64:
            user_content.append({"type":"text","text":f"CAPTURA DE HOME ({request.url}):"})
            user_content.append({"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{home_b64}","detail":"high"}})

        key_pages = extract_key_pages(request.url, home_soup)
        print(f"[DEBUG] Subpáginas detectadas: {key_pages}")

        for p_type, sub_url in key_pages:
            _, content = scrape_page(sub_url)
            ss_b64 = take_screenshot(sub_url, access_key)
            all_content_parts.append(f"=== {p_type.upper()} ({sub_url}) ===\n{content}")
            pages_info.append({"type": p_type, "url": sub_url,
                "screenshot_url": f"data:image/jpeg;base64,{ss_b64}" if ss_b64 else None})
            if ss_b64:
                user_content.append({"type":"text","text":f"CAPTURA DE {p_type.upper()} ({sub_url}):"})
                user_content.append({"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{ss_b64}","detail":"high"}})

        print(f"[DEBUG] Total páginas: {len(pages_info)}")
        all_content = "\n\n".join(all_content_parts)

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        user_content.append({"type":"text","text":f"""Contenido de {len(pages_info)} páginas clave extraídas:

{all_content}

---

Genera una AUDITORÍA UX B2B ULTRA-DETALLADA desde la perspectiva exclusiva del Buyer Persona: **{request.persona}**

REGLA ESTRUCTURAL DE ORO PARA LA REDACCIÓN (SECCIÓN 4):
En CADA UNO de los 5 Módulos, incluye:
1. **Cómo lo percibe el buyer persona**
2. **Puntos de Validación Específicos** con calificación ('cumple', 'parcial', o 'falla')
3. **✅ Fortalezas**
4. **❌ Debilidades**
5. **💡 Recomendaciones**

¡MUY IMPORTANTE!: NO escribas "📸 TESTIGO VISUAL" ni URLs de imágenes. La interfaz las inserta automáticamente.

## MÓDULO 1: Identidad Visual y Marca
Puntos obligatorios: Identidad de Marca, Diseño Gráfico, Paleta de Colores, Tipografías.

## MÓDULO 2: Experiencia de Usuario y Usabilidad UX/UI
Puntos obligatorios: Navegación, Arquitectura, Facilidad de Uso.

## MÓDULO 3: Calidad y Relevancia del Contenido
Puntos obligatorios: Calidad de Contenido, Interlinking, Lenguaje B2B.

## MÓDULO 4: Proceso de Compra y E-commerce
Puntos obligatorios: Accesibilidad de Productos, Carrito, Checkout, Políticas.

## MÓDULO 5: Arquitectura y Estructura SEO
Puntos obligatorios: Keywords Menú, Keywords Long-tail, Jerarquía.

---

Al FINAL incluye OBLIGATORIAMENTE:

---JSON_DATA---
{{
  "scores": {{"Identidad Visual": 6,"UX Usabilidad": 5,"Contenido": 5,"Proceso Compra": 4,"SEO": 5}},
  "gap": {{"actual": "Resumen actual.","expected": "Lo esperado."}},
  "matrix": {{
    "Identidad Visual": {{"base":4,"cumple":2,"parcial":1,"falla":1}},
    "Exp. Usabilidad": {{"base":3,"cumple":2,"parcial":1,"falla":0}},
    "Relevancia Contenido": {{"base":3,"cumple":1,"parcial":1,"falla":1}},
    "Proceso de Compra": {{"base":4,"cumple":1,"parcial":1,"falla":2}},
    "Estructura SEO": {{"base":3,"cumple":2,"parcial":0,"falla":1}}
  }},
  "criteria_status": {{
    "Identidad Visual": [
      {{"name":"Identidad de Marca","status":"cumple","note":"Nota"}},
      {{"name":"Diseño Gráfico","status":"parcial","note":"Nota"}},
      {{"name":"Paleta de Colores","status":"cumple","note":"Nota"}},
      {{"name":"Tipografías","status":"parcial","note":"Nota"}}
    ],
    "Exp. Usabilidad": [
      {{"name":"Navegación","status":"cumple","note":"Nota"}},
      {{"name":"Arquitectura","status":"parcial","note":"Nota"}},
      {{"name":"Facilidad de Uso","status":"parcial","note":"Nota"}}
    ],
    "Relevancia Contenido": [
      {{"name":"Calidad Contenido","status":"parcial","note":"Nota"}},
      {{"name":"Interlinking","status":"falla","note":"Nota"}},
      {{"name":"Lenguaje B2B","status":"cumple","note":"Nota"}}
    ],
    "Proceso de Compra": [
      {{"name":"Accesibilidad","status":"falla","note":"Nota"}},
      {{"name":"Carrito","status":"parcial","note":"Nota"}},
      {{"name":"Checkout","status":"falla","note":"Nota"}},
      {{"name":"Políticas","status":"cumple","note":"Nota"}}
    ],
    "Estructura SEO": [
      {{"name":"Keywords Menú","status":"cumple","note":"Nota"}},
      {{"name":"Keywords Long-tail","status":"cumple","note":"Nota"}},
      {{"name":"Jerarquía","status":"falla","note":"Nota"}}
    ]
  }},
  "seo_proposals": [
    {{"url":"/propuesta-1/","type":"Clúster B2B Central","color":"purple","desc":"Descripción."}},
    {{"url":"/propuesta-2/","type":"Transaccional/Cotización","color":"red","desc":"Descripción."}},
    {{"url":"/propuesta-3/","type":"Inbound / Informativa","color":"green","desc":"Descripción."}}
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
                {"role":"system","content":f"Eres un experto en UX y marketing B2B. Analizas sitios desde la perspectiva del Buyer Persona: {request.persona}. Respondes en español con Markdown profesional. Siempre incluyes el JSON estructurado al final."},
                {"role":"user","content":user_content}
            ],
            max_completion_tokens=6000
        )

        return {
            "report": response.choices[0].message.content,
            "pages": pages_info,
            "pages_analyzed": len(pages_info),
            "screenshot_url": home_b64 if home_b64 else None
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
Acabas de visitar una página web. Tus impresiones basadas ESTRICTAMENTE en este reporte:

=== CONTEXTO ===
{request.report_context}
================

REGLAS: Responde en primera persona, nunca inventes, sé concreto y directo."""

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
    return {"status": "UX Auditor Pro — Backend Ligero Activo ✅"}

@app.get("/debug")
def debug_crawl(url: str):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        key_pages = extract_key_pages(url, soup)
        all_links = [a['href'] for a in soup.find_all('a', href=True)][:50]
        return {"base_url": url, "total_links_found": len(all_links),
                "sample_links": all_links[:20], "key_pages_detected": key_pages}
    except Exception as e:
        return {"error": str(e)}
