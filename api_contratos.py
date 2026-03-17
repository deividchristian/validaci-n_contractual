from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import docx
import io
import json
import base64
import os
import asyncio
import google.generativeai as genai

llave_secreta = os.getenv("GEMINI_API_KEY")

if not llave_secreta:
    raise ValueError("No se encontró GEMINI_API_KEY en las variables de entorno.")

genai.configure(api_key=llave_secreta)
modelo = genai.GenerativeModel(
    'gemini-2.5-flash',
    generation_config={"response_mime_type": "application/json"}
)

app = FastAPI(title="Auditor Legal IA - Enterprise")

class PeticionContrato(BaseModel):
    nombre_archivo: str
    archivo_base64: str

BASE_LEGAL_RGPD = """
ARTÍCULO 28: El tratamiento por el encargado se regirá por un contrato que estipule que tratará los datos únicamente siguiendo instrucciones documentadas, garantizará confidencialidad, y no subcontratará sin autorización.
ARTÍCULO 32: Aplicar medidas técnicas y organizativas para garantizar un nivel de seguridad adecuado.
ARTÍCULO 33/34: Obligación de notificar violaciones de seguridad sin dilación indebida.
CAPÍTULO V: Prohibida la transferencia de datos fuera del EEE sin garantías adecuadas.
"""

BASE_LEGAL_DORA = """
ARTÍCULO 30: Los acuerdos sobre servicios TIC incluirán:
a) descripción clara de funciones TIC.
b) disposiciones sobre disponibilidad, autenticidad e integridad.
c) Acuerdos de Nivel de Servicio (SLA) cuantitativos.
d) derecho de acceso, inspección y auditoría sin restricciones.
e) obligaciones claras en caso de incidentes.
f) estrategias de salida con periodos de transición obligatorios.
"""

@app.post("/auditar-contrato")
async def auditar_contrato(peticion: PeticionContrato):
    if not peticion.nombre_archivo.endswith('.docx'):
        raise HTTPException(status_code=400, detail="Solo se permiten archivos .docx.")
    
    try:
        contenido_binario = base64.b64decode(peticion.archivo_base64)
        documento_io = io.BytesIO(contenido_binario)
        doc = docx.Document(documento_io)
        texto_completo = "\n".join([parrafo.text for parrafo in doc.paragraphs if parrafo.text.strip()])
        
        prompt_info = f"""
        Extrae la información básica del contrato. 
        Devuelve ÚNICAMENTE un JSON con: proveedor, tipo_contrato, duracion, fecha.
        CONTRATO: {texto_completo}
        """

        prompt_rgpd = f"""
        Eres un auditor legal experto. Evalúa 5 controles: Encargado de tratamiento, DPA, Transferencias, Seguridad, Brechas.
        
        [LEY EUROPEA DE REFERENCIA]
        {BASE_LEGAL_RGPD}
        
        [EJEMPLOS DE CALIBRACIÓN DE LA EMPRESA]
        Ejemplo 1: Si el contrato remite a un "Anexo IV" para el tratamiento de datos pero el anexo no está en el texto.
        Evaluación -> estado: "Riesgo", observacion: "Se menciona un DPA en Anexo IV, pero al no estar adjunto no se puede validar el Art. 28."
        Ejemplo 2: Si no menciona nada sobre transferencias fuera de Europa.
        Evaluación -> estado: "Falta", observacion: "Omisión total sobre transferencias internacionales (Capítulo V)."

        Regla: Extrae "evidencia_textual". Si no hay, pon "No se encontró cláusula".
        Devuelve ÚNICAMENTE un JSON con: {{"cumplimiento_rgpd": [{{"control": "", "estado": "", "observacion": "", "evidencia_textual": ""}}]}}
        CONTRATO: {texto_completo}
        """

        prompt_dora = f"""
        Eres un auditor legal experto. Evalúa 6 controles: Descripción del servicio, SLA, Gestión de incidentes, Derechos de auditoría, Subcontratación, Estrategia de salida.
        
        [NORMATIVA BANCARIA DORA]
        {BASE_LEGAL_DORA}
        
        [EJEMPLOS DE CALIBRACIÓN DE LA EMPRESA]
        Ejemplo 1 (Auditoría): Si el contrato exige "previo aviso" para auditar.
        Evaluación -> estado: "Riesgo", observacion: "Permite auditoría pero exige previo aviso, limitando el acceso sin restricciones que pide DORA."
        Ejemplo 2 (Subcontratación): Si permite subcontratar pero exige autorización previa del cliente.
        Evaluación -> estado: "OK", observacion: "Cumple al exigir control sobre la cadena de subcontratación."

        Regla: Extrae "evidencia_textual". Si no hay, pon "No se encontró cláusula".
        Devuelve ÚNICAMENTE un JSON con: {{"cumplimiento_dora": [{{"control": "", "estado": "", "observacion": "", "evidencia_textual": ""}}]}}
        CONTRATO: {texto_completo}
        """

        tarea_info = modelo.generate_content_async(prompt_info)
        tarea_rgpd = modelo.generate_content_async(prompt_rgpd)
        tarea_dora = modelo.generate_content_async(prompt_dora)

        resp_info, resp_rgpd, resp_dora = await asyncio.gather(tarea_info, tarea_rgpd, tarea_dora)

        datos_info = json.loads(resp_info.text)
        datos_rgpd = json.loads(resp_rgpd.text)
        datos_dora = json.loads(resp_dora.text)

        lista_estados_rgpd = [item["estado"] for item in datos_rgpd.get("cumplimiento_rgpd", [])]
        lista_estados_dora = [item["estado"] for item in datos_dora.get("cumplimiento_dora", [])]
        todos_los_estados = lista_estados_rgpd + lista_estados_dora

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