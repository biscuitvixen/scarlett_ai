# NVIDIA's arm64 vllm build for the DGX Spark, with one fix: the bundled
# prometheus-fastapi-instrumentator 8.0.0 crashes on fastapi 0.137's
# _IncludedRouter route type, which makes every API request 500.
FROM nvcr.io/nvidia/vllm:26.06-py3

RUN pip install --no-cache-dir --root-user-action=ignore \
    prometheus-fastapi-instrumentator==8.0.2
