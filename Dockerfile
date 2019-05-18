FROM python:3.6
RUN pip install pipenv
WORKDIR /app
COPY . .
RUN pipenv install --system --deploy
CMD ["python", "-u", "ecrupdater.py"]