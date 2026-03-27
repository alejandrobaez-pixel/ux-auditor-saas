from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import os, requests, base64
from bs4 import BeautifulSoup
from urllib.parse import urlparse

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}

# Patrones de subpaginas por categoria
PATTERNS = {
    "Blog o Novedades": ["/blog/", "/noticias/", "/novedades/", "/articles/", "/recursos/", "/recetas/", "/recetario/", "/blog", "/noticias"],
    "Nosotros":         ["/nosotros/", "/about/", "/quienes-somos/", "/empresa/", "/historia/", "/equipo/", "/nosotros", "/historia", "/about"],
    "Tienda":           ["/tienda/", "/shop/", "/productos/", "/catalogo/", "/store/", "/productos-chantilly/", "/tienda", "/shop", "/productos", "/productos-chantilly"],
    "Categoria":        ["/toppings/", "/cremas/", "/harinas/", "/ganaches/", "/categoria/", "/category/", "/coleccion/", "/toppings", "/cremas"],
    "Producto":         ["/crema-batida-2/", "/crema-batida/", "/top-cream/", "/chanty-wip/", "/producto/", "/crema-batida-2", "/crema-batida"],
    "Politicas":        ["/politica-de-inocuidad/", "/politicas/", "/politica/", "/devoluciones/", "/envios/", "/privacidad/", "/carrito/", "/checkout/", "/politicas", "/politica-de-inocuidad"],
}


class AuditRequest(BaseModel):
    url: str
    persona: str


class ChatRequest(BaseModel):
    message: str
    report_context: str
    persona: str


def scrape_page(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        title = soup.title.string.strip() if soup.title else "Sin titulo"
        headings = [h.get_text(strip=True) for h in soup.find_all(["h1", "h2", "h3"])][:12]
        links = [a.get_text(strip=True) for a in soup.find_all("a") if a.get_text(strip=True)][:30]
        body = soup.get_text(separator="\n", strip=True)[:2500]
        content = (
            "URL: " + url + "\n"
            "TITULO: " + title + "\n"
            "ENCABEZADOS:\n" + "\n".join(headings) + "\n"
            "NAVEGACION:\n" + "\n".join(links) + "\n"
            "CONTENIDO:\n" + body
        )
        return soup, content
    except Exception as e:
        return None, "[Error accediendo a " + url + ": " + str(e) + "]"


def extract_key_pages(base_url, soup):
    base = urlparse(base_url)
    base_root = base.scheme + "://" + base.netloc
    found = []
    seen = {base_url.rstrip("/"), base_root, base_root + "/"}

    # Paso 1: links del HTML estatico
    if soup:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("/"):
                full = base_root + href
            elif href.startswith("http") and base.netloc in href:
                full = href
            else:
                continue
            full_clean = full.split("?")[0].split("#")[0].rstrip("/")
            if full_clean in seen:
                continue
            for cat, kws in PATTERNS.items():
                if cat not in [x[0] for x in found]:
                    if any(kw.rstrip("/") in full_clean.lower() for kw in kws):
                        found.append((cat, full_clean))
                        seen.add(full_clean)
                        break

    # Paso 2: probing para sitios con JS rendering
    if len(found) < 2:
        print("[DEBUG] Probing activado — " + str(len(found)) + " links encontrados en HTML")
        for cat, paths in PATTERNS.items():
            if cat not in [x[0] for x in found]:
                for path in paths:
                    candidate = base_root + path
                    candidate_clean = candidate.rstrip("/")
                    if candidate_clean in seen:
                        continue
                    try:
                        r = requests.head(candidate, headers=HEADERS, timeout=6, allow_redirects=True)
                        if r.status_code in [200, 301, 302]:
                            found.append((cat, candidate_clean))
                            seen.add(candidate_clean)
                            print("[DEBUG] Probing OK: " + cat + " -> " + candidate)
                            break
                    except Exception:
                        continue
    return found


def take_screenshot(url, access_key):
    if not access_key:
        return None
    try:
        encoded_url = requests.utils.quote(url, safe="")
        api_url = (
            "https://api.screenshotone.com/take"
            "?access_key=" + access_key +
            "&url=" + encoded_url +
            "&format=jpg"
            "&viewport_width=1280"
            "&viewport_height=800"
            "&full_page=false"
            "&image_quality=60"
        )
        r = requests.get(api_url, timeout=30)
        if r.status_code == 200:
            return base64.b64encode(r.content).decode("utf-8")
        print("[SCREENSHOT] Error " + str(r.status_code) + " para " + url)
        return None
    except Exception as e:
        print("[SCREENSHOT] Exception para " + url + ": " + str(e))
        return None


def build_prompt(persona, n_pages, all_content):
    # IMPORTANTE: estos encabezados deben coincidir con lo que el frontend busca
    # El frontend busca: "MODULO 1", "MODULO 2", etc. (sin acento, en mayusculas)
    return (
        "Analiza " + str(n_pages) + " paginas del sitio web desde la perspectiva del Buyer Persona: " + persona + "\n\n"
        "CONTENIDO EXTRAIDO DE LAS PAGINAS:\n" + all_content + "\n\n"
        "---\n\n"
        "Genera una AUDITORIA UX B2B ULTRA-DETALLADA. Para cada modulo:\n"
        "1. Como lo percibe el buyer persona al navegar\n"
        "2. Evaluacion de cada punto con etiqueta: CUMPLE / PARCIAL / FALLA\n"
        "3. Fortalezas detectadas\n"
        "4. Debilidades detectadas\n"
        "5. Recomendaciones de mejora\n\n"
        "MUY IMPORTANTE: NO menciones capturas ni URLs de imagenes. La interfaz las agrega sola.\n\n"
        "## MODULO 1: Identidad Visual y Marca\n"
        "Analiza: Identidad de Marca, Diseno Grafico, Paleta de Colores, Tipografias.\n\n"
        "## MODULO 2: Experiencia de Usuario y Usabilidad UX/UI\n"
        "Analiza: Navegacion, Arquitectura de Informacion, Facilidad de Uso.\n\n"
        "## MODULO 3: Calidad y Relevancia del Contenido\n"
        "Analiza: Calidad de Contenido, Interlinking, Lenguaje B2B.\n\n"
        "## MODULO 4: Proceso de Compra y E-commerce\n"
        "Analiza: Accesibilidad de Productos, Carrito, Checkout, Politicas de Devolucion/Envio.\n\n"
        "## MODULO 5: Arquitectura y Estructura SEO\n"
        "Analiza: Keywords en Menu, Keywords Long-tail, Jerarquia de Contenido.\n\n"
        "---\n\n"
        "Al FINAL, escribe EXACTAMENTE este bloque (reemplaza los valores ejemplo por los reales):\n\n"
        "---JSON_DATA---\n"
        '{"scores":{"Identidad Visual":6,"UX Usabilidad":5,"Contenido":5,"Proceso Compra":4,"SEO":5},'
        '"gap":{"actual":"Describe el estado real del sitio.","expected":"Lo que el buyer persona esperaria."},'
        '"matrix":{"Identidad Visual":{"base":4,"cumple":2,"parcial":1,"falla":1},"Exp. Usabilidad":{"base":3,"cumple":2,"parcial":1,"falla":0},"Relevancia Contenido":{"base":3,"cumple":1,"parcial":1,"falla":1},"Proceso de Compra":{"base":4,"cumple":1,"parcial":1,"falla":2},"Estructura SEO":{"base":3,"cumple":2,"parcial":0,"falla":1}},'
        '"criteria_status":{"Identidad Visual":[{"name":"Identidad de Marca","status":"cumple","note":"Nota real"},{"name":"Diseno Grafico","status":"parcial","note":"Nota real"},{"name":"Paleta de Colores","status":"cumple","note":"Nota real"},{"name":"Tipografias","status":"parcial","note":"Nota real"}],"Exp. Usabilidad":[{"name":"Navegacion","status":"cumple","note":"Nota real"},{"name":"Arquitectura","status":"parcial","note":"Nota real"},{"name":"Facilidad de Uso","status":"parcial","note":"Nota real"}],"Relevancia Contenido":[{"name":"Calidad Contenido","status":"parcial","note":"Nota real"},{"name":"Interlinking","status":"falla","note":"Nota real"},{"name":"Lenguaje B2B","status":"cumple","note":"Nota real"}],"Proceso de Compra":[{"name":"Accesibilidad","status":"falla","note":"Nota real"},{"name":"Carrito","status":"parcial","note":"Nota real"},{"name":"Checkout","status":"falla","note":"Nota real"},{"name":"Politicas","status":"cumple","note":"Nota real"}],"Estructura SEO":[{"name":"Keywords Menu","status":"cumple","note":"Nota real"},{"name":"Keywords Long-tail","status":"cumple","note":"Nota real"},{"name":"Jerarquia","status":"falla","note":"Nota real"}]},'
        '"seo_proposals":[{"url":"/propuesta-1/","type":"Cluster B2B","color":"purple","desc":"Descripcion real."},{"url":"/propuesta-2/","type":"Transaccional","color":"red","desc":"Descripcion real."},{"url":"/propuesta-3/","type":"Inbound","color":"green","desc":"Descripcion real."}],'
        '"action_plan":{"now":["Accion 1.","Accion 2.","Accion 3."],"next":["Accion 1.","Accion 2.","Accion 3."],"later":["Accion 1.","Accion 2.","Accion 3."]}}\n'
        "---END_JSON---\n"
    )


@app.post("/audit")
async def run_audit(request: AuditRequest, x_token: str = Header(None)):
    if x_token != os.getenv("ACCESS_TOKEN"):
        raise HTTPException(status_code=403, detail="Token invalido")
    try:
        access_key = os.getenv("SCREENSHOTONE_KEY", "")

        # 1. Home
        home_soup, home_content = scrape_page(request.url)
        home_b64 = take_screenshot(request.url, access_key)

        all_content_parts = ["=== HOME (" + request.url + ") ===\n" + home_content]
        pages_info = [{
            "type": "Home",
            "url": request.url,
            "screenshot_url": ("data:image/jpeg;base64," + home_b64) if home_b64 else None
        }]

        user_content = []
        if home_b64:
            user_content.append({"type": "text", "text": "CAPTURA HOME (" + request.url + "):"})
            user_content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + home_b64, "detail": "high"}})

        # 2. Detectar subpaginas
        key_pages = extract_key_pages(request.url, home_soup)
        print("[DEBUG] Paginas detectadas: " + str(key_pages))

        # 3. Scrape + screenshot de cada subpagina
        for p_type, sub_url in key_pages:
            _, content = scrape_page(sub_url)
            ss_b64 = take_screenshot(sub_url, access_key)

            all_content_parts.append("=== " + p_type.upper() + " (" + sub_url + ") ===\n" + content)
            pages_info.append({
                "type": p_type,
                "url": sub_url,
                "screenshot_url": ("data:image/jpeg;base64," + ss_b64) if ss_b64 else None
            })
            if ss_b64:
                user_content.append({"type": "text", "text": "CAPTURA " + p_type.upper() + " (" + sub_url + "):"})
                user_content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + ss_b64, "detail": "high"}})

        print("[DEBUG] Total paginas: " + str(len(pages_info)))
        all_content = "\n\n".join(all_content_parts)

        # 4. Llamada a OpenAI
        prompt_text = build_prompt(request.persona, len(pages_info), all_content)
        user_content.append({"type": "text", "text": prompt_text})

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Eres experto en UX y marketing B2B. Analizas el sitio desde la perspectiva del buyer persona: " + request.persona + ". "
                        "Escribes en espanol con Markdown profesional. "
                        "OBLIGATORIO: al final incluyes el bloque ---JSON_DATA--- con los datos reales evaluados, terminado en ---END_JSON---."
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
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Eres el buyer persona: " + request.persona + ". "
                        "Tus opiniones se basan SOLO en este reporte:\n\n" + request.report_context + "\n\n"
                        "Responde en primera persona, nunca inventes informacion."
                    )
                },
                {"role": "user", "content": request.message}
            ],
            max_completion_tokens=500
        )
        return {"reply": response.choices[0].message.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def home():
    return {"status": "UX Auditor Pro — Backend Activo"}


@app.get("/debug")
def debug_crawl(url: str):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        key_pages = extract_key_pages(url, soup)
        all_links = [a["href"] for a in soup.find_all("a", href=True)][:50]
        return {
            "base_url": url,
            "total_links_in_html": len(all_links),
            "sample_links": all_links[:20],
            "key_pages_detected": key_pages
        }
    except Exception as e:
        return {"error": str(e)}
