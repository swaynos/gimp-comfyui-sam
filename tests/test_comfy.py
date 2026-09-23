import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import pathlib
import sys
import threading
import unittest


PLUGIN = pathlib.Path(__file__).parents[1] / "plug-ins" / "gimp-comfyui-sam"
sys.path.insert(0, str(PLUGIN))

from sam_comfy import (  # noqa: E402
    DEFAULT_ENDPOINT,
    ComfyClient,
    MODEL_NAME,
    UploadReference,
    build_workflow,
    find_dotenv,
    get_default_endpoint,
    load_dotenv,
    normalize_endpoint,
)
from sam_core import SamError  # noqa: E402
from sam_png import encode_png  # noqa: E402


MASK = encode_png(1, 1, bytes([255, 255, 255]), 3)


def node_info(name):
    if name == "CheckpointLoaderSimple":
        return {
            "input": {"required": {"ckpt_name": [[MODEL_NAME]]}},
            "output": ["MODEL", "CLIP", "VAE"],
        }
    if name == "SAM3_Detect":
        return {
            "input": {
                "required": {
                    "model": ["MODEL", {}],
                    "image": ["IMAGE", {}],
                    "threshold": [
                        "FLOAT",
                        {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01},
                    ],
                    "refine_iterations": [
                        "INT",
                        {"default": 2, "min": 0, "max": 5},
                    ],
                    "individual_masks": ["BOOLEAN", {"default": False}],
                },
                "optional": {
                    "positive_coords": ["STRING", {}],
                    "negative_coords": ["STRING", {}],
                },
            },
            "output": ["MASK", "BOUNDING_BOX"],
        }
    if name == "LoadImage":
        return {
            "input": {"required": {"image": [["source.png"], {"image_upload": True}]}},
            "output": ["IMAGE", "MASK"],
        }
    return {
        "input": {"required": {"mask": ["MASK", {}]}},
        "output": ["MASK"],
        "output_node": True,
    }


class Handler(BaseHTTPRequestHandler):
    prompt = None

    def log_message(self, _format, *_args):
        pass

    def _send(self, body, content_type="application/json"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/system_stats":
            self._send(b'{"system":{"comfyui_version":"test"}}')
        elif self.path.startswith("/object_info/"):
            name = self.path.rsplit("/", 1)[-1]
            self._send(json.dumps({name: node_info(name)}).encode())
        elif self.path == "/history/prompt-1":
            history = {
                "prompt-1": {
                    "status": {"status_str": "success", "completed": True},
                    "outputs": {
                        "6": {
                            "images": [
                                {"filename": "mask.png", "subfolder": "", "type": "temp"}
                            ]
                        }
                    },
                }
            }
            self._send(json.dumps(history).encode())
        elif self.path.startswith("/view?"):
            self._send(MASK, "image/png")
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        if self.path == "/upload/image":
            if b"\x89PNG\r\n\x1a\n" not in body:
                self.send_error(400)
                return
            self._send(b'{"name":"source.png","subfolder":"","type":"input"}')
        elif self.path == "/prompt":
            Handler.prompt = json.loads(body)
            self._send(b'{"prompt_id":"prompt-1"}')
        else:
            self.send_error(404)


class ComfyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_workflow_serializes_both_arrays(self):
        workflow = build_workflow(
            UploadReference("source.png", "folder", "input"),
            [{"x": 1, "y": 2}],
            [],
            0.5,
            2,
        )
        self.assertEqual(workflow["1"]["inputs"]["image"], "folder/source.png")
        self.assertEqual(workflow["5"]["inputs"]["positive_coords"], '[{"x":1,"y":2}]')
        self.assertEqual(workflow["5"]["inputs"]["negative_coords"], "[]")

    def test_end_to_end_transport_contract(self):
        endpoint = f"http://127.0.0.1:{self.server.server_port}"
        client = ComfyClient(endpoint, operation_timeout=2, total_timeout=5)
        response = client.generate(
            png=encode_png(1, 1, bytes([1, 2, 3]), 3),
            positive=[{"x": 0, "y": 0}],
            negative=[],
            threshold=0.5,
            refinement=2,
            client_id="test-client",
            cancel=threading.Event(),
        )
        self.assertEqual(response.prompt_id, "prompt-1")
        self.assertEqual(response.mask_png, MASK)
        self.assertEqual(Handler.prompt["client_id"], "test-client")

    def test_default_endpoint_behavior(self):
        original = os.environ.get("COMFYUI_ENDPOINT")
        from unittest.mock import patch

        try:
            with patch("sam_comfy.find_dotenv", return_value=None):
                os.environ.pop("COMFYUI_ENDPOINT", None)
                self.assertEqual(get_default_endpoint(), "http://127.0.0.1:8188")
                self.assertEqual(DEFAULT_ENDPOINT, "http://127.0.0.1:8188")

                os.environ["COMFYUI_ENDPOINT"] = "http://my-comfy-host:8188/"
                self.assertEqual(get_default_endpoint(), "http://my-comfy-host:8188")

                os.environ["COMFYUI_ENDPOINT"] = "not-a-valid-url"
                self.assertEqual(get_default_endpoint(), "http://127.0.0.1:8188")
        finally:
            if original is not None:
                os.environ["COMFYUI_ENDPOINT"] = original
            else:
                os.environ.pop("COMFYUI_ENDPOINT", None)

    def test_normalize_endpoint(self):
        self.assertEqual(normalize_endpoint("http://localhost:8188/"), "http://localhost:8188")
        self.assertEqual(normalize_endpoint("  https://server.internal:9000  "), "https://server.internal:9000")
        with self.assertRaises(SamError):
            normalize_endpoint("ftp://localhost:8188")
        with self.assertRaises(SamError):
            normalize_endpoint("http://user:pass@localhost:8188")
        with self.assertRaises(SamError):
            normalize_endpoint("http://localhost:8188?query=1")

    def test_load_dotenv(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = pathlib.Path(temp_dir) / ".env"
            env_file.write_text(
                "# Test .env file\n"
                "COMFYUI_ENDPOINT=http://env-host:8188\n"
                "EXPORTED_VAL=\"quoted-value\"\n"
                "export ANOTHER_VAL='single-quoted'\n",
                encoding="utf-8",
            )
            orig_endpoint = os.environ.get("COMFYUI_ENDPOINT")
            try:
                self.assertTrue(load_dotenv(env_file, override=True))
                self.assertEqual(os.environ.get("COMFYUI_ENDPOINT"), "http://env-host:8188")
                self.assertEqual(os.environ.get("EXPORTED_VAL"), "quoted-value")
                self.assertEqual(os.environ.get("ANOTHER_VAL"), "single-quoted")
                self.assertEqual(get_default_endpoint(), "http://env-host:8188")
            finally:
                if orig_endpoint is not None:
                    os.environ["COMFYUI_ENDPOINT"] = orig_endpoint
                else:
                    os.environ.pop("COMFYUI_ENDPOINT", None)
                os.environ.pop("EXPORTED_VAL", None)
                os.environ.pop("ANOTHER_VAL", None)


if __name__ == "__main__":
    unittest.main()
