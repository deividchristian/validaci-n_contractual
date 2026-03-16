from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import docx
import io
import json
import base64
import os
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

app = FastAPI(title="Auditor Legal IA - MVP")

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
        
        prompt = f"""
        Eres un auditor legal experto en normativas bancarias, específicamente DORA y RGPD.
        Tu tarea es analizar el contrato proporcionado y generar un reporte de cumplimiento en formato JSON.

        CRITERIOS RGPD A VALIDAR:
        1. Encargado de tratamiento: Buscar mención a responsable, encargado y finalidad.
        2. Acuerdo de tratamiento de datos (DPA): Buscar instrucciones documentadas, confidencialidad y subencargados.
        3. Transferencias internacionales: Buscar transferencias fuera de la UE o cláusulas tipo.
        4. Seguridad de la información: Buscar medidas técnicas, organizativas, cifrado, control de accesos.
        5. Brechas de seguridad: Buscar obligación de notificación de incidentes en tiempo razonable.

        CRITERIOS DORA A VALIDAR:
        1. Descripción del servicio: Servicios TIC prestados, dependencias, alcance.
        2. SLA: Niveles de servicio, disponibilidad, tiempos de recuperación.
        3. Gestión de incidentes: Procedimiento de notificación, tiempos, responsabilidades.
        4. Derechos de auditoría: Derecho a auditar al proveedor, inspeccionar procesos (Si no está, es Riesgo alto).
        5. Subcontratación: Cláusula sobre subcontratistas TIC y autorización previa.
        6. Estrategia de salida: Plan de salida, migración de servicios, devolución de datos.

        REGLAS DE SALIDA ESTRICTAS:
        Devuelve ÚNICAMENTE un objeto JSON válido con la siguiente estructura exacta:
        {{
          "informacion_basica": {{
            "proveedor": "Nombre extraído o Desconocido",
            "tipo_contrato": "Tipo extraído o Desconocido",
            "duracion": "Duración extraída o No especificada",
            "fecha": "Fecha extraída o No especificada"
          }},
          "cumplimiento_rgpd": [
            {{"control": "Nombre del control", "estado": "OK o Falta o Riesgo o No detectado", "observacion": "Cláusula X o breve motivo"}}
          ],
          "cumplimiento_dora": [
            {{"control": "Nombre del control", "estado": "OK o Falta o Riesgo o No detectado", "observacion": "Cláusula X o breve motivo"}}
          ],
          "resultado_final": {{
            "nivel_cumplimiento": "Alto o Medio o Bajo",
            "recomendacion": "Aprobable o Aprobable con cambios o Revisión legal obligatoria"
          }}
        }}

        CONTRATO A ANALIZAR:
        {texto_completo}
        """

        # ¡AQUÍ ESTÁ LA MAGIA ASÍNCRONA QUE EVITA QUE EL SERVIDOR SE APAGUE!
        respuesta = await modelo.generate_content_async(prompt)
        resultado_json = json.loads(respuesta.text)
        return resultado_json

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en el servidor: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)