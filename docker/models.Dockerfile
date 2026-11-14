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
# The PyTorch CPU wheel index is used ONLY for the pinned CPU wheel.
# --no-deps is required: its transitive requirements otherwise resolve through
# files.pythonhosted.org, which is unreachable on some regional Docker networks.
# The following full requirements install resolves *all* missing dependencies
# from Liara, falling back to Chabokan, without replacing the installed CPU wheel.
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --no-deps --timeout 120 --retries 3 \
      --index-url "${TORCH_CPU_INDEX_URL}" 'torch==2.6.0+cpu'
RUN --mount=type=cache,target=/root/.cache/pip \
    (python -m pip install --timeout 60 --retries 3 \
       --index-url "${PIP_PRIMARY_INDEX_URL}" -r /app/requirements.txt \
     || python -m pip install --timeout 60 --retries 3 \
       --index-url "${PIP_FALLBACK_INDEX_URL}" -r /app/requirements.txt) \
    && python -m pip check \
    && python -c "import torch; assert torch.__version__ == '2.6.0+cpu', torch.__version__; assert torch.version.cuda is None, 'CUDA build prohibited'"
COPY soorin /app/soorin
# Download-only invocations override HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE to 0.
# Increase idle CDN read timeouts; retries remain bounded in artifacts.py.
# Serving stays offline and does not contact remote storage.
ENV HF_HOME=/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DOWNLOAD_TIMEOUT=120 HF_HUB_ETAG_TIMEOUT=30 \
    SOORIN_HF_RETRIES=3 SOORIN_MODEL_THREADS=2
USER 65532:65532
ENTRYPOINT ["python", "-m", "soorin.services.cpu_models"]
