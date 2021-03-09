ARG CUDA_VERSION=11.2.1
ARG BASE_IMAGE=nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu20.04

FROM ${BASE_IMAGE}

ENV LC_ALL=en_US.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/home/CenterHMR/src

RUN apt-get update && \
    apt-get install -y --no-install-suggests --no-install-recommends \
        unzip locales software-properties-common wget ffmpeg libsm6 libxext6 \
        libglfw3-dev libgles2-mesa-dev libosmesa6-dev freeglut3-dev && \
    add-apt-repository -y ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y --no-install-suggests --no-install-recommends \
        python3.8 python3.8-dev python3.8-distutils && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen && \
    wget -O - https://bootstrap.pypa.io/get-pip.py | python3.8 && \
    mkdir /home/CenterHMR && \
    cd /home/CenterHMR && \
    wget https://github.com/Arthur151/CenterHMR/releases/download/v0.0/CenterHMR_data.zip && \
    unzip CenterHMR_data.zip -d ./CenterHMR/

ADD ./src/requirements.txt /home/CenterHMR/src/requirements.txt

WORKDIR /home/CenterHMR/src
RUN pip3 install -r requirements.txt

ADD . /home/CenterHMR/
