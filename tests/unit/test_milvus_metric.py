"""vector_db.metric_type drives index creation; searches follow the existing index's metric."""
import pytest

from src.modules.assistant.infrastructure.database.milvus_client import MilvusClient


class FakePyMilvus:
    def __init__(self, *, exists: bool, index_metric: str | None = None):
        self.exists = exists
        self.index_metric = index_metric
        self.created_index = None
        self.search_params = None

    def has_collection(self, name):
        return self.exists

    def create_collection(self, collection_name, schema, index_params):
        self.created_index = index_params

    def describe_index(self, collection_name, index_name):
        if self.index_metric is None:
            raise RuntimeError("index missing")
        return {"metric_type": self.index_metric, "field_name": index_name}

    def search(self, *, search_params, **kwargs):
        self.search_params = search_params
        return [[]]


def connect(client: MilvusClient, fake: FakePyMilvus) -> None:
    client._ensure_collection(fake)
    client._connection = fake


def test_new_collection_is_indexed_with_configured_metric():
    fake = FakePyMilvus(exists=False)
    client = MilvusClient(metric_type="ip")
    connect(client, fake)

    index = next(iter(fake.created_index))
    assert index.to_dict()["metric_type"] == "IP"
    client.search_similar([0.1], top_k=3)
    assert fake.search_params == {"metric_type": "IP", "params": {"ef": 100}}


def test_existing_collection_metric_wins_over_config():
    fake = FakePyMilvus(exists=True, index_metric="COSINE")
    client = MilvusClient(metric_type="L2")
    connect(client, fake)

    assert client.metric_type == "COSINE"
    client.search_similar([0.1], top_k=3, ef=64)
    assert fake.search_params == {"metric_type": "COSINE", "params": {"ef": 64}}


def test_unreadable_index_keeps_configured_metric():
    client = MilvusClient(metric_type="L2")
    connect(client, FakePyMilvus(exists=True, index_metric=None))
    assert client.metric_type == "L2"


def test_unknown_metric_is_rejected():
    with pytest.raises(ValueError):
        MilvusClient(metric_type="HAMMING")
