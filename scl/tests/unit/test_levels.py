from pathlib import Path
import scl_fse_cpp as fse

data = Path(
    "/Users/aayushgupta/Desktop/Stanford/FA25/274/project/scl/benchmark/datasets/silesia/webster"
).read_bytes()

for lvl in (1,2,3,4):
    enc = fse.encode_stream_level(data, lvl)
    dec = fse.decode_stream_level(enc, lvl)
    print(lvl, len(enc), len(dec), dec[:64] == data[:64], len(dec) == len(data))
