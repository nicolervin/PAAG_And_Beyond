from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

import streamlit as st


_HTML = """
<div class="clipboard-capture">
  <button id="paste-button" type="button">Paste screenshot</button>
  <div id="paste-target" tabindex="0">or click here and press Ctrl+V</div>
  <span id="paste-status" role="status"></span>
</div>
"""

_CSS = """
.clipboard-capture {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.55rem;
  color: var(--st-text-color);
  font-family: var(--st-font);
}
#paste-button {
  appearance: none;
  border: 1px solid color-mix(in srgb, var(--st-text-color) 22%, transparent);
  border-radius: var(--st-button-radius, 0.4rem);
  background: var(--st-secondary-background-color);
  color: var(--st-text-color);
  cursor: pointer;
  font: inherit;
  font-weight: 600;
  padding: 0.5rem 0.8rem;
}
#paste-button:hover { border-color: var(--st-primary-color); color: var(--st-primary-color); }
#paste-target {
  border: 1px dashed color-mix(in srgb, var(--st-text-color) 28%, transparent);
  border-radius: var(--st-base-radius, 0.4rem);
  cursor: text;
  padding: 0.45rem 0.7rem;
}
#paste-target:focus { border-color: var(--st-primary-color); outline: 2px solid color-mix(in srgb, var(--st-primary-color) 25%, transparent); }
#paste-status { font-size: 0.82rem; opacity: 0.8; }
"""

_JS = """
export default function(component) {
  const { parentElement, setTriggerValue } = component
  const button = parentElement.querySelector("#paste-button")
  const target = parentElement.querySelector("#paste-target")
  const status = parentElement.querySelector("#paste-status")
  if (!button || !target || !status) return

  const sendImage = (blob) => {
    if (!blob || !blob.type.startsWith("image/")) {
      status.textContent = "Clipboard does not contain an image."
      return
    }
    status.textContent = "Reading screenshot…"
    const reader = new FileReader()
    reader.onload = () => {
      setTriggerValue("image", {
        data_url: reader.result,
        mime_type: blob.type || "image/png",
        name: `screenshot-${Date.now()}.png`,
      })
      status.textContent = "Screenshot received."
    }
    reader.onerror = () => { status.textContent = "Could not read the screenshot." }
    reader.readAsDataURL(blob)
  }

  target.onpaste = (event) => {
    event.preventDefault()
    const items = Array.from(event.clipboardData?.items || [])
    const imageItem = items.find((item) => item.type.startsWith("image/"))
    sendImage(imageItem?.getAsFile())
  }

  button.onclick = async () => {
    try {
      const clipboardItems = await navigator.clipboard.read()
      for (const item of clipboardItems) {
        const imageType = item.types.find((type) => type.startsWith("image/"))
        if (imageType) {
          sendImage(await item.getType(imageType))
          return
        }
      }
      status.textContent = "Clipboard does not contain an image."
    } catch (error) {
      status.textContent = "Clipboard access was blocked—click the dashed area and press Ctrl+V."
      target.focus()
    }
  }
}
"""

_CLIPBOARD_IMAGE = st.components.v2.component(
    "paag_clipboard_image",
    html=_HTML,
    css=_CSS,
    js=_JS,
)


def clipboard_image(*, key: str):
    return _CLIPBOARD_IMAGE(key=key, on_image_change=lambda: None, height="content")


def decode_clipboard_image(payload: Any, *, max_bytes: int = 50 * 1024 * 1024) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("The clipboard did not provide an image.")
    data_url = str(payload.get("data_url", ""))
    if not data_url.startswith("data:image/") or ";base64," not in data_url:
        raise ValueError("Only clipboard images are supported.")
    header, encoded = data_url.split(",", 1)
    mime_type = header[5:].split(";", 1)[0].lower()
    allowed = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
    if mime_type not in allowed:
        raise ValueError("Paste a PNG, JPEG, or WEBP screenshot.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise ValueError("The clipboard image was not valid.") from exc
    if not content or len(content) > max_bytes:
        raise ValueError("The clipboard image is empty or larger than 50 MB.")
    return {"bytes": content, "name": f"clipboard-screenshot{allowed[mime_type]}", "mime_type": mime_type}


def as_uploaded_file(image: dict[str, Any]) -> BytesIO:
    uploaded = BytesIO(image["bytes"])
    uploaded.name = image["name"]
    return uploaded
