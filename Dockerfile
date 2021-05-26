FROM python:3.8

COPY ./requirements.txt /requirements.txt
RUN pip install -r requirements.txt
RUN rm requirements.txt

EXPOSE 80

COPY ./app /app
COPY ./assets /assets
COPY ./object_cache /object_cache
RUN mkdir /cache

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]