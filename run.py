"""Entrypoint: python run.py

Binds 0.0.0.0 so the same command works inside a container. Hosts that inject
a PORT (Render, Cloud Run, Railway) are honoured; otherwise it serves on 8000.
"""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=False)
