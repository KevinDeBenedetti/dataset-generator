# Test Suite Documentation

This directory contains comprehensive tests for the FastAPI dataset generator server.

## Test Structure

```
tests/
├── api/                    # API endpoint tests
│   ├── test_main.py        # Health check and root endpoints
│   ├── test_dataset.py     # Dataset CRUD operations
│   ├── test_q_a.py         # Q&A retrieval endpoints
│   └── test_openai.py      # OpenAI model listing
├── models/                 # Database model tests
│   └── test_dataset.py     # Dataset and QASource model tests
├── services/               # Service layer tests
│   ├── test_dataset.py     # Dataset service tests
│   └── test_llm.py         # LLM service tests
└── conftest.py             # Pytest configuration and fixtures

```

## Running Tests

### Run all tests
```bash
cd /path/to/dataset-generator
PYTHONPATH=apps/server python3 -m pytest apps/server/tests/ -v
```

### Run specific test file
```bash
PYTHONPATH=apps/server python3 -m pytest apps/server/tests/api/test_dataset.py -v
```

### Run with coverage
```bash
PYTHONPATH=apps/server python3 -m pytest apps/server/tests/ --cov=apps/server --cov-report=term-missing
```

### Using the Makefile (from project root)
```bash
make test
```

## Test Coverage

Current coverage: **67%**

### High Coverage Areas (>80%)
- API endpoints (dataset, q_a, openai)
- Models (Dataset, QASource)
- LLM Service
- Schemas

### Areas with Lower Coverage
- Pipeline logic (26%)
- Main application with lifespan (0% - skipped in tests)
- Migration utilities (0% - not tested)
- Langfuse integration (0% - optional feature)

## Test Fixtures

The following fixtures are available in `conftest.py`:

- `test_engine`: Creates a fresh in-memory SQLite database for each test
- `test_db`: Provides a database session for tests
- `client`: FastAPI TestClient with database override
- `sample_dataset_data`: Sample dataset data for tests
- `sample_qa_data`: Sample Q&A data for tests
- `sample_generation_request`: Sample generation request data

## Key Test Categories

### API Tests
- **Health & Documentation**: Verifies health endpoint and API documentation accessibility
- **Dataset CRUD**: Tests dataset creation, retrieval, update, and deletion
- **Q&A Retrieval**: Tests Q&A listing with pagination and filtering
- **OpenAI Integration**: Tests model listing endpoint

### Model Tests
- **Dataset Model**: Tests dataset creation and validation
- **QASource Model**: Tests Q&A source creation, hash computation, duplicate detection
- **Langfuse Integration**: Tests conversion to Langfuse dataset format

### Service Tests
- **Dataset Service**: Tests service layer for dataset operations
- **LLM Service**: Tests text cleaning, QA generation, and model listing

## Mocking Strategy

External API calls (OpenAI) are mocked using `unittest.mock` to:
- Avoid making real API calls during tests
- Ensure tests run quickly and reliably
- Test error handling scenarios

## Environment Variables

Tests automatically set required environment variables:
- `OPENAI_API_KEY=test-api-key`
- `OPENAI_BASE_URL=https://api.openai.com/v1`

## Known Limitations

1. **Pipeline Tests**: Not yet implemented - requires more complex setup with scraping
2. **Integration Tests**: Current tests are mostly unit tests with mocked dependencies
3. **Lifespan Tests**: Application lifespan (migrations) is skipped in tests to avoid complexity

## Contributing

When adding new features:
1. Add corresponding tests in the appropriate directory
2. Aim for >80% coverage on new code
3. Use existing fixtures and follow the established patterns
4. Run the full test suite before committing
