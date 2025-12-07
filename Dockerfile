# syntax=docker/dockerfile:1

# ---- Builder Stage ----
FROM python:3.9.18-slim-bookworm AS builder
ARG INSTALL_DEV_DEPS=false

WORKDIR /app

# Install Poetry
RUN pip install poetry

# Copy only the dependency files to leverage Docker cache
COPY pyproject.toml poetry.lock* ./

# Install dependencies, but not in a virtualenv
RUN poetry config virtualenvs.create false && \
    if [ "$INSTALL_DEV_DEPS" = "true" ]; then \
        poetry install --no-root; \
    else \
        poetry install --without dev --no-root; \
    fi

# ---- Final Stage ----
FROM python:3.9.18-slim-bookworm AS final

# Create a non-root user
RUN addgroup --system app && adduser --system --group app

# Set the working directory
WORKDIR /app

# Copy the installed packages and executables from the builder stage
COPY --from=builder /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy the application code
COPY . .

# Set the user
USER app

# Expose the port
EXPOSE 8080

# Run the application
CMD ["python", "main.py"]

