FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=10000
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home --uid 10001 pageburrow
COPY app.py compressor.py editor.py online.py COPYING ./
COPY pdftools ./pdftools
COPY scripts/install_mupdf_js.py ./scripts/
RUN python scripts/install_mupdf_js.py
COPY web ./web
COPY tessdata ./tessdata
USER pageburrow
EXPOSE 10000
CMD ["python", "online.py"]
