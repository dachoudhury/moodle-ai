// Background script for handling screenshot requests and Groq API calls

// Keep track of the extension popup connection port
let popupPort = null;

// Listen for connections from the popup
chrome.runtime.onConnect.addListener(function(port) {
  if (port.name === "popup") {
    console.log("Background: Popup connected");
    popupPort = port;
    
    // Handle disconnection (e.g., popup closed)
    port.onDisconnect.addListener(function() {
      console.log("Background: Popup disconnected");
      popupPort = null;
    });

    // Optional: Listen for messages FROM the popup via the port
    // port.onMessage.addListener(function(msg) {
    //   console.log("Background received message via port:", msg);
    // });
  }
});

// Listen for one-time messages (e.g., trigger screenshot)
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  console.log("Background received message:", request.action);
  
  // Handle screenshot capture request from popup
  if (request.action === "captureScreenshot") {
    console.log("Handling captureScreenshot request");
    // Récupérer la valeur envoyée depuis le popup
    const expectedLinesFromPopup = request.expectedLines;
    console.log("Expected lines received from popup:", expectedLinesFromPopup); 

    // Inject the selection functionality into the active tab
    chrome.tabs.query({active: true, currentWindow: true}, function(tabs) {
      if (tabs.length > 0) {
        const activeTab = tabs[0];
        console.log("Active tab for selection:", activeTab.id);
        
        // Envoyer le message au content script pour démarrer la sélection
        // On garde expectedLines pour plus tard (quand on aura la capture)
        chrome.tabs.sendMessage(activeTab.id, {action: "startSelection"}, function(response) {
          if (chrome.runtime.lastError) {
            console.log("Content script likely not injected, attempting injection:", chrome.runtime.lastError.message);
            // If content script is not loaded, inject it and try again
            chrome.scripting.executeScript({
              target: {tabId: activeTab.id},
              files: ['content.js']
            }, function(injectionResults) {
              // Check for injection errors
              if (chrome.runtime.lastError || !injectionResults || injectionResults.length === 0) {
                const errorMsg = chrome.runtime.lastError ? chrome.runtime.lastError.message : "Failed to inject content script.";
                console.error("Failed to inject content script:", errorMsg);
                sendErrorToPopup('Failed to inject content script: ' + errorMsg);
                sendResponse({ error: errorMsg }); // Respond to the initial sendMessage
                return;
              }
              
              console.log("Content script injected successfully, sending startSelection again.");
              // Now send the selection message - use a small delay 
              setTimeout(() => {
                chrome.tabs.sendMessage(activeTab.id, {action: "startSelection"}, function(responseAfterInjection) {
                  if (chrome.runtime.lastError || (responseAfterInjection && responseAfterInjection.error)) {
                    const errorMsg = responseAfterInjection?.error || chrome.runtime.lastError?.message || "Unknown error starting selection after injection.";
                    console.error("Failed to start selection after injection:", errorMsg);
                    sendErrorToPopup('Failed to start selection: ' + errorMsg);
                    sendResponse({error: "Failed to start selection after injection"});
                  } else {
                    console.log("Selection started successfully after injection.");
                    sendResponse({success: true}); // Respond to the initial sendMessage
                  }
                });
              }, 150); // Delay to allow script to initialize
            });
          } else if (response && response.error) {
            // Content script responded with an error
            console.error("startSelection returned error:", response.error);
            sendErrorToPopup('Failed to start selection: ' + response.error);
            sendResponse({error: response.error}); // Respond to the initial sendMessage
          } else {
            // Content script responded successfully
            console.log("Selection started successfully (content script already present).");
            sendResponse({success: true}); // Respond to the initial sendMessage
          }
        });
      } else {
        console.error("No active tab found");
        sendErrorToPopup('No active tab found');
        sendResponse({error: "No active tab found"}); // Respond to the initial sendMessage
      }
    });
    
    // Stocker expectedLines pour l'utiliser après la capture
    // Utilisation d'une variable globale ou stockage temporaire si nécessaire.
    // Pour simplifier, on la passera directement dans la chaîne d'appel.
    // IMPORTANT: Cette approche simplifiée suppose que les messages captureArea
    // arriveront séquentiellement pour la bonne requête captureScreenshot.
    // Une approche plus robuste utiliserait un ID de requête.
    chrome.storage.local.set({ currentExpectedLines: expectedLinesFromPopup }, () => {
        console.log('Expected lines stored locally temporarily.');
    });

    return true; // Garder canal ouvert
  }
  
  // Handle area capture from content script
  if (request.action === "captureArea") {
    console.log("Handling captureArea request with area:", request.area);
    
    // Récupérer expectedLines stocké temporairement
    chrome.storage.local.get(["currentExpectedLines"], function(result) {
        const expectedLinesForBackend = result.currentExpectedLines;
        console.log("Retrieved expected lines for backend:", expectedLinesForBackend);
        // Nettoyer le stockage après lecture
        chrome.storage.local.remove("currentExpectedLines"); 

        // Capture visible tab
        chrome.tabs.captureVisibleTab(null, {format: 'png'}, function(dataUrl) {
          if (chrome.runtime.lastError) {
            console.error("Failed to capture tab:", chrome.runtime.lastError);
            sendErrorToPopup('Failed to capture screen: ' + chrome.runtime.lastError.message);
            // Don't use sendResponse here as the original message was from content script
            return;
          }
          if (!dataUrl) {
              console.error("captureVisibleTab returned empty dataUrl.");
              sendErrorToPopup('Failed to capture screen: No image data received.');
              return;
          }
          
          console.log("Tab captured successfully, sending to backend with crop coordinates and expected lines");
          
          // Informer le popup que la capture est faite
          if (popupPort) {
            popupPort.postMessage({ action: "screenshotCaptured" });
          }
          
          // Process the image with the backend, including crop coordinates AND expected lines
          processImageWithBackend(dataUrl, request.area, expectedLinesForBackend, (backendResponse) => {
              if (!popupPort) {
                 console.warn("Backend analysis finished, but popup port is no longer connected.");
                 return;
              }
              if (backendResponse.error) {
                 console.log("Sending analysisError to popup.");
                 popupPort.postMessage({ action: "analysisError", error: backendResponse.error });
              } else {
                 console.log("Sending analysisComplete to popup.");
                 popupPort.postMessage({ action: "analysisComplete", answers: backendResponse.answers });
              }
          });
          
        }); // Fin captureVisibleTab
    }); // Fin storage.local.get
    
    // Don't use sendResponse here - message is from content script
    // Don't return true - message channel from content script doesn't need to be kept open long
    return false; 
  }
  
  // Handle cancel selection from content script
  if (request.action === "cancelAreaSelection") {
    console.log("Handling cancelAreaSelection request");
    
    // Send cancellation message to popup via the port
    if (popupPort) {
      popupPort.postMessage({
        action: "screenshotCancelled"
      });
    } else {
      console.error("No popup port available to send cancellation");
    }
    // Don't use sendResponse, message from content script
    return false;
  }
  
  // Handle image processing request (adaptation pour inclure expectedLines si jamais utilisé)
  if (request.action === "processImage") {
    console.warn("processImage action called directly (potentially deprecated flow)");
    const expectedLinesDirect = request.expectedLines || null; // Récupérer si fourni
    processImageWithBackend(request.imageData, null, expectedLinesDirect, (backendResponse) => {
        sendResponse(backendResponse);
    });
    return true; 
  }
  
  // Default response for unhandled messages
  console.log("Unhandled message action:", request.action);
  // sendResponse({error: "Unhandled message action: " + request.action});
  return false; // No async response planned
});

// Function to send error message to popup via the port
function sendErrorToPopup(errorMessage) {
  console.error("Sending error to popup:", errorMessage);
  if (popupPort) {
    popupPort.postMessage({
      action: "error", // Generic error message for popup
      message: errorMessage
    });
  } else {
    console.error("No popup port available to send error");
  }
}

// Function to process image via the backend (OCR + LLM)
// Mise à jour pour accepter cropArea et expectedLines
async function processImageWithBackend(imageData, cropArea, expectedLines, callback) { 
  console.log("Sending image to backend. CropArea:", cropArea, "ExpectedLines:", expectedLines);
  const backendUrl = 'http://localhost:8000/analyze_screenshot'; 

  try {
    const bodyPayload = {
        imageData: imageData, // Données image base64
        cropArea: cropArea    // Coordonnées de recadrage (peut être null)
    };
    
    // Ajouter expectedOutputLines seulement s'il a une valeur valide
    if (expectedLines !== null && expectedLines !== undefined) {
        bodyPayload.expectedOutputLines = expectedLines;
    }

    const response = await fetch(backendUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      // Envoyer le payload construit
      body: JSON.stringify(bodyPayload) 
    });

    const data = await response.json(); 

    if (!response.ok) {
      console.error("Backend request failed:", response.status, data);
      const errorMessage = data.detail || `Backend error: ${response.status} ${response.statusText}`;
      throw new Error(errorMessage);
    }

    console.log("Backend processing successful, received results.");
    callback({ answers: data.results });

  } catch (error) {
    console.error('Error calling backend API:', error);
    callback({ error: error.message || 'Failed to get answers from backend API' });
  }
}

console.log("MoodleAI background script loaded - v5 Expected Lines");