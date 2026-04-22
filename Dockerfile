FROM python:3.14

ENV PYTHONUNBUFFERED=1

RUN apt-get update

RUN addgroup --gid 1031 charts
RUN useradd -g charts -ms /bin/bash charts
RUN pip install --upgrade pip

USER charts
WORKDIR /home/charts

COPY --chown=charts:charts . /home/charts

RUN pip install --user -r requirements.txt


CMD ["python", "run_batch.py", "--use-google-drive-folder", "--max-workers", "4"]