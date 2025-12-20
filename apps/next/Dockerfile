FROM oven/bun:1 AS base

RUN apt-get update -y \
&& apt-get install -y --no-install-recommends openssl nodejs npm \
&& rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json bun.lock ./

RUN bun install --frozen-lockfile

COPY . .

EXPOSE ${APP_PORT}

CMD ["sh", "-c", "bun install && bun run dev"]
