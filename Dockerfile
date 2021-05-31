FROM python:3.8-alpine
RUN pip install pipenv
WORKDIR /app
COPY . .
RUN pipenv install --system --deploy
CMD ["python", "-u", "ecrupdater.py"]
