import pytest


@pytest.fixture
def sample_df():
    import pandas as pd

    return pd.DataFrame(
        {"id": [1, 2, 3], "name": ["alice", "bob", "charlie"], "score": [10.0, 20.0, 30.0]}
    )
