FROM oven/bun:1 AS base

RUN apt-get update -y \
&& apt-get install -y openssl nodejs npm

WORKDIR /usr/src/app

COPY package.json bun.lock ./

RUN bun install --frozen-lockfile

COPY . .

EXPOSE ${APP_PORT}

CMD ["sh", "-c", "bun run dev", "--host", "0.0.0.0"]