from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

import streamlit as st


_HTML = """
<div class="clipboard-capture">
  <button id="camera-button" type="button" title="Take a photo using your device camera or choose an image">📷 Take photo</button>
  <input id="camera-input" type="file" accept="image/*" capture="environment" hidden />
  <button id="paste-button" type="button">📋 Paste screenshot</button>
  <div id="paste-target" tabindex="0">or click here and press Ctrl+V</div>
  <span id="paste-status" role="status"></span>
</div>
"""

_CSS = """
.clipboard-capture {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  color: var(--st-text-color);
  font-family: var(--st-font);
}
#camera-button,
#paste-button {
  appearance: none;
  border: 1px solid color-mix(in srgb, var(--st-text-color) 22%, transparent);
  border-radius: var(--st-button-radius, 0.4rem);
  background: var(--st-secondary-background-color);
  color: var(--st-text-color);
  cursor: pointer;
  font: inherit;
  font-size: 0.88rem;
  font-weight: 600;
  padding: 0.45rem 0.75rem;
  line-height: 1.25;
  white-space: nowrap;
}
#camera-button:hover,
#paste-button:hover { border-color: var(--st-primary-color); color: var(--st-primary-color); }
#paste-target {
  border: 1px dashed color-mix(in srgb, var(--st-text-color) 28%, transparent);
  border-radius: var(--st-base-radius, 0.4rem);
  cursor: text;
  font-size: 0.85rem;
  padding: 0.42rem 0.68rem;
  line-height: 1.25;
}
#paste-target:focus { border-color: var(--st-primary-color); outline: 2px solid color-mix(in srgb, var(--st-primary-color) 25%, transparent); }
#paste-status { font-size: 0.82rem; opacity: 0.85; }
@media (max-width: 640px) {
  .clipboard-capture {
    gap: 0.4rem;
  }
  #camera-button,
  #paste-button {
    flex: 1 1 auto;
    text-align: center;
    padding: 0.5rem 0.65rem;
  }
  #paste-target {
    flex: 1 1 100%;
    text-align: center;
  }
}
"""

_JS = """
export default function(component) {
  const { parentElement, setTriggerValue } = component
  const cameraButton = parentElement.querySelector("#camera-button")
  const cameraInput = parentElement.querySelector("#camera-input")
  const button = parentElement.querySelector("#paste-button")
  const target = parentElement.querySelector("#paste-target")
  const status = parentElement.querySelector("#paste-status")
  if (!button || !target || !status) return

  const normalizeCameraImage = (file) => new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      try {
        const maxDim = 2400
        let width = img.naturalWidth || img.width
        let height = img.naturalHeight || img.height
        if (width > maxDim || height > maxDim) {
          const scale = maxDim / Math.max(width, height)
          width = Math.max(1, Math.round(width * scale))
          height = Math.max(1, Math.round(height * scale))
        }
        const canvas = document.createElement("canvas")
        canvas.width = width
        canvas.height = height
        const ctx = canvas.getContext("2d")
        ctx.drawImage(img, 0, 0, width, height)
        const dataUrl = canvas.toDataURL("image/jpeg", 0.9)
        URL.revokeObjectURL(url)
        resolve({ data_url: dataUrl, mime_type: "image/jpeg" })
      } catch (err) {
        URL.revokeObjectURL(url)
        reject(err)
      }
    }
    img.onerror = (err) => {
      URL.revokeObjectURL(url)
      reject(err)
    }
    img.src = url
  })

  const sendImage = (blob, label = "Screenshot") => {
    if (!blob || !blob.type.startsWith("image/")) {
      status.textContent = "Clipboard does not contain an image."
      return
    }
    status.textContent = `Reading ${label.toLowerCase()}…`
    const reader = new FileReader()
    reader.onload = () => {
      setTriggerValue("image", {
        data_url: reader.result,
        mime_type: blob.type || "image/png",
        name: `screenshot-${Date.now()}.png`,
      })
      status.textContent = `${label} received.`
    }
    reader.onerror = () => { status.textContent = `Could not read the ${label.toLowerCase()}.` }
    reader.readAsDataURL(blob)
  }

  if (cameraButton && cameraInput) {
    cameraButton.onclick = () => {
      cameraInput.value = ""
      cameraInput.click()
    }
    cameraInput.onchange = async (event) => {
      const file = event.target.files?.[0]
      if (!file) return
      status.textContent = "Processing photo…"
      try {
        const normalized = await normalizeCameraImage(file)
        setTriggerValue("image", {
          data_url: normalized.data_url,
          mime_type: normalized.mime_type,
          name: `camera-photo-${Date.now()}.jpg`,
        })
        status.textContent = "Photo captured."
      } catch (_err) {
        sendImage(file, "Photo")
      }
    }
  }

  target.onpaste = (event) => {
    event.preventDefault()
    const items = Array.from(event.clipboardData?.items || [])
    const imageItem = items.find((item) => item.type.startsWith("image/"))
    sendImage(imageItem?.getAsFile(), "Screenshot")
  }

  button.onclick = async () => {
    try {
      const clipboardItems = await navigator.clipboard.read()
      for (const item of clipboardItems) {
        const imageType = item.types.find((type) => type.startsWith("image/"))
        if (imageType) {
          sendImage(await item.getType(imageType), "Screenshot")
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
    try:
        return _CLIPBOARD_IMAGE(key=key, on_image_change=lambda: None, height="content")
    except Exception:
        return None


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
    if not content:
        raise ValueError("The clipboard image is empty.")
    if len(content) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise ValueError(f"The clipboard image is larger than {limit_mb} MB.")
    return {"bytes": content, "name": f"clipboard-screenshot{allowed[mime_type]}", "mime_type": mime_type}


def as_uploaded_file(image: dict[str, Any]) -> BytesIO:
    uploaded = BytesIO(image["bytes"])
    uploaded.name = image["name"]
    return uploaded
