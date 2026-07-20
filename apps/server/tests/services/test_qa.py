"""Tests for QA service"""

from unittest.mock import Mock, patch

from server.services.qa import QAService
from server.services.dedup import DuplicateVerdict, compute_hash_from_content


def _existing_item(question: str, answer: str, context: str, source_url: str) -> dict:
    """A Langfuse dataset item shaped like `get_dataset_items` returns."""
    return {
        "id": compute_hash_from_content(question, answer, context, source_url),
        "status": "ACTIVE",
        "input": {"question": question, "context": context, "source_url": source_url},
        "expected_output": {"answer": answer},
        "metadata": {},
    }


class TestQAService:
    """Tests for QAService class"""

    def test_process_qa_pairs_new_items(self):
        """New QA pairs (no existing items) are all kept."""
        with patch("server.services.qa.get_dataset_items", return_value=[]):
            qa_service = QAService("test_dataset")

            mock_qa1 = Mock()
            mock_qa1.question = "What is Docker?"
            mock_qa1.answer = "A containerization platform"
            mock_qa1.confidence = 0.9

            mock_qa2 = Mock()
            mock_qa2.question = "What is Kubernetes?"
            mock_qa2.answer = "An orchestration system"
            mock_qa2.confidence = 0.85

            result = qa_service.process_qa_pairs(
                qa_list=[mock_qa1, mock_qa2],
                cleaned_text="Docker and Kubernetes are important DevOps tools.",
                url="https://example.com",
                model="gpt-4o-mini",
                similarity_threshold=0.9,
            )

        assert result["total"] == 2
        assert result["exact_duplicates"] == 0
        assert result["similar_duplicates"] == 0
        assert len(result["items"]) == 2
        assert {i["input"]["question"] for i in result["items"]} == {
            "What is Docker?",
            "What is Kubernetes?",
        }

    def test_process_qa_pairs_exact_duplicate(self):
        """A candidate matching an existing item's content hash is dropped."""
        existing = _existing_item(
            question="What is Python?",
            answer="A programming language",
            context="Python is a high-level programming language.",
            source_url="https://example.com",
        )
        with patch("server.services.qa.get_dataset_items", return_value=[existing]):
            qa_service = QAService("test_dataset")

            mock_qa = Mock()
            mock_qa.question = "What is Python?"
            mock_qa.answer = "A programming language"

            result = qa_service.process_qa_pairs(
                qa_list=[mock_qa],
                cleaned_text="Python is a high-level programming language.",
                url="https://example.com",
                model="gpt-4o-mini",
                similarity_threshold=0.9,
            )

        assert result["exact_duplicates"] == 1
        assert result["total"] == 0
        assert result["items"] == []

    @patch("server.services.qa.classify_duplicate")
    def test_process_qa_pairs_similar_duplicate(self, mock_classify):
        """Mocked dedup classification of 'similar' drops the candidate."""
        mock_classify.return_value = DuplicateVerdict(
            type="similar", duplicate_hash="similar-id", similarity_score=0.92
        )
        with patch("server.services.qa.get_dataset_items", return_value=[]):
            qa_service = QAService("test_dataset")

            mock_qa = Mock()
            mock_qa.question = "What exactly is Python?"
            mock_qa.answer = "Python is a programming language"

            result = qa_service.process_qa_pairs(
                qa_list=[mock_qa],
                cleaned_text="Python programming",
                url="https://example.com",
                model="gpt-4o-mini",
                similarity_threshold=0.9,
            )

        assert result["similar_duplicates"] == 1
        assert result["total"] == 0

    def test_process_qa_pairs_without_confidence(self):
        """Missing `confidence` attribute defaults to 1.0."""
        with patch("server.services.qa.get_dataset_items", return_value=[]):
            qa_service = QAService("test_dataset")

            mock_qa = Mock(spec=["question", "answer"])  # No confidence attribute
            mock_qa.question = "What is Redis?"
            mock_qa.answer = "An in-memory database"

            result = qa_service.process_qa_pairs(
                qa_list=[mock_qa],
                cleaned_text="Redis is fast",
                url="https://example.com",
                model="gpt-4o-mini",
                similarity_threshold=0.9,
            )

        assert result["total"] == 1
        assert result["items"][0]["expected_output"]["confidence"] == 1.0

    def test_process_qa_pairs_mixed_results(self):
        """A mix of new and exact-duplicate candidates in one call."""
        existing = _existing_item(
            question="What is Python?",
            answer="A programming language",
            context="ctx",
            source_url="https://example.com",
        )
        with patch("server.services.qa.get_dataset_items", return_value=[existing]):
            qa_service = QAService("test_dataset")

            mock_qa1 = Mock()
            mock_qa1.question = "New question 1?"
            mock_qa1.answer = "New answer 1"
            mock_qa1.confidence = 0.9

            mock_qa2 = Mock()
            mock_qa2.question = "What is Python?"
            mock_qa2.answer = "A programming language"
            mock_qa2.confidence = 0.9

            mock_qa3 = Mock()
            mock_qa3.question = "New question 2?"
            mock_qa3.answer = "New answer 2"
            mock_qa3.confidence = 0.8

            result = qa_service.process_qa_pairs(
                qa_list=[mock_qa1, mock_qa2, mock_qa3],
                cleaned_text="ctx",
                url="https://example.com",
                model="gpt-4o-mini",
                similarity_threshold=0.9,
            )

        assert result["total"] == 2
        assert result["exact_duplicates"] == 1

    def test_process_qa_pairs_empty_list(self):
        """Empty input yields empty output, no calls needed."""
        with patch("server.services.qa.get_dataset_items", return_value=[]):
            qa_service = QAService("test_dataset")
            result = qa_service.process_qa_pairs(
                qa_list=[],
                cleaned_text="Some text",
                url="https://example.com",
                model="gpt-4o-mini",
                similarity_threshold=0.9,
            )

        assert result["total"] == 0
        assert result["exact_duplicates"] == 0
        assert result["similar_duplicates"] == 0
        assert result["items"] == []

    def test_process_qa_pairs_dedups_across_calls_without_requery(self):
        """A duplicate introduced across two process_qa_pairs calls (e.g. two
        pages in the same pipeline run) is caught by the in-memory pool, with
        no extra Langfuse fetch between calls."""
        with patch(
            "server.services.qa.get_dataset_items", return_value=[]
        ) as mock_fetch:
            qa_service = QAService("test_dataset")

            mock_qa1 = Mock()
            mock_qa1.question = "What is Terraform?"
            mock_qa1.answer = "An infrastructure-as-code tool"
            mock_qa1.confidence = 0.9

            first = qa_service.process_qa_pairs(
                qa_list=[mock_qa1],
                cleaned_text="Terraform manages infrastructure.",
                url="https://example.com/page1",
                model="gpt-4o-mini",
                similarity_threshold=0.9,
            )
            assert first["total"] == 1

            mock_qa2 = Mock()
            mock_qa2.question = "What is Terraform?"
            mock_qa2.answer = "An infrastructure-as-code tool"

            second = qa_service.process_qa_pairs(
                qa_list=[mock_qa2],
                cleaned_text="Terraform manages infrastructure.",
                url="https://example.com/page1",
                model="gpt-4o-mini",
                similarity_threshold=0.9,
            )

        assert second["exact_duplicates"] == 1
        assert second["total"] == 0
        mock_fetch.assert_called_once()

    def test_process_qa_pairs_reuses_the_same_in_memory_pool(self):
        """The existing-entries pool is loaded once (lazily) and reused across
        calls — not reloaded from Langfuse every time."""
        with patch("server.services.qa.get_dataset_items", return_value=[]):
            qa_service = QAService("test_dataset")
            assert qa_service._existing_entries is None

            mock_qa1 = Mock()
            mock_qa1.question = "Q1?"
            mock_qa1.answer = "A1"
            mock_qa1.confidence = 0.9
            qa_service.process_qa_pairs(
                qa_list=[mock_qa1],
                cleaned_text="ctx",
                url="https://example.com",
                model="gpt-4o-mini",
                similarity_threshold=0.9,
            )
            pool_after_first_call = qa_service._existing_entries
            assert pool_after_first_call is not None
            assert len(pool_after_first_call) == 1

            mock_qa2 = Mock()
            mock_qa2.question = "Q2?"
            mock_qa2.answer = "A2"
            mock_qa2.confidence = 0.9
            qa_service.process_qa_pairs(
                qa_list=[mock_qa2],
                cleaned_text="ctx2",
                url="https://example.com",
                model="gpt-4o-mini",
                similarity_threshold=0.9,
            )
            # Same list object reused (not reloaded) and grown in place.
            assert qa_service._existing_entries is pool_after_first_call
            assert len(qa_service._existing_entries) == 2

    def test_process_qa_pairs_scoped_to_this_dataset_only(self):
        """`get_dataset_items` is called with this dataset's name, not globally."""
        with patch(
            "server.services.qa.get_dataset_items", return_value=[]
        ) as mock_fetch:
            qa_service = QAService("my-dataset")
            mock_qa = Mock()
            mock_qa.question = "Q?"
            mock_qa.answer = "A"
            mock_qa.confidence = 0.9
            qa_service.process_qa_pairs(
                qa_list=[mock_qa],
                cleaned_text="ctx",
                url="https://example.com",
                model="gpt-4o-mini",
                similarity_threshold=0.9,
            )
        mock_fetch.assert_called_once_with("my-dataset")

    def test_process_qa_pairs_langfuse_unreachable_falls_back_to_empty_pool(self):
        """If the Langfuse fetch errors (e.g. unreachable), dedup proceeds
        against an empty pool rather than failing generation."""
        with patch(
            "server.services.qa.get_dataset_items",
            side_effect=RuntimeError("unreachable"),
        ):
            qa_service = QAService("test_dataset")
            mock_qa = Mock()
            mock_qa.question = "Q?"
            mock_qa.answer = "A"
            mock_qa.confidence = 0.9
            result = qa_service.process_qa_pairs(
                qa_list=[mock_qa],
                cleaned_text="ctx",
                url="https://example.com",
                model="gpt-4o-mini",
                similarity_threshold=0.9,
            )

        assert result["total"] == 1

    def test_process_qa_pairs_applies_quality_rules_when_enabled(self):
        """With auto_reject_enabled, short answers and low-confidence pairs are
        rejected before dedup; without rules, everything passes."""
        rules = {
            "auto_reject_enabled": True,
            "min_answer_words": 3,
            "reject_below_confidence": 0.7,
        }
        with patch("server.services.qa.get_dataset_items", return_value=[]):
            qa_service = QAService("test_dataset", quality_rules=rules)

            too_short = Mock()
            too_short.question = "Q1?"
            too_short.answer = "Too short"  # 2 words < 3
            too_short.confidence = 0.9

            low_conf = Mock()
            low_conf.question = "Q2?"
            low_conf.answer = "A perfectly long enough answer"
            low_conf.confidence = 0.5  # < 0.7

            keeper = Mock()
            keeper.question = "Q3?"
            keeper.answer = "Another perfectly valid answer"
            keeper.confidence = 0.9

            result = qa_service.process_qa_pairs(
                qa_list=[too_short, low_conf, keeper],
                cleaned_text="ctx",
                url="https://example.com",
                model="gpt-4o-mini",
                similarity_threshold=0.9,
            )

        assert result["quality_rejected"] == 2
        assert result["total"] == 1
        assert result["items"][0]["input"]["question"] == "Q3?"

    def test_process_qa_pairs_quality_rules_disabled_by_default(self):
        """No rules passed → nothing is rejected (backwards compatible)."""
        with patch("server.services.qa.get_dataset_items", return_value=[]):
            qa_service = QAService("test_dataset")
            mock_qa = Mock()
            mock_qa.question = "Q?"
            mock_qa.answer = "Short"
            mock_qa.confidence = 0.1
            result = qa_service.process_qa_pairs(
                qa_list=[mock_qa],
                cleaned_text="ctx",
                url="https://example.com",
                model="gpt-4o-mini",
                similarity_threshold=0.9,
            )

        assert result["quality_rejected"] == 0
        assert result["total"] == 1
