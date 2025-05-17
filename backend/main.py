import os
import json # Ajout de l'import json
import asyncio # For running sync Gemini in async FastAPI
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import base64
import traceback
from dotenv import load_dotenv
# --- Importer les clients nécessaires --- 
from mistralai import Mistral # Kept for OCR
# from groq import Groq # To be replaced by Gemini
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

# --- Importer les exceptions spécifiques ---
# Importer `models` pour accéder aux exceptions SDKError et HTTPValidationError
from mistralai import models as mistral_models 

# from groq import APIError as GroqAPIError # To be replaced

# Import pour manipuler les images et conversion
from io import BytesIO
from PIL import Image
import tempfile

# Ajouter ces imports pour la compilation du code C
import subprocess
import os
import re

# Importer Optional depuis typing
from typing import Optional

# Charger les variables d'environnement depuis .env
load_dotenv()

# --- Récupérer les clés API depuis les variables d'environnement ---
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
# GROQ_API_KEY = os.getenv("GROQ_API_KEY") # Commented out
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- Initialiser les clients API --- 
mistral_client = None
if MISTRAL_API_KEY:
    try:
        mistral_client = Mistral(api_key=MISTRAL_API_KEY)
        print("Client Mistral initialisé.")
    except Exception as e:
        print(f"CRITICAL: Erreur initialisation client Mistral: {e}")
else:
    print("CRITICAL: Clé API Mistral (MISTRAL_API_KEY) manquante dans .env. OCR Mistral désactivé.")

# groq_client = None # Commented out
# if GROQ_API_KEY:
#     try:
#         groq_client = Groq(api_key=GROQ_API_KEY)
#         print("Client Groq initialisé.")
#     except Exception as e:
#         print(f"CRITICAL: Erreur initialisation client Groq: {e}")
# else:
#     print("CRITICAL: Clé API Groq (GROQ_API_KEY) manquante dans .env. Analyse LLM Groq désactivée.")

gemini_model = None
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel("gemini-2.5-flash-preview-04-17") # Updated model
        print("Modèle Gemini initialisé (gemini-2.5-flash-preview-04-17).")
    except Exception as e:
        print(f"CRITICAL: Erreur initialisation modèle Gemini: {e}")
else:
    print("CRITICAL: Clé API Gemini (GEMINI_API_KEY) manquante dans .env. Analyse LLM Gemini désactivée.")


# Modèle Pydantic pour la requête (pas besoin des clés ici, elles sont dans .env)
class CropArea(BaseModel):
    x: int
    y: int
    width: int
    height: int
    dpr: float = 1.0

class AnalyzeRequest(BaseModel):
    imageData: str # Base64 encoded image data
    cropArea: Optional[CropArea] = None
    expectedOutputLines: Optional[int] = None

# Modèle Pydantic pour la réponse
class QAPair(BaseModel):
    question: str
    answer: str = "" 
    question_type: str = "course" # "code" ou "course"
    language_detected: Optional[str] = None # To store detected language for code
    
class AnalyzeResponse(BaseModel):
    results: list[QAPair]

app = FastAPI()

# Configuration CORS
origins = ["*"] # Permissif pour le dev, à restreindre en prod

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Backend MoodleAI OCR/LLM"}

@app.post("/analyze_screenshot", response_model=AnalyzeResponse)
async def analyze_screenshot(request: Request):
    """
    Endpoint pour recevoir une image (base64), l'analyser via OCR puis LLM.
    """
    print("Requête reçue sur /analyze_screenshot")
    
    # Vérifier si les clients sont initialisés
    if not mistral_client:
        raise HTTPException(status_code=503, detail="Service OCR (Mistral) non disponible côté backend.")
    # if not groq_client: # Commented out
    #     raise HTTPException(status_code=503, detail="Service LLM (Groq) non disponible côté backend.")
    if not gemini_model:
        raise HTTPException(status_code=503, detail="Service LLM (Gemini) non disponible côté backend.")
    
    try:
        body = await request.json()
        image_data = body.get("imageData", "")
        crop_area_data = body.get("cropArea", None) # Renamed to avoid conflict
        expected_lines = body.get("expectedOutputLines", None)
        print(f"Nombre de lignes d'output attendu (depuis requête): {expected_lines}")
        
        # 1. Décoder et traiter l'image
        try:
            base64_data = image_data.split(',')[1] if ',' in image_data else image_data
            image_data_bytes = base64.b64decode(base64_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Format image invalide: {e}")

        image = Image.open(BytesIO(image_data_bytes))
        if crop_area_data: # Use renamed variable
            try:
                dpr = crop_area_data.get("dpr", 1.0)
                x, y, w, h = int(crop_area_data["x"]*dpr), int(crop_area_data["y"]*dpr), int(crop_area_data["width"]*dpr), int(crop_area_data["height"]*dpr)
                if w <= 0 or h <= 0: raise ValueError("Dimensions invalides")
                image = image.crop((x, y, x + w, y + h))
                print(f"Image recadrée: {image.size}px")
            except Exception as e:
                print(f"Erreur recadrage: {e}, utilisation image complète.")

        # 2. OCR
        pdf_bytes = convert_image_to_pdf(image)
        ocr_text = await perform_ocr(pdf_bytes)
        if not ocr_text or ocr_text.isspace():
            print("OCR a retourné un texte vide.")
            return AnalyzeResponse(results=[])
        print(f"Texte OCR (longueur): {len(ocr_text)}")

        # 3. Nouvelle logique d'analyse basée sur expected_lines
        analysis_results = await analyze_ocr_content(ocr_text, expected_lines=expected_lines)
        print(f"Analyse OCR terminée, {len(analysis_results)} résultats.")

        return AnalyzeResponse(results=analysis_results)

    except HTTPException as http_exc:
        raise http_exc 
    except Exception as e:
        print(f"Erreur inattendue: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {e}")

def convert_image_to_pdf(image):
    """
    Convertit une image PIL en PDF pour l'OCR Mistral
    """
    print("Conversion de l'image en PDF pour l'OCR Mistral")
    pdf_buffer = BytesIO()
    
    # Convertir en RGB si nécessaire (pour éviter les erreurs avec les images RGBA)
    if image.mode == 'RGBA':
        image = image.convert('RGB')
    
    # Sauvegarder l'image au format PDF
    image.save(pdf_buffer, 'PDF')
    
    # Récupérer les bytes du PDF
    pdf_bytes = pdf_buffer.getvalue()
    print(f"Conversion en PDF terminée, taille: {len(pdf_bytes)} bytes")
    
    return pdf_bytes

# --- Fonctions Helper --- 

async def perform_ocr(pdf_bytes: bytes) -> str:
    """
    Effectue l'OCR sur les bytes du PDF en utilisant l'API Mistral.
    """
    print("--- Début OCR (Mistral) ---")
    if not mistral_client:
        print("Erreur: Tentative d'appel OCR sans client Mistral initialisé.")
        # Lever une exception interne ou SDKError si approprié
        raise mistral_models.SDKError("Client Mistral non configuré.") 

    uploaded_file = None 
    try:
        temp_filename = "document.pdf" # Utiliser l'extension PDF
        uploaded_file = mistral_client.files.upload(
            file={"file_name": temp_filename, "content": pdf_bytes},
            purpose="ocr"
        )
        print(f"Fichier uploadé pour OCR: {uploaded_file.id}")
        
        signed_url_response = mistral_client.files.get_signed_url(file_id=uploaded_file.id)
        signed_url = signed_url_response.url
        print("URL signée obtenue pour OCR.")
    
        ocr_response = mistral_client.ocr.process(
            model="mistral-ocr-latest", 
            document={"type": "document_url", "document_url": signed_url}
        )
        print(f"Réponse OCR reçue. Pages traitées: {ocr_response.usage_info.pages_processed}")
        
        ocr_text_result = "\n\n".join([page.markdown for page in ocr_response.pages])
        
        try:
            client_response = mistral_client.files.delete(file_id=uploaded_file.id)
            if client_response.deleted:
                 print(f"Fichier temporaire OCR {uploaded_file.id} supprimé avec succès.")
            else:
                 print(f"Avertissement: La suppression du fichier temporaire OCR {uploaded_file.id} a échoué selon l'API.")
        except Exception as del_e:
            print(f"Avertissement: échec lors de la tentative de suppression du fichier temporaire OCR {uploaded_file.id}: {del_e}")
            
        print("--- Fin OCR (Mistral) ---")
        return ocr_text_result
        
    # Attraper les erreurs Mistral spécifiques
    except mistral_models.SDKError as e: # <--- Utilisation de SDKError
        print(f"Erreur SDK Mistral pendant l'OCR: {e}")
        if uploaded_file:
            try: mistral_client.files.delete(file_id=uploaded_file.id)
            except Exception as del_e2: print(f"Avertissement: échec nettoyage fichier OCR {uploaded_file.id} après erreur: {del_e2}")
        raise e # Relancer pour la gestion centralisée
    except Exception as e:
        print(f"Erreur inattendue pendant l'OCR: {e}")
        traceback.print_exc()
        if uploaded_file:
             try: mistral_client.files.delete(file_id=uploaded_file.id)
             except Exception as del_e2: print(f"Avertissement: échec nettoyage fichier OCR {uploaded_file.id} après erreur: {del_e2}")
        raise HTTPException(status_code=500, detail=f"Erreur inattendue lors du processus OCR: {e}")

async def analyze_ocr_content(ocr_text: str, expected_lines: Optional[int] = None) -> list[QAPair]:
    """
    Analyse le contenu OCR.
    Si expected_lines est fourni:
        1. Détecte le langage (JS, HTML, CSS, PHP) et extrait le code.
        2. Pour JS/PHP: Tente d'exécuter avec une boucle de correction (1 correction).
        3. Pour HTML/CSS: Formatte et décrit le code.
        4. Formatte la réponse finale.
    Sinon (pas d'expected_lines): traite comme du contenu de cours.
    """
    # if not groq_client: raise GroqAPIError("Client Groq non configuré.") # Commented out
    if not gemini_model: raise HTTPException(status_code=503, detail="Client Gemini non configuré pour analyze_ocr_content.")
    if not ocr_text or ocr_text.isspace(): return []

    qa_pair = QAPair(question="") # Initialisation
    final_answer = "[Traitement de la requête a échoué]" # Default error

    if expected_lines is not None: 
        qa_pair.question_type = "code" 
        print(f"--- Traitement comme CODE (expected_lines = {expected_lines}) ---")
        
        # --- LLM Call 1: Détection de Langage et Extraction de Code ---
        print("  -> LLM Étape 1: Détection Langage & Extraction Code...")
        # Prompt pour la détection et extraction
        # Traduction du prompt pour détection/extraction
        prompt_detect_extract = f'''
Analysez le texte OCR suivant :
"""
{ocr_text}
"""
Tâche :
1. Identifiez le langage de programmation principal (javascript, php, html, css, ou 'other' si non reconnu ou mixte).
2. Extrayez le bloc de code principal correspondant. Le code extrait doit être une chaîne JSON valide, ce qui signifie que les backslashes (\\\\) et les guillemets (\\") doivent être échappés (\\\\\\\\ et \\\\\\") et les nouvelles lignes doivent être représentées par \\\\n.
3. Répondez UNIQUEMENT avec un objet JSON contenant les clés "language" et "code".
   Exemple de réponse pour du code sur une seule ligne : {{"language": "javascript", "code": "console.log(\\'Hello World!\\');"}}
   Exemple de réponse pour du code sur plusieurs lignes : {{"language": "php", "code": "$name = \\\\"Monde\\\\";\\\\necho \\\\"Bonjour $name!\\\\";"}}
   Si aucun code n'est trouvé ou si le langage n'est pas clair, utilisez "language": "none", "code": "".

JSON Réponse :
'''
        detected_language = "none"
        extracted_code = ""
        try:
            # response_json_str = await call_groq_llm(prompt_detect_extract, is_json_output_expected=True) # Commented out
            response_json_str = await call_gemini_llm(prompt_detect_extract, is_json_output_expected=True)
            response_data = json.loads(response_json_str)
            detected_language = response_data.get("language", "none").lower()
            extracted_code = response_data.get("code", "")
            qa_pair.language_detected = detected_language
            print(f"    -> Langage Détecté: {detected_language}, Code Extrait (longueur): {len(extracted_code)}")
        except Exception as e:
            print(f"    -> Erreur LLM Étape 1 (Détection/Extraction): {e}")
            final_answer = f"[Erreur LLM lors de la détection du langage: {e}]"
            qa_pair.answer = final_answer
            return [qa_pair]

        if detected_language == "none" or not extracted_code.strip():
            final_answer = "[Aucun code pertinent trouvé dans le texte OCR]"
            qa_pair.question = "Analyse de Code (aucun code trouvé)"
            qa_pair.answer = final_answer
            return [qa_pair]

        qa_pair.question = f"Analyse de code {detected_language.upper()}"
        current_code_to_process = clean_llm_code_output(extracted_code) # Nettoyer le code extrait

        # --- Traitement Spécifique par Langage ---
        max_attempts = 2 # 1 exécution initiale + 1 correction
        
        if detected_language in ["javascript", "php"]:
            exec_function = run_js_code if detected_language == "javascript" else run_php_code
            lang_name_for_prompt = "JavaScript" if detected_language == "javascript" else "PHP"

            for attempt in range(max_attempts):
                print(f"  -> Tentative Exécution {lang_name_for_prompt} {attempt + 1}/{max_attempts}...")
                exec_result = exec_function(current_code_to_process)
                print(f"    -> Résultat Exécution: {exec_result['status']}")

                if exec_result['status'] == 'executed':
                    print(f"  -> LLM Étape Finale ({lang_name_for_prompt} OK): Formatage Réponse...")
                    # Prompt pour formater la réponse finale (code OK)
                    prompt_final_answer_code = f"""
Contexte: Le code {lang_name_for_prompt} suivant a été exécuté :
Code Exécuté :
\`\`\`{detected_language}
{exec_result['formatted_code']}
\`\`\`
Sortie d'Exécution :
{exec_result['output'] if exec_result['output'] else 'Aucune sortie'}
Nombre de lignes attendues par l'utilisateur : {expected_lines}

Tâche: Fournissez UNIQUEMENT la sortie d'exécution, formatée pour correspondre au nombre de lignes attendues.
N'ajoutez aucune explication, seulement la sortie. Si vide, répondez "(Aucune sortie produite)".
Réponse :
"""
                    try:
                        # final_answer_text = await call_groq_llm(prompt_final_answer_code, is_json_output_expected=False) # Commented out
                        final_answer_text = await call_gemini_llm(prompt_final_answer_code, is_json_output_expected=False)
                        final_answer = final_answer_text.strip()
                        print(f"    -> Réponse LLM (Code OK) obtenue.")
                        break # Succès
                    except Exception as e:
                        print(f"    -> Erreur LLM Étape Finale (Formatage): {e}")
                        final_answer = f"[Erreur LLM pour la réponse finale du code: {e}]"
                        break 
                else: # Erreur d'exécution
                    if attempt < max_attempts - 1:
                        print(f"  -> LLM Étape Correction ({lang_name_for_prompt} Échoué): Tentative de Correction...")
                        # Prompt pour correction de code
                        prompt_fix_code = f"""
Le code {lang_name_for_prompt} suivant a produit une erreur :
Code Échoué :
\`\`\`{detected_language}
{exec_result['formatted_code']}
\`\`\`
Erreur d'Exécution ({exec_result['status']}) :
{exec_result['output']}

Tâche: Corrigez le code pour résoudre l'erreur. Retournez UNIQUEMENT le code {lang_name_for_prompt} corrigé et brut.
Code Corrigé :
"""
                        try:
                            # corrected_code_raw = await call_groq_llm(prompt_fix_code, is_json_output_expected=False) # Commented out
                            corrected_code_raw = await call_gemini_llm(prompt_fix_code, is_json_output_expected=False)
                            current_code_to_process = clean_llm_code_output(corrected_code_raw)
                            if not current_code_to_process:
                                print("    -> LLM n'a pas retourné de code corrigé.")
                                final_answer = f"[Échec de la correction du code {lang_name_for_prompt} par LLM]"
                                break # Sortir de la boucle de tentative
                            print(f"    -> Code {lang_name_for_prompt} corrigé par LLM, nouvelle tentative...")
                        except Exception as e:
                            print(f"    -> Erreur LLM Étape Correction: {e}")
                            final_answer = f"[Erreur LLM lors de la tentative de correction du code: {e}]"
                            break # Sortir de la boucle de tentative
                    else:
                        final_answer = f"[Échec d'exécution du code {lang_name_for_prompt} après {max_attempts} tentatives. Erreur: {exec_result['output']}]"
                        break # Fin des tentatives

        elif detected_language in ["html", "css"]:
            lang_name_for_prompt = "HTML" if detected_language == "html" else "CSS"
            print(f"  -> LLM Étape Finale ({lang_name_for_prompt}): Formatage et Description...")
            # Prompt pour HTML/CSS
            prompt_format_describe_static = f"""
Le code {lang_name_for_prompt} suivant a été extrait :
\`\`\`{detected_language}
{current_code_to_process}
\`\`\`
Tâche:
1. Formattez ce code {lang_name_for_prompt} proprement.
2. Fournissez une brève description de ce que fait ce code ou de ce qu'il représente.
Répondez avec le code formaté, suivi de "---DESCRIPTION---", puis la description.
Réponse :
"""
            try:
                # response_text = await call_groq_llm(prompt_format_describe_static, is_json_output_expected=False) # Commented out
                response_text = await call_gemini_llm(prompt_format_describe_static, is_json_output_expected=False)
                parts = response_text.split("---DESCRIPTION---", 1)
                formatted_code = parts[0].strip()
                description = parts[1].strip() if len(parts) > 1 else "Aucune description fournie."
                final_answer = f"Code {lang_name_for_prompt} Formaté:\n{formatted_code}\n\nDescription:\n{description}"
                print(f"    -> Réponse LLM ({lang_name_for_prompt}) obtenue.")
            except Exception as e:
                print(f"    -> Erreur LLM ({lang_name_for_prompt}): {e}")
                final_answer = f"[Erreur LLM lors du formatage/description du code {lang_name_for_prompt}: {e}]"
        
        else: # 'other' ou non géré
            print(f"  -> Langage '{detected_language}' non supporté pour exécution/traitement spécifique.")
            final_answer = f"[Langage '{detected_language}' détecté mais non supporté pour un traitement avancé. Code extrait:\n{current_code_to_process[:1000]}]"

        qa_pair.answer = final_answer

    else: 
        # --- Traitement comme COURS --- 
        qa_pair.question = "Analyse du Contenu du Cours"
        qa_pair.question_type = "course"
        print("--- Traitement comme COURS (expected_lines non fourni) ---")
        
        prompt_answer_course = f"""
Analysez le texte suivant extrait d'une capture d'écran de matériel de cours.
Votre objectif principal est d'identifier une question (explicite ou implicite) et de fournir UNIQUEMENT sa réponse la plus directe et unique.

Si vous identifiez une seule réponse claire et certaine :
Fournissez cette unique réponse, sans aucune explication supplémentaire.

Si vous hésitez entre plusieurs réponses distinctes OU si plusieurs réponses semblent également valides :
Listez chaque proposition de réponse. Pour chaque proposition, expliquez brièvement (en 1-2 phrases) pourquoi elle pourrait être correcte.
Formattez comme suit :
PROPOSITION 1: [Texte de la réponse 1]
JUSTIFICATION 1: [Explication pour la réponse 1]

PROPOSITION 2: [Texte de la réponse 2]
JUSTIFICATION 2: [Explication pour la réponse 2]
(et ainsi de suite pour d'autres propositions si nécessaire)

Si le texte ne contient pas de question claire ou si aucune réponse pertinente ne peut être extraite :
Répondez par : '(Pas de question directe ou réponse trouvée)'

Ne reformulez pas la question. Ne donnez pas de résumé général du texte.

Contenu du Texte :
---
{ocr_text}
---

Réponse(s) et Justification(s) (si applicable) :
"""
        try:
            # answer_text = await call_groq_llm(prompt_answer_course, is_json_output_expected=False) # Commented out
            answer_text = await call_gemini_llm(prompt_answer_course, is_json_output_expected=False)
            qa_pair.answer = answer_text.strip()
            print(f"  -> Réponse LLM (Cours) obtenue.")
        except Exception as e:
            print(f"Erreur LLM Réponse Cours: {e}")
            qa_pair.answer = f"[Erreur analyse LLM Cours: {e}]"

    return [qa_pair]

def clean_llm_code_output(raw_code: str) -> str:
    """Nettoie la sortie de code du LLM en supprimant les marqueurs Markdown."""
    cleaned = raw_code
    # Supprimer les marqueurs de début/fin ```javascript ou ```js ou ```
    cleaned = re.sub(r'^```(?:javascript|js)?\s*\n?', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\n?```$\n?', '', cleaned)
    return cleaned.strip() # Supprimer aussi les espaces/lignes vides autour

async def call_gemini_llm(prompt_content: str, is_json_output_expected: bool) -> str:
    """
    Helper pour appeler l'API Gemini et gérer les erreurs communes.
    Utilise le modèle gemini-2.5-flash-preview-04-17.
    """
    if not gemini_model:
        print("Erreur: Tentative d'appel LLM Gemini sans modèle initialisé.")
        raise HTTPException(status_code=503, detail="Modèle Gemini non configuré.")

    try:
        # Le system_message est maintenant intégré dans prompt_content par la logique appelante
        # ou géré par les instructions spécifiques dans prompt_content.
        
        generation_config = None
        effective_prompt = prompt_content

        # Gemini utilise response_mime_type pour le mode JSON.
        # Le rôle "system" est géré soit par system_instruction au niveau du modèle,
        # soit en l'intégrant au début du prompt utilisateur.
        # Ici, les prompts existants sont déjà assez directifs.
        
        # Construction du message système à préfixer si besoin (pour plus de clarté)
        # Cela reprend l'idée du system_message de l'ancienne fonction Groq
        system_prefix = ""
        if is_json_output_expected:
            system_prefix = "Vous êtes un générateur JSON expert. Répondez UNIQUEMENT avec le JSON valide demandé. N'incluez aucun autre texte, explication ou formatage Markdown. Assurez-vous que toutes les chaînes, en particulier celles sur plusieurs lignes, sont correctement échappées selon les normes JSON.\\n\\n"
            generation_config = genai.types.GenerationConfig(
                response_mime_type="application/json"
            )
        else:
            system_prefix = "Vous êtes un assistant utile.\\n\\n"
            # Pour la sortie texte, pas de config spéciale de mime_type par défaut

        final_prompt_for_gemini = system_prefix + prompt_content
        
        print(f"Appel LLM Gemini (Modèle: gemini-2.5-flash-preview-04-17, JSON attendu: {is_json_output_expected})...")
        
        # Gemini SDK est synchrone, exécutez-le dans un thread pour ne pas bloquer l'event loop FastAPI
        response = await asyncio.to_thread(
            gemini_model.generate_content,
            final_prompt_for_gemini,
            generation_config=generation_config
        )
        
        response_text = response.text # Gemini met directement le texte (ou JSON str) ici
        print(f"Réponse LLM Gemini reçue (longueur: {len(response_text)}).")

        if is_json_output_expected:
            # La logique de réparation JSON existante peut toujours être utile,
            # même si Gemini est censé retourner du JSON valide en mode JSON.
            print(f"Tentative de validation/réparation JSON de la réponse Gemini: '{response_text[:100]}...'")
            
            # En mode JSON, Gemini devrait retourner une chaîne JSON directement.
            # Si response.text n'est pas un JSON valide, la réparation est tentée.
            try:
                json.loads(response_text)
                print(f"JSON Gemini validé directement: '{response_text[:200]}...'")
                return response_text
            except json.JSONDecodeError as e_initial_parse:
                print(f"JSON Gemini (\'{response_text[:100]}...\') invalide: {e_initial_parse}. Tentative de réparation...")
                repaired_json = response_text
                
                if repaired_json.endswith("..."): # Cas où le LLM tronque avec "..."
                    repaired_json = repaired_json[:-3].rstrip()
                    print(f"  Réparation (suppression \'...\'): \'{repaired_json[:100]}...\'")

                # Remplacer les nouvelles lignes non échappées (plus simple que la version précédente)
                # Attention à ne pas double-échapper si le LLM a parfois raison
                # Cette logique est simplifiée : si \n est là et que ce n'est pas \\n, on le transforme.
                # Peut nécessiter un ajustement plus fin si le LLM est incohérent.
                if '\\n' in repaired_json and not re.search(r'(?<!\\)\\n', repaired_json.replace('\\\\','')): # Heuristique
                     pass # Si \n est déjà là (correctement ou incorrectement), on ne touche plus pour l'instant
                elif '\n' in repaired_json:
                    repaired_json = repaired_json.replace('\n', '\\\\n')
                    print(f"  Réparation (remplacement \\n -> \\\\\\\\n): \'{repaired_json[:100]}...\'")
                
                if '\\r' in repaired_json and not re.search(r'(?<!\\)\\r', repaired_json.replace('\\\\','')):
                     pass
                elif '\r' in repaired_json:
                    repaired_json = repaired_json.replace('\r', '\\\\r')
                    print(f"  Réparation (remplacement \\r -> \\\\\\\\r): \'{repaired_json[:100]}...\'")

                try:
                    json.loads(repaired_json)
                    print(f"JSON Gemini réparé et validé: '{repaired_json[:200]}...'")
                    return repaired_json
                except json.JSONDecodeError as e_repair_failed:
                    print(f"Échec de la réparation du JSON Gemini ('{repaired_json[:100]}...'): {e_repair_failed}.")
                    print(f"Retourne la réponse texte originale de Gemini qui a échoué à parser: '{response_text[:200]}...'")
                    # Retourner le texte original, car c'est ce que Gemini a donné.
                    # La fonction appelante (analyze_ocr_content) tentera json.loads() et gérera l'erreur.
                    return response_text 
        else: # Si pas de JSON attendu, retourner le texte brut
            return response_text

    except google_exceptions.GoogleAPIError as e:
        print(f"Erreur API Gemini: {e}")
        # Vous pouvez mapper cela à une HTTPException si nécessaire, par exemple:
        # raise HTTPException(status_code=500, detail=f"Erreur API Gemini: {e}")
        raise e # Relancer pour une gestion plus haut niveau ou débogage
    except Exception as e:
        print(f"Erreur inattendue appel LLM Gemini: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Erreur inattendue lors de l'appel LLM Gemini: {e}")

def format_js_code(code):
    """
    Formatage basique du code Javascript.
    (Utilise une indentation similaire à la fonction C pour la simplicité)
    """
    formatted = []
    indent_level = 0
    indent_chars = '    ' # 4 espaces
    for line in code.split('\n'):
        stripped = line.strip()
        
        # Gérer la désindentation avant d'ajouter la ligne
        if stripped.startswith('}') or stripped.startswith(')') or stripped.startswith(']'):
            indent_level = max(0, indent_level - 1)
            
        if stripped: # Ne pas ajouter de lignes vides indentées
             formatted.append(indent_chars * indent_level + stripped)
        else:
             formatted.append('') # Garder les lignes vides
        
        # Gérer l'indentation après avoir ajouté la ligne
        if stripped.endswith('{') or stripped.endswith('(') or stripped.endswith('['):
            indent_level += 1
        # Cas spécifique pour les blocs sans accolades (if, for, while...)
        elif stripped.endswith(':') and indent_level == 0 : # Début de bloc potentiel sans {}
             pass # L'indentation est gérée par la ligne suivante
             
    return '\n'.join(formatted)

def run_js_code(code):
    """
    Exécute un extrait de code Javascript avec Node.js.
    Retourne un dict avec le code formaté, le statut et la sortie d'exécution.
    """
    result = {
        'formatted_code': format_js_code(code),
        'output': '',
        'status': 'not_executed'
    }
    temp_filepath = None
    try:
        # Créer un fichier temporaire pour le code JS
        with tempfile.NamedTemporaryFile(suffix='.js', delete=False, mode='w', encoding='utf-8') as temp_file:
            temp_filepath = temp_file.name
            temp_file.write(code)
        
        # Exécuter le code avec Node.js
        run_process = subprocess.run(
            ['node', temp_filepath],
            capture_output=True,
            text=True,
            timeout=5,  # Timeout de 5 secondes pour l'exécution JS
            encoding='utf-8', # S'assurer que l'output est correctement décodé
            errors='replace' # Remplacer les caractères invalides
        )
        
        result['output'] = run_process.stdout
        if run_process.stderr:
             # Filtrer les avertissements de dépréciation potentiels de Node
             if "DeprecationWarning" not in run_process.stderr:
                result['output'] += f"\nStderr: {run_process.stderr}"
                result['status'] = 'execution_error' # Marquer comme erreur si stderr non vide (et pas juste un avertissement)
             else:
                result['output'] += f"\nStderr (Warning): {run_process.stderr}" # Inclure les avertissements
        
        # Le statut reste 'executed' même avec stderr s'il ne contient pas d'erreur bloquante
        if result['status'] != 'execution_error':
             result['status'] = 'executed' 
        
    except subprocess.TimeoutExpired:
        result['status'] = 'timeout'
        result['output'] = "Timeout (possible boucle infinie ou attente d'entrée)"
    except FileNotFoundError:
        result['status'] = 'error_node_not_found'
        result['output'] = "Erreur système: Commande 'node' non trouvée. Node.js est-il installé et dans le PATH?"
    except Exception as run_error:
        result['status'] = 'runtime_error'
        result['output'] = f"Erreur d'exécution JS: {str(run_error)}"
    
    finally:
        # Nettoyer le fichier temporaire
        if temp_filepath and os.path.exists(temp_filepath):
            try:
                os.unlink(temp_filepath)
            except Exception as clean_e:
                 print(f"Warn: Failed to clean temp file {temp_filepath}: {clean_e}")
            
    return result

def run_php_code(code):
    """
    Exécute un extrait de code PHP avec l'interpréteur PHP.
    Retourne un dict avec le code formaté, le statut et la sortie d'exécution.
    """
    # PHP n'a pas de formateur simple intégré comme pour JS dans ce contexte,
    # donc on retourne le code tel quel ou après un nettoyage basique.
    # Un formatage plus avancé nécessiterait un outil externe.
    formatted_php_code = code.strip() # Simple strip

    result = {
        'formatted_code': formatted_php_code,
        'output': '',
        'status': 'not_executed'
    }
    temp_filepath = None
    php_executable_path = os.getenv("PHP_EXECUTABLE_PATH", r"C:\\xampp\\php\\php.exe") # Read from .env or default

    try:
        # --- Check if PHP executable exists ---
        if not os.path.exists(php_executable_path):
            result['status'] = 'error_php_executable_not_found_at_path'
            result['output'] = f"Erreur système: Exécutable PHP non trouvé à {php_executable_path}. Vérifiez le chemin."
            print(f"PHP executable not found at: {php_executable_path}")
            return result
        # --- End Check ---

        with tempfile.NamedTemporaryFile(suffix='.php', delete=False, mode='w', encoding='utf-8') as temp_file:
            temp_filepath = temp_file.name
            temp_file.write(code)
        
        run_process = subprocess.run(
            [php_executable_path, temp_filepath], # Use the full path
            capture_output=True,
            text=True,
            timeout=5,
            encoding='utf-8',
            errors='replace'
        )
        
        result['output'] = run_process.stdout
        if run_process.stderr:
            result['output'] += f"\nStderr: {run_process.stderr}" # Include Stderr in output
            result['status'] = 'execution_error' 
        
        if result['status'] != 'execution_error':
             result['status'] = 'executed'
        
    except subprocess.TimeoutExpired:
        result['status'] = 'timeout'
        result['output'] = "Timeout PHP (possible boucle infinie ou attente d'entrée)"
    except FileNotFoundError:
        result['status'] = 'error_php_not_found'
        result['output'] = "Erreur système: Commande 'php' non trouvée. PHP est-il installé et dans le PATH?"
    except Exception as run_error:
        result['status'] = 'runtime_error'
        result['output'] = f"Erreur d'exécution PHP: {str(run_error)}"
    
    finally:
        if temp_filepath and os.path.exists(temp_filepath):
            try:
                os.unlink(temp_filepath)
            except Exception as clean_e:
                 print(f"Warn: Failed to clean temp PHP file {temp_filepath}: {clean_e}")
            
    return result

# Lancement du serveur
if __name__ == "__main__":
    import uvicorn
    print("Lancement du serveur FastAPI sur http://0.0.0.0:8000")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True) 