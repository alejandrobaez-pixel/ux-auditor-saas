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
        params = f"?access_key={access_key}&url={encoded_url}&format=jpg&viewport_width=1024&viewport_height=768&full_page=false&image_quality=60"
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

        # 1. Scrape homepage
        home_soup, home_content = scrape_page(request.url)

        # 2. Detectar subpáginas del menú
        sub_urls = extract_menu_links(request.url, home_soup, max_links=3)

        # 3. Scrape subpáginas
        all_content_parts = [f"=== PÁGINA PRINCIPAL ===\n{home_content}"]
        pages_info = [{"url": request.url, "screenshot_url": None}]

        for sub_url in sub_urls:
            _, content = scrape_page(sub_url)
            all_content_parts.append(f"=== SUBPÁGINA: {sub_url} ===\n{content}")
            pages_info.append({"url": sub_url, "screenshot_url": None})

        all_content = "\n\n".join(all_content_parts)

        # 4. Capturas de pantalla (home + hasta 2 subpáginas)
        home_b64, home_ss_url = take_screenshot(request.url, access_key)
        pages_info[0]["screenshot_url"] = home_ss_url

        for idx, sub_url in enumerate(sub_urls[:2]):
            _, ss_url = take_screenshot(sub_url, access_key)
            if idx + 1 < len(pages_info):
                pages_info[idx + 1]["screenshot_url"] = ss_url

        # 5. Construir mensaje para GPT
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        user_content = []

        if home_b64:
            user_content.append({"type": "text", "text": f"CAPTURA DE PANTALLA REAL de la página principal ({request.url}):"})
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{home_b64}", "detail": "high"}})

        user_content.append({"type": "text", "text": f"""Contenido real extraído de {len(pages_info)} páginas del sitio:

{all_content}

---

Genera una AUDITORÍA UX B2B ULTRA-DETALLADA analizando TODO desde la perspectiva del Buyer Persona: **{request.persona}**

Piensa y actúa COMO si fueras ese perfil navegando este sitio. ¿Qué le llama la atención? ¿Qué le frustra? ¿Qué le genera confianza?

Estructura tu respuesta en estos 5 módulos OBLIGATORIOS (usa exactamente estos encabezados):

## MÓDULO 1: Identidad Visual y Marca
Evalúa cómo percibe el Buyer Persona estos elementos:
- **Identidad de Marca**: Logos, isotipos, voz de marca, tono (¿B2B o B2C? ¿tradicional o moderno?)
- **Diseño Gráfico**: Disposición, espacios en blanco, márgenes, asimetrías, estilo de fotografía
- **Paleta de Colores**: Colores primarios/secundarios/acento (con nombres o códigos hex), uso, contraste, impacto psicológico
- **Tipografías**: Familia de fuentes, peso visual, jerarquía, legibilidad para el perfil

## MÓDULO 2: Experiencia de Usuario y Usabilidad UX/UI
Evalúa desde los ojos del Buyer Persona:
- **Navegación y Arquitectura**: ¿Qué tan fácil encuentra lo que busca el perfil? Menú, submenús, footer, breadcrumbs
- **Facilidad de Uso**: Botones, formularios, fluidez, respuesta visual, claridad de CTAs
- **Coherencia Heurística**: Visibilidad del sistema, prevención de errores, control del usuario

## MÓDULO 3: Calidad y Relevancia del Contenido
Evalúa qué tan relevante es el contenido para el Buyer Persona:
- **Calidad del Contenido**: Profundidad, largo, aporte de valor real para el perfil
- **Interlinking y Semántica**: Enlaces internos, lógica de navegación, clústeres temáticos
- **Lenguaje y Tono B2B**: ¿El contenido habla al perfil? ¿Técnico, aspiracional o transaccional? Congruencia con marca

## MÓDULO 4: Proceso de Compra y E-commerce
Evalúa el recorrido de compra desde la perspectiva del Buyer Persona:
- **Accesibilidad de Productos**: ¿A cuántos clics están? ¿Visibles desde menú? ¿En la Home?
- **Carrito / Cotizador**: Facilidad de agregar, modificar cantidades y especificaciones
- **Proceso de Checkout**: ¿Rápido? ¿Exige registro? ¿Múltiples métodos de pago? ¿Muestra descuentos?
- **Políticas Logísticas**: Envíos, devoluciones, transparencia y facilidad de encontrar la info

## MÓDULO 5: Arquitectura y Estructura SEO
Evalúa el potencial de encontrabilidad y la estructura del sitio:
- **Keywords del Menú**: ¿Qué palabras clave refleja la navegación? ¿Relevantes para el perfil?
- **Keywords Long-tail**: ¿El contenido cubre búsquedas específicas del buyer persona?
- **Jerarquía y Sitemap**: Estructura de URLs, profundidad del sitio, pilares de contenido

---

Para cada módulo incluye:
- ✅ **Fortalezas** con ejemplos específicos de las páginas visitadas
- ❌ **Debilidades críticas** desde la perspectiva del perfil
- 💡 **Recomendaciones** priorizadas y accionables

---

## ANÁLISIS DE BRECHA B2B
Crea esta tabla comparando la realidad del sitio vs lo que espera el perfil:
| Dimensión | Realidad Actual del Sitio | Expectativa del Perfil ({request.persona}) |
|-----------|--------------------------|-------------------------------------------|
| Comunicación Visual | ... | ... |
| Confianza Institucional | ... | ... |
| Eficiencia Operativa | ... | ... |
| Soporte y Servicio B2B | ... | ... |
| Proceso de Compra | ... | ... |

## PLAN DE ACCIÓN ESTRATÉGICO
**[NOW] 0-30 Días (Quick Wins):** Acciones inmediatas de alto impacto y bajo costo
**[NEXT] 30-90 Días (UX & Flow):** Mejoras estructurales de mediana complejidad
**[LATER] 90+ Días (SEO Estructural):** Mejoras de largo plazo y posicionamiento

---

Al FINAL, añade EXACTAMENTE este bloque con tus puntuaciones reales del 1 al 10:
---SCORES---
{{"Identidad Visual": 6, "UX Usabilidad": 5, "Contenido": 6, "Proceso Compra": 5, "SEO": 5, "Global": 5.4}}
"""})

        # 6. Llamar a GPT
        response = client.chat.completions.create(
            model="gpt-5.4-nano",
            messages=[
                {"role": "system", "content": f"Eres un experto en UX, usabilidad y marketing B2B. Analizas sitios web EXCLUSIVAMENTE desde la perspectiva del Buyer Persona: {request.persona}. Todo tu análisis debe estar filtrado por cómo ese perfil experimenta el sitio. Respondes en español con formato Markdown profesional y muy detallado."},
                {"role": "user", "content": user_content}
            ],
            max_completion_tokens=5000
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
    return {"status": "UX Auditor Pro Multi-Página - Activo ✅"}
