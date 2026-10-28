"""CPU checks of the standalone Ollama notebook; no model download or network."""

import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock


NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks/colab/03_ollama_search.ipynb"


def tagged_source(tag):
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return next("".join(cell["source"]) for cell in notebook["cells"]
                if tag in cell["metadata"].get("tags", []))


class OllamaNotebookTests(unittest.TestCase):
    def helpers(self, api=None):
        scope = {"math": math, "MODEL": "test-model:1", "DIMENSIONS": 2,
                 "ollama_api": api, "QUERY_INSTRUCTION": "test instruction"}
        exec(tagged_source("embedding-helpers"), scope)
        return scope

    def test_python_cells_are_valid_and_outputs_are_cleared(self):
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        self.assertEqual(notebook["nbformat"], 4)
        self.assertEqual(notebook["metadata"]["kernelspec"]["name"], "python3")
        for index, cell in enumerate(notebook["cells"]):
            if cell["cell_type"] == "code":
                self.assertEqual(cell["outputs"], [])
                self.assertIsNone(cell["execution_count"])
                compile("".join(cell["source"]), f"{NOTEBOOK.name}:cell{index}", "exec")

    def test_embedding_rejects_invalid_vectors_and_truncation(self):
        api = Mock(return_value={"model": "test-model:1", "embeddings": [[3, 4]]})
        scope = self.helpers(api)
        self.assertEqual(scope["embed"](["Ví đen phòng E.205"]), [[0.6, 0.8]])
        api.assert_called_once_with("/api/embed", {
            "model": "test-model:1", "input": ["Ví đen phòng E.205"],
            "dimensions": 2, "truncate": False,
        })
        for invalid in ([0, 0], [1], [math.nan, 1], [math.inf, 1], [True, 1], ["1", 1]):
            with self.subTest(vector=invalid), self.assertRaises(ValueError):
                scope["validate_vector"](invalid, 2)
        for invalid in ([], [""], [" "], [1], "query"):
            with self.subTest(query=invalid), self.assertRaises(ValueError):
                scope["embed"](invalid)
        api.return_value = {"model": "test-model:1", "embeddings": []}
        with self.assertRaisesRegex(ValueError, "số lượng"):
            scope["embed"](["E.205"])

    def test_ranking_is_deterministic_and_rejects_bad_dimensions(self):
        rank = self.helpers()["rank_documents"]
        records = [{"id": "b", "description": "E.206"}, {"id": "a", "description": "E.205"}]
        self.assertEqual([row["id"] for row in rank([1, 0], [[2, 0], [3, 0]], records)], ["a", "b"])
        with self.assertRaises(ValueError):
            rank([1, 0], [[1, 0]], records)
        with self.assertRaises(ValueError):
            rank([1, 0], [[1], [1, 0]], records)

    def test_digest_mismatch_stops_before_inference(self):
        scope = {
            "subprocess": Mock(), "ollama_env": {}, "MODEL": "test-model:1",
            "EXPECTED_REVISION": "a" * 64,
            "ollama_api": Mock(return_value={"models": [{"name": "test-model:1", "digest": "b" * 64}]}),
        }
        with self.assertRaisesRegex(RuntimeError, "Digest"):
            exec(tagged_source("model-identity"), scope)

    def test_export_contains_only_allowlisted_configuration_and_sample_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            scope = {
                "json": json, "WORK": Path(directory), "MODEL": "test-model:1",
                "observed_revision": "a" * 64, "DIMENSIONS": 2,
                "runtime_version": "test", "QUERY_INSTRUCTION": "test instruction",
                "QUERY": "private arbitrary query", "OLLAMA_API_KEY": "secret credential",
                "DOWNLOAD_RESULTS": False, "sample_evaluation": [{"query": "synthetic E.205"}],
            }
            exec(tagged_source("export"), scope)
            output = (Path(directory) / "findie-ollama-sample.json").read_text(encoding="utf-8")
            self.assertNotIn(scope["OLLAMA_API_KEY"], output)
            self.assertNotIn(scope["QUERY"], output)
            self.assertEqual(json.loads(output)["sample_cases"], scope["sample_evaluation"])


if __name__ == "__main__":
    unittest.main()
