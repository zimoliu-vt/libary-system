# Library Management System

A Flask library app with a public book gallery, a management page, JSON API documentation, cover uploads, reading status and ratings, AI-assisted categories, and NLB catalogue checks.

## Setup

Python 3.10 or newer is recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Then open:

- Library: <http://127.0.0.1:2500/>
- Management: <http://127.0.0.1:2500/management>
- API documentation: <http://127.0.0.1:2500/api>

## Configuration

Add your TypeSafe Jev API key to `.env` if you want AI-assisted categorisation:

```dotenv
TYPESAFE_API_KEY=your_typesafe_api_key_here
```

The app works without this key, but automatic AI categorisation will be unavailable. NLB catalogue checks use the public catalogue endpoint and do not require a key.

## Local data

Books, logs, uploaded covers, and backups are created locally when the app runs. They are excluded from Git and from the shareable upload bundle so personal data and credentials are not accidentally published.

The maximum uploaded cover size is 6 MB. Supported formats are JPEG, PNG, WebP, and GIF.
