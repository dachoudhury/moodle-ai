import React from 'react';
import PropTypes from 'prop-types';

function AnalysisButton({ onClick, disabled }) {
  return (
    <button 
      className="analysis-button" 
      onClick={onClick} 
      disabled={disabled}
    >
      {disabled ? 'Processing...' : 'Start Analysis'}
    </button>
  );
}

AnalysisButton.propTypes = {
  onClick: PropTypes.func.isRequired,
  disabled: PropTypes.bool,
};

AnalysisButton.defaultProps = {
  disabled: false,
};

export default AnalysisButton; 