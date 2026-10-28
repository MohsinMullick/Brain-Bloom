# Brain Bloom

A Django-based educational platform for North South University students, with user authentication and email verification. Students join timed study rooms, upload PDFs to get AI-generated summaries and key points, chat in real time, take a quiz, and see a live ranking.

## Features

- OTP email verification for @northsouth.edu students
- Public and private study rooms (private rooms use a join code)
- Timed room flow: 20-minute study session, 7-minute quiz, then live ranking
- PDF summarization with DistilBART (long documents are split into chunks)
- OCR (Tesseract) and image captioning (BLIP) for scanned PDFs
- Key-phrase extraction with KeyBERT and suggested Google and YouTube resources
- Quiz generation for each room (Celery task)
- Real-time updates with WebSockets (Django Channels)
- Notes upload, filter, download and rating with reviews
- Study partner recommendations by department, semester and shared rooms, with request accept/reject
- Password recovery by OTP, user profiles, platform reviews
- Progressive Web App support with an offline page

## Tech Stack

| Area | Technology |
|------|------------|
| Backend | Python, Django, Django Channels, Celery |
| NLP / ML | PyTorch, Hugging Face Transformers (DistilBART), KeyBERT, Sentence-Transformers |
| PDF / OCR | PyPDF2, PyMuPDF, Tesseract OCR |
| Database | SQLite |
| Deployment | Docker, Render, Fly.io |

## Screenshots

<!-- ![Dashboard](screenshots/dashboard.png) -->
<!-- ![Study Room](screenshots/room.png) -->
<!-- ![Quiz](screenshots/quiz.png) -->

## Getting Started

### Requirements
- Python 3.10+
- Tesseract OCR installed on your machine
- A Gmail (or other SMTP) account for sending OTP emails

### Installation

```bash
git clone https://github.com/MohsinMullick/Brain-Bloom.git
cd Brain-Bloom
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux / Mac
pip install -r requirements.txt
```

### Configuration

Set your email credentials and secret key in `settings.py` (or as environment variables):

- `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD`
- `SECRET_KEY`

Set the Tesseract path in `views.py` to match your installation.

### Run

```bash
python manage.py migrate
python manage.py runserver
```

Open `http://127.0.0.1:8000/` in your browser.

## Project Structure

| Path | Purpose |
|------|---------|
| `accounts/models.py` | User, Room, Summary, Quiz, Note and other models |
| `accounts/views.py` | Authentication, rooms, summarization, quiz, notes, study partners |
| `accounts/utils.py` | PDF text and key-point helpers |
| `accounts/templatetags/` | Custom template filters |
| `Dockerfile`, `render.yaml`, `fly.toml` | Deployment configuration |

## Author

**Mohsin Mullik**
[GitHub](https://github.com/MohsinMullick) · [ORCID](https://orcid.org/0009-0002-3664-4142)
