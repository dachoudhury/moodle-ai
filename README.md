# MoodleAI Helper Chrome Extension

This Chrome extension provides AI-powered assistance for Moodle activities by analyzing selected screenshots. It uses Mistral AI for OCR and Gemini for LLM analysis (specifically code execution and course content summarization, with a primary focus on helping with practice quizzes).

## Components

*   **Frontend (Popup):** Provides the user interface within the browser extension popup.
*   **Backend:** A Python FastAPI server that handles image processing (OCR via Mistral) and AI analysis (via Gemini). Found in the `backend` directory.
*   **Content Script:** Injected into web pages to enable screen area selection (`content-script.js`).
*   **Background Script:** Manages communication between the popup, content script, and backend (`background.js`).

## Setup

### 1. Backend Setup (Python FastAPI)

The backend server is required for the extension to function.

1.  **Navigate to the backend directory:**
    ```bash
    cd backend
    ```
2.  **(Optional but Recommended) Create and activate a virtual environment:**
    ```bash
    python -m venv venv
    # On Windows
    .\venv\Scripts\activate
    # On macOS/Linux
    source venv/bin/activate
    ```
3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
4.  **Configure API Keys:**
    *   Create a file named `.env` in the `backend` directory.
    *   Add your API keys to this file:
        ```dotenv
        MISTRAL_API_KEY="your_mistral_api_key_here"
        GEMINI_API_KEY="your_gemini_api_key_here"
        ```
    *   *Note: The backend requires both Mistral (for OCR) and Gemini (for LLM analysis) keys to be configured.*
5.  **Run the backend server:**
    ```bash
    python main.py
    ```
    The server will start, usually at `http://localhost:8000`. Keep this terminal running.

### 2. Prepare the Extension Files

1.  **Navigate back to the project root directory:**
    ```bash
    cd ..
    ```
2.  **Install necessary Node.js build tools (if not already done):**
    ```bash
    npm install
    ```
3.  **Build the extension files:**
    ```bash
    npm run build
    ```
    This command bundles the necessary files for the extension into the `dist` directory.

### 3. Loading the Extension in Chrome

1.  Open Google Chrome and navigate to `chrome://extensions/`.
2.  Enable **"Developer mode"** using the toggle switch (usually in the top-right corner).
3.  Click the **"Load unpacked"** button.
4.  Select the `dist` directory that was created by the build command.
5.  The "MoodleAI Helper" extension should now appear in your list of extensions.

## Usage

1.  Make sure the Python backend server is running.
2.  Navigate to the web page (e.g., a Moodle quiz or code exercise page) you want to analyze.
    *   *Note: The selection overlay currently only works on standard HTML pages, not directly on PDF viewer pages.*
3.  Click the MoodleAI Helper extension icon in your Chrome toolbar.
4.  (Optional) Enter the expected number of output lines if analyzing code.
5.  Click the **"Start Analysis"** button.
6.  The page will dim slightly. Click and drag to select the area you want to analyze.
7.  Once you release the mouse button, click the **"Capture Selection"** button that appears.
8.  The extension popup will show "Processing..." and then display the analysis results.
9.  Results are saved, so if the popup closes, reopening it will show the last analysis.
