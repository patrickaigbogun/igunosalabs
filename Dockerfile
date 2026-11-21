FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Pre-convert Unose-Huen-Small and Unose-Huen-Base to int8 CTranslate2 during image build
RUN mkdir -p /app/models && \
    ct2-transformers-converter --model igunosalabs/Unose-Huen-Small --output_dir /app/models/unose-huen-small --quantization int8 --copy_files tokenizer.json preprocessor_config.json && \
    ct2-transformers-converter --model igunosalabs/Unose-Huen-Base --output_dir /app/models/unose-huen-base --quantization int8 --copy_files tokenizer.json preprocessor_config.json && \
    rm -rf /root/.cache/huggingface

COPY server.py ./
COPY public ./public

EXPOSE 80
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "80", "--workers", "1"]
