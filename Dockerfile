FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    MPLCONFIGDIR=/tmp/matplotlib

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        python3 python3-venv ca-certificates \
        build-essential clang llvm pkg-config \
        libbpf-dev libelf-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv "$VIRTUAL_ENV"

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

ENTRYPOINT ["python", "-m", "src.assignment2_pipeline"]