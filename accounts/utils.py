# utils.py
from keybert import KeyBERT
import logging

logger = logging.getLogger(__name__)

def extract_text_from_pdf(pdf_file):
    """
    Extract text from a PDF file.
    
    Args:
        pdf_file: The PDF file object.
    
    Returns:
        str: The extracted text.
    """
    # Placeholder implementation (you may already have this)
    try:
        import PyPDF2
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {str(e)}")
        return ""

def get_key_points(text, num_points=5):
    """
    Extract key points from text using KeyBERT.
    
    Args:
        text (str): The text to extract key points from.
        num_points (int): Number of key points to extract.
    
    Returns:
        list: A list of key points (strings).
    """
    try:
        # Initialize KeyBERT model
        kw_model = KeyBERT()
        # Extract keywords/key phrases
        keywords = kw_model.extract_keywords(
            text,
            keyphrase_ngram_range=(1, 3),  # Allow 1-3 word phrases
            stop_words='english',
            top_n=num_points
        )
        # Extract just the key phrases (not the scores)
        key_points = [keyword[0] for keyword in keywords]
        return key_points
    except Exception as e:
        logger.error(f"Error extracting key points: {str(e)}")
        return []