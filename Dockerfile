FROM python:3.7-alpine

WORKDIR .

RUN apk add --no-cache gcc g++ musl-dev linux-headers geos libc-dev postgresql-dev
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

EXPOSE 7001

COPY . .
CMD ["flask", "run", "--host", "0.0.0.0", "-p", "7001"]
