"""Bounded ComfyUI HTTP client for the owned SAM3 workflow."""

from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
import os
from pathlib import Path
import ssl
import threading
import time
from typing import Callable, Iterable, Optional
from urllib.parse import quote, urlencode, urlsplit
import uuid

from sam_core import MAX_DOWNLOAD_BYTES, SamError


MODEL_NAME = "sam3.1_multiplex_fp16.safetensors"
REQUIRED_NODES = ("LoadImage", "CheckpointLoaderSimple", "SAM3_Detect", "MaskPreview")


class CancelledError(SamError):
    pass


class HttpStatusError(SamError):
    pass


class TransportError(SamError):
    pass


class SubmissionUncertainError(SamError):
    pass


@dataclass(frozen=True)
class UploadReference:
    name: str
    subfolder: str
    kind: str


@dataclass(frozen=True)
class GenerationResponse:
    prompt_id: str
    upload: UploadReference
    mask_png: bytes


DEFAULT_ENDPOINT = "http://127.0.0.1:8188"


def find_dotenv(start: Optional[Path | str] = None) -> Optional[Path]:
    """Search for a .env file in standard locations."""
    if start:
        candidate = Path(start)
        if candidate.is_file():
            return candidate
        if candidate.is_dir() and (candidate / ".env").is_file():
            return candidate / ".env"

    try:
        cwd_env = Path.cwd() / ".env"
        if cwd_env.is_file():
            return cwd_env
    except Exception:
        pass

    try:
        current = Path(__file__).resolve().parent
        for _ in range(5):
            candidate = current / ".env"
            if candidate.is_file():
                return candidate
            if (current / ".git").exists():
                break
            if current.parent == current:
                break
            current = current.parent
    except Exception:
        pass

    try:
        gimp_env = Path.home() / ".config" / "GIMP" / "3.2" / "plug-in-settings" / ".env"
        if gimp_env.is_file():
            return gimp_env
    except Exception:
        pass

    return None


def load_dotenv(path: Optional[Path | str] = None, override: bool = False) -> bool:
    """Load key-value pairs from a .env file into os.environ."""
    target = find_dotenv(path)
    if not target:
        return False
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return False

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and (
            (val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")
        ):
            val = val[1:-1]
        if key and (override or key not in os.environ):
            os.environ[key] = val
    return True


load_dotenv()


def get_default_endpoint() -> str:
    load_dotenv()
    raw = os.environ.get("COMFYUI_ENDPOINT")
    if raw:
        try:
            return normalize_endpoint(raw)
        except SamError:
            pass
    return DEFAULT_ENDPOINT


def normalize_endpoint(value: str) -> str:
    endpoint = value.strip().rstrip("/")
    parsed = urlsplit(endpoint)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SamError("Server endpoint must be an http:// or https:// URL.")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise SamError("Server endpoint cannot contain credentials, a query, or a fragment.")
    return endpoint


def build_workflow(
    upload: UploadReference,
    positive: list[dict[str, int]],
    negative: list[dict[str, int]],
    threshold: float,
    refinement: int,
) -> dict[str, object]:
    if not positive:
        raise SamError("SAM generation requires at least one positive point.")
    if not 0.0 <= threshold <= 1.0:
        raise SamError("Threshold must be between 0.00 and 1.00.")
    if not 0 <= refinement <= 5:
        raise SamError("Refinement passes must be between 0 and 5.")
    image_name = upload.name
    if upload.subfolder:
        image_name = f"{upload.subfolder}/{image_name}"
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": MODEL_NAME},
        },
        "5": {
            "class_type": "SAM3_Detect",
            "inputs": {
                "model": ["4", 0],
                "image": ["1", 0],
                "positive_coords": json.dumps(positive, separators=(",", ":")),
                "negative_coords": json.dumps(negative, separators=(",", ":")),
                "threshold": threshold,
                "refine_iterations": refinement,
                "individual_masks": False,
            },
        },
        "6": {"class_type": "MaskPreview", "inputs": {"mask": ["5", 0]}},
    }


def extract_output_reference(history: dict[str, object], prompt_id: str) -> UploadReference:
    record = history.get(prompt_id)
    if not isinstance(record, dict):
        raise SamError("ComfyUI history did not contain the submitted prompt.")
    outputs = record.get("outputs")
    node = outputs.get("6") if isinstance(outputs, dict) else None
    images = node.get("images") if isinstance(node, dict) else None
    if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], dict):
        raise SamError("ComfyUI returned an unexpected number of mask outputs.")
    image = images[0]
    name = image.get("filename")
    subfolder = image.get("subfolder", "")
    kind = image.get("type", "temp")
    if not all(isinstance(value, str) for value in (name, subfolder, kind)) or not name:
        raise SamError("ComfyUI returned a malformed mask reference.")
    return UploadReference(name, subfolder, kind)


class ComfyClient:
    def __init__(
        self,
        endpoint: str,
        operation_timeout: float = 15.0,
        total_timeout: float = 600.0,
    ) -> None:
        self.endpoint = normalize_endpoint(endpoint)
        self.parsed = urlsplit(self.endpoint)
        self.operation_timeout = operation_timeout
        self.total_timeout = total_timeout

    @property
    def origin(self) -> str:
        return f"{self.parsed.scheme}://{self.parsed.netloc}"

    def _path(self, route: str) -> str:
        base = self.parsed.path.rstrip("/")
        return f"{base}{route}"

    def _remaining_timeout(self, deadline: Optional[float]) -> float:
        if deadline is None:
            return self.operation_timeout
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SamError("ComfyUI request exceeded the configured total deadline.")
        return min(self.operation_timeout, remaining)

    def _connection(self, timeout: Optional[float] = None) -> http.client.HTTPConnection:
        timeout = self.operation_timeout if timeout is None else timeout
        if self.parsed.scheme == "https":
            return http.client.HTTPSConnection(
                self.parsed.hostname,
                self.parsed.port,
                timeout=timeout,
                context=ssl.create_default_context(),
            )
        return http.client.HTTPConnection(
            self.parsed.hostname, self.parsed.port, timeout=timeout
        )

    def _request(
        self,
        method: str,
        route: str,
        *,
        body: Optional[bytes] = None,
        chunks: Optional[Iterable[bytes]] = None,
        content_length: Optional[int] = None,
        content_type: Optional[str] = None,
        max_bytes: int = 8 * 1024 * 1024,
        timeout: Optional[float] = None,
        deadline: Optional[float] = None,
    ) -> bytes:
        if deadline is not None:
            timeout = min(timeout or self.operation_timeout, self._remaining_timeout(deadline))
        connection = self._connection(timeout)
        deadline_timer: Optional[threading.Timer] = None
        if deadline is not None:
            deadline_timer = threading.Timer(
                max(0.0, deadline - time.monotonic()), connection.close
            )
            deadline_timer.daemon = True
            deadline_timer.start()
        try:
            connection.putrequest(method, self._path(route))
            connection.putheader("Accept", "application/json, image/png")
            connection.putheader("User-Agent", "gimp-comfyui-sam/1")
            if content_type:
                connection.putheader("Content-Type", content_type)
            if body is not None:
                content_length = len(body)
            if content_length is not None:
                connection.putheader("Content-Length", str(content_length))
            connection.endheaders()
            if body is not None:
                if connection.sock is not None:
                    connection.sock.settimeout(self._remaining_timeout(deadline))
                connection.send(body)
            elif chunks is not None:
                for chunk in chunks:
                    if connection.sock is not None:
                        connection.sock.settimeout(self._remaining_timeout(deadline))
                    connection.send(chunk)
            if connection.sock is not None:
                connection.sock.settimeout(self._remaining_timeout(deadline))
            response = connection.getresponse()
            if response.length is not None and response.length > max_bytes:
                raise SamError("Server response exceeds the configured download limit.")
            payload = bytearray()
            while True:
                if deadline is not None and time.monotonic() >= deadline:
                    raise SamError("ComfyUI request exceeded the configured total deadline.")
                if connection.sock is not None:
                    connection.sock.settimeout(self._remaining_timeout(deadline))
                part = response.read1(min(64 * 1024, max_bytes + 1 - len(payload)))
                if not part:
                    break
                payload.extend(part)
                if len(payload) > max_bytes:
                    raise SamError("Server response exceeds the configured download limit.")
            if not 200 <= response.status < 300:
                raise HttpStatusError(f"ComfyUI returned HTTP {response.status}.")
            return bytes(payload)
        except (OSError, http.client.HTTPException) as error:
            raise TransportError(f"Could not reach ComfyUI at {self.origin}: {error}") from error
        finally:
            if deadline_timer is not None:
                deadline_timer.cancel()
            connection.close()

    def _json(
        self,
        method: str,
        route: str,
        body: Optional[dict[str, object]] = None,
        deadline: Optional[float] = None,
    ) -> dict[str, object]:
        encoded = None
        content_type = None
        if body is not None:
            encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
            content_type = "application/json"
        payload = self._request(
            method, route, body=encoded, content_type=content_type, deadline=deadline
        )
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SamError("ComfyUI returned malformed JSON.") from error
        if not isinstance(value, dict):
            raise SamError("ComfyUI returned an unexpected JSON value.")
        return value

    def inspect(self, deadline: Optional[float] = None) -> dict[str, object]:
        if deadline is None:
            deadline = time.monotonic() + self.total_timeout
        stats = self._json("GET", "/system_stats", deadline=deadline)
        metadata: dict[str, object] = {}
        for name in REQUIRED_NODES:
            response = self._json(
                "GET", f"/object_info/{quote(name)}", deadline=deadline
            )
            node = response.get(name)
            if not isinstance(node, dict):
                raise SamError(f"ComfyUI is missing required node {name}.")
            metadata[name] = node

        checkpoint = metadata["CheckpointLoaderSimple"]
        checkpoint_input = checkpoint.get("input") if isinstance(checkpoint, dict) else None
        required = checkpoint_input.get("required") if isinstance(checkpoint_input, dict) else None
        ckpt = required.get("ckpt_name") if isinstance(required, dict) else None
        choices = ckpt[0] if isinstance(ckpt, list) and ckpt else None
        if not isinstance(choices, list) or MODEL_NAME not in choices:
            raise SamError(f"ComfyUI does not provide checkpoint {MODEL_NAME}.")

        load_image = metadata["LoadImage"]
        load_input = load_image.get("input") if isinstance(load_image, dict) else None
        load_required = load_input.get("required") if isinstance(load_input, dict) else None
        if not isinstance(load_required, dict) or "image" not in load_required:
            raise SamError("LoadImage has an incompatible input schema.")
        image_descriptor = load_required.get("image")
        if (
            not isinstance(image_descriptor, list)
            or len(image_descriptor) < 2
            or not isinstance(image_descriptor[0], list)
            or not isinstance(image_descriptor[1], dict)
            or image_descriptor[1].get("image_upload") is not True
        ):
            raise SamError("LoadImage does not expose a compatible upload input.")
        if list(load_image.get("output", []))[:2] != ["IMAGE", "MASK"]:
            raise SamError("LoadImage has an incompatible output schema.")
        if list(checkpoint.get("output", []))[:1] != ["MODEL"]:
            raise SamError("CheckpointLoaderSimple has an incompatible output schema.")

        sam = metadata["SAM3_Detect"]
        sam_input = sam.get("input") if isinstance(sam, dict) else None
        sam_required = sam_input.get("required") if isinstance(sam_input, dict) else None
        sam_optional = sam_input.get("optional") if isinstance(sam_input, dict) else None
        required_names = {"model", "image", "threshold", "refine_iterations", "individual_masks"}
        optional_names = {"positive_coords", "negative_coords"}
        if not isinstance(sam_required, dict) or not required_names.issubset(sam_required):
            raise SamError("SAM3_Detect has an incompatible required-input schema.")
        if not isinstance(sam_optional, dict) or not optional_names.issubset(sam_optional):
            raise SamError("SAM3_Detect does not support point prompt arrays.")
        expected_types = {
            "model": "MODEL",
            "image": "IMAGE",
            "threshold": "FLOAT",
            "refine_iterations": "INT",
            "individual_masks": "BOOLEAN",
        }
        for field, expected_type in expected_types.items():
            descriptor = sam_required.get(field)
            if (
                not isinstance(descriptor, list)
                or len(descriptor) < 2
                or descriptor[0] != expected_type
            ):
                raise SamError(f"SAM3_Detect input {field} has an incompatible type.")
        threshold_options = sam_required["threshold"][1]
        refinement_options = sam_required["refine_iterations"][1]
        boolean_options = sam_required["individual_masks"][1]
        if (
            not isinstance(threshold_options, dict)
            or threshold_options.get("min") != 0.0
            or threshold_options.get("max") != 1.0
            or threshold_options.get("default") != 0.5
        ):
            raise SamError("SAM3_Detect threshold limits are incompatible.")
        if (
            not isinstance(refinement_options, dict)
            or refinement_options.get("min") != 0
            or refinement_options.get("max") != 5
            or refinement_options.get("default") != 2
        ):
            raise SamError("SAM3_Detect refinement limits are incompatible.")
        if not isinstance(boolean_options, dict) or boolean_options.get("default") is not False:
            raise SamError("SAM3_Detect individual-mask behavior is incompatible.")
        for field in optional_names:
            descriptor = sam_optional.get(field)
            if (
                not isinstance(descriptor, list)
                or not descriptor
                or descriptor[0] != "STRING"
            ):
                raise SamError(f"SAM3_Detect input {field} has an incompatible type.")
        if list(sam.get("output", []))[:1] != ["MASK"]:
            raise SamError("SAM3_Detect has an incompatible output schema.")

        preview = metadata["MaskPreview"]
        preview_input = preview.get("input") if isinstance(preview, dict) else None
        preview_required = preview_input.get("required") if isinstance(preview_input, dict) else None
        if not isinstance(preview_required, dict) or "mask" not in preview_required:
            raise SamError("MaskPreview has an incompatible input schema.")
        mask_descriptor = preview_required.get("mask")
        if not isinstance(mask_descriptor, list) or not mask_descriptor or mask_descriptor[0] != "MASK":
            raise SamError("MaskPreview does not accept a MASK input.")
        if list(preview.get("output", []))[:1] != ["MASK"] or not preview.get("output_node"):
            raise SamError("MaskPreview has an incompatible output schema.")
        return {"system": stats.get("system", {}), "nodes": metadata}

    def upload(self, png: bytes, deadline: Optional[float] = None) -> UploadReference:
        boundary = f"----gimp-sam-{uuid.uuid4().hex}"
        filename = f"gimp-sam-{uuid.uuid4().hex}.png"
        prefix = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode("ascii")
        suffix = f"\r\n--{boundary}--\r\n".encode("ascii")
        payload = self._request(
            "POST",
            "/upload/image",
            chunks=(prefix, png, suffix),
            content_length=len(prefix) + len(png) + len(suffix),
            content_type=f"multipart/form-data; boundary={boundary}",
            max_bytes=1024 * 1024,
            deadline=deadline,
        )
        try:
            result = json.loads(payload)
            name = result["name"]
            subfolder = result.get("subfolder", "")
            kind = result.get("type", "input")
            if not all(isinstance(value, str) for value in (name, subfolder, kind)) or not name:
                raise ValueError("invalid upload reference")
            reference = UploadReference(name, subfolder, kind)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise SamError("ComfyUI returned a malformed upload reference.") from error
        return reference

    def queue(
        self,
        workflow: dict[str, object],
        client_id: str,
        deadline: Optional[float] = None,
    ) -> str:
        body = json.dumps(
            {"prompt": workflow, "client_id": client_id}, separators=(",", ":")
        ).encode("utf-8")
        try:
            payload = self._request(
                "POST",
                "/prompt",
                body=body,
                content_type="application/json",
                deadline=deadline,
            )
        except HttpStatusError:
            raise
        except (TransportError, SamError) as error:
            raise SubmissionUncertainError(
                "The connection failed while submitting the prompt. It may be running on the server; "
                "the plug-in will not retry automatically."
            ) from error
        try:
            response = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SubmissionUncertainError(
                "ComfyUI may have accepted the prompt but returned a malformed acknowledgement. "
                "The plug-in will not retry automatically."
            ) from error
        if not isinstance(response, dict):
            raise SubmissionUncertainError(
                "ComfyUI may have accepted the prompt but returned an unexpected acknowledgement. "
                "The plug-in will not retry automatically."
            )
        prompt_id = response.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            node_errors = response.get("node_errors")
            if node_errors:
                raise SamError("ComfyUI rejected the workflow because one or more nodes are invalid.")
            raise SubmissionUncertainError(
                "ComfyUI may have accepted the prompt without returning its ID. "
                "The plug-in will not retry automatically."
            )
        return prompt_id

    def wait_for_output(
        self, prompt_id: str, cancel: threading.Event, deadline: float
    ) -> UploadReference:
        while time.monotonic() < deadline:
            if cancel.is_set():
                raise CancelledError("Request cancelled locally.")
            history = self._json(
                "GET", f"/history/{quote(prompt_id)}", deadline=deadline
            )
            record = history.get(prompt_id)
            if record is not None and not isinstance(record, dict):
                raise SamError("ComfyUI returned a malformed history record.")
            if isinstance(record, dict):
                status = record.get("status")
                if not isinstance(status, dict) or not isinstance(
                    status.get("status_str"), str
                ):
                    raise SamError("ComfyUI returned malformed prompt status.")
                if status.get("status_str") == "error":
                    raise SamError("ComfyUI reported an inference error.")
                outputs = record.get("outputs")
                if isinstance(outputs, dict) and "6" in outputs:
                    return extract_output_reference(history, prompt_id)
                if status.get("completed"):
                    raise SamError("ComfyUI returned completed history without the expected mask output.")
            cancel.wait(0.5)
        raise SamError("ComfyUI inference exceeded the configured total deadline.")

    def download(
        self, reference: UploadReference, deadline: Optional[float] = None
    ) -> bytes:
        query = urlencode(
            {"filename": reference.name, "subfolder": reference.subfolder, "type": reference.kind}
        )
        payload = self._request(
            "GET",
            f"/view?{query}",
            max_bytes=MAX_DOWNLOAD_BYTES,
            timeout=self.operation_timeout,
            deadline=deadline,
        )
        if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise SamError("ComfyUI mask response is not a PNG image.")
        return payload

    def generate(
        self,
        png: bytes,
        positive: list[dict[str, int]],
        negative: list[dict[str, int]],
        threshold: float,
        refinement: int,
        client_id: str,
        cancel: threading.Event,
        upload: Optional[UploadReference] = None,
        progress: Optional[Callable[[str], None]] = None,
    ) -> GenerationResponse:
        deadline = time.monotonic() + self.total_timeout
        self.inspect(deadline)
        if progress:
            progress("uploading")
        if cancel.is_set():
            raise CancelledError("Request cancelled locally.")
        upload = upload or self.upload(png, deadline)
        if progress:
            progress("submitting")
        if cancel.is_set():
            raise CancelledError("Request cancelled locally.")
        workflow = build_workflow(upload, positive, negative, threshold, refinement)
        prompt_id = self.queue(workflow, client_id, deadline)
        if progress:
            progress("inferring")
        output = self.wait_for_output(prompt_id, cancel, deadline)
        if cancel.is_set():
            raise CancelledError("Request cancelled locally.")
        if progress:
            progress("downloading")
        mask_png = self.download(output, deadline)
        if cancel.is_set():
            raise CancelledError("Request cancelled locally.")
        return GenerationResponse(prompt_id, upload, mask_png)
