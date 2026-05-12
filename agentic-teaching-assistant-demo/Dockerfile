# Use a base image with Python
FROM python:3.12-slim 

# Set timezone and Python config
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/Stockholm
ENV PYTHONUNBUFFERED=1
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Install system dependencies
RUN apt update -y && \
    apt install -y procps && \
    apt clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /workspace

# Upgrade pip
RUN python -m pip install --upgrade pip

# Install Python dependencies (copy only requirements.txt)
# This layer will be cached unless requirements.txt changes
COPY requirements.txt /workspace/

RUN pip install -r requirements.txt

# Install additional packages
RUN pip install -U \
    gretel_client \
    datasets \
    langchain-core \
    langgraph \
    langchain-nvidia-ai-endpoints \
    openai \
    langchain-community \
    faiss-gpu-cu12 \
    jupyterlab \
    fastmcp \
    colorama \
    markdown \
    gradio \
    nv-ingest==25.9.0 \
    nv-ingest-api==25.9.0 \
    nv-ingest-client==25.9.0 \
    milvus-lite==2.4.12 \
    pypdf

# Expose ports
EXPOSE 8888 9999 8000 7860 7861 60808

# Source code will be mounted as a volume at runtime
# See docker-compose.yml: volumes: - .:/workspace

# Keep container running
#CMD ["sh", "-c", "tail -f /dev/null"]
CMD ["python","extract_sub_chapters.py","--pdf_file_loc","/workspace/test_pdfs/SwedenFacts.pdf"]
