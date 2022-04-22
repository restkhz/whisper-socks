import logging
import struct
import brotli
import gzip
import time
#import zstd
import zstandard as zstd # 'zstd' is too simple. We need to import 'zstandard' if we want to use advance APIs.
import ipaddress

def compress(data, cmp_level=3, cmp_dict=None, collect_data=False):
    if collect_data: _collect(data)
    if cmp_dict:
        compressor = zstd.ZstdCompressor(cmp_level, zstd.ZstdCompressionDict(_get_dict(cmp_dict)))
    else:
        compressor = zstd.ZstdCompressor(cmp_level)

    return compressor.compress(data)

def decompress(data, cmp_dict=None, collect_data=False):
    if cmp_dict:
        decompressor = zstd.ZstdDecompressor(zstd.ZstdCompressionDict(_get_dict(cmp_dict)))
    else:
        decompressor = zstd.ZstdDecompressor()

    data = decompressor.decompress(data)

    if collect_data: _collect(data)

    return data

def _collect(data):
    f = open('./samples/'+str(time.time()),'ab')
    f.write(data)
    f.close()

def _get_dict(cmp_dict):
    f = open(cmp_dict, 'rb')
    return f.read()
