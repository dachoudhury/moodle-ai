// Listen for messages from the popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  console.log("Content script received message:", request);
  
  if (request.action === "extractQuiz") {
    try {
      const questions = extractQuizQuestions();
      console.log("Extracted questions:", questions);
      sendResponse({ questions });
    } catch (error) {
      console.error('Error extracting quiz:', error);
      sendResponse({ error: error.message });
    }
  }
  
  // Handle screenshot selection request
  if (request.action === "startSelection") {
    try {
      createSelectionOverlay();
      sendResponse({ success: true });
    } catch (error) {
      console.error('Error creating selection overlay:', error);
      sendResponse({ error: error.message });
    }
  }
  
  return true; // Keep the message channel open for async response
});

// Function to extract quiz questions from the Moodle page
function extractQuizQuestions() {
  const questions = [];
  
  // Try to find questions in Moodle's standard quiz format
  const questionElements = document.querySelectorAll('.que');
  
  if (questionElements && questionElements.length > 0) {
    questionElements.forEach((qElem) => {
      try {
        // Extract question text
        const questionTextElem = qElem.querySelector('.qtext');
        if (!questionTextElem) return;
        
        let questionText = questionTextElem.innerText.trim();
        
        // Extract question images if any
        const questionImages = questionTextElem.querySelectorAll('img');
        if (questionImages.length > 0) {
          questionText += "\n[This question contains images that can't be processed]";
        }
        
        // Extract answer options for multiple choice questions
        const answerOptions = qElem.querySelectorAll('.answer .r0, .answer .r1');
        if (answerOptions && answerOptions.length > 0) {
          questionText += "\nOptions:";
          answerOptions.forEach((option) => {
            const optionText = option.innerText.trim();
            if (optionText) {
              questionText += `\n- ${optionText}`;
            }
          });
        }
        
        questions.push(questionText);
      } catch (err) {
        console.error('Error processing question element:', err);
      }
    });
  }
  
  // If no questions found, try alternate selectors for different Moodle themes
  if (questions.length === 0) {
    // Attempt with generic selectors
    const formElement = document.querySelector('form#responseform');
    if (formElement) {
      const allQuestionContainers = formElement.querySelectorAll('.formulation');
      allQuestionContainers.forEach((container) => {
        const text = container.innerText.trim();
        if (text) {
          questions.push(text);
        }
      });
    }
    
    // Try even more generic approach if still no questions
    if (questions.length === 0) {
      // Look for any content that seems like a question
      const possibleQuestions = document.querySelectorAll('div.question, .questiontext, .content');
      possibleQuestions.forEach((elem) => {
        if (elem.innerText && elem.innerText.trim().length > 10) {
          questions.push(elem.innerText.trim());
        }
      });
    }
  }
  
  // If still no questions, grab the main content area
  if (questions.length === 0) {
    const mainContent = document.querySelector('#region-main, #page-content, main');
    if (mainContent) {
      questions.push("Please analyze this content:\n\n" + mainContent.innerText.trim());
    }
  }
  
  return questions;
}

// Function to create a selection overlay on the current page
function createSelectionOverlay() {
  // Remove existing overlay if any
  const existingOverlay = document.getElementById('moodleai-selection-overlay');
  if (existingOverlay) {
    // Clean up old listeners if necessary (though removing the element should suffice)
    document.body.removeChild(existingOverlay);
  }
  
  // Create overlay container
  const overlay = document.createElement('div');
  overlay.id = 'moodleai-selection-overlay';
  overlay.style.position = 'fixed';
  overlay.style.top = '0';
  overlay.style.left = '0';
  overlay.style.width = '100vw'; // Use viewport units
  overlay.style.height = '100vh'; // Use viewport units
  overlay.style.backgroundColor = 'rgba(0, 0, 0, 0.3)';
  overlay.style.zIndex = '2147483647'; // Max z-index
  overlay.style.cursor = 'crosshair';
  
  // Create selection box
  const selectionBox = document.createElement('div');
  selectionBox.id = 'moodleai-selection-box';
  selectionBox.style.position = 'absolute';
  selectionBox.style.border = '2px dashed #fff';
  selectionBox.style.backgroundColor = 'rgba(66, 133, 244, 0.2)';
  selectionBox.style.display = 'none';
  selectionBox.style.pointerEvents = 'none'; // Prevent box from interfering with overlay events
  
  // Create instructions
  const instructions = document.createElement('div');
  instructions.style.position = 'fixed';
  instructions.style.top = '20px';
  instructions.style.left = '50%';
  instructions.style.transform = 'translateX(-50%)';
  instructions.style.backgroundColor = 'rgba(0, 0, 0, 0.7)';
  instructions.style.color = 'white';
  instructions.style.padding = '10px 20px';
  instructions.style.borderRadius = '5px';
  instructions.style.fontSize = '14px';
  instructions.style.zIndex = '2147483647'; // Max z-index
  instructions.style.textAlign = 'center';
  instructions.style.pointerEvents = 'none'; // Don't capture mouse events
  instructions.textContent = 'Click and drag to select an area';
  
  // Create button container
  const buttonContainer = document.createElement('div');
  buttonContainer.id = 'moodleai-button-container';
  buttonContainer.style.position = 'fixed'; // Changed to fixed
  buttonContainer.style.bottom = '20px';
  buttonContainer.style.left = '50%';
  buttonContainer.style.transform = 'translateX(-50%)';
  buttonContainer.style.zIndex = '2147483647'; // Max z-index
  buttonContainer.style.display = 'none'; // Initially hidden
  buttonContainer.style.gap = '10px';
  
  // Create capture button
  const captureBtn = document.createElement('button');
  captureBtn.textContent = 'Capture Selection';
  captureBtn.style.padding = '8px 16px';
  captureBtn.style.border = 'none';
  captureBtn.style.borderRadius = '4px';
  captureBtn.style.backgroundColor = '#4285f4';
  captureBtn.style.color = 'white';
  captureBtn.style.fontWeight = '500';
  captureBtn.style.cursor = 'pointer';
  captureBtn.style.fontSize = '14px';
  
  // Create cancel button
  const cancelBtn = document.createElement('button');
  cancelBtn.textContent = 'Cancel';
  cancelBtn.style.padding = '8px 16px';
  cancelBtn.style.border = 'none';
  cancelBtn.style.borderRadius = '4px';
  cancelBtn.style.backgroundColor = '#f44336';
  cancelBtn.style.color = 'white';
  cancelBtn.style.fontWeight = '500';
  cancelBtn.style.cursor = 'pointer';
  cancelBtn.style.fontSize = '14px';
  
  // Add buttons to container
  buttonContainer.appendChild(captureBtn);
  buttonContainer.appendChild(cancelBtn);
  
  // Add elements to overlay
  overlay.appendChild(selectionBox);
  overlay.appendChild(instructions);
  overlay.appendChild(buttonContainer); // Append here, manage visibility
  
  // Add overlay to body
  document.body.appendChild(overlay);
  
  // --- Refactored Event Handling --- 
  let isSelecting = false;
  let startX = 0;
  let startY = 0;

  const handleMouseMove = (e) => {
    if (!isSelecting) return;

    const currentX = e.clientX;
    const currentY = e.clientY;

    // Calculate position and dimensions
    const left = Math.min(startX, currentX);
    const top = Math.min(startY, currentY);
    const width = Math.abs(currentX - startX);
    const height = Math.abs(currentY - startY);
    
    // Update selection box visually
    selectionBox.style.left = left + 'px';
    selectionBox.style.top = top + 'px';
    selectionBox.style.width = width + 'px';
    selectionBox.style.height = height + 'px';
  };

  const handleMouseUp = (e) => {
    if (!isSelecting) return;
    isSelecting = false;

    // Remove window listeners
    window.removeEventListener('mousemove', handleMouseMove);
    window.removeEventListener('mouseup', handleMouseUp);

    // Check if selection has a minimum size
    const width = parseInt(selectionBox.style.width);
    const height = parseInt(selectionBox.style.height);
    
    if (width > 10 && height > 10) {
        // Position and show buttons near the selection box
        const rect = selectionBox.getBoundingClientRect();
        buttonContainer.style.top = `${rect.bottom + 5}px`; // Position below the box
        buttonContainer.style.left = `${rect.left}px`; // Align with left edge
        buttonContainer.style.transform = 'translateX(0)'; // Reset transform
        buttonContainer.style.display = 'flex'; 
        selectionBox.style.pointerEvents = 'auto'; // Allow interaction if needed later?
    } else {
      // If selection is too small, hide the box 
      selectionBox.style.display = 'none';
      // No need to show buttons, potentially close overlay or allow re-selection
      // For now, let the overlay stay for another attempt
    }
  };
  
  // Mouse down on overlay STARTS the process
  overlay.addEventListener('mousedown', (e) => {
    // Prevent starting selection if clicking on buttons
    if (e.target === captureBtn || e.target === cancelBtn) {
      return; 
    }
    
    isSelecting = true;
    startX = e.clientX;
    startY = e.clientY;
    
    // Initialize selection box at mouse position
    selectionBox.style.left = startX + 'px';
    selectionBox.style.top = startY + 'px';
    selectionBox.style.width = '0px';
    selectionBox.style.height = '0px';
    selectionBox.style.display = 'block';
    selectionBox.style.pointerEvents = 'none'; // Ensure mouse events go to overlay
    
    // Hide buttons during selection drawing
    buttonContainer.style.display = 'none'; 

    // Attach move and up listeners to the window
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
  });

  // --- Button Click Handlers --- 
  captureBtn.addEventListener('click', () => {
    console.log("Capture button clicked");
    const rect = selectionBox.getBoundingClientRect(); // Use getBoundingClientRect for accuracy
    const dpr = window.devicePixelRatio || 1;
    
    chrome.runtime.sendMessage({
      action: 'captureArea',
      area: {
        x: rect.left, // Use rect values directly
        y: rect.top,
        width: rect.width,
        height: rect.height,
        dpr: dpr
      }
    });
    cleanup(); // Remove overlay and listeners
  });
  
  // Cancel button click
  cancelBtn.addEventListener('click', function() {
    console.log("Cancel button clicked");
    chrome.runtime.sendMessage({ action: 'cancelAreaSelection' });
    cleanup(); // Remove overlay and listeners
  });
  
  // Escape key to cancel
  const handleEscKey = function(e) {
    if (e.key === 'Escape') {
      console.log("Escape key pressed");
      chrome.runtime.sendMessage({ action: 'cancelAreaSelection' });
      cleanup(); // Remove overlay and listeners
    }
  };
  document.addEventListener('keydown', handleEscKey);

  const cleanup = () => {
      const overlayElement = document.getElementById('moodleai-selection-overlay');
      if (overlayElement) {
          document.body.removeChild(overlayElement);
      }
      // Remove window listeners just in case they are lingering
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
      document.removeEventListener('keydown', handleEscKey);
  };

}

// Debug logging
console.log("MoodleAI content script loaded v3 - Refactored Overlay");