# Dataset Generator

Web scraping and automatic dataset generation tool for question-answer datasets.

## 🎯 Objective

Create quality datasets for training AI models by automatically scraping reliable sources and generating contextualized question-answer pairs.

## ⚡ Quick Start

```bash
# Configuration
cp .env.example .env
# Edit .env with your API keys

# Launch
make start
```

## 🏗️ Architecture

This project is designed with a modular architecture that separates concerns into distinct components:

- **Scraper**: Retrieval of web content from specified URLs
- **LLM Client**: Interaction with language models to generate question-answer pairs
- **Data Manager**: Data management and dataset storage
- **Pipeline**: Orchestration of the complete dataset generation process

The main workflow is managed by the `ScrapingPipeline` class which coordinates the entire process.

## 📚 Libraries Used

- **requests**: Execution of HTTP requests for scraping
- **scrapy**: Extraction of structured data from HTML
- **fake-useragent**: Rotation of user-agents to avoid scraping detection
- **openai**: Communication with OpenAI API for text processing
- **instructor**: Enhancement of interaction with LLMs to generate structured outputs
- **dotenv**: Management of environment variables and configurations

## 🛠️ Features

### Web Scraping

The scraping module (`app/scraper.py`) allows you to:
- Retrieve web page content with error handling and retries
- Extract relevant text from HTML pages by eliminating unwanted elements
- Use a user-agent rotation system to avoid blocking
- Cache results to avoid requesting the same URLs multiple times

```python
# Example of scraper usage
from app.scraper import WebScraper

scraper = WebScraper(use_cache=True)
content = scraper.scrape_url("https://example.com")
```

### Using LLMs

The project uses language models for two main tasks:

1. **Text Cleaning**: Extraction of relevant information and noise removal
2. **QA Generation**: Automatic creation of contextualized question-answer pairs

Interactions with LLMs are managed through the OpenAI API using specific prompts.

### Dataset Generation

Datasets are generated in several formats:
- **JSON**: Structured format for programmatic access
- **JSONL**: Line-by-line format ideal for large datasets
- **CSV**: Tabular format for analysis with tools like Excel

Each entry contains:
- A question
- A detailed answer
- The source context
- A confidence score

### Cache System

To optimize performance and reduce network calls:
- Scraping results are cached
- API requests to LLMs can be cached

## 📂 Project Structure

```
datasets/
├── app/                      # Main code
│   ├── cache.py              # Caching system
│   ├── config.py             # Configuration
│   ├── data_manager.py       # Data management and storage
│   ├── llm_client.py         # Interaction with LLMs
│   ├── models.py             # Data model definitions
│   ├── scraper.py            # Scraping module
│   └── utils.py              # Utilities
├── datasets/                 # Generated datasets
│   ├── qa/                   # Generated QA pairs
│   └── texts/                # Cleaned texts
├── scrapes/                  # Raw scraped data
├── main.py                   # Entry point
├── Makefile                  # Make commands
└── pyproject.toml            # Project configuration
```

## 🔄 Workflow

1. **Scraping**: Retrieving raw web data
2. **Cleaning**: Processing text to extract relevant content
3. **QA Generation**: Creating question-answer pairs via LLMs
4. **Storage**: Exporting data in different formats

## 🧩 Extensibility

The project can easily be extended to:
- Add new data sources
- Integrate other AI models
- Modify output formats
- Customize text processing

## 📝 Notes

- Make sure to respect the terms of use of the websites you scrape
- Using LLM APIs may incur costs depending on your provider

## 🚀 API Usage

Le projet expose une API REST qui permet de lancer des tâches de scraping et de génération de datasets:

```bash
# Lancer le serveur API
make api
```

### Endpoints

- `GET /` - Informations sur l'API
- `POST /scrape/urls` - Lancer une tâche avec configuration hiérarchique
- `POST /scrape/simple` - Lancer une tâche avec liste simple d'URLs
- `GET /tasks/{task_id}` - Vérifier le statut d'une tâche

### Exemples d'utilisation

#### Configuration hiérarchique (comme urls.json)

```bash
curl -X POST http://localhost:8000/scrape/urls \
  -H "Content-Type: application/json" \
  -d '{
    "urls_config": {
      "ministeres": {
        "interieur": {
          "url": "https://fr.wikipedia.org/wiki/Minist%C3%A8re_de_l%27Int%C3%A9rieur_(France)",
          "description": "Page Wikipedia du ministère de l'Intérieur"
        }
      }
    },
    "use_cache": true,
    "target_language": "fr"
  }'
```

#### Liste simple d'URLs

```bash
curl -X POST http://localhost:8000/scrape/simple \
  -H "Content-Type: application/json" \
  -d '{
    "urls": [
      "https://fr.wikipedia.org/wiki/Minist%C3%A8re_de_l%27Int%C3%A9rieur_(France)"
    ],
    "category": "gouvernement",
    "use_cache": true
  }'
```

#### Vérification du statut

```bash
curl -X GET http://localhost:8000/tasks/f47ac10b-58cc-4372-a567-0e02b2c3d479
```

La documentation complète de l'API est disponible à l'adresse `http://localhost:8000/docs` après le lancement du serveur.

