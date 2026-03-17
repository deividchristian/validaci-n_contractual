from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import docx
import io
import json
import base64
import os
import asyncio
import google.generativeai as genai

# 1. Configuración de Gemini (De forma segura)
llave_secreta = os.getenv("GEMINI_API_KEY")

if not llave_secreta:
    raise ValueError("No se encontró GEMINI_API_KEY en las variables de entorno.")

genai.configure(api_key=llave_secreta)
modelo = genai.GenerativeModel(
    'gemini-2.5-flash',
    generation_config={"response_mime_type": "application/json"}
)

app = FastAPI(title="Auditor Legal IA - Nivel 2 Multi-Agente")

class PeticionContrato(BaseModel):
    nombre_archivo: str
    archivo_base64: str

@app.post("/auditar-contrato")
async def auditar_contrato(peticion: PeticionContrato):
    if not peticion.nombre_archivo.endswith('.docx'):
        raise HTTPException(status_code=400, detail="Solo se permiten archivos .docx.")
    
    try:
        contenido_binario = base64.b64decode(peticion.archivo_base64)
        documento_io = io.BytesIO(contenido_binario)
        doc = docx.Document(documento_io)
        texto_completo = "\n".join([parrafo.text for parrafo in doc.paragraphs if parrafo.text.strip()])
        
        # ---------------------------------------------------------
        # AGENTE 1: Especialista en Información Básica
        # ---------------------------------------------------------
        prompt_info = f"""
        Extrae la información básica del contrato. 
        Devuelve ÚNICAMENTE un JSON con esta estructura exacta:
        {{
          "proveedor": "Nombre extraído o Desconocido",
          "tipo_contrato": "Tipo extraído o Desconocido",
          "duracion": "Duración extraída o No especificada",
          "fecha": "Fecha extraída o No especificada"
        }}
        CONTRATO A ANALIZAR:
        {texto_completo}
        """

        # ---------------------------------------------------------
        # AGENTE 2: Especialista en RGPD
        # ---------------------------------------------------------
        prompt_rgpd = f"""
        Eres un auditor legal experto en RGPD. Evalúa estos 5 controles:
        1. Encargado de tratamiento
        2. Acuerdo de tratamiento de datos (DPA)
        3. Transferencias internacionales
        4. Seguridad de la información
        5. Brechas de seguridad

        Regla estricta: Extrae una "evidencia_textual" (cita exacta del contrato). Si falta, pon: "No se encontró cláusula."
        Devuelve ÚNICAMENTE un JSON con esta estructura exacta:
        {{
          "cumplimiento_rgpd": [
            {{"control": "Nombre", "estado": "OK o Falta o Riesgo", "observacion": "Breve motivo", "evidencia_textual": "Cita exacta"}}
          ]
        }}
        CONTRATO A ANALIZAR:
        {texto_completo}
        """

        # ---------------------------------------------------------
        # AGENTE 3: Especialista en DORA
        # ---------------------------------------------------------
        prompt_dora = f"""
        Eres un auditor legal experto en DORA. Evalúa estos 6 controles:
        1. Descripción del servicio
        2. SLA
        3. Gestión de incidentes
        4. Derechos de auditoría
        5. Subcontratación
        6. Estrategia de salida

        Regla estricta: Extrae una "evidencia_textual" (cita exacta del contrato). Si falta, pon: "No se encontró cláusula."
        Devuelve ÚNICAMENTE un JSON con esta estructura exacta:
        {{
          "cumplimiento_dora": [
            {{"control": "Nombre", "estado": "OK o Falta o Riesgo", "observacion": "Breve motivo", "evidencia_textual": "Cita exacta"}}
          ]
        }}
        CONTRATO A ANALIZAR:
        {texto_completo}
        """

        # ---------------------------------------------------------
        # ORQUESTADOR: Lanzar los 3 Agentes al mismo tiempo (Paralelismo)
        # ---------------------------------------------------------
        tarea_info = modelo.generate_content_async(prompt_info)
        tarea_rgpd = modelo.generate_content_async(prompt_rgpd)
        tarea_dora = modelo.generate_content_async(prompt_dora)

        # Esperamos a que los 3 expertos terminen su lectura
        resp_info, resp_rgpd, resp_dora = await asyncio.gather(tarea_info, tarea_rgpd, tarea_dora)

        # Convertimos las respuestas a diccionarios
        datos_info = json.loads(resp_info.text)
        datos_rgpd = json.loads(resp_rgpd.text)
        datos_dora = json.loads(resp_dora.text)

        # ---------------------------------------------------------
        # AGENTE 4: El Juez Supremo (Algoritmo Determinista)
        # ---------------------------------------------------------
        # Recopilamos todos los estados ("OK", "Falta", "Riesgo") de ambos reportes
        lista_estados_rgpd = [item["estado"] for item in datos_rgpd.get("cumplimiento_rgpd", [])]
        lista_estados_dora = [item["estado"] for item in datos_dora.get("cumplimiento_dora", [])]
        todos_los_estados = lista_estados_rgpd + lista_estados_dora

        # Contamos matemáticamente los errores (La IA ya no inventa el resultado final)
        total_faltas = todos_los_estados.count("Falta")
        total_riesgos = todos_los_estados.count("Riesgo")

        if total_faltas >= 2 or total_riesgos >= 3:
            nivel = "Bajo"
            recomendacion = "Revisión legal obligatoria"
        elif total_faltas > 0 or total_riesgos > 0:
            nivel = "Medio"
            recomendacion = "Aprobable con cambios"
        else:
            nivel = "Alto"
            recomendacion = "Aprobable"

        # ---------------------------------------------------------
        # ENSAMBLAJE FINAL: Empaquetar todo para Power Automate
        # ---------------------------------------------------------
        json_final = {
            "informacion_basica": datos_info,
            "cumplimiento_rgpd": datos_rgpd.get("cumplimiento_rgpd", []),
            "cumplimiento_dora": datos_dora.get("cumplimiento_dora", []),
            "resultado_final": {
                "nivel_cumplimiento": nivel,
                "recomendacion": recomendacion
            }
        }

        return json_final

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en el servidor: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)