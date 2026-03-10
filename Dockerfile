FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV DOCKER=true
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Chrome + ChromeDriver
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg2 unzip curl fonts-liberation libnss3 libxss1 \
    libappindicator3-1 libasound2 libatk-bridge2.0-0 libgtk-3-0 \
    libgbm1 libdrm2 libx11-xcb1 libxcomposite1 libxdamage1 \
    libxrandr2 xdg-utils ca-certificates \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
    && CHROME_VERSION=$(google-chrome-stable --version | grep -oP '\d+\.\d+\.\d+') \
    && DRIVER_URL="https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}.0/linux64/chromedriver-linux64.zip" \
    && wget -q "$DRIVER_URL" -O /tmp/chromedriver.zip || true \
    && if [ -f /tmp/chromedriver.zip ]; then \
         unzip -o /tmp/chromedriver.zip -d /tmp && mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/ && chmod +x /usr/local/bin/chromedriver; \
       fi \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/resultados

EXPOSE 8080

CMD ["python", "api.py"]
