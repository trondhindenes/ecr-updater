FROM ubuntu
RUN apt-get update \
    && apt-get install -y wget python curl \
    && curl "https://bootstrap.pypa.io/get-pip.py" -o "get-pip.py" \
    && apt-get remove --purge -y curl \
    && apt-get -y autoremove \
    && rm -rf /var/lib/apt/lists/*
RUN python get-pip.py
RUN pip install boto3 
RUN pip install kubernetes==3.0.0
WORKDIR /app
COPY ./ecrupdater.py /app/ecrupdater.py
CMD ["python", "-u", "ecrupdater.py"]