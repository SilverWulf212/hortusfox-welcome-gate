# Tiny runtime for deploy/bake.py: Python + Pillow, nothing else.
# Built on first use by deploy/bake.sh (docker build -f bake.Dockerfile).
FROM python:3.12-alpine
RUN pip install --no-cache-dir "pillow>=10,<13"
ENTRYPOINT ["python", "-I", "/gate/deploy/bake.py"]
