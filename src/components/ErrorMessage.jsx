import React from 'react';
import PropTypes from 'prop-types';

function ErrorMessage({ message }) {
  if (!message) {
    return null;
  }

  // Détecter si c'est un message d'erreur "sérieux" ou juste un statut
  const isError = message.toLowerCase().includes('erreur') || 
                  message.toLowerCase().includes('failed') || 
                  message.toLowerCase().includes('impossible');
                  
  const messageClass = isError ? 'error-message error' : 'error-message status';

  return (
    <div className={messageClass}>
      {message}
    </div>
  );
}

ErrorMessage.propTypes = {
  message: PropTypes.string,
};

ErrorMessage.defaultProps = {
  message: '',
};

export default ErrorMessage; 