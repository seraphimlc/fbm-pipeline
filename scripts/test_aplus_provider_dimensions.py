"""Provider request, size rejection and final artifact tests without paid calls."""
import asyncio
import base64
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.pipeline import step9_aplus_image as step9


def image_bytes(size):
    buffer = BytesIO()
    Image.new("RGB", size, "white").save(buffer, format="PNG")
    return buffer.getvalue()


async def main():
    assert step9._generation_provider_size(1940, 1200) == "3104x1920"
    assert step9._generation_provider_size(970, 600) == "1552x960"
    for dimensions in ((0, 1200), (4000, 1200), (2000, 100)):
        try:
            step9._generation_provider_size(*dimensions)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid dimensions accepted: {dimensions}")

    for dimensions in ((1595, 986), (1593, 987), (1952, 1199)):
        try:
            step9._ensure_provider_image_large_enough({"bytes": image_bytes(dimensions)}, 1940, 1200, "fixture")
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"undersized image accepted: {dimensions}")

    requests = []
    returned_dimensions = (3104, 1920)

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["size"] == "3104x1920"
        assert payload["quality"] == "high" and payload["image"]
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(image_bytes(returned_dimensions)).decode()}]})

    client_class = httpx.AsyncClient
    def client(**kwargs):
        return client_class(transport=httpx.MockTransport(respond), **kwargs)

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        reference = root / "reference.png"
        reference.write_bytes(image_bytes((128, 128)))
        script = {"module_position": 2, "width": 1940, "height": 1200,
                  "prompt": "A cabinet", "reference_images": [{"path": str(reference)}]}
        with patch.object(step9.httpx, "AsyncClient", client), \
             patch.object(step9, "_upload_generated_image_to_oss", return_value={"oss_url": "https://fixture.invalid/image.jpg"}) as upload, \
             patch.object(step9, "_apply_aplus_compliance", return_value={}):
            # The synchronous module path must submit explicit size and save exact JPEG dimensions.
            result = await step9._generate_single_image(script, root / "success.jpg", asyncio.Semaphore(1), "fixture")
            assert result["status"] == "done", result
            with Image.open(result["path"]) as image:
                assert image.size == (1940, 1200)
            assert Path(result["path"]).stat().st_size <= step9.settings.APLUS_IMAGE_MAX_BYTES
            assert result["raw_width"] == 3104 and result["raw_height"] == 1920
            # The durable initial-generation path must send the same size contract.
            submitted = await step9.submit_aplus_image_generation(script, brand=None, idempotency_key="fixture")
            assert submitted["state"] == "completed", submitted
            upload.reset_mock()
            # Even when a provider ignores size, fail before upload; never upscale.
            returned_dimensions = (1593, 987)
            result = await step9._generate_single_image(script, root / "small.jpg", asyncio.Semaphore(1), "fixture")
            assert result["status"] == "failed" and "1593x987" in result["error"]
            assert not (root / "small.jpg").exists()
            upload.assert_not_called()
    assert len(requests) == 3
    print("PASS: size rounding/limits, two provider submission paths, exact output, small-image rejection, no failed upload")


if __name__ == "__main__":
    asyncio.run(main())
