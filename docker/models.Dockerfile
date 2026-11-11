FROM python:3.12-slim-bookworm
WORKDIR /app
COPY soorin/services/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r /app/requirements.txt
COPY soorin /app/soorin
ENV HF_HOME=/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 SOORIN_MODEL_THREADS=2
USER 65532:65532
ENTRYPOINT ["python", "-m", "soorin.services.cpu_models"]
