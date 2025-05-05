import os
import json # Ajout de l'import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import base64
import traceback
from dotenv import load_dotenv
# --- Importer les clients nécessaires --- 
from mistralai import Mistral
from groq import Groq
# --- Importer les exceptions spécifiques ---
# Importer `models` pour accéder aux exceptions SDKError et HTTPValidationError
from mistralai import models as mistral_models 

from groq import APIError as GroqAPIError

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
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

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

groq_client = None
if GROQ_API_KEY:
    try:
        groq_client = Groq(api_key=GROQ_API_KEY)
        print("Client Groq initialisé.")
    except Exception as e:
        print(f"CRITICAL: Erreur initialisation client Groq: {e}")
else:
    print("CRITICAL: Clé API Groq (GROQ_API_KEY) manquante dans .env. Analyse LLM Groq désactivée.")


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
    if not groq_client:
        raise HTTPException(status_code=503, detail="Service LLM (Groq) non disponible côté backend.")
    
    # Parse le body JSON manuellement pour plus de flexibilité    
    try:
        body = await request.json()
        image_data = body.get("imageData", "")
        crop_area = body.get("cropArea", None)
        expected_lines = body.get("expectedOutputLines", None)
        print(f"Nombre de lignes d'output attendu (depuis requête): {expected_lines}")
        
        # 1. Décoder et traiter l'image
        try:
            base64_data = image_data.split(',')[1] if ',' in image_data else image_data
            image_data_bytes = base64.b64decode(base64_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Format image invalide: {e}")

        image = Image.open(BytesIO(image_data_bytes))
        if crop_area:
            try:
                dpr = crop_area.get("dpr", 1.0)
                x, y, w, h = int(crop_area["x"]*dpr), int(crop_area["y"]*dpr), int(crop_area["width"]*dpr), int(crop_area["height"]*dpr)
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
    Analyse le contenu OCR. Si expected_lines est fourni, traite comme du code JS 
    avec boucle de correction. Sinon, traite comme du contenu de cours.
    """
    if not groq_client: raise GroqAPIError("Client Groq non configuré.")
    if not ocr_text or ocr_text.isspace(): return []

    final_results = []
    qa_pair = QAPair(question="") # Initialisation

    # --- Branchement Principal: Code vs Cours --- 
    if expected_lines is not None: 
        # --- Traitement comme CODE --- 
        qa_pair.question = "Analyse du Code Javascript" # Question générique en français
        qa_pair.question_type = "code" 
        print(f"--- Traitement comme CODE (expected_lines = {expected_lines}) ---")
        
        current_code = None
        exec_result = None
        final_answer = "[Traitement de la question de code a échoué]"; # Message d'erreur en français
        max_attempts = 2 
        previous_code = None
        previous_error_output = None
        previous_error_status = None

        for attempt in range(max_attempts):
            print(f"--- Tentative Code {attempt + 1}/{max_attempts} ---")
            code_to_execute = None

            if attempt == 0:
                # --- LLM 2: Réécriture Code Initial --- 
                print(f"  -> LLM Étape 2: Réécriture Code JS initial...")
                # Traduction du prompt 2
                prompt2_rewrite_code = f"""
Contexte: Le texte suivant a été extrait via OCR :
"{ocr_text}"

Tâche: Extrayez le fragment de code Javascript principal du texte ci-dessus.
Réécrivez le code proprement, en corrigeant les erreurs OCR potentielles ou les problèmes de syntaxe mineurs.
Retournez UNIQUEMENT le code Javascript brut, sans explications ni démarques Markdown.
Si aucun code Javascript n'est trouvé, répondez : NO_CODE_FOUND
Code Réécrit :
"""
                try:
                    raw_code_from_llm = await call_groq_llm(prompt2_rewrite_code, is_json_output_expected=False)
                    cleaned_code = clean_llm_code_output(raw_code_from_llm)
                    if cleaned_code and cleaned_code != "NO_CODE_FOUND" and len(cleaned_code) > 5:
                        code_to_execute = cleaned_code
                        print(f"    -> Code JS réécrit et nettoyé (Tentative 1):")
                        print(f"    ```javascript")
                        print(code_to_execute)
                        print(f"    ```")
                    else:
                        print(f"    -> LLM 2 n'a pas trouvé/réécrit de code JS pertinent.")
                        final_answer = "[Impossible d'extraire le code JS du texte OCR]"; # Message en français
                        break 
                except Exception as e:
                    print(f"    -> Erreur LLM Étape 2 (Réécriture): {e}")
                    final_answer = f"[Erreur LLM lors de l'extraction du code: {e}]"; # Message en français
                    break
            else: # attempt > 0: Correction
                # --- LLM 4: Correction Code --- 
                print(f"  -> LLM Étape 4: Correction Code JS suite à erreur...")
                if previous_code and previous_error_output:
                    print(f"    -> Erreur Précédente (Status: {previous_error_status}): {previous_error_output}")
                    # Traduction du prompt 4
                    prompt4_fix_code = f"""
Le code Javascript suivant a échoué lors de son exécution.
Code Échoué :
```javascript
{previous_code}
```
Statut d'Erreur d'Exécution : {previous_error_status}
Message d'Erreur : {previous_error_output}

Réécrivez le code pour corriger l'erreur spécifique rapportée dans le Message d'Erreur.
Retournez UNIQUEMENT le code Javascript brut et corrigé, sans explications.
Code Corrigé :
"""
                    try:
                        raw_code_from_llm = await call_groq_llm(prompt4_fix_code, is_json_output_expected=False)
                        cleaned_code = clean_llm_code_output(raw_code_from_llm)
                        if cleaned_code and len(cleaned_code) > 5 and cleaned_code != "NO_CODE_FOUND":
                            code_to_execute = cleaned_code
                            print(f"    -> Code JS corrigé et nettoyé (Tentative 2):")
                            print(f"    ```javascript")
                            print(code_to_execute)
                            print(f"    ```")
                        else:
                            print(f"    -> LLM 4 n'a pas pu corriger le code.")
                            final_answer = "[LLM n'a pas pu corriger le code après erreur d'exécution]"; # Message en français
                            break 
                    except Exception as e:
                        print(f"    -> Erreur LLM Étape 4 (Correction): {e}")
                        final_answer = f"[Erreur LLM lors de la correction du code: {e}]"; # Message en français
                        break 
                else:
                    print("    -> Erreur interne: Manque d'infos pour correction.")
                    break

            # --- Exécution du code --- 
            if code_to_execute:
                print(f"  -> Exécution Tentative {attempt + 1} du Code JS NETTOYÉ...")
                exec_result = run_js_code(code_to_execute)
                print(f"    -> Résultat Exécution: {exec_result['status']}")

                if exec_result['status'] == 'executed':
                    # --- LLM 3: Réponse Finale (Code OK) --- 
                    print(f"  -> LLM Étape 3: Réponse Finale (Code OK)...")
                    # Traduction du prompt 3 (code)
                    prompt3_answer_code = f"""
Contexte: Le fragment de code Javascript suivant a été exécuté.
Fragment de Code (Nettoyé & Exécuté) :
```javascript
{exec_result['formatted_code']}
```
Sortie d'Exécution :
{exec_result['output'] if exec_result['output'] else 'Aucune sortie'}
Indice Utilisateur (Nb Max Lignes Attendues) : {expected_lines if expected_lines is not None else 'Non spécifié'}

Tâche: Analysez la Sortie d'Exécution. Fournissez UNIQUEMENT la sortie elle-même, formatée de manière appropriée en fonction du contenu réel de la sortie et de l'indice utilisateur sur les lignes attendues (si la sortie a moins de lignes ou des lignes vides, respectez cela). N'expliquez pas le code, l'exécution, ni n'ajoutez d'étiquettes comme "Sortie :". S'il n'y a pas eu de sortie, répondez par "(Aucune sortie produite)".
Réponse :
"""
                    try:
                        final_answer_text = await call_groq_llm(prompt3_answer_code, is_json_output_expected=False)
                        final_answer = final_answer_text.strip()
                        print(f"    -> Réponse LLM 3 (Code OK) obtenue.")
                        break # Succès!
                    except Exception as e:
                        print(f"    -> Erreur LLM Étape 3 (Réponse Code OK): {e}")
                        final_answer = f"[Erreur LLM pour la réponse finale: {e}]"; # Message en français
                        break 
                else: # Erreur d'exécution
                    print(f"    -> Exécution échouée (Tentative {attempt + 1}). Préparation pour correction.")
                    previous_code = exec_result['formatted_code']
                    previous_error_output = exec_result['output']
                    previous_error_status = exec_result['status']
                    if attempt == max_attempts - 1:
                        final_answer = f"[Échec d'exécution du code JS même après correction (Status: {exec_result['status']})]"; # Message en français
                    else:
                         final_answer = f"[Échec d'exécution du code JS (Status: {exec_result['status']})]"; # Message en français
            else:
                print("  -> Erreur: Pas de code valide à exécuter.")
                break # Sortir boucle tentative si pas de code

        # Fin boucle de tentatives pour le code
        qa_pair.answer = final_answer
        final_results.append(qa_pair)

    else: 
        # --- Traitement comme COURS --- 
        qa_pair.question = "Analyse du Contenu du Cours" # Question générique en français
        qa_pair.question_type = "course"
        print("--- Traitement comme COURS (expected_lines non fourni) ---")
        
        # Traduction du prompt cours
        prompt_answer_course = f"""
Analysez le texte suivant extrait d'une capture d'écran de matériel de cours.
Résumez les points clés ou répondez de manière concise à toute question implicite trouvée dans le texte.

Contenu du Texte :
---
{ocr_text}
---

Analyse/Résumé :
"""
        try:
            answer_text = await call_groq_llm(prompt_answer_course, is_json_output_expected=False)
            qa_pair.answer = answer_text.strip()
            print(f"  -> Réponse LLM (Cours) obtenue.")
        except Exception as e:
            print(f"Erreur LLM Réponse Cours: {e}")
            qa_pair.answer = f"[Erreur analyse LLM Cours: {e}]"; # Message en français
        final_results.append(qa_pair)

    print(f"Analyse OCR complète. {len(final_results)} réponse générée.")
    return final_results

def clean_llm_code_output(raw_code: str) -> str:
    """Nettoie la sortie de code du LLM en supprimant les marqueurs Markdown."""
    cleaned = raw_code
    # Supprimer les marqueurs de début/fin ```javascript ou ```js ou ```
    cleaned = re.sub(r'^```(?:javascript|js)?\s*\n?', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\n?```$\n?', '', cleaned)
    return cleaned.strip() # Supprimer aussi les espaces/lignes vides autour

async def call_groq_llm(prompt_content: str, is_json_output_expected: bool) -> str:
    """
    Helper pour appeler l'API Groq et gérer les erreurs communes.
    Utilise le modèle meta-llama/llama-4-maverick-17b-128e-instruct.
    """
    try:
        # Traduction des messages système
        system_message = "Vous êtes un assistant utile."
        if is_json_output_expected:
            system_message = "Vous êtes un générateur JSON expert. Répondez UNIQUEMENT avec le JSON valide demandé. N'incluez aucun autre texte, explication ou formatage Markdown. Assurez-vous que toutes les chaînes, en particulier celles sur plusieurs lignes, sont correctement échappées selon les normes JSON."

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt_content}
        ]
        
        print(f"Appel LLM Groq (Modèle: meta-llama/llama-4-maverick-17b-128e-instruct, JSON attendu: {is_json_output_expected})...") 
        completion = groq_client.chat.completions.create(
            model="meta-llama/llama-4-maverick-17b-128e-instruct", 
            messages=messages,
            temperature=0, # Basse température pour plus de déterminisme
            max_tokens=4096, # Augmenté pour les réponses potentiellement plus longues
            top_p=1,
            stream=False,
        )
        response_text = completion.choices[0].message.content
        print("Réponse LLM reçue.") 
        
        if is_json_output_expected:
            print("Tentative d'extraction JSON...") 
            match = re.search(r'(?s)(^.*?(\[.*?\]|\{.*?\}))', response_text)
            json_string = None
            if match:
                potential_json = match.group(2)
                print(f"Bloc JSON potentiel trouvé (longueur: {len(potential_json)})...") 
                if (potential_json.startswith('[') and potential_json.endswith(']')) or \
                   (potential_json.startswith('{') and potential_json.endswith('}')):
                   json_string = potential_json
            if json_string:
                try:
                    json.loads(json_string)
                    print("JSON extrait et validé.") 
                    return json_string
                except json.JSONDecodeError as json_val_e:
                    print(f"JSON potentiel extrait mais invalide: {json_val_e}. Réponse brute: {json_string[:500]}...") 
                    return response_text 
            else:
                 print("Aucun bloc JSON clair ([...] ou {...}) trouvé dans la réponse. Retourne la réponse brute.") 
                 return response_text 
        else:
            return response_text

    except GroqAPIError as e:
        print(f"Erreur API Groq: {e}")
        raise e 
    except Exception as e:
        print(f"Erreur inattendue appel LLM: {e}")
        raise e

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

# Lancement du serveur
if __name__ == "__main__":
    import uvicorn
    print("Lancement du serveur FastAPI sur http://0.0.0.0:8000")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True) 