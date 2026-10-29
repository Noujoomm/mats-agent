# Nemotron ASR on a Nebius Serverless Endpoint (GPU).
FROM nvcr.io/nvidia/pytorch:25.04-py3

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optional: bake the checkpoint into the image for faster cold starts
ARG ASR_MODEL=nvidia/nemotron-3.5-asr-streaming-0.6b
ENV ASR_MODEL=${ASR_MODEL}
RUN python -c "import nemo.collections.asr as a; a.models.ASRModel.from_pretrained(model_name='${ASR_MODEL}')" || true

COPY server.py .
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
