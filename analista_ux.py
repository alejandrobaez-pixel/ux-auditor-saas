import os
import warnings

# Suprimir advertencias generales para mantener limpia la consola
warnings.filterwarnings('ignore')

from crewai import Agent, Task, Crew, Process
from langchain_google_genai import ChatGoogleGenerativeAI
from crewai_tools import ScrapeWebsiteTool

# ==========================================
# 1. SEGURIDAD: Tu Llave al Motor de Google
# ==========================================
# IMPORTANTE: Reemplaza o pega aquí tu clave API correcta de Gemini.
os.environ["GEMINI_API_KEY"] = "TU_CLAVE_API_DE_GEMINI_AQUÍ"

def ejecutar_auditoria():
    print("🧠 Despertando al modelo Gemini (1.5 Pro)...")
    llm = ChatGoogleGenerativeAI(
        model="gemini-1.5-pro",
        verbose=True,
        temperature=0.7 # Tolerancia para ideas creativas (0 = rígido, 1 = disperso)
    )

    # El equivalente a tu subagente navegador actúal, pero corriendo en la nube/servidor
    herramienta_scraping = ScrapeWebsiteTool()

    # ==========================================
# 2. CONFIGURACIÓN DEL "SKILL" Y EL ROL
# ==========================================
    print("👤 Configurando la personalidad de tu Analista UX...")
    analista_ux = Agent(
        role='Analista Senior de Heurísticas UX',
        goal='Auditar interfaces B2B con extrema precisión, rastreando fallos de conversión (CTAs, Arquitectura de Información).',
        backstory=(
            "Llevas 15 años diseñando y evaluando portales B2B complejos. No toleras "
            "sitios web confusos o sin un 'camino feliz' claro para el cliente industrial. "
            "Tus reportes son crudos, directos al grano y siempre basados en datos reales extraídos, "
            "nunca inventas contenido si no está en la página."
        ),
        verbose=True, # Aquí el Agente "habla en voz alta" en la terminal
        allow_delegation=False,
        tools=[herramienta_scraping],
        llm=llm
    )

    # ==========================================
# 3. LA TAREA (El Prompt/Prompt Engineering)
# ==========================================
    print("📋 Asignando la instrucción del día a tu Agente...")
    tarea_analisis_puratos = Task(
        description=(
            "1. Utiliza tu herramienta 'ScrapeWebsiteTool' para navegar meticulosamente la URL: https://www.puratos.com.mx/ \n"
            "2. Identifica inmediatamente cuál es el Headline (H1) que recibe a los usuarios y valora su claridad B2B.\n"
            "3. Explora la navegación principal que ofrece. \n"
            "4. Enumera EXACTAMENTE 2 fortalezas en usabilidad y 2 áreas de mejora críticas (errores heurísticos) que estén afectando el túnel de ventas puro. "
            "El reporte debe ser breve y en español."
        ),
        expected_output="Un reporte en Markdown conciso con fortalezas y debilidades reales basadas en el texto raspado de la web.",
        agent=analista_ux
    )

    # ==========================================
# 4. EL ORQUESTADOR
# ==========================================
    # Si en el futuro integramos más de tus Skills (ej. un Analista SEO, un Redactor), acá es donde se agregan en lista
    equipo = Crew(
        agents=[analista_ux],
        tasks=[tarea_analisis_puratos],
        process=Process.sequential 
    )

    print("\n🚀 ¡Lanzando tu Auditoría fuera de Antigravity!\n")
    print("🌐 Leyendo y Analizando URL...")
    print("--------------------------------------------------")
    
    # Inicia el proceso
    resultado_final = equipo.kickoff()
    
    print("\n==================================================")
    print("📊 REPORTE DE IA TERMINADO CON ÉXITO:")
    print("==================================================")
    print(resultado_final)

if __name__ == "__main__":
    # Chequeo de seguridad para asegurarnos de que has puesto una clave válida.
    if "TU_CLAVE_API_DE_GEMINI_AQUÍ" in os.environ["GEMINI_API_KEY"]:
        print("\n==================================================")
        print("⚠️ ALTO! No has configurado tu clave API.")
        print("==================================================")
        print("Por seguridad, no puse mi clave en tu archivo.")
        print("1. Abre el archivo 'analista_ux.py' en un editor de texto (como VS Code o bloc de notas).")
        print("2. Pega tu propia clave de Gemini en la línea 15 (Donde dice 'TU_CLAVE_API_DE_GEMINI_AQUÍ').")
        print("3. Vuelve a ejecutar este script en tu terminal.")
        print("==================================================\n")
    else:
        ejecutar_auditoria()
