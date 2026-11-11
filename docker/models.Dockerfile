# syntax=docker/dockerfile:1.6
ARG PYTHON_BASE_IMAGE=docker.arvancloud.ir/python:3.12-slim-bookworm
FROM ${PYTHON_BASE_IMAGE}
ARG PIP_PRIMARY_INDEX_URL=https://package-mirror.liara.ir/repository/pypi/simple
ARG PIP_FALLBACK_INDEX_URL=https://mirror2.chabokan.net/pypi/simple/
ARG TORCH_CPU_INDEX_URL=https://download.pytorch.org/whl/cpu
WORKDIR /app
COPY soorin/services/requirements.txt /app/requirements.txt
# Keep Torch explicitly CPU-only. Do not permit ordinary PyPI mirrors to
# silently replace the pinned CPU wheel.
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --timeout 120 --retries 3 \
      --index-url "${TORCH_CPU_INDEX_URL}" 'torch==2.6.0+cpu'
RUN --mount=type=cache,target=/root/.cache/pip \
    (python -m pip install --timeout 60 --retries 3 \
       --index-url "${PIP_PRIMARY_INDEX_URL}" -r /app/requirements.txt \
     || python -m pip install --timeout 60 --retries 3 \
       --index-url "${PIP_FALLBACK_INDEX_URL}" -r /app/requirements.txt) \
    && python -m pip check \
    && python -c "import torch; assert torch.version.cuda is None, 'CUDA build prohibited'"
COPY soorin /app/soorin
ENV HF_HOME=/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 SOORIN_MODEL_THREADS=2
USER 65532:65532
ENTRYPOINT ["python", "-m", "soorin.services.cpu_models"]
