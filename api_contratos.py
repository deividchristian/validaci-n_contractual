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
        
        prompt_maestro = f"""
        Eres un auditor legal experto. Evalúa el contrato contra el texto íntegro del Reglamento General de Protección de Datos (RGPD) y el Reglamento DORA.
        
        [LEY EUROPEA DE REFERENCIA RGPD]
        {LEY_RGPD_COMPLETA}
        
        [NORMATIVA BANCARIA DORA]
        {LEY_DORA_COMPLETA}
        
        [CONTRATO A ANALIZAR]
        {texto_completo}
        
        TAREAS OBLIGATORIAS:
        1. Extrae la información básica: proveedor, tipo_contrato, duracion, fecha.
        2. Evalúa 5 controles RGPD: Encargado de tratamiento y Devolución/Destrucción, DPA, Transferencias internacionales, Seguridad y Brechas, Asistencia en Derechos ARCO y Auditorías.
        3. Evalúa 6 controles DORA: Descripción de funciones y ubicación, SLA y Gestión de incidentes, Derechos de acceso y auditoría sin restricciones, Subcontratación, Estrategias de salida, Medidas de seguridad TIC.
        
        [EJEMPLOS DE CALIBRACIÓN]
        - Si el contrato remite a un "Anexo IV" para datos pero no está adjunto -> estado: "Riesgo", observacion: "Falta Anexo IV para validar DPA."
        - Si exige "previo aviso" para auditar -> estado: "Riesgo", observacion: "Limita el acceso sin restricciones exigido."
        
        REGLAS DE FORMATO ESTRICTAS:
        - 'observacion': Máximo 12 palabras.
        - 'evidencia_textual': DEBES iniciar indicando la sección exacta entre corchetes (Ej: "[Cláusula Segunda]"). Luego, máximo 15 palabras de cita usando [...]. Si falta, pon "No se encontró cláusula."
        
        Devuelve ÚNICAMENTE un JSON con esta estructura:
        {{
          "informacion_basica": {{ "proveedor": "", "tipo_contrato": "", "duracion": "", "fecha": "" }},
          "cumplimiento_rgpd": [ {{"control": "", "estado": "", "observacion": "", "evidencia_textual": ""}} ],
          "cumplimiento_dora": [ {{"control": "", "estado": "", "observacion": "", "evidencia_textual": ""}} ]
        }}
        """

        respuesta = await modelo.generate_content_async(prompt_maestro)
        datos = json.loads(respuesta.text)

        lista_estados_rgpd = [item["estado"] for item in datos.get("cumplimiento_rgpd", [])]
        lista_estados_dora = [item["estado"] for item in datos.get("cumplimiento_dora", [])]
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

        datos["resultado_final"] = {
            "nivel_cumplimiento": nivel,
            "recomendacion": recomendacion
        }

        return datos

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en el servidor: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)