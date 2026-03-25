from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import warnings

# Suprimir advertencias generales
warnings.filterwarnings('ignore')

from crewai import Agent, Task, Crew, Process
from langchain_google_genai import ChatGoogleGenerativeAI
from crewai_tools import ScrapeWebsiteTool

# Inicializamos nuestra Web API
app = FastAPI(title="UX Auditor SaaS API", description="Servidor Core de Inteligencia Artificial")

# Reglas CORS: Permitir que cualquier página web (incluida tu interfaz en el escritorio) se conecte sin bloqueos de seguridad del navegador.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Estructura obligatoria de los datos que la Web App nos debe enviar
class DatosAuditoria(BaseModel):
    url: str
    persona: str
    focus: str

# Esta es la ruta principal. Cuando la Web App le avise a esta URL (/api/audit), arrancarán los agentes.
@app.post("/api/audit")
def ejecutar_auditoria(datos: DatosAuditoria):
    
    # 1. Chequeo de seguridad de tu Llave Gemini API
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or "TU_CLAVE_" in api_key:
        raise HTTPException(
            status_code=500, 
            detail="Error del Servidor: La clave API de Gemini no está configurada en las variables de entorno."
        )
    
    try:
        # Preparamos al modelo con tu clave interceptada dinámicamente
        llm = ChatGoogleGenerativeAI(
            model="gemini-1.5-pro",
            verbose=True,
            temperature=0.7,
            google_api_key=api_key
        )
        herramienta_scraping = ScrapeWebsiteTool()

        # 2. Configuración Dinámica: El Agente adapta su mente al perfil B2B que el usuario escogió en la interfaz
        analista_ux = Agent(
            role='Analista Senior Experto en Heurísticas UX',
            goal=f'Auditar de forma crítica la web {datos.url} pensando 100% como un {datos.persona}.',
            backstory=(
                f"Tienes 15 años de experiencia. Tu mentalidad al evaluar debe ser la de un experto que "
                f"conoce al dedillo la psicología de un '{datos.persona}'. Tu foco para este análisis específico es: "
                f"'{datos.focus}'. No toleras CTAs confusos y siempre respaldas tus observaciones con el texto real de la web."
            ),
            verbose=True,
            allow_delegation=False,
            tools=[herramienta_scraping],
            llm=llm
        )

        # 3. Asignación Dinámica: La Tarea lee la URL del Frontend
        tarea_principal = Task(
            description=(
                f"1. Ve con tu ScrapeWebsiteTool y extrae el texto de: {datos.url}\n"
                f"2. A partir de esa extracción, actúa como un experto entendiendo las necesidades de un '{datos.persona}'.\n"
                f"3. Resalta 2 aciertos rotundos de UX y 2 errores graves (con heurísticas violadas) que entorpezcan el '{datos.focus}'.\n"
                "4. Redacta el reporte en formato Markdown."
            ),
            expected_output="Un reporte UX en Markdown impecable.",
            agent=analista_ux
        )

        equipo = Crew(
            agents=[analista_ux],
            tasks=[tarea_principal],
            process=Process.sequential 
        )

        # 4. Lanzamiento Oficial
        resultado = equipo.kickoff()
        
        # Devolver el reporte crudo a la Web App en formato JSON
        return {
            "estado": "exitoso",
            "reporte_markdown": str(resultado) # CrewAI a veces devuelve un objeto, por seguridad lo pasamos a texto
        }

    except Exception as e:
        # Si algo explota (la red se cae, la ruta web no existe), le avisa elegantemente a tu página
        raise HTTPException(status_code=500, detail=str(e))

# Este pedazo sirve si quieres encender el servidor tú mismo en local.
if __name__ == "__main__":
    import uvicorn
    # Levanta un servidor que escuchará en http://localhost:8000
    uvicorn.run(app, host="0.0.0.0", port=8000)
