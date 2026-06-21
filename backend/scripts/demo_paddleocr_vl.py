#!/usr/bin/env python3
"""PaddleOCR-VL Adapter demo — test the adapter independently.

Usage:
    # Set your API token (or pass via --token):
    export PADDLEOCR_VL_TOKEN="your_token_here"

    # Test with a local image (run from project root):
    python backend/scripts/demo_paddleocr_vl.py --image path/to/page.png

    # Test with an image URL:
    python backend/scripts/demo_paddleocr_vl.py --url https://example.com/page.png

    # Use a custom base URL:
    python backend/scripts/demo_paddleocr_vl.py --image test.png --base-url https://custom.api.com
"""

import argparse
import asyncio
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("demo_paddleocr_vl")


async def demo_image(api_token: str, base_url: str, image_path: str) -> None:
    """Run PaddleOCR-VL on a local image file."""
    from app.features.ocr_vl.paddleocr_vl_client import PaddleOCRVLClient

    logger.info("Reading image: %s", image_path)
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    logger.info("Image size: %d bytes", len(image_bytes))

    client = PaddleOCRVLClient(api_token=api_token, base_url=base_url)
    result = await client.ocr_image(image_bytes, filename=os.path.basename(image_path))

    print("\n" + "=" * 60)
    print("PaddleOCR-VL Result")
    print("=" * 60)
    print(f"Confidence: {result.confidence}")
    print(f"Text length: {len(result.text)}")
    print("-" * 60)
    print(result.text[:2000])
    if len(result.text) > 2000:
        print(f"\n... (truncated, {len(result.text)} characters total)")
    print("=" * 60)


async def demo_url(api_token: str, base_url: str, file_url: str) -> None:
    """Run PaddleOCR-VL on a remote image URL."""
    from app.features.ocr_vl.paddleocr_vl_client import PaddleOCRVLClient

    logger.info("Processing URL: %s", file_url)
    client = PaddleOCRVLClient(api_token=api_token, base_url=base_url)
    result = await client.ocr_image_url(file_url)

    print("\n" + "=" * 60)
    print("PaddleOCR-VL Result (URL mode)")
    print("=" * 60)
    print(f"Confidence: {result.confidence}")
    print(f"Text length: {len(result.text)}")
    print("-" * 60)
    print(result.text[:2000])
    if len(result.text) > 2000:
        print(f"\n... (truncated, {len(result.text)} characters total)")
    print("=" * 60)


async def demo_adapter(api_token: str, base_url: str, image_path: str) -> None:
    """Test the adapter through OCRFixerProtocol interface."""
    from app.features.ocr_vl.paddleocr_vl_adapter import PaddleOCRVLAdapter

    logger.info("Testing adapter with image: %s", image_path)
    with open(image_path, "rb") as f:
        image_bytes = f.read()

    adapter = PaddleOCRVLAdapter(
        api_token=api_token,
        base_url=base_url,
        config={"demo_mode": True},
    )
    print(f"\nAdapter available: {adapter.is_available}")

    result = await adapter.fix(
        image=image_bytes,
        ocr_text="",
        context={"filename": os.path.basename(image_path)},
    )

    print("\n" + "=" * 60)
    print("Adapter Result")
    print("=" * 60)
    print(f"Model: {result.model_used}")
    print(f"Confidence: {result.confidence}")
    print(f"Duration: {result.duration_ms}ms")
    print(f"Tokens used: {result.tokens_used}")
    print("-" * 60)
    print(result.fixed_text[:2000])
    if len(result.fixed_text) > 2000:
        print(f"\n... (truncated, {len(result.fixed_text)} characters total)")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PaddleOCR-VL Adapter Demo",
    )
    parser.add_argument("--image", help="Local image file path")
    parser.add_argument("--url", help="Remote image URL")
    parser.add_argument(
        "--token",
        default=os.environ.get("PADDLEOCR_VL_TOKEN", ""),
        help="API token (or set PADDLEOCR_VL_TOKEN env var)",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get(
            "PADDLEOCR_VL_BASE_URL",
            "https://paddleocr.aistudio-app.com",
        ),
        help="API base URL",
    )
    parser.add_argument(
        "--adapter",
        action="store_true",
        help="Also test through the OCRFixerProtocol adapter",
    )
    args = parser.parse_args()

    if not args.token:
        print("Error: API token required. Set PADDLEOCR_VL_TOKEN or pass --token.")
        sys.exit(1)

    if not args.image and not args.url:
        print("Error: provide --image or --url")
        sys.exit(1)

    if args.image:
        asyncio.run(demo_image(args.token, args.base_url, args.image))
        if args.adapter:
            print("\n")
            asyncio.run(demo_adapter(args.token, args.base_url, args.image))

    if args.url:
        asyncio.run(demo_url(args.token, args.base_url, args.url))


if __name__ == "__main__":
    main()
