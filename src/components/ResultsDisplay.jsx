import React from 'react';
import PropTypes from 'prop-types';

function ResultsDisplay({ results }) {
  if (!results || results.length === 0) {
    return null; // Ne rien afficher si pas de résultats
  }

  const handleCopy = (textToCopy) => {
    navigator.clipboard.writeText(textToCopy)
      .then(() => console.log("Text copied!"))
      .catch(err => console.error("Failed to copy text:", err));
  };

  const handleCopyAll = () => {
      const allText = results.map((item, index) => 
          `Question ${index + 1}:\n${item.question}\n\nAnswer ${index + 1}:\n${item.answer}`
      ).join("\n\n---\n\n");
      handleCopy(allText);
  };

  return (
    <div className="results-container">
      <h2>Analysis Results:</h2>
      <button onClick={handleCopyAll} className="copy-all-button">Copy All Results</button>
      {results.map((item, index) => (
        <div key={index} className="result-item">
          <h4>Question {index + 1}</h4>
          <pre className="question-text">{item.question}</pre>
          <h4>Answer {index + 1}</h4>
          <pre className="answer-text">{item.answer}</pre>
          <button onClick={() => handleCopy(item.answer)} className="copy-single-button">
              Copy Answer {index + 1}
          </button>
        </div>
      ))}
    </div>
  );
}

ResultsDisplay.propTypes = {
  results: PropTypes.arrayOf(PropTypes.shape({
    question: PropTypes.string.isRequired,
    answer: PropTypes.string.isRequired,
  })).isRequired,
};

export default ResultsDisplay; 