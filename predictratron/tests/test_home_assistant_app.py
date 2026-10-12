import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.home_assistant import HAClient
from app.launch import configure
from app.main import create_app


def test_app_repository_metadata(tmp_path):
    root = Path(__file__).parents[1]
    config = yaml.safe_load((root / 'config.yaml').read_text())
    repository = yaml.safe_load((root.parent / 'repository.yaml').read_text())
    assert repository['url'] == 'https://github.com/AndreasFridh/Predictratron'
    assert config['name'] == 'Predictratron' and config['slug'] == 'predictratron'
    assert config['arch'] == ['aarch64', 'amd64']
    assert config['ingress'] and config['ingress_port'] == 8080
    assert config['homeassistant_api']
    assert config['backup'] == 'cold'
    assert 'image' not in config  # Supervisor builds the source on the host architecture.
    assert 'ports' not in config and not config.get('host_network', False)
    assert not config.get('hassio_api') and not config.get('privileged')
    with TestClient(create_app(data_dir=tmp_path, ha=HAClient(url='', token=''))) as client:
        assert client.get('/health').json()['version'] == config['version']


def test_launcher_uses_supervisor_without_exposing_token(tmp_path):
    options = tmp_path / 'options.json'
    options.write_text(json.dumps({'log_level': 'warning'}))
    env = {'SUPERVISOR_TOKEN': 'secret-for-test', 'APP_TOKEN': 'standalone-test-token'}
    assert configure(env, options) == 'warning'
    assert env['HA_URL'] == 'http://supervisor/core'
    assert env['INGRESS_ONLY'] == 'true'
    assert 'APP_TOKEN' not in env
    assert env['SUPERVISOR_TOKEN'] == 'secret-for-test'
    assert configure({}, tmp_path / 'missing') == 'info'
    options.write_text(json.dumps({'log_level': 'invalid'}))
    with pytest.raises(ValueError):
        configure({}, options)


def test_supervisor_ha_client_uses_own_service_credential(monkeypatch):
    monkeypatch.setenv('SUPERVISOR_TOKEN', 'test-secret')
    monkeypatch.delenv('HA_URL', raising=False)
    monkeypatch.delenv('HA_TOKEN', raising=False)
    monkeypatch.delenv('HA_TOKEN_FILE', raising=False)
    client = HAClient()
    assert client.url == 'http://supervisor/core'
    assert client.token == 'test-secret'
    assert client.configured


@pytest.mark.parametrize('url,expected', [('http://supervisor/core', 'ws://supervisor/core/websocket'), ('https://homeassistant.example', 'wss://homeassistant.example/api/websocket')])
def test_websocket_proxy_routes_are_correct(monkeypatch, url, expected):
    calls = []
    class Socket:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def __init__(self): self.messages = iter([{'type':'auth_required'}, {'type':'auth_ok'}, {'id':1, 'success':True, 'result':{'ok':True}}])
        def recv(self, **kwargs): return json.dumps(next(self.messages))
        def send(self, message): calls.append(json.loads(message))
    def connect(address, **kwargs):
        assert address == expected
        return Socket()
    monkeypatch.setattr('app.home_assistant.connect', connect)
    assert HAClient(url=url, token='test-secret').websocket({'type':'test_command'}) == {'ok':True}
    assert calls[0] == {'type':'auth', 'access_token':'test-secret'}


def test_ingress_prefix_and_standalone_assets(tmp_path):
    with TestClient(create_app(tmp_path, HAClient(url='', token=''))) as client:
        page = client.get('/')
        assert '<base href="/">' in page.text
        import re
        from urllib.parse import urlsplit
        asset = re.search(r'src="([^"]*app\.js[^"]*)"', page.text).group(1)
        assert urlsplit(asset).path == 'static/app.js'
        assert urlsplit(asset).query == 'v=' + client.get('/health').json()['version']
        assert client.get('/' + asset).status_code == 200
        assert '<title>Predictratron' in page.text
        prefixed = client.get('/', headers={'X-Ingress-Path':'/api/hassio_ingress/test-session'})
        assert '<base href="/api/hassio_ingress/test-session/">' in prefixed.text
        assert client.get('/static/app.js').status_code == 200
        assert "new URL('api/' + path, document.baseURI)" in client.get('/static/app.js').text
        assert client.get('/', headers={'X-Ingress-Path':'//evil.example'}).status_code == 400
        assert client.get('/', headers={'X-Ingress-Path':'/api/hassio_ingress/" onclick="x'}).status_code == 400


def test_ingress_rejects_non_supervisor_and_spoofed_forwarded_ip(tmp_path, monkeypatch):
    monkeypatch.setenv('INGRESS_ONLY', 'true')
    app = create_app(tmp_path, HAClient(url='', token=''))
    with TestClient(app, client=('172.30.33.4', 50000)) as client:
        assert client.get('/').status_code == 403
        assert client.get('/api/models', headers={'X-Forwarded-For':'172.30.32.2'}).status_code == 403
    with TestClient(app, client=('172.30.32.2', 50000)) as client:
        assert client.get('/', headers={'X-Ingress-Path':'/api/hassio_ingress/session'}).status_code == 200
        assert client.get('/api/models').status_code == 200
    with TestClient(app, client=('127.0.0.1', 50000)) as client:
        assert client.get('/health').status_code == 200
        assert client.get('/api/models').status_code == 403


def test_release_build_has_no_demo_creation_or_demo_navigation(tmp_path):
    with TestClient(create_app(tmp_path, HAClient(url='', token=''), dev_mode=False)) as client:
        assert client.get('/api/status').json()['dev_mode'] is False
        assert client.post('/api/demo/water').status_code == 404
        from app.engine import demo_data
        spec, _ = demo_data('water')
        client.app.state.store.create(spec)
        assert client.get('/api/models').json() == []
        assert 'lang="en"' in client.get('/').text


def test_development_build_retains_demo_examples(tmp_path):
    with TestClient(create_app(tmp_path, HAClient(url='', token=''), dev_mode=True)) as client:
        assert client.get('/api/status').json()['dev_mode'] is True
        assert client.post('/api/demo/water').status_code == 201
        assert len(client.get('/api/models').json()) == 1
