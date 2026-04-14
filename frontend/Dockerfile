FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ENV NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_WS_URL=ws://localhost:8000

EXPOSE 3000

CMD ["npm", "run", "dev"]
