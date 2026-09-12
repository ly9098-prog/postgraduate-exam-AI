#!/usr/bin/env python3
"""Collect per-page OCR evidence (remote 8080 + local PP-OCRv4) for a page range.

Saves:
  backend-ocr/remote/p-<NNNN>.json   remote PaddleOCR-VL result (text+boxes+scores)
  backend-ocr/remote/p-<NNNN>.txt    plain text
  mcp-ocr/independent/p-<NNNN>.txt   local PP-OCRv4 text (independent engine)

Usage:
    .venv/bin/python /abs/collect_ocr_evidence.py --start 1 --end 10
"""
import argparse
import json
import os
import sys

sys.path.insert(0, "/home/lmh/projects/postgraduate-ai/backend")
PDF = "/home/lmh/projects/postgraduate-ai/ocr_test/import/cs_ds.pdf"
BASE = "/home/lmh/projects/postgraduate-ai/artifacts/computer-organization-import"


def remote_ocr(png_bytes):
    import base64
    import urllib.request
    body = json.dumps({"file": base64.b64encode(png_bytes).decode(), "fileType": 1}).encode()
    req = urllib.request.Request("http://172.27.64.1:8080/ocr", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read())
    pr = data["result"]["ocrResults"][0]["prunedResult"]
    lines = []
    for t, s, b in zip(pr["rec_texts"], pr["rec_scores"], pr["rec_polys"]):
        x0, y0 = int(b[0][0]), int(b[0][1])
        x1, y1 = int(b[2][0]), int(b[2][1])
        lines.append({"text": t, "conf": round(float(s), 4), "box": [x0, y0, x1, y1]})
    return lines


def independent_ocr(png_path):
    import subprocess
    script = (
        "import os;os.environ['CUDA_VISIBLE_DEVICES']='';"
        "from paddleocr import PaddleOCR;"
        "o=PaddleOCR(use_angle_cls=True,lang='ch',show_log=False,use_gpu=False);"
        f"r=o.ocr('{png_path}',cls=True);"
        "print('\\n'.join(x[1][0] for x in (r[0] or [])))"
    )
    out = subprocess.run(["/home/lmh/projects/postgraduate-ai/backend/.venv/bin/python", "-c", script],
                         capture_output=True, text=True, timeout=300, cwd="/home/lmh/projects/postgraduate-ai/backend")
    if out.returncode != 0:
        return f"<INDEPENDENT OCR FAILED>: {out.stderr[-300:]}"
    return out.stdout


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=int, required=True)
    p.add_argument("--end", type=int, required=True)
    p.add_argument("--dpi", type=int, default=300)
    args = p.parse_args()

    import fitz
    os.makedirs(f"{BASE}/backend-ocr/remote", exist_ok=True)
    os.makedirs(f"{BASE}/mcp-ocr/independent", exist_ok=True)

    doc = fitz.open(PDF)
    for n in range(args.start, args.end + 1):
        pix = doc[n - 1].get_pixmap(dpi=args.dpi)
        png_path = f"{BASE}/source-pages/page-{n:04d}.png"
        if not os.path.exists(png_path):
            pix.save(png_path)
        png = pix.tobytes("png")
        try:
            lines = remote_ocr(png)
            with open(f"{BASE}/backend-ocr/remote/p-{n:04d}.json", "w") as f:
                json.dump({"page": n, "lines": lines}, f, ensure_ascii=False, indent=1)
            text = "\n".join(l["text"] for l in lines)
            with open(f"{BASE}/backend-ocr/remote/p-{n:04d}.txt", "w") as f:
                f.write(text)
            print(f"page {n}: remote {len(lines)} lines, {len(text)} chars", flush=True)
        except Exception as e:
            print(f"page {n}: remote OCR FAILED: {e}", flush=True)
    doc.close()


if __name__ == "__main__":
    main()
