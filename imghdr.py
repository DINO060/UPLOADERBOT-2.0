"""
Compatibility module for imghdr (removed in Python 3.13)
This provides a minimal implementation of the imghdr module.
"""

import os

def what(file, h=None):
    """
    Determine the type of image contained in a file or byte stream.
    This is a simplified version that only handles basic cases.
    """
    if h is None:
        if hasattr(file, 'read'):
            h = file.read(32)
        else:
            with open(file, 'rb') as f:
                h = f.read(32)
    
    if not h:
        return None
    
    # Check for common image formats
    if h.startswith(b'\xff\xd8\xff'):
        return 'jpeg'
    elif h.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    elif h.startswith(b'GIF87a') or h.startswith(b'GIF89a'):
        return 'gif'
    elif h.startswith(b'RIFF') and b'WEBP' in h[:12]:
        return 'webp'
    elif h.startswith(b'BM'):
        return 'bmp'
    elif h.startswith(b'\x00\x00\x01\x00'):
        return 'ico'
    
    return None

def test_jpeg(h, f):
    """Test for JPEG format."""
    return what(f, h) == 'jpeg'

def test_png(h, f):
    """Test for PNG format."""
    return what(f, h) == 'png'

def test_gif(h, f):
    """Test for GIF format."""
    return what(f, h) == 'gif'

def test_webp(h, f):
    """Test for WebP format."""
    return what(f, h) == 'webp'

def test_bmp(h, f):
    """Test for BMP format."""
    return what(f, h) == 'bmp'

def test_ico(h, f):
    """Test for ICO format."""
    return what(f, h) == 'ico'
