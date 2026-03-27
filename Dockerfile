# Usa la imagen oficial de Playwright que ya incluye Chromium y sus dependencias (fuentes, librerías del sistema)
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Copiar configuración e instalar librerías Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Asegurar la instalación binaria de Chromium (por si acaso la imagen base requiere el paso)
RUN playwright install chromium

# Copiar el servior
COPY . .

# Exponer el puerto
EXPOSE 10000

# Render inyecta la variable $PORT dinámicamente. Levantamos Uvicorn en ese puerto.
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}
