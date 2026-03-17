from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import docx
import io
import json
import base64
import os
import PyPDF2
import google.generativeai as genai

llave_secreta = os.getenv("GEMINI_API_KEY")

if not llave_secreta:
    raise ValueError("No se encontró GEMINI_API_KEY en las variables de entorno.")

genai.configure(api_key=llave_secreta)
modelo = genai.GenerativeModel(
    'gemini-2.5-flash',
    generation_config={"response_mime_type": "application/json"}
)

app = FastAPI(title="Auditor Legal IA - Enterprise Final")

def leer_pdf_completo(ruta_archivo):
    texto_extraido = ""
    try:
        with open(ruta_archivo, "rb") as archivo:
            lector = PyPDF2.PdfReader(archivo)
            for pagina in lector.pages:
                texto_extraido += pagina.extract_text() + "\n"
    except Exception:
        texto_extraido = "Error al leer el documento legal."
    return texto_extraido

LEY_RGPD_COMPLETA = leer_pdf_completo("RGPD_SPAIN.pdf")
LEY_DORA_COMPLETA = leer_pdf_completo("DORA_SPAIN.pdf")

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
        
        prompt_info = f"""
        Extrae la información básica del contrato. 
        Devuelve ÚNICAMENTE un JSON con: proveedor, tipo_contrato, duracion, fecha.
        CONTRATO: {texto_completo}
        """

        prompt_rgpd = f"""
        Eres un auditor legal experto. Evalúa el contrato contra el texto íntegro del Reglamento General de Protección de Datos (RGPD).
        
        [LEY EUROPEA DE REFERENCIA - TEXTO COMPLETO]
        {LEY_RGPD_COMPLETA}
        
        [EJEMPLOS DE CALIBRACIÓN DE LA EMPRESA]
        Ejemplo 1: Si el contrato remite a un "Anexo IV" para el tratamiento de datos pero el anexo no está en el texto.
        Evaluación -> estado: "Riesgo", observacion: "Falta Anexo IV para validar DPA."
        Ejemplo 2: Si no menciona nada sobre transferencias fuera de Europa.
        Evaluación -> estado: "Falta", observacion: "Omisión total sobre transferencias internacionales."

        Evalúa EXHAUSTIVAMENTE estos 5 controles:
        1. Encargado de tratamiento y Devolución/Destrucción de datos
        2. Acuerdo de tratamiento de datos (DPA)
        3. Transferencias internacionales (Capítulo V)
        4. Seguridad de la información y Notificación de Brechas
        5. Asistencia en Derechos ARCO y Auditorías
        
        REGLAS DE FORMATO ESTRICTAS (¡IMPORTANTE!):
        - 'observacion': Máximo 12 palabras. Ve directo al grano.
        - 'evidencia_textual': DEBES iniciar obligatoriamente indicando la sección o cláusula exacta entre corchetes (Ej: "[Cláusula Segunda]" o "[Anexo IV]"). Luego, escribe máximo 15 palabras de cita usando [...] para acortar. Si falta, pon "No se encontró cláusula."

        Devuelve ÚNICAMENTE un JSON con: {{"cumplimiento_rgpd": [{{"control": "", "estado": "", "observacion": "", "evidencia_textual": ""}}]}}
        CONTRATO: {texto_completo}
        """

        prompt_dora = f"""
        Eres un auditor legal experto. Evalúa el contrato contra el texto íntegro del Reglamento DORA.
        
        [NORMATIVA BANCARIA DORA - TEXTO COMPLETO]
        {LEY_DORA_COMPLETA}
        
        [EJEMPLOS DE CALIBRACIÓN DE LA EMPRESA]
        Ejemplo 1: Si el contrato exige "previo aviso" para auditar.
        Evaluación -> estado: "Riesgo", observacion: "Limita el acceso sin restricciones exigido."
        
        Evalúa EXHAUSTIVAMENTE estos 6 controles:
        1. Descripción de funciones, ubicación de servicio y datos
        2. SLA y Gestión de incidentes TIC
        3. Derechos de acceso y auditoría sin restricciones (locales físicos)
        4. Subcontratación en la cadena de proveedores
        5. Estrategias de salida
        6. Medidas de seguridad TIC
        
        REGLAS DE FORMATO ESTRICTAS (¡IMPORTANTE!):
        - 'observacion': Máximo 12 palabras. Ve directo al grano.
        - 'evidencia_textual': DEBES iniciar obligatoriamente indicando la sección o cláusula exacta entre corchetes (Ej: "[Cláusula Segunda]" o "[Anexo IV]"). Luego, escribe máximo 15 palabras de cita usando [...] para acortar. Si falta, pon "No se encontró cláusula."

        Devuelve ÚNICAMENTE un JSON con: {{"cumplimiento_dora": [{{"control": "", "estado": "", "observacion": "", "evidencia_textual": ""}}]}}
        CONTRATO: {texto_completo}
        """

        resp_info = await modelo.generate_content_async(prompt_info)
        resp_rgpd = await modelo.generate_content_async(prompt_rgpd)
        resp_dora = await modelo.generate_content_async(prompt_dora)

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