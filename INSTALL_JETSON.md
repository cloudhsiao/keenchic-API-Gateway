# Keenchic API Gateway - Jetson Orin Installation Guide

This guide walks you through installing and running the Keenchic API Gateway
on a **NVIDIA Jetson Orin** device with JetPack 6.x.

---

## Prerequisites

| Item | Requirement |
|------|-------------|
| Hardware | NVIDIA Jetson Orin (any variant) |
| OS | JetPack 6.x (Ubuntu 22.04 based) |
| Python | 3.10 (JetPack pre-installed) |
| Pre-installed by JetPack | TensorRT, OpenCV, NumPy, matplotlib |

## Files You Need

Copy the following file to the Jetson (via USB, SCP, or any method):

```
keenchic_api_gateway-0.1.0-cp310-cp310-linux_aarch64.whl
```

For the rest of this guide, we assume the file is placed at:

```
/home/nvidia/keenchic_api_gateway-0.1.0-cp310-cp310-linux_aarch64.whl
```

---

## Step 1: Create a Virtual Environment

Open a terminal on the Jetson and run:

```bash
cd /home/nvidia
python3 -m venv --system-site-packages keenchic-env
```

> **Why `--system-site-packages`?**
> JetPack pre-installs TensorRT, OpenCV, NumPy, and matplotlib into the
> system Python. This flag allows the virtual environment to access those
> packages. Without it, the application will fail because these packages
> are not available on PyPI for aarch64.

## Step 2: Activate the Virtual Environment

```bash
source /home/nvidia/keenchic-env/bin/activate
```

After activation, your terminal prompt will change to show `(keenchic-env)`:

```
(keenchic-env) nvidia@jetson:~$
```

## Step 3: Verify Pre-installed Packages

Run the following command to confirm JetPack packages are accessible:

```bash
python3 -c "import numpy; import cv2; import tensorrt; print('All pre-installed packages OK')"
```

Expected output:

```
All pre-installed packages OK
```

If you see an `ImportError`, check that your JetPack installation is complete.

## Step 4: Install the Wheel

```bash
pip install /home/nvidia/keenchic_api_gateway-0.1.0-cp310-cp310-linux_aarch64.whl
```

pip will automatically install the remaining dependencies (FastAPI, uvicorn,
etc.). This may take a few minutes on the first run.

To verify the installation succeeded:

```bash
pip show keenchic-api-gateway
```

You should see output showing `Name: keenchic-api-gateway` and `Version: 0.1.0`.

## Step 5: Set the API Key

The gateway requires an API key to authenticate incoming requests. Set it as
an environment variable:

```bash
export KEENCHIC_API_KEY="your-api-key-here"
```

Replace `your-api-key-here` with the actual API key provided to you.

## Step 6: Start the Service

```bash
keenchic-serve --backend gpu --port 8000
```

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--backend` | Inference backend: `gpu` (TensorRT), `cpu`, `auto` | `gpu` |
| `--host` | Listen address | `0.0.0.0` (all interfaces) |
| `--port` | Listen port | `8000` |

When the service starts successfully, you will see output similar to:

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

## Step 7: Test the Service

From another terminal (or another machine on the same network), send a health
check request:

```bash
curl http://<JETSON_IP>:8000/health
```

Replace `<JETSON_IP>` with the Jetson's IP address (use `hostname -I` to find it).

---

## Running as a Background Service (Optional)

To keep the gateway running after you close the terminal, you can use `systemd`.

### Create the Service File

```bash
sudo tee /etc/systemd/system/keenchic.service > /dev/null << 'EOF'
[Unit]
Description=Keenchic API Gateway
After=network.target

[Service]
Type=simple
User=nvidia
Environment="KEENCHIC_API_KEY=your-api-key-here"
Environment="KEENCHIC_BACKEND=GPU"
ExecStart=/home/nvidia/keenchic-env/bin/keenchic-serve --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

> Remember to replace `your-api-key-here` with the actual API key.

### Enable and Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable keenchic        # auto-start on boot
sudo systemctl start keenchic         # start now
```

### Check Status

```bash
sudo systemctl status keenchic
```

### View Logs

```bash
journalctl -u keenchic -f
```

### Stop the Service

```bash
sudo systemctl stop keenchic
```

---

## Troubleshooting

### `ImportError: No module named 'tensorrt'`

Virtual environment was created without `--system-site-packages`. Recreate it:

```bash
rm -rf /home/nvidia/keenchic-env
python3 -m venv --system-site-packages /home/nvidia/keenchic-env
source /home/nvidia/keenchic-env/bin/activate
pip install /home/nvidia/keenchic_api_gateway-0.1.0-cp310-cp310-linux_aarch64.whl
```

### `Connection refused` when testing with curl

1. Check the service is running: `sudo systemctl status keenchic`
2. Check the port is not blocked by firewall: `sudo ufw allow 8000`
3. Check the Jetson's IP: `hostname -I`

### `401 Unauthorized`

The request is missing the `X-API-KEY` header or the key does not match.
Include it in your curl command:

```bash
curl -H "X-API-KEY: your-api-key-here" http://<JETSON_IP>:8000/api/v1/inspect ...
```

### Service crashes on first request

The first inference request loads the TensorRT model into GPU memory, which
may take 10-30 seconds. If the Jetson runs out of memory, try closing other
GPU-intensive applications first.

---

## Environment Variables Reference

| Variable | Description | Default |
|----------|-------------|---------|
| `KEENCHIC_API_KEY` | API key for request authentication (required) | `""` |
| `KEENCHIC_BACKEND` | Inference backend: `GPU`, `CPU`, `AUTO` | `GPU` |
| `KEENCHIC_UPLOAD_DIR` | Directory to save uploaded images (optional) | not set |
| `LOG_FORMAT` | Log format: `text` or `json` | `text` |
| `LOG_LEVEL` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |
