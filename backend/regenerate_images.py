"""
Regenerate code/table/diagram region images from PDF at high quality.
Uses template matching to locate the region, then crops at 300 DPI.
"""
import cv2
import numpy as np
from PIL import Image
import fitz
import os
import json
import sqlite3

PDF_PATH = "/home/lmh/projects/postgraduate-ai/ocr_test/import/os_sc.pdf"
ASSETS_DIR = "/home/lmh/projects/postgraduate-ai/backend/static/question-assets"
DPI = 300

# Map: filename -> (source_page, description)
REGIONS = {
    "code_region_192.webp":          (209, "并发进程P1和P2的代码"),
    "code_region_216_peterson.webp": (216, "进程P0和P1的Peterson算法代码"),
    "code_region_219_tsl.webp":      (219, "TSL指令实现进程互斥"),
    "code_region_245_semaphore.webp":(245, "并发进程信号量代码"),
    "code_region_246_concurrent.webp":(246, "并发进程程序代码"),
    "table_dynamic_partition.webp":  (313, "动态分区空闲表"),
    "table_resource_alloc.webp":     (252, "资源分配表"),
    "diagram_io_buffer.webp":        (473, "IO缓冲示意图"),
}

doc = fitz.open(PDF_PATH)

for fname, (src_page, desc) in REGIONS.items():
    src_path = os.path.join(ASSETS_DIR, fname)
    if not os.path.exists(src_path):
        print(f"[SKIP] {fname}: source not found")
        continue

    # Load low-res template
    template = cv2.imread(src_path, cv2.IMREAD_GRAYSCALE)
    if template is None:
        print(f"[SKIP] {fname}: cannot read template")
        continue
    th, tw = template.shape

    # Render page at 300 DPI
    page = doc[src_page - 1]  # 0-indexed
    pix = page.get_pixmap(dpi=DPI)
    img_bytes = pix.tobytes("png")
    page_img = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)

    # Template matching
    result = cv2.matchTemplate(page_img, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val < 0.5:
        print(f"[FAIL] {fname}: match confidence too low ({max_val:.3f})")
        # Fallback: try resizing template slightly
        for scale in [1.05, 0.95, 1.1, 0.9]:
            w = int(tw * scale)
            h = int(th * scale)
            resized = cv2.resize(template, (w, h), interpolation=cv2.INTER_LINEAR)
            r = cv2.matchTemplate(page_img, resized, cv2.TM_CCOEFF_NORMED)
            _, mv, _, ml = cv2.minMaxLoc(r)
            if mv > max_val:
                max_val = mv
                max_loc = ml
                th, tw = h, w
        if max_val < 0.5:
            print(f"[FAIL] {fname}: still too low after resize ({max_val:.3f})")
            continue

    x, y = max_loc
    print(f"[OK] {fname}: match={max_val:.3f}, loc=({x},{y}), size={tw}x{th}")

    # Crop high-res region
    # Use RGB for saving
    page_rgb = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
    cropped = page_rgb[y:y+th, x:x+tw]

    # Save as high-quality WebP (quality=95)
    out_path = os.path.join(ASSETS_DIR, fname)
    success = cv2.imwrite(out_path, cropped, [cv2.IMWRITE_WEBP_QUALITY, 95])
    if success:
        new_size = os.path.getsize(out_path)
        print(f"  -> saved {tw}x{th}, {new_size/1024:.1f} KB")
    else:
        print(f"  -> FAILED to save")

doc.close()
print("\nDone.")
