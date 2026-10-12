from fastapi.testclient import TestClient

from app.home_assistant import HAClient
from app.main import create_app


def test_entity_catalog_retains_latest_state_unit_and_observation_timestamp(tmp_path):
    class CatalogHA(HAClient):
        def request(self, method, path, **kwargs):
            assert (method, path) == ('GET', 'states')
            return [
                {'entity_id': 'sensor.temperature', 'state': '21.7',
                 'last_updated': '2026-10-12T09:03:00Z', 'last_changed': '2026-10-12T09:00:00Z',
                 'attributes': {'friendly_name': 'Temperatur kök', 'unit_of_measurement': '°C'}},
                {'entity_id': 'sensor.missing', 'state': 'unavailable', 'attributes': {}},
                {'entity_id': 'binary_sensor.rain', 'state': 'off', 'attributes': {}},
                {'entity_id': 'light.kitchen', 'state': 'on', 'attributes': {}},
            ]
    with TestClient(create_app(tmp_path, CatalogHA(url='http://example.test', token='test'))) as client:
        response = client.get('/api/entities')
        assert response.status_code == 200
        entities = response.json()
    assert len(entities) == 3
    assert entities[0]['state'] == '21.7'
    assert entities[0]['unit'] == '°C'
    assert entities[0]['name'] == 'Temperatur kök'
    assert entities[0]['last_updated'] == '2026-10-12T09:03:00Z'
    assert entities[0]['last_changed'] == '2026-10-12T09:00:00Z'
    assert entities[1]['state'] == 'unavailable' and entities[1]['last_updated'] is None
