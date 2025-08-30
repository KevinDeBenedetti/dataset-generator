# Dataset Generator

Web scraping and automatic dataset generation tool for question-answer datasets.

## 🎯 Objective

Create quality datasets for training AI models by automatically scraping reliable sources and generating contextualized question-answer pairs.

## ⚡ Quick Start

```env
# OpenAI API Key
# Get your key from https://platform.openai.com/api-keys
OPENAI_API_KEY=sk-your-openai-api-key-here

# OpenAI API base URL
# Use the official URL or your custom proxy/gateway
# Official URL: https://api.openai.com/v1
# Proxy example: https://your-proxy.example.com/v1
OPENAI_BASE_URL=https://api.openai.com/v1
```

```bash
# Configuration
cp .env.example .env
# Edit .env with your API keys

# Launch
make start
```

## Using the POST /dataset API

This API triggers dataset generation from one or more URLs. The pipeline will: scrape the page, clean the text via an LLM, generate question-answer pairs, and save files (raw markdown, cleaned text, datasets).

- Endpoint: POST /dataset
- Content-Type: application/json
- Query parameters:
  - target_language: target language (e.g. fr, en)
  - model_cleaning: name of the model used for cleaning (e.g. gpt-4, gpt-3.5-turbo)
  - model_qa: name of the model used for QA generation (e.g. gpt-4, gpt-3.5-turbo)

Example curl command:

```bash
curl -X POST "http://localhost:8000/dataset?target_language=fr&model_cleaning=gpt-4&model_qa=gpt-4" \
  -H "Content-Type: application/json" \
  --data-raw '{
    "official_sources": {
      "main_site": {
        "url": "https://example-official.gov",
        "description": "Site officiel de l\'organisation"
      },
      "annex": {
        "url": "https://example-official.gov/annexe",
        "description": "Useful annex page"
      }
    }
  }'
```

Expected JSON body structure: any valid structure matching the UrlsConfig model. A minimal example:

```json
{
  "official_sources": {
    "main_site": {
      "url": "https://example-official.gov",
      "description": "Main official website"
    }
  }
}
```

API behavior:
- For each valid URL, the service:
  1. scrapes the page and saves the raw markdown,
  2. cleans the text using the `model_cleaning` model and saves the cleaned text,
  3. generates question-answer pairs using `model_qa` and saves the dataset(s).
- Progress and errors are printed to the server console (✅ / ❌) and logged.

Returned response (DatasetResult) — simplified example:

```json
{
  "task_id": "dataset-creation",
  "status": "completed",
  "urls_processed": 2,
  "qa_pairs_generated": 14,
  "files_generated": [
    "data/markdown/main_site.md",
    "data/cleaned/main_site.txt",
    "data/datasets/main_site.jsonl"
  ],
  "errors": [],
  "duration": 12.34,
  "rate": 0.16
}
```

- files_generated: list of paths to created files (paths returned by DataManager).
- errors: list of errors encountered during processing.
- duration, rate: processing metrics.

Where are files stored?
- Exact paths and folder structure are defined by the DataManager class (see `app/data_manager.py`). Typically the pipeline saves:
  - raw markdown,
  - cleaned text,
  - datasets (JSON / JSONL / CSV) in output folders configured by DataManager.

Practical tips:
- Make sure the API is running (e.g. uvicorn on localhost:8000).
- Ensure your LLM API keys are loaded in the environment (.env).
- Check `app/data_manager.py` to change output paths if needed.
- On errors, inspect the server logs to see messages recorded by ScrapingMetrics.


## 🏗️ Architecture

This project is designed with a modular architecture that separates concerns into distinct components:

- **Scraper**: Retrieval of web content from specified URLs
- **LLM Client**: Interaction with language models to generate question-answer pairs
- **Data Manager**: Data management and dataset storage
- **Pipeline**: Orchestration of the complete dataset generation process

The main workflow is managed by the `ScrapingPipeline` class which coordinates the entire process.

## 📚 Libraries Used

- **requests** >= 2.32.5 — HTTP requests for scraping
- **scrapy** >= 2.13.3 — Structured data extraction from HTML
- **fake-useragent** >= 2.2.0 — User-agent rotation to avoid scraping detection
- **openai** >= 1.102.0 — OpenAI API client for text processing
- **instructor** >= 1.10.0 — Tools to build structured LLM prompts / structured outputs
- **python-dotenv** >= 0.9.9 — Load environment variables from a .env file
- **fastapi** >= 0.116.1 — API framework used by the service
- **pytest** >= 8.4.1 — Testing framework

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
