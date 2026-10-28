import asyncio
import base64
from dataclasses import replace
from io import BytesIO
import json

import httpx2 as httpx
import pytest
from PIL import Image

from findie_ai.config import Settings
from findie_ai.ollama import ModelUnavailable, Ollama


SETTINGS = Settings(service_token='test', revision='a' * 64, dimensions=2)


def test_remote_endpoints_and_model_configuration_require_safe_values():
    for changes in ({'dimensions': 0}, {'dimensions': 16001}, {'revision': 'latest'},
                    {'redaction_revision': 'latest'},
                    {'ollama_base_url': 'http://remote.example'},
                    {'ollama_base_url': 'https://remote.example'},
                    {'ollama_base_url': 'https://user:pass@remote.example', 'ollama_api_key': 'test'},
                    {'rabbitmq_url': 'amqp://remote.example'},
                    {'image_queue': SETTINGS.query_queue}):
        with pytest.raises(ValueError):
            replace(SETTINGS, **changes)
    configured = replace(SETTINGS, ollama_base_url='https://gateway.example/ollama', ollama_api_key='secret')
    assert 'secret' not in repr(configured)


def image_bytes():
    buffer = BytesIO()
    with Image.new('RGB', (4, 4), 'white') as image:
        image.save(buffer, format='PNG')
    return buffer.getvalue()


def test_native_image_embedding_uses_same_model_space_and_authenticated_gateway():
    settings = replace(SETTINGS, image_search_enabled=True, ollama_base_url='https://gateway.example', ollama_api_key='secret')
    image = image_bytes()

    def respond(request):
        assert request.headers['Authorization'] == 'Bearer secret'
        assert request.headers['ngrok-skip-browser-warning'] == 'true'
        if request.method == 'GET':
            return httpx.Response(200, json={'models': [{'name': settings.model_id, 'digest': settings.revision}]})
        body = json.loads(request.content)
        assert body['input'] == {'image': base64.b64encode(image).decode()}
        assert body['model'] == settings.model_id and body['dimensions'] == settings.dimensions
        return httpx.Response(200, json={'model': settings.model_id, 'embeddings': [[3.0, 4.0]]})

    async def run():
        model = Ollama(settings, httpx.MockTransport(respond))
        try:
            assert await model.embed_image(image) == [0.6, 0.8]
        finally:
            await model.close()
    asyncio.run(run())


def test_media_calls_require_explicit_configuration():
    async def run():
        model = Ollama(SETTINGS)
        try:
            with pytest.raises(ModelUnavailable, match='image_search_not_configured'):
                await model.embed_image(image_bytes())
            with pytest.raises(ModelUnavailable, match='redaction_not_configured'):
                await model.detect_regions(image_bytes())
        finally:
            await model.close()
    asyncio.run(run())


def test_vision_redaction_uses_pinned_model_and_strict_structured_schema():
    settings = replace(SETTINGS, redaction_revision='b' * 64)
    image = image_bytes()
    paths = []

    def respond(request):
        paths.append(request.url.path)
        if request.method == 'GET':
            return httpx.Response(200, json={'models': [{'name': settings.redaction_model, 'digest': settings.redaction_revision}]})
        body = json.loads(request.content)
        assert body['model'] == settings.redaction_model and body['stream'] is False
        assert base64.b64decode(body['images'][0]) == image
        assert body['format']['additionalProperties'] is False
        assert body['format']['properties']['regions']['maxItems'] == 32
        return httpx.Response(200, json={'model': settings.redaction_model, 'done': True, 'done_reason': 'stop',
                                        'response': '{"regions":[{"label":"face","bbox":[0,0,100,100]}]}'})

    async def run():
        model = Ollama(settings, httpx.MockTransport(respond))
        try:
            assert await model.detect_regions(image) == [{'label': 'face', 'bbox': [0.0, 0.0, 100.0, 100.0]}]
            assert paths == ['/api/tags', '/api/generate', '/api/tags']
        finally:
            await model.close()
    asyncio.run(run())


@pytest.mark.parametrize('changes', [
    {'response': '{"regions":[{"label":"face","bbox":[0,0,NaN,100]}]}'},
    {'response': '{"regions":[{"label":"face","bbox":[0,0,100,100],"text":"private"}]}'},
    {'response': '{"regions":[{"label":"unknown","bbox":[0,0,100,100]}]}'},
    {'response': '{"regions":[]', 'done_reason': 'length'},
    {'done': False}, {'model': 'other'}, {'response': None}, {'response': 'private unstructured response'},
])
def test_redaction_rejects_invalid_or_incomplete_model_output_without_leaking_it(changes):
    settings = replace(SETTINGS, redaction_revision='b' * 64)

    def respond(request):
        body = {'models': [{'name': settings.redaction_model, 'digest': settings.redaction_revision}]} if request.method == 'GET' else {
            'model': settings.redaction_model, 'done': True, 'done_reason': 'stop', 'response': '{"regions":[]}', **changes}
        return httpx.Response(200, json=body)

    async def run():
        model = Ollama(settings, httpx.MockTransport(respond))
        try:
            with pytest.raises(ModelUnavailable, match='invalid_regions') as raised:
                await model.detect_regions(image_bytes())
            assert 'private' not in str(raised.value)
        finally:
            await model.close()
    asyncio.run(run())


@pytest.mark.parametrize('switch_after_generate', [False, True])
def test_redaction_changed_model_digest_fails_closed(switch_after_generate):
    settings = replace(SETTINGS, redaction_revision='b' * 64)
    generated = False

    def respond(request):
        nonlocal generated
        if request.method == 'POST':
            generated = True
            return httpx.Response(200, json={'model': settings.redaction_model, 'done': True,
                                           'done_reason': 'stop', 'response': '{"regions":[]}'})
        digest = settings.redaction_revision if switch_after_generate and not generated else 'c' * 64
        return httpx.Response(200, json={'models': [{'name': settings.redaction_model, 'digest': digest}]})

    async def run():
        model = Ollama(settings, httpx.MockTransport(respond))
        try:
            with pytest.raises(ModelUnavailable, match='revision'):
                await model.detect_regions(image_bytes())
        finally:
            await model.close()
    asyncio.run(run())
    assert generated == switch_after_generate


@pytest.mark.parametrize('vision_supported', [True, False])
def test_media_probe_checks_capabilities_and_caches_success_without_inference(vision_supported):
    settings = replace(SETTINGS, image_search_enabled=True, redaction_revision='b' * 64)
    requests = []

    def respond(request):
        requests.append(request.url.path)
        if request.method == 'GET':
            return httpx.Response(200, json={'models': [
                {'name': settings.model_id, 'digest': settings.revision},
                {'name': settings.redaction_model, 'digest': settings.redaction_revision}]})
        assert request.url.path == '/api/show'
        model = json.loads(request.content)['model']
        capabilities = ['embedding'] if model == settings.model_id else ['completion']
        return httpx.Response(200, json={'capabilities': capabilities + (['vision'] if vision_supported else [])})

    async def run():
        model = Ollama(settings, httpx.MockTransport(respond))
        try:
            if vision_supported:
                async with model.lock, asyncio.timeout(1):
                    await model.verify_models()
                assert requests == ['/api/tags', '/api/show', '/api/tags', '/api/show']
                await model.verify_models()
                assert len(requests) == 4
            else:
                with pytest.raises(ModelUnavailable, match='capability'):
                    await model.verify_models()
                assert model.media_verified_at == 0
        finally:
            await model.close()
    asyncio.run(run())


def test_image_search_environment_requires_boolean_and_defaults_to_text_only(monkeypatch):
    monkeypatch.setenv('AI_SERVICE_TOKEN', 'test')
    monkeypatch.setenv('AI_IMAGE_SEARCH_ENABLED', 'yes')
    with pytest.raises(ValueError, match='AI_IMAGE_SEARCH_ENABLED'):
        Settings.from_env()
    monkeypatch.delenv('AI_IMAGE_SEARCH_ENABLED')
    assert Settings.from_env().image_search_enabled is False


def test_embedding_pins_digest_preserves_instruction_and_normalizes():
    requests = []

    def respond(request):
        requests.append(request)
        if request.method == 'GET':
            return httpx.Response(200, json={'models': [{'name': SETTINGS.model_id, 'digest': SETTINGS.revision}]})
        body = json.loads(request.content)
        assert body['truncate'] is False and body['dimensions'] == 2
        assert body['input'].endswith('Query: ví đen phòng E.205')
        return httpx.Response(200, json={'model': SETTINGS.model_id, 'embeddings': [[3.0, 4.0]]})

    async def run():
        model = Ollama(SETTINGS, httpx.MockTransport(respond))
        try:
            assert await model.embed('ví đen phòng E.205', query=True) == [0.6, 0.8]
            assert [r.url.path for r in requests] == ['/api/tags', '/api/embed', '/api/tags']
        finally:
            await model.close()
    asyncio.run(run())


@pytest.mark.parametrize('vector', [[0, 0], [1], [float('nan'), 1], [float('inf'), 1], [True, 0], ['1', 0]])
def test_embedding_rejects_invalid_vectors(vector):
    def respond(request):
        payload = {'models': [{'name': SETTINGS.model_id, 'digest': SETTINGS.revision}]} if request.method == 'GET' else {
            'model': SETTINGS.model_id, 'embeddings': [vector]}
        return httpx.Response(200, content=json.dumps(payload).encode())

    async def run():
        model = Ollama(SETTINGS, httpx.MockTransport(respond))
        try:
            with pytest.raises(ModelUnavailable, match='invalid_embedding'):
                await model.embed('ví')
        finally:
            await model.close()
    asyncio.run(run())


@pytest.mark.parametrize('switch_after_embed', [False, True])
def test_changed_model_digest_fails_closed(switch_after_embed):
    embedded = False

    def respond(request):
        nonlocal embedded
        if request.method == 'POST':
            embedded = True
            return httpx.Response(200, json={'model': SETTINGS.model_id, 'embeddings': [[1, 0]]})
        digest = SETTINGS.revision if switch_after_embed and not embedded else 'b' * 64
        return httpx.Response(200, json={'models': [{'name': SETTINGS.model_id, 'digest': digest}]})

    async def run():
        model = Ollama(SETTINGS, httpx.MockTransport(respond))
        try:
            with pytest.raises(ModelUnavailable, match='revision'):
                await model.embed('ví')
        finally:
            await model.close()
    asyncio.run(run())
    assert embedded == switch_after_embed


def test_remote_error_body_is_not_exposed_and_redirect_is_not_followed():
    def respond(request):
        return httpx.Response(302, headers={'Location': 'https://other.example'}, text='private body')

    async def run():
        model = Ollama(SETTINGS, httpx.MockTransport(respond))
        try:
            with pytest.raises(ModelUnavailable) as raised:
                await model.embed('private query')
            assert 'private' not in str(raised.value)
        finally:
            await model.close()
    asyncio.run(run())
