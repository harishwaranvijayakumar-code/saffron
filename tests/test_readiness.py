
from unittest.mock import patch

import pytest
from django.test import Client


@pytest.mark.django_db
def test_readiness_returns_ready_when_database_is_available():
    response = Client().get("/ready/")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": "saffron",
        "database": "connected",
    }


@pytest.mark.django_db
def test_readiness_returns_503_when_database_is_unavailable():
    with patch(
        "config.views.connections"
    ) as connections:
        connections.__getitem__.return_value.cursor.side_effect = Exception(
            "database unavailable"
        )

        response = Client().get("/ready/")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "service": "saffron",
    }
