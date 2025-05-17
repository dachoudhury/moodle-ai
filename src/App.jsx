// ------------------------------------------------------
// src/App.js - Main React Application
// ------------------------------------------------------

import React, { useState, useEffect, useRef } from 'react';
import AnalysisButton from './components/AnalysisButton';
import ResultsDisplay from './components/ResultsDisplay';
import ErrorMessage from './components/ErrorMessage';
import './App.css';

function App() {
  const [isLoading, setIsLoading] = useState(false);
  const [analysisResults, setAnalysisResults] = useState([]);
  const [errorMessage, setErrorMessage] = useState('');
  const [expectedLines, setExpectedLines] = useState('');
  const backgroundPort = useRef(null);
  
  useEffect(() => {
    // --- Load results from storage on initial load ---
    chrome.storage.local.get(['lastAnalysisResults'], (result) => {
      if (result.lastAnalysisResults) {
        console.log("Popup: Loaded last results from storage:", result.lastAnalysisResults);
        setAnalysisResults(result.lastAnalysisResults);
      }
    });
    // --- End load results ---

    try {
      backgroundPort.current = chrome.runtime.connect({ name: "popup" });
      console.log("Popup: Connection established with background script.");
    } catch (error) {
      console.error("Popup: Failed to connect to background script:", error);
      setErrorMessage("Impossible de se connecter au script d'arrière-plan de l'extension.");
      return;
    }

    const messageListener = (msg) => {
      console.log("Popup received message:", msg);
      if (msg.action === "analysisComplete") {
        setIsLoading(false);
        setErrorMessage('');
        setAnalysisResults(msg.answers || []);
        // --- Save results to storage ---
        chrome.storage.local.set({ lastAnalysisResults: msg.answers || [] }, () => {
          console.log("Popup: Saved results to storage.");
        });
        // --- End save results ---
        if (!msg.answers || msg.answers.length === 0) {
           setErrorMessage("L'analyse n'a retourné aucun résultat.");
        }
      } else if (msg.action === "analysisError") {
        setIsLoading(false);
        setAnalysisResults([]);
        setErrorMessage(msg.error || "Une erreur inconnue est survenue lors de l'analyse.");
      } else if (msg.action === "screenshotCaptured") {
         setIsLoading(true);
         setErrorMessage("Capture d'écran réussie. Analyse en cours...");
         setAnalysisResults([]);
      } else if (msg.action === "screenshotCancelled") {
         setIsLoading(false);
         setErrorMessage('Capture d\'écran annulée.');
         setAnalysisResults([]);
      } else if (msg.action === "error") {
        setIsLoading(false);
        setAnalysisResults([]);
        setErrorMessage(msg.message || "Erreur interne du background script.");
      }
    };

    if (backgroundPort.current) {
        backgroundPort.current.onMessage.addListener(messageListener);
    
        backgroundPort.current.onDisconnect.addListener(() => {
          console.log("Popup: Disconnected from background script.");
          backgroundPort.current = null;
        });
    }

    return () => {
      if (backgroundPort.current) {
        try {
          backgroundPort.current.onMessage.removeListener(messageListener);
          console.log("Popup: Removed message listener.");
        } catch (error) {
             console.warn("Popup: Error removing listener or disconnecting port:", error);
      }
      }
    };
  }, []);
  
  const handleStartAnalysis = () => {
    setIsLoading(true);
    setErrorMessage('Initiation de la capture d\'écran...');
    setAnalysisResults([]);

    if (!backgroundPort.current) {
        setErrorMessage("Erreur: Pas de connexion au service d'arrière-plan.");
        setIsLoading(false);
        return;
    }
    
    const lines = expectedLines.trim() === '' ? null : parseInt(expectedLines, 10);
    const validExpectedLines = (lines !== null && !isNaN(lines) && lines >= 0) ? lines : null;
    console.log("Expected Output Lines to send:", validExpectedLines);
            
    try {
      chrome.runtime.sendMessage(
        { 
            action: "captureScreenshot",
            expectedLines: validExpectedLines
        },
        (response) => {
          if (chrome.runtime.lastError) {
            console.error("Error sending captureScreenshot message:", chrome.runtime.lastError);
            setIsLoading(false);
            setErrorMessage(`Erreur d'envoi: ${chrome.runtime.lastError.message}`);
            return;
          }
          if (response && response.error) {
             console.error("Error response from captureScreenshot:", response.error);
             setIsLoading(false);
             setErrorMessage(`Erreur réponse: ${response.error}`);
             return;
          }
           console.log("Capture screenshot message sent successfully. Waiting for selection...");
        }
      );
    } catch (error) {
       console.error("Failed to send message:", error);
       setIsLoading(false);
       setErrorMessage(`Erreur d'exécution: ${error.message}`);
    }
  };

  return (
    <div className="app-container">
      {/* <h1>MoodleAI</h1> Removed title */}
      
      <div className="input-group">
        {/* <label htmlFor="expected-lines">Lignes d'output attendues (Code) :</label> Removed label */}
        <input 
          type="number" 
          id="expected-lines" 
          value={expectedLines}
          onChange={(e) => setExpectedLines(e.target.value)} 
          placeholder="Lignes d'output attendues (Code)"
          min="0"
          disabled={isLoading}
        />
      </div>
      
      <AnalysisButton onClick={handleStartAnalysis} disabled={isLoading} />
      
      {errorMessage && <ErrorMessage message={errorMessage} />}
      
      {isLoading && !errorMessage && (
          <div className="loading-indicator">Chargement...</div>
      )}
      
      {analysisResults.length > 0 && (
        <ResultsDisplay results={analysisResults} />
      )}
    </div>
  );
}

export default App;