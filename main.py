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

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}

# Patrones de subpáginas por categoría
PATTERNS = {
    'Blog o Novedades': ['/blog/', '/noticias/', '/novedades/', '/articles/', '/recursos/', '/recetas/', '/recetario/', '/blog', '/noticias'],
    'Nosotros': ['/nosotros/', '/about/', '/quienes-somos/', '/empresa/', '/historia/', '/conocenos/', '/equipo/', '/nosotros', '/historia', '/about'],
    'Tienda': ['/tienda/', '/shop/', '/productos/', '/catalogo/', '/store/', '/productos-chantilly/', '/tienda', '/shop', '/productos', '/productos-chantilly'],
    'Categoria': ['/toppings/', '/cremas/', '/harinas/', '/ganaches/', '/categoria/', '/category/', '/coleccion/', '/collections/', '/toppings', '/cremas'],
    'Producto': ['/crema-batida-2/', '/crema-batida/', '/top-cream/', '/chanty-wip/', '/producto/', '/product/', '/crema-batida-2', '/crema-batida'],
    'Politicas': ['/politica-de-inocuidad/', '/politicas/', '/politica/', '/devoluciones/', '/envios/', '/privacidad/', '/carrito/', '/checkout/', '/politicas', '/politica']
}

def scrape_page(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, 'html.parser')
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        title = soup.title.string.strip() if soup.title else "Sin titulo"
        headings = [h.get_text(strip=True) for h in soup.find_all(['h1', 'h2', 'h3'])][:12]
        links = [a.get_text(strip=True) for a in soup.find_all('a') if a.get_text(strip=True)][:30]
        body = soup.get_text(separator='\n', strip=True)[:2500]
        content = f"URL: {url}\nTITULO: {title}\nENCEBEZADOS:\n{chr(10).join(headings)}\nNAVEGACION:\n{chr(10).join(links)}\nCONTENIDO:\n{body}"
        return soup, content
    except Exception as e:
        return None, f"[Error accediendo a {url}: {e}]"

def extract_key_pages(base_url, soup):
    base = urlparse(base_url)
    base_root = f"{base.scheme}://{base.netloc}"
    found = []
    seen = {base_url.rstrip('/'), base_root, base_root + '/'}

    # Paso 1: Buscar links en el HTML estático
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
            if full_clean in seen:
                continue
            for cat, kws in PATTERNS.items():
                if cat not in [x[0] for x in found]:
                    if any(kw.rstrip('/') in full_clean.lower() for kw in kws):
                        found.append((cat, full_clean))
                        seen.add(full_clean)
                        break

    # Paso 2: Si el sitio usa JS y no encontramos links, probamos URLs comunes con HEAD
    if len(found) < 2:
        print(f"[DEBUG] Modo probing activado (solo {len(found)} links en HTML estatico)")
        for cat, paths in PATTERNS.items():
            if cat not in [x[0] for x in found]:
                for path in paths:
                    candidate = base_root + path
                    candidate_clean = candidate.rstrip('/')
                    if candidate_clean in seen:
                        continue
                    try:
                        r = requests.head(candidate, headers=HEADERS, timeout=6, allow_redirects=True)
                        if r.status_code in [200, 301, 302]:
                            found.append((cat, candidate_clean))
                            seen.add(candidate_clean)
                            print(f"[DEBUG] Probado OK: {cat} -> {candidate}")
                            break
                    except Exception:
                        continue

    return found

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
        print(f"[SCREENSHOT ERROR] {url} HTTP {r.status_code}: {r.text[:100]}")
        return None
    except Exception as e:
        print(f"[SCREENSHOT EXCEPTION] {url}: {e}")
        return None

@app.post("/audit")
async def run_audit(request: AuditRequest, x_token: str = Header(None)):
    if x_token != os.getenv("ACCESS_TOKEN"):
        raise HTTPException(status_code=403, detail="Token invalido")
    try:
        access_key = os.getenv("SCREENSHOTONE_KEY", "")

        # 1. Home
        home_soup, home_content = scrape_page(request.url)
        home_b64 = take_screenshot(request.url, access_key)

        all_content_parts = [f"=== PAGINA PRINCIPAL (Home) ===\n{home_content}"]
        pages_info = [{
            "type": "Home",
            "url": request.url,
            "screenshot_url": f"data:image/jpeg;base64,{home_b64}" if home_b64 else None
        }]

        user_content = []
        if home_b64:
            user_content.append({"type": "text", "text": f"CAPTURA DE HOME ({request.url}):"})
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{home_b64}", "detail": "high"}})

        # 2. Detectar subpaginas (con fallback probing para sitios JS)
        key_pages = extract_key_pages(request.url, home_soup)
        print(f"[DEBUG] Paginas clave detectadas: {key_pages}")

        # 3. Scrape + Screenshot secuencial
        for p_type, sub_url in key_pages:
            _, content = scrape_page(sub_url)
            ss_b64 = take_screenshot(sub_url, access_key)

            all_content_parts.append(f"=== {p_type.upper()} ({sub_url}) ===\n{content}")
            pages_info.append({
                "type": p_type,
                "url": sub_url,
                "screenshot_url": f"data:image/jpeg;base64,{ss_b64}" if ss_b64 else None
            })
            if ss_b64:
                user_content.append({"type": "text", "text": f"CAPTURA DE {p_type.upper()} ({sub_url}):"})
                user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{ss_b64}", "detail": "high"}})

        print(f"[DEBUG] Total paginas procesadas: {len(pages_info)}")
        all_content = "\n\n".join(all_content_parts)

        # 4. OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        prompt_text = (
            f"Contenido de {len(pages_info)} paginas clave extraidas:\n\n{all_content}\n\n---\n\n"
            f"Genera una AUDITORIA UX B2B ULTRA-DETALLADA desde la perspectiva exclusiva del Buyer Persona: **{request.persona}**\n\n"
            "REGLA ESTRUCTURAL DE ORO (SECCION 4):\n"
            "En CADA UNO de los 5 Modulos, incluye:\n"
            "1. **Como lo percibe el buyer persona**\n"
            "2. **Puntos de Validacion Especificos** con calificacion (cumple/parcial/falla)\n"
            "3. **Fortalezas**\n"
            "4. **Debilidades**\n"
            "5. **Recomendaciones**\n\n"
            "MUY IMPORTANTE: NO escribas 'TESTIGO VISUAL' ni URLs de imagenes. La interfaz las inserta sola.\n\n"
            "## MODULO 1: Identidad Visual y Marca\n"
            "Puntos: Identidad de Marca, Diseno Grafico, Paleta de Colores, Tipografias.\n\n"
            "## MODULO 2: Experiencia de Usuario y Usabilidad UX/UI\n"
            "Puntos: Navegacion, Arquitectura, Facilidad de Uso.\n\n"
            "## MODULO 3: Calidad y Relevancia del Contenido\n"
            "Puntos: Calidad de Contenido, Interlinking, Lenguaje B2B.\n\n"
            "## MODULO 4: Proceso de Compra y E-commerce\n"
            "Puntos: Accesibilidad de Productos, Carrito, Checkout, Politicas.\n\n"
            "## MODULO 5: Arquitectura y Estructura SEO\n"
            "Puntos: Keywords Menu, Keywords Long-tail, Jerarquia.\n\n"
            "---\n\n"
            "Al FINAL incluye OBLIGATORIAMENTE:\n\n"
            "---JSON_DATA---\n"
            "{\n"
            '  "scores": {"Identidad Visual": 6, "UX Usabilidad": 5, "Contenido": 5, "Proceso Compra": 4, "SEO": 5},\n'
            '  "gap": {"actual": "Resumen actual.", "expected": "Lo esperado."},\n'
            '  "matrix": {\n'
            '    "Identidad Visual": {"base": 4, "cumple": 2, "parcial": 1, "falla": 1},\n'
            '    "Exp. Usabilidad": {"base": 3, "cumple": 2, "parcial": 1, "falla": 0},\n'
            '    "Relevancia Contenido": {"base": 3, "cumple": 1, "parcial": 1, "falla": 1},\n'
            '    "Proceso de Compra": {"base": 4, "cumple": 1, "parcial": 1, "falla": 2},\n'
            '    "Estructura SEO": {"base": 3, "cumple": 2, "parcial": 0, "falla": 1}\n'
            '  },\n'
            '  "criteria_status": {\n'
            '    "Identidad Visual": [\n'
            '      {"name": "Identidad de Marca", "status": "cumple", "note": "Nota"},\n'
            '      {"name": "Diseno Grafico", "status": "parcial", "note": "Nota"},\n'
            '      {"name": "Paleta de Colores", "status": "cumple", "note": "Nota"},\n'
            '      {"name": "Tipografias", "status": "parcial", "note": "Nota"}\n'
            '    ],\n'
            '    "Exp. Usabilidad": [\n'
            '      {"name": "Navegacion", "status": "cumple", "note": "Nota"},\n'
            '      {"name": "Arquitectura", "status": "parcial", "note": "Nota"},\n'
            '      {"name": "Facilidad de Uso", "status": "parcial", "note": "Nota"}\n'
            '    ],\n'
            '    "Relevancia Contenido": [\n'
            '      {"name": "Calidad Contenido", "status": "parcial", "note": "Nota"},\n'
            '      {"name": "Interlinking", "status": "falla", "note": "Nota"},\n'
            '      {"name": "Lenguaje B2B", "status": "cumple", "note": "Nota"}\n'
            '    ],\n'
            '    "Proceso de Compra": [\n'
            '      {"name": "Accesibilidad", "status": "falla", "note": "Nota"},\n'
            '      {"name": "Carrito", "status": "parcial", "note": "Nota"},\n'
            '      {"name": "Checkout", "status": "falla", "note": "Nota"},\n'
            '      {"name": "Politicas", "status": "cumple", "note": "Nota"}\n'
            '    ],\n'
            '    "Estructura SEO": [\n'
            '      {"name": "Keywords Menu", "status": "cumple", "note": "Nota"},\n'
            '      {"name": "Keywords Long-tail", "status": "cumple", "note": "Nota"},\n'
            '      {"name": "Jerarquia", "status": "falla", "note": "Nota"}\n'
            '    ]\n'
            '  },\n'
            '  "seo_proposals": [\n'
            '    {"url": "/propuesta-1/", "type": "Cluster B2B Central", "color": "purple", "desc": "Descripcion."},\n'
            '    {"url": "/propuesta-2/", "type": "Transaccional", "color": "red", "desc": "Descripcion."},\n'
            '    {"url": "/propuesta-3/", "type": "Inbound / Informativa", "color": "green", "desc": "Descripcion."}\n'
            '  ],\n'
            '  "action_plan": {\n'
            '    "now": ["Accion 1.", "Accion 2.", "Accion 3."],\n'
            '    "next": ["Accion 1.", "Accion 2.", "Accion 3."],\n'
            '    "later": ["Accion 1.", "Accion 2.", "Accion 3."]\n'
            '  }\n'
            "}\n"
            "---END_JSON---\n"
        )

        user_content.append({"type": "text", "text": prompt_text})

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Eres un experto en UX y marketing B2B. Analizas sitios desde la perspectiva del Buyer Persona: {request.persona}. "
                        "Respondes en espanol con Markdown profesional. Siempre incluyes el JSON estructurado EXACTAMENTE al final."
                    )
                },
                {"role": "user", "content": user_content}
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
        raise HTTPException(status_code=403, detail="Token invalido")
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        system_prompt = (
            f'Eres el buyer persona: "{request.persona}". '
            "Acabas de visitar una pagina web. Tus impresiones basadas ESTRICTAMENTE en este reporte:\n\n"
            f"=== CONTEXTO ===\n{request.report_context}\n================\n\n"
            "REGLAS: Responde en primera persona, nunca inventes, se concreto y directo."
        )
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.message}
            ],
            max_completion_tokens=500
        )
        return {"reply": response.choices[0].message.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def home():
    return {"status": "UX Auditor Pro — Backend Ligero con Probing Activo"}

@app.get("/debug")
def debug_crawl(url: str):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        key_pages = extract_key_pages(url, soup)
        all_links = [a['href'] for a in soup.find_all('a', href=True)][:50]
        return {
            "base_url": url,
            "total_links_in_html": len(all_links),
            "sample_links": all_links[:20],
            "key_pages_detected": key_pages
        }
    except Exception as e:
        return {"error": str(e)}
