"""
Smoke tests for the GUI's page structure: navigation and the three
required modes all resolve and render (Section 4). These don't test
feature behavior yet -- that grows alongside gui/controllers and
gui/forms as they get implemented.
"""


def test_index_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200


def test_config_editor_page_loads(client):
    response = client.get("/configuration/")
    assert response.status_code == 200


def test_schedule_generator_page_loads(client):
    response = client.get("/generate/")
    assert response.status_code == 200


def test_schedule_viewer_page_loads(client):
    response = client.get("/schedules/")
    assert response.status_code == 200
