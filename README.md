
# Chatbot Starter (Flask + OpenAI)

Minimal, portable school chatbot you can run locally or host yourself. 

## Quick Start

1) Create and activate a virtual environment:
```bash
mkdir -p ~/chatbot && cd ~/chatbot
python3 -m venv venv
source venv/bin/activate
```

2) Unzip this project here and install dependencies:
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

3) Add your OpenAI API key:
```bash
cp .env.example .env
# edit .env and paste your key
```

4) Run the app:
```bash
python app.py
```

Visit http://127.0.0.1:5000 in your browser. Paste school FAQs in the big box, ask a question, get an answer.

### Notes
- Uses the `gpt-4o-mini` model for speed + low cost.
- The knowledge box content is sent as context with each question.
- For production hosting later, we can deploy this to a small VPS or a serverless platform.
