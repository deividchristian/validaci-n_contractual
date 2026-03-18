from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import docx
import io
import json
import base64
import os
import PyPDF2
import re
import google.generativeai as genai

# --- CONFIGURACIÓN DE IA ---
llave_secreta = os.getenv("GEMINI_API_KEY")

if not llave_secreta:
    raise ValueError("No se encontró GEMINI_API_KEY en las variables de entorno.")

genai.configure(api_key=llave_secreta)
modelo = genai.GenerativeModel(
    'gemini-2.5-flash',
    generation_config={"response_mime_type": "application/json"}
)

app = FastAPI(title="Auditor Legal IA - Enterprise Final")

# --- CARGA DE LEYES ---
def leer_pdf_completo(ruta_archivo: str) -> str:
    texto_extraido = ""
    if not os.path.exists(ruta_archivo):
        # Es mejor que el programa falle rápido si faltan las leyes base
        raise FileNotFoundError(f"Falta el archivo indispensable: {ruta_archivo}")
        
    try:
        with open(ruta_archivo, "rb") as archivo:
            lector = PyPDF2.PdfReader(archivo)
            for pagina in lector.pages:
                texto_extraido += pagina.extract_text() + "\n"
    except Exception as e:
        raise RuntimeError(f"Error crítico al leer {ruta_archivo}: {str(e)}")
        
    return texto_extraido

# Nota: Cargar leyes enteras en cada prompt consume muchos tokens. 
# Si usas Gemini 1.5/2.5 Flash soporta hasta 1M de tokens, pero impacta la latencia.
LEY_RGPD_COMPLETA = leer_pdf_completo("RGPD_SPAIN.pdf")
LEY_DORA_COMPLETA = leer_pdf_completo("DORA_SPAIN.pdf")

# --- MODELOS DE DATOS ---
class PeticionContrato(BaseModel):
    nombre_archivo: str
    archivo_base64: str

class PeticionPregunta(BaseModel):
    archivo_base64: str
    pregunta: str

# --- FUNCIONES AUXILIARES ---
def procesar_archivo_base64(texto_b64: str) -> str:
    """Filtra la basura de Power Automate, decodifica y extrae el texto del Word."""
    if "contentBytes" in texto_b64:
        try:
            obj = json.loads(texto_b64)
            texto_b64 = obj.get("contentBytes", texto_b64)
        except json.JSONDecodeError:
            pass
            
    try:
        contenido_binario = base64.b64decode(texto_b64)
        documento_io = io.BytesIO(contenido_binario)
        doc = docx.Document(documento_io)
        texto_completo = "\n".join([parrafo.text for parrafo in doc.paragraphs if parrafo.text.strip()])
        return texto_completo
    except Exception as e:
        raise ValueError(f"Error al decodificar o leer el documento Word: {str(e)}")

# --- ENDPOINT 1: LA AUDITORÍA ESTRICTA ---
@app.post("/auditar-contrato")
async def auditar_contrato(peticion: PeticionContrato):
    try:
        texto_completo = procesar_archivo_base64(peticion.archivo_base64)
        
        prompt_maestro = f"""
        Eres un auditor legal experto y MUY ESTRICTO. Evalúa el contrato contra el texto íntegro del Reglamento General de Protección de Datos (RGPD) y el Reglamento DORA.
        
        [LEY EUROPEA DE REFERENCIA RGPD]
        {LEY_RGPD_COMPLETA}
        
        [NORMATIVA BANCARIA DORA]
        {LEY_DORA_COMPLETA}
        
        [CONTRATO A ANALIZAR]
        {texto_completo}
        
        TAREAS OBLIGATORIAS:
        1. Extrae la información básica: proveedor, tipo_contrato, duracion, fecha.
        2. Evalúa EXHAUSTIVAMENTE 5 controles RGPD:
           - Encargado de tratamiento y Devolución/Destrucción de datos
           - Acuerdo de tratamiento de datos (DPA)
           - Transferencias internacionales (Capítulo V)
           - Seguridad de la información y Notificación de Brechas
           - Asistencia en Derechos ARCO y Auditorías
        3. Evalúa EXHAUSTIVAMENTE 6 controles DORA:
           - Descripción de funciones, ubicación de servicio y datos
           - SLA y Gestión de incidentes TIC
           - Derechos de acceso y auditoría sin restricciones (locales físicos)
           - Subcontratación en la cadena de proveedores
           - Estrategias de salida
           - Medidas de seguridad TIC
        
        [EJEMPLOS DE CALIBRACIÓN DE RIESGO - MUY IMPORTANTE]
        Ejemplo 1: Si el contrato remite a un "Anexo IV" o "Documento aparte" para el tratamiento de datos pero el anexo no está en el texto principal.
        -> estado: "Falta", observacion: "Falta Anexo IV para validar DPA."
        Ejemplo 2: Si no menciona nada sobre transferencias fuera de Europa.
        -> estado: "Falta", observacion: "Omisión total sobre transferencias internacionales."
        Ejemplo 3: Si exige "previo aviso" para auditar.
        -> estado: "Riesgo", observacion: "Limita el acceso sin restricciones exigido por DORA."
        Ejemplo 4: Si habla de destrucción de "Información Confidencial" pero no detalla explícitamente "datos personales" según RGPD.
        -> estado: "Riesgo", observacion: "No especifica destrucción de datos personales."
        
        REGLAS DE FORMATO ESTRICTAS:
        - 'estado': DEBE SER EXACTAMENTE UNA DE ESTAS 3 PALABRAS: "OK", "Falta", o "Riesgo". (No uses "Cumple" ni "Parcialmente cumple").
        - 'observacion': Máximo 12 palabras. Ve directo al grano.
        - 'evidencia_textual': DEBES iniciar obligatoriamente indicando la sección o cláusula exacta entre corchetes (Ej: "[Cláusula Segunda]" o "[Anexo IV]"). Luego, escribe máximo 15 palabras de cita usando [...] para acortar. Si falta, pon "No se encontró cláusula."

        Devuelve ÚNICAMENTE un JSON con esta estructura:
        {{
          "informacion_basica": {{ "proveedor": "", "tipo_contrato": "", "duracion": "", "fecha": "" }},
          "cumplimiento_rgpd": [ {{"control": "", "estado": "", "observacion": "", "evidencia_textual": ""}} ],
          "cumplimiento_dora": [ {{"control": "", "estado": "", "observacion": "", "evidencia_textual": ""}} ]
        }}
        """

        respuesta = await modelo.generate_content_async(prompt_maestro)
        datos = json.loads(respuesta.text)

        lista_estados_rgpd = [item.get("estado", "OK") for item in datos.get("cumplimiento_rgpd", [])]
        lista_estados_dora = [item.get("estado", "OK") for item in datos.get("cumplimiento_dora", [])]
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

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")


# --- ENDPOINT 2: EL NUEVO CHATBOT CONVERSACIONAL (BLINDADO) ---
@app.post("/preguntar-contrato")
async def preguntar_contrato(peticion: PeticionPregunta):
    try:
        # 1 y 2. Limpieza y lectura extraídas a la función auxiliar
        texto_completo = procesar_archivo_base64(peticion.archivo_base64)
        
        # 3. Prompt Estricto
        prompt_qa = f"""
        Eres un asistente legal experto. Responde a la pregunta basándote EXCLUSIVAMENTE en el contrato proporcionado.
        REGLAS:
        1. NO uses información de internet.
        2. Si no está en el contrato, responde: "La información solicitada no se encuentra detallada en este contrato."
        3. MUY IMPORTANTE: Resume la respuesta. NUNCA superes las 150 palabras.
        
        [CONTRATO]
        {texto_completo}
        
        [PREGUNTA DEL USUARIO]
        {peticion.pregunta}
        
        Devuelve ÚNICAMENTE un JSON con esta estructura:
        {{
          "respuesta": "tu respuesta aquí"
        }}
        """
        
        respuesta = await modelo.generate_content_async(prompt_qa)
        datos = json.loads(respuesta.text)
        
        # 4. EL BLINDAJE DEFINITIVO (Mejorado)
        respuesta_cruda = datos.get("respuesta", "")
        
        # A) Guillotina
        if len(respuesta_cruda) > 1500:
            respuesta_cruda = respuesta_cruda[:1497] + "..."
            
        # B) Regex mejorado: Ahora permite comillas (""), corchetes ([]), y el símbolo de porcentaje (%). 
        texto_limpio = re.sub(r'[^\w\s.,;:!?()\'"\[\]%áéíóúÁÉÍÓÚñÑüÜ-]', '', respuesta_cruda)
        
        # C) Eliminamos todos los saltos de línea
        texto_limpio = texto_limpio.replace('\n', ' ').replace('\r', ' ')
        
        # D) Normalizamos los espacios
        texto_limpio = " ".join(texto_limpio.split()) 
        
        datos["respuesta"] = texto_limpio
        return datos

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)