# Zentra

## Install
Zentra project can be run with two kinds setup: any Linux with conda-forge or Ubuntu 22.04 LTS

### conda-forge

Install conda-forge

[https://conda-forge.org/download/](https://conda-forge.org/download/)

Create zentra environment

    mamba create -n zentra python==3.10

    mamba activate zentra

    mamba install python-rocksdb

    cd zentra_folder

    pip install -r requirements.txt

### Ubuntu 22.04 LTS

    sudo apt install python3-pip python3-rocksdb python-is-python3

## Run Zentra

The gazer

    python gazer_base.py

The indexer

    python indexer.py
