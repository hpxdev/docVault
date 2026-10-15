# Production build served by Vite's preview server; /api is proxied to the api service.
FROM node:24.22.0-slim
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build
ENV VITE_API_PROXY=http://api:8000
EXPOSE 5173
CMD ["npx", "vite", "preview", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]
