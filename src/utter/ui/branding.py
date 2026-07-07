"""Shared brand imagery — the otter face, cropped from the packaged logo asset."""

from __future__ import annotations

from PIL import Image, ImageDraw

# fraction box of the otter's face within logo.jpg (l, t, r, b)
_FACE_BOX = (0.35, 0.125, 0.62, 0.395)


def otter_face(size: int, circular: bool = True) -> Image.Image:
    """The otter's face at `size` px; circular alpha mask unless circular=False.

    Raises if the packaged asset is unavailable — callers keep their own fallback.
    """
    from importlib import resources

    with resources.files("utter").joinpath("assets/logo.jpg").open("rb") as f:
        img = Image.open(f).convert("RGBA")
    w, h = img.size
    img = img.crop(
        (
            int(_FACE_BOX[0] * w),
            int(_FACE_BOX[1] * h),
            int(_FACE_BOX[2] * w),
            int(_FACE_BOX[3] * h),
        )
    ).resize((size, size), Image.LANCZOS)
    if circular:
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
        img.putalpha(mask)
    return img
