# Resources Directory

This directory contains static resources for the OviX Desktop application.

## Icons

- `icon.png` - Application icon (PNG format, 512x512 recommended)
- `icon.ico` - Windows icon (ICO format, 256x256 recommended)

## Python Runtime

The Python runtime will be embedded here for production builds.

### Setup Instructions

1. Download Python embeddable package from https://www.python.org/downloads/windows/
2. Extract to `resources/python/python-3.10.x-embed-amd64`
3. Install required packages using pip:
   ```bash
   cd resources/python/python-3.10.x-embed-amd64
   python -m pip install --target . -r ../../../requirements.txt
   ```
4. Create `python310._pth` file to include packages:
   ```
   python310.zip
   .
   
   # Uncomment to run site.main() automatically
   #import site
   ```

## Configuration

Default configuration files can be placed here for first-time installation.
